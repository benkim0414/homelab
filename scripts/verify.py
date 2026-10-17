#!/usr/bin/env python3
"""Render and verify declared Applications without cluster credentials.

Bootstrap: python3 verification/bootstrap.py
Run: verification/venv/bin/python scripts/verify.py --all [--base COMMIT]
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "verification/config.json"
CACHE = ROOT / "verification/cache"
REPORTS = ROOT / "verification/reports"


class Failure(Exception):
    pass


class StrictLoader(yaml.SafeLoader):
    pass


# YAML 1.2 booleans: GitHub's `on` must not become Python True.
StrictLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for key, entries in StrictLoader.yaml_implicit_resolvers.items():
    StrictLoader.yaml_implicit_resolvers[key] = [e for e in entries if e[0] not in {'tag:yaml.org,2002:bool', 'tag:yaml.org,2002:value', 'tag:yaml.org,2002:timestamp'}]
StrictLoader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false|True|False|TRUE|FALSE)$'), list('tTfF'))


def unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise Failure(f"duplicate YAML key at line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse(text, label):
    try:
        return [d for d in yaml.load_all(text, Loader=StrictLoader) if d is not None]
    except yaml.YAMLError as exc:
        # Parser exceptions include source lines; never echo potential secret data.
        mark = getattr(exc, 'problem_mark', None)
        raise Failure(f"{label}: invalid YAML" + (f" at line {mark.line + 1}" if mark else '')) from None


def run(args, *, cwd=ROOT, env=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        # Third-party tools may echo Secrets or rendered content; diagnostics stay private.
        raise Failure(f"{Path(str(args[0])).name} failed (exit {result.returncode}); tool output withheld to protect credentials")
    return result.stdout


def safe_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise Failure(f"missing or unsafe repository path: {relative}")
    return path


def patterns(pattern):
    # ArgoCD directory selection uses brace alternatives, unlike Python fnmatch.
    match = re.search(r'\{([^{}]+)\}', pattern)
    if not match:
        return [pattern]
    return [p for alt in match[1].split(',') for p in patterns(pattern[:match.start()] + alt + pattern[match.end():])]


def matches(path, pattern):
    # Supported subset matches current Applications. Refuse ambiguous new patterns.
    if any(s in pattern for s in ('**', '[', '?', '\\')):
        raise Failure(f"unsupported directory glob: {pattern}")
    return any(fnmatch.fnmatchcase(path, p) for p in patterns(pattern))


def selected(root, source):
    directory = source.get('directory', {})
    if set(directory) - {'include', 'exclude', 'recurse'}:
        raise Failure('unsupported directory source option')
    path = (root / source['path']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_dir():
        raise Failure('missing or unsafe directory source')
    candidates = path.rglob('*') if directory.get('recurse') else path.glob('*')
    return sorted(p for p in candidates if p.is_file() and p.suffix in {'.yaml', '.yml', '.json'}
                  and matches(p.relative_to(path).as_posix(), directory.get('include', '*'))
                  and not (directory.get('exclude') and matches(p.relative_to(path).as_posix(), directory['exclude'])))


def identity(doc, namespace=''):
    meta = doc.get('metadata', {})
    group = doc.get('apiVersion', '').split('/')[0] if '/' in doc.get('apiVersion', '') else ''
    return '/'.join((group, doc.get('kind', ''), meta.get('namespace', namespace), meta.get('name', '')))


def sources(app):
    spec = app['spec']
    if 'source' in spec and 'sources' in spec:
        raise Failure('Application defines both source and sources')
    return spec.get('sources', [spec.get('source', {})])


def candidate_files(root):
    names = run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).split('\0')
    deleted = set(run(['git', 'ls-files', '-z', '--deleted'], cwd=root).split('\0'))
    return sorted(set(names) - deleted - {''})


def read_repo(root, config, *, snapshot_files=False):
    # Only tracked candidate inputs; ignored local credentials are never opened.
    names = ([p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()] if snapshot_files else
             candidate_files(root))
    documents = {}
    for name in sorted(set(filter(None, names))):
        if name.startswith(('verification/', '.worktrees/')) or Path(name).suffix not in {'.yaml', '.yml', '.json'}:
            continue
        documents[name] = parse(safe_path(root, name).read_text(), name)
    root_app = documents[config['root']][0]
    applications = [root_app]
    projects = {'default'}
    project_specs = {}
    app_files = set()
    for source in sources(root_app):
        for path in selected(root, source):
            name = path.relative_to(root).as_posix()
            app_files.add(name)
            for doc in documents[name]:
                if doc.get('kind') == 'Application':
                    applications.append(doc)
                elif doc.get('kind') == 'AppProject':
                    projects.add(doc['metadata']['name'])
                    project_specs[doc['metadata']['name']] = doc['spec']
                else:
                    raise Failure(f"unexpected root resource in {name}")
    seen_apps = set()
    covered = {config['root']} | app_files
    raw = [{'app': root_app['metadata']['name'], 'namespace': 'argocd', 'resource': d, 'file': path}
           for path in sorted({config['root']} | app_files) for d in documents[path]]
    chart_inputs = []
    for app in applications:
        name = app['metadata']['name']
        if name in seen_apps:
            raise Failure(f"duplicate Application: {name}")
        seen_apps.add(name)
        spec = app['spec']
        if spec.get('project') not in projects or spec.get('destination', {}).get('server') != config['destination'] or not spec.get('destination', {}).get('namespace'):
            raise Failure(f"{name}: invalid project or destination")
        project = project_specs.get(spec['project'])
        if project is not None:
            destination = spec['destination']
            if not any(fnmatch.fnmatchcase(destination['server'], d.get('server', '')) and
                       fnmatch.fnmatchcase(destination['namespace'], d.get('namespace', ''))
                       for d in project.get('destinations', [])):
                raise Failure(f'{name}: destination is not allowed by AppProject')
        srcs = sources(app)
        refs = {s['ref']: s for s in srcs if 'ref' in s}
        if len(refs) != sum('ref' in s for s in srcs):
            raise Failure(f"{name}: duplicate source reference")
        for source in srcs:
            if project is not None and not any(fnmatch.fnmatchcase(source.get('repoURL', ''), pattern) for pattern in project.get('sourceRepos', [])):
                raise Failure(f'{name}: source is not allowed by AppProject')
            if set(source) - {'repoURL', 'chart', 'targetRevision', 'helm', 'path', 'directory', 'ref'}:
                raise Failure(f"{name}: unsupported source configuration")
            if 'chart' in source:
                if any(field in source for field in ('path', 'directory', 'ref')):
                    raise Failure(f'{name}: unsupported combination of chart source fields')
                if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', str(source.get('targetRevision', ''))):
                    raise Failure(f"{name}: chart must use an exact version")
                helm = source.get('helm', {})
                if set(helm) - {'releaseName', 'valueFiles', 'values', 'valuesObject', 'parameters', 'skipCrds', 'skipTests', 'skipSchemaValidation', 'kubeVersion', 'apiVersions', 'ignoreMissingValueFiles'}:
                    raise Failure(f"{name}: unsupported Helm option")
                values = []
                for value in helm.get('valueFiles', []):
                    match = re.fullmatch(r'\$([^/]+)/(.+)', value)
                    if not match or match[1] not in refs or refs[match[1]].get('repoURL') != config['repository']:
                        raise Failure(f"{name}: unsupported value reference")
                    path = safe_path(root, match[2])
                    values.append(path)
                    covered.add(match[2])
                chart_inputs.append((app, source, values))
            else:
                if source.get('repoURL') != config['repository'] or source.get('targetRevision') != 'main':
                    raise Failure(f"{name}: repository sources must track the configured repository on main")
                if 'helm' in source or not ('path' in source or 'ref' in source):
                    raise Failure(f"{name}: unsupported Git source")
                if source.get('path') and name != root_app['metadata']['name']:
                    for path in selected(root, source):
                        rel = path.relative_to(root).as_posix()
                        covered.add(rel)
                        for doc in documents[rel]:
                            raw.append({'app': name, 'namespace': spec['destination']['namespace'], 'resource': doc, 'file': rel})
    for name, reason in config['excluded'].items():
        if name not in documents or not reason:
            raise Failure(f"stale or unexplained exclusion: {name}")
        if name in covered:
            raise Failure(f"explicitly excluded resource activated: {name}")
    for name, docs in documents.items():
        if any(isinstance(d, dict) and 'apiVersion' in d and 'kind' in d for d in docs):
            if name not in covered and name not in config['excluded']:
                raise Failure(f"unclassified Kubernetes manifest: {name}")
    return applications, documents, raw, chart_inputs


def fetch(url, path):
    if not url.startswith('https://'):
        raise Failure('dependency downloads require HTTPS')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            path.write_bytes(data)
        except Exception as exc:
            status = getattr(exc, 'code', type(exc).__name__)
            from urllib.parse import urlparse
            public = urlparse(url)
            raise Failure(f'dependency download failed ({status}): {public.hostname}/{public.path.rsplit("/", 1)[-1]}') from None
    return path


def tool(name):
    path = CACHE / 'bin' / name
    if not path.is_file():
        raise Failure(f"missing {name}; run python3 verification/bootstrap.py")
    return path


def isolated_env():
    home = CACHE / 'home'
    home.mkdir(parents=True, exist_ok=True)
    # Do not pass AWS, Kubernetes, ArgoCD, registry, proxy, or Helm credentials.
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(home),
            'HELM_CONFIG_HOME': str(home / 'helm/config'), 'HELM_CACHE_HOME': str(home / 'helm/cache'),
            'HELM_DATA_HOME': str(home / 'helm/data'), 'HELM_PLUGINS': str(home / 'helm/plugins'),
            'KUBECONFIG': str(home / 'no-kubeconfig'), 'LANG': 'C.UTF-8'}


def kubernetes_version(root):
    text = safe_path(root, 'k3s-ansible/inventory.yml').read_text()
    match = re.search(r'k3s_version:\s*v(\d+\.\d+\.\d+)\+k3s\d+', text)
    if not match:
        raise Failure('cannot determine Kubernetes target from K3s inventory')
    return match[1]


def render(root, inputs, version, api_versions=()):
    resources = []
    env = isolated_env()
    for app, source, values in inputs:
        name = app['metadata']['name']
        repo, chart, pin = source['repoURL'], source['chart'], str(source['targetRevision'])
        key = hashlib.sha256(f'{repo}/{chart}@{pin}'.encode()).hexdigest()
        directory = CACHE / 'charts' / key
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / 'chart.tgz'
        if not archive.exists():
            args = [tool('helm'), 'pull', '--version', pin, '--destination', directory]
            if repo.startswith('https://'):
                args += ['--repo', repo, chart]
            else:
                args += [f'oci://{repo}/{chart}']
            run(args, env=env)
            packages = list(directory.glob('*.tgz'))
            if len(packages) != 1:
                raise Failure(f'{name}: expected exactly one downloaded chart package')
            packages[0].rename(archive)
        # Upstream URLs need not use the chart's version as the filename (Tailscale).
        import tarfile
        with tarfile.open(archive) as package:
            metadata = parse(package.extractfile(f'{chart}/Chart.yaml').read().decode(), 'chart metadata')[0]
        if metadata.get('name') != chart or str(metadata.get('version')) != pin:
            raise Failure(f'{name}: downloaded chart identity differs from Application pin')
        helm = source.get('helm', {})
        namespace = app['spec']['destination']['namespace']
        args = [tool('helm'), 'template', helm.get('releaseName', name), archive, '--namespace', namespace,
                '--kube-version', helm.get('kubeVersion', version)]
        if not helm.get('skipCrds'):
            args.append('--include-crds')
        if helm.get('skipTests'):
            args.append('--skip-tests')
        if helm.get('skipSchemaValidation'):
            args.append('--skip-schema-validation')
        for api in sorted(set(api_versions) | set(helm.get('apiVersions', []))):
            args += ['--api-versions', api]
        for value in values:
            args += ['--values', value]
        with tempfile.TemporaryDirectory(dir=CACHE) as temp:
            # ArgoCD ValuesYAML selects valuesObject instead of merging both forms.
            field = 'valuesObject' if helm.get('valuesObject') is not None else 'values'
            if field in helm:
                path = Path(temp) / f'{field}.yaml'
                path.write_text(helm[field] if field == 'values' else yaml.safe_dump(helm[field]))
                args += ['--values', path]
            for parameter in helm.get('parameters', []):
                if set(parameter) - {'name', 'value', 'forceString'}:
                    raise Failure(f'{name}: unsupported Helm parameter')
                args += ['--set-string' if parameter.get('forceString') else '--set', f"{parameter['name']}={parameter['value']}"]
            try:
                output = run(args, env=env)
            except Failure as exc:
                raise Failure(f'{name} chart {chart}@{pin}: {exc}') from None
        for doc in parse(output, f'{name} render'):
            resources.append({'app': name, 'namespace': namespace, 'resource': doc, 'file': f'chart:{chart}@{pin}'})
    return resources


def render_all(root, charts, version, raw):
    preliminary = render(root, charts, version)
    apis = set()
    for entry in preliminary + raw:
        doc = entry['resource']
        if doc.get('kind') == 'CustomResourceDefinition':
            for api in doc['spec']['versions']:
                if api.get('served', True):
                    group_version = f"{doc['spec']['group']}/{api['name']}"
                    apis.update({group_version, f"{group_version}/{doc['spec']['names']['kind']}"})
    # ArgoCD uses live discovery. Offline, model the APIs declared by selected charts.
    return normalize_namespaces(raw + render(root, charts, version, apis))


def normalize_namespaces(resources):
    cluster_kinds = {'Namespace', 'Node', 'PersistentVolume', 'CustomResourceDefinition', 'ClusterRole',
                     'ClusterRoleBinding', 'StorageClass', 'CSIDriver', 'CSINode', 'VolumeAttachment',
                     'PriorityClass', 'MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration',
                     'APIService', 'IngressClass', 'RuntimeClass'}
    cluster_kinds.update(d['resource']['spec']['names']['kind'] for d in resources
                         if d['resource'].get('kind') == 'CustomResourceDefinition' and d['resource']['spec']['scope'] == 'Cluster')
    seen = {}
    for entry in resources:
        doc = entry['resource']
        if doc.get('kind') == 'List':
            raise Failure('List resources require explicit expansion support')
        if doc.get('kind') not in cluster_kinds:
            doc.setdefault('metadata', {}).setdefault('namespace', entry['namespace'])
        key = identity(doc)
        if key in seen:
            raise Failure(f'duplicate resource identity: {key} ({seen[key]}, {entry["app"]})')
        seen[key] = entry['app']
    return resources


def convert_schema(value):
    """Translate OpenAPI schema nodes, without treating property names as keywords."""
    if not isinstance(value, dict):
        return value
    result = copy.deepcopy(value)
    for keyword in ('properties', 'patternProperties', 'definitions', '$defs'):
        if keyword in result:
            result[keyword] = {name: convert_schema(schema) for name, schema in result[keyword].items()}
    for keyword in ('items', 'additionalItems', 'additionalProperties', 'not'):
        if keyword in result:
            result[keyword] = ([convert_schema(schema) for schema in result[keyword]]
                               if isinstance(result[keyword], list) else convert_schema(result[keyword]))
    for keyword in ('allOf', 'anyOf', 'oneOf'):
        if keyword in result:
            result[keyword] = [convert_schema(schema) for schema in result[keyword]]
    if result.pop('x-kubernetes-int-or-string', False):
        result.pop('type', None)
        result['anyOf'] = [{'type': 'integer'}, {'type': 'string'}]
    if result.pop('nullable', False) and isinstance(result.get('type'), str):
        result['type'] = [result['type'], 'null']
    result.pop('x-kubernetes-validations', None)  # CEL requires the API server.
    if result.get('type') == 'object' and not result.get('x-kubernetes-preserve-unknown-fields'):
        result.setdefault('additionalProperties', False)
    return result



def schema_filename(group, kind, version):
    # Schema names originate in chart content; validate before using them as paths.
    if not (isinstance(group, str) and (not group or re.fullmatch(r'[a-z0-9][a-z0-9.-]*', group))
            and isinstance(kind, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', kind)
            and isinstance(version, str) and re.fullmatch(r'[a-z][a-z0-9]*', version)):
        raise Failure('unsafe or invalid schema group, kind or version')
    return f'{group or version}_{kind.lower()}_{version}.json'


def schemas(resources, config):
    directory = CACHE / 'schemas' / hashlib.sha256(json.dumps(resources, sort_keys=True).encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    crds = [e['resource'] for e in resources if e['resource'].get('kind') == 'CustomResourceDefinition']
    for url in config['external_crds']:
        path = fetch(url, CACHE / 'external' / hashlib.sha256(url.encode()).hexdigest())
        crds.extend(parse(path.read_text(), 'external CRD'))
    result = {}
    for crd in crds:
        spec = crd['spec']
        for version in spec['versions']:
            if 'schema' not in version:
                continue
            schema = convert_schema(version['schema']['openAPIV3Schema'])
            schema.setdefault('properties', {}).update({'apiVersion': {'type': 'string'}, 'kind': {'type': 'string'}, 'metadata': {'type': 'object'}})
            key = (spec['group'], version['name'], spec['names']['kind'])
            if key in result and result[key] != schema:
                raise Failure(f'conflicting CRD schemas: {key}')
            result[key] = schema
            (directory / schema_filename(key[0], key[2], key[1])).write_text(json.dumps(schema))
    return directory, result


def crd_definition_schema(version):
    # CRD is served by apiextensions, so it is absent from the core schema catalog.
    url = f'https://raw.githubusercontent.com/kubernetes/kubernetes/v{version}/api/openapi-spec/v3/apis__apiextensions.k8s.io__v1_openapi.json'
    path = fetch(url, CACHE / 'schema-downloads' / hashlib.sha256(url.encode()).hexdigest())
    definitions = json.loads(path.read_text())['components']['schemas']
    converted = {name: convert_schema(schema) for name, schema in definitions.items()}
    converted = json.loads(json.dumps(converted).replace('#/components/schemas/', '#/definitions/'))
    return {'$ref': '#/definitions/io.k8s.apiextensions-apiserver.pkg.apis.apiextensions.v1.CustomResourceDefinition',
            'definitions': converted}


def validate_schemas(resources, config, version):
    directory, custom = schemas(resources, config)
    for entry in resources:
        doc = entry['resource']
        api = doc.get('apiVersion', '')
        if not api or not doc.get('kind'):
            raise Failure(f'{entry["app"]}: resource missing kind or apiVersion')
        group, api_version = api.split('/') if '/' in api else ('', api)
        key = (group, api_version, doc['kind'])
        schema_filename(group, doc['kind'], api_version)
        if key in custom:
            continue
        if key == ('apiextensions.k8s.io', 'v1', 'CustomResourceDefinition'):
            (directory / schema_filename(group, doc['kind'], api_version)).write_text(json.dumps(crd_definition_schema(version)))
            continue
        filename = doc['kind'].lower() + (f'-{group.split(".")[0]}-{api_version}' if group else '') + '.json'
        url = f'https://raw.githubusercontent.com/yannh/kubernetes-json-schema/{config["schema_revision"]}/v{version}-standalone-strict/{filename}'
        cached = fetch(url, CACHE / 'schema-downloads' / hashlib.sha256(url.encode()).hexdigest())
        (directory / schema_filename(group, doc['kind'], api_version)).write_bytes(cached.read_bytes())
    with tempfile.TemporaryDirectory(dir=CACHE) as temp:
        path = Path(temp) / 'resources.yaml'
        path.write_text(yaml.safe_dump_all([e['resource'] for e in resources]))
        args = [tool('kubeconform'), '-strict', '-summary', '-output', 'json', '-kubernetes-version', version,
                '-schema-location', str(directory / '{{.Group}}_{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'), path]
        result = subprocess.run([str(x) for x in args], capture_output=True, text=True, env=isolated_env())
        try:
            report = json.loads(result.stdout)
        except ValueError:
            raise Failure('kubeconform did not return a validation report') from None
        failures = [f'{r.get("kind", "?")}/{r.get("name", "?")}: {r.get("status", "ERROR")}'
                    for r in report.get('resources', []) if r.get('status') not in {'VALID', 'statusValid'}]
        summary = report.get('summary', {})
        if result.returncode or failures:
            raise Failure('schema validation failed: ' + '; '.join(failures))
        if summary.get('valid') != len(resources) or any(summary.get(key, 0) for key in ('invalid', 'errors', 'skipped')):
            raise Failure('schema validation did not validate every resource')
    return report['summary']


def remove_pointer(doc, pointer):
    parts = [p.replace('~1', '/').replace('~0', '~') for p in pointer.lstrip('/').split('/')]
    target = doc
    for part in parts[:-1]:
        target = target.get(part, {}) if isinstance(target, dict) else {}
    if isinstance(target, dict):
        target.pop(parts[-1], None)


def sanitize(doc, config):
    doc = copy.deepcopy(doc)
    if doc.get('kind') == 'Secret':
        for key in ('data', 'stringData'):
            if key in doc:
                doc[key] = {k: '<redacted-sha256:' + hashlib.sha256(str(value).encode()).hexdigest() + '>' for k, value in doc[key].items()}
    if doc.get('kind') == 'SealedSecret':
        encrypted = doc.get('spec', {}).get('encryptedData', {})
        doc.get('spec', {})['encryptedData'] = {k: '<redacted-sha256:' + hashlib.sha256(str(value).encode()).hexdigest() + '>' for k, value in encrypted.items()}
    for rule in config['generated_fields']:
        if all(doc.get('metadata', {}).get(k) == rule[k] for k in ('name', 'namespace')) and doc.get('kind') == rule['kind']:
            for pointer in rule['paths']:
                remove_pointer(doc, pointer)
    return doc


def changes(before, after, config):
    old = {identity(e['resource']): sanitize(e['resource'], config) for e in before}
    new = {identity(e['resource']): sanitize(e['resource'], config) for e in after}
    return [{'resource': key, 'change': 'added' if key not in old else 'removed' if key not in new else 'modified',
             'categories': categories(old.get(key), new.get(key))}
            for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]


def categories(before, after):
    doc = after or before
    kind = doc['kind']
    result = []
    if kind in {'PersistentVolume', 'PersistentVolumeClaim', 'StatefulSet', 'StorageClass'}:
        result.append('storage')
    if kind in {'Role', 'RoleBinding', 'ClusterRole', 'ClusterRoleBinding', 'ServiceAccount'}:
        result.append('RBAC')
    if kind in {'Service', 'Ingress', 'IngressRoute', 'IPAddressPool', 'L2Advertisement'}:
        result.append('exposure')
    def images(value):
        if isinstance(value, dict):
            return ([value['image']] if isinstance(value.get('image'), str) else []) + [i for v in value.values() for i in images(v)]
        return [i for v in value for i in images(v)] if isinstance(value, list) else []
    if images(before) != images(after):
        result.append('images')
    return result


def storage_changes(before, after):
    old = {identity(e['resource']): e['resource'] for e in before}
    new = {identity(e['resource']): e['resource'] for e in after}
    violations = []
    for key, doc in old.items():
        if doc.get('kind') not in {'PersistentVolume', 'PersistentVolumeClaim', 'StatefulSet', 'StorageClass'}:
            continue
        other = new.get(key)
        if other is None:
            violations.append({'rule': 'storage-removal', 'resource': key})
            continue
        spec, next_spec = doc.get('spec', {}), other.get('spec', {})
        fields = {'PersistentVolume': ['claimRef', 'nfs', 'csi', 'local', 'hostPath', 'storageClassName', 'persistentVolumeReclaimPolicy', 'capacity'],
                  'PersistentVolumeClaim': ['volumeName', 'storageClassName', 'accessModes', 'dataSource', 'dataSourceRef'],
                  'StatefulSet': ['volumeClaimTemplates', 'persistentVolumeClaimRetentionPolicy'],
                  'StorageClass': ['provisioner', 'parameters', 'reclaimPolicy']}[doc['kind']]
        # StorageClass fields are top-level, not in spec.
        if doc['kind'] == 'StorageClass':
            spec, next_spec = doc, other
        if any(spec.get(k) != next_spec.get(k) for k in fields):
            violations.append({'rule': 'storage-identity', 'resource': key})
        for field in ('storage',):
            current = spec.get('resources', {}).get('requests', {}).get(field)
            candidate = next_spec.get('resources', {}).get('requests', {}).get(field)
            if current != candidate:
                # All resize requests require review; no unreliable quantity comparison.
                violations.append({'rule': 'storage-resize', 'resource': key})
    return violations


def apply_exceptions(violations, config, root):
    remaining = list(violations)
    used = []
    for exception in config['exceptions']:
        if set(exception) != {'rule', 'resource', 'reason', 'document'} or not exception['reason']:
            raise Failure('exceptions require rule, exact resource identity, reason and document')
        safe_path(root, exception['document'])
        target = {'rule': exception['rule'], 'resource': exception['resource']}
        if target not in remaining:
            raise Failure('stale or unmatched policy exception')
        remaining.remove(target)
        used.append(exception)
    if remaining:
        raise Failure('policy violations: ' + '; '.join(f'{v["rule"]}: {v["resource"]}' for v in remaining))
    return used


def policies(root, apps, documents, resources, before, config):
    known_apps = {identity(app) for app in apps}
    for entry in resources:
        resource = entry['resource']
        if (resource.get('kind') == 'Application' and
                resource.get('apiVersion', '').startswith('argoproj.io/') and
                identity(resource) not in known_apps):
            raise Failure(f'unsupported nested Application: {identity(resource)}; include it in root discovery')
    payload = {'applications': apps, 'committed': [d for docs in documents.values() for d in docs if isinstance(d, dict)],
               'resources': [e['resource'] for e in resources]}
    with tempfile.TemporaryDirectory(dir=CACHE) as temp:
        path = Path(temp) / 'input.json'
        path.write_text(json.dumps(payload))
        completed = subprocess.run([str(x) for x in [tool('conftest'), 'test', path, '--policy', ROOT / 'verification/policy', '--output', 'json']], env=isolated_env(), text=True, capture_output=True)
        if completed.returncode not in {0, 1}:
            raise Failure('Conftest could not evaluate policies')
        output = completed.stdout
        violations = []
        for result in json.loads(output):
            for failure in result.get('failures', []):
                violations.append(json.loads(failure['msg']))
    violations += storage_changes(before, resources)
    return apply_exceptions(violations, config, root)


def snapshot(commit, directory):
    # Read only Git objects; do not checkout, execute, or run base-revision scripts.
    resolved = run(['git', 'rev-parse', '--verify', f'{commit}^{{commit}}']).strip()
    import tarfile
    import io
    result = subprocess.run(['git', 'archive', resolved], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise Failure('unable to read base commit')
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(directory, filter='data')
    # A snapshot has no .git; read_repo enumerates its archived files directly.
    return resolved


def write_report(report):
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Verify', '', f"Result: **{report['result']}**", '', f"Commit: `{report['commit']}`", '',
             f"Kubernetes: `{report.get('kubernetes', 'unknown')}`", '',
             'Tool pins: ' + ', '.join(f'{k} {v}' for k,v in report['tools'].items()), '']
    if report.get('error'):
        lines += [report['error'], '']
    lines += [f"Working tree modified: {report.get('working_tree_dirty', False)}", '',
              f"Schema source: `{report['schema_revision']}`", '',
              f"Validated resources: {report.get('resource_count', 0)}", '', '## Charts', '']
    lines += [f"- `{c['app']}`: `{c['chart']}@{c['version']}`" for c in report.get('charts', [])]
    lines += ['', '## Resource changes', '']
    lines += [f"- {c['change']}: `{c['resource']}` ({', '.join(c['categories']) or 'configuration'})" for c in report.get('changes', [])]
    lines += ['', '## Coverage and limitations', '', '- CI validation does not establish live admission, backup validity or workload health.',
              '- Traefik HelmChartConfig values are parsed; its K3s-managed chart is not rendered.', '']
    lines += [f'- Excluded `{p}`: {reason}' for p,reason in report['excluded'].items()]
    lines += [f'- Exception `{e["rule"]}` / `{e["resource"]}`: {e["reason"]} ({e["document"]})' for e in report.get('exceptions', [])]
    (REPORTS / 'summary.md').write_text('\n'.join(lines) + '\n')


def scan_files(root, documents, names=None):
    """Scan candidate contents without ignored credentials or encrypted payloads."""
    with tempfile.TemporaryDirectory(dir=CACHE) as temp:
        scan = Path(temp)
        names = candidate_files(root) if names is None else names
        for name in filter(None, names):
            path = safe_path(root, name)
            destination = scan / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = path.read_bytes()
            for doc in documents.get(name, []):
                if isinstance(doc, dict) and doc.get('kind') == 'SealedSecret':
                    for ciphertext in doc.get('spec', {}).get('encryptedData', {}).values():
                        if not isinstance(ciphertext, str) or not re.fullmatch(r'Ag[A-Za-z0-9+/=]{100,}', ciphertext):
                            raise Failure(f'{name}: invalid SealedSecret ciphertext format')
                        data = data.replace(ciphertext.encode(), b'<encrypted>')
            destination.write_bytes(data)
        scan_result = subprocess.run([str(x) for x in [tool('gitleaks'), 'dir', scan, '--redact', '--no-banner',
            '--exit-code', '1', '--config', ROOT / 'verification/gitleaks.toml', '--ignore-gitleaks-allow',
            '--report-format', 'json', '--report-path', '-', '--gitleaks-ignore-path', CACHE / 'no-ignore-file']], env=isolated_env(), text=True, capture_output=True)
        if scan_result.returncode:
            try:
                findings = json.loads(scan_result.stdout)
                locations = [f'{f["RuleID"]}: {Path(f["File"]).relative_to(scan)}:{f["StartLine"]}' for f in findings]
            except (ValueError, KeyError, TypeError):
                locations = ['scanner did not return a valid report']
            raise Failure('secret scanning failed: ' + '; '.join(locations))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='validate every selected Application (also the default)')
    parser.add_argument('--base', help='compare rendered resources against this local Git commit')
    parser.add_argument('--offline', action='store_true', help='check repository structure only; never produces a passing full-verification result')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    CACHE.mkdir(parents=True, exist_ok=True)
    report = {'result': 'failed', 'commit': run(['git', 'rev-parse', 'HEAD']).strip(), 'tools': config['tools'], 'excluded': config['excluded'], 'schema_revision': config['schema_revision'],
              'working_tree_dirty': bool(run(['git', 'status', '--porcelain']))}
    try:
        apps, documents, raw, charts = read_repo(ROOT, config)
        for name, docs in documents.items():
            for doc in docs:
                if isinstance(doc, dict) and doc.get('kind') == 'HelmChartConfig':
                    parse(doc['spec']['valuesContent'], f'{name} valuesContent')
        version = kubernetes_version(ROOT)
        report['kubernetes'] = version
        report['charts'] = [{'app': a['metadata']['name'], 'chart': s['chart'], 'version': s['targetRevision']} for a,s,_ in charts]
        if args.offline:
            report['result'] = 'partial'
            print('Repository structure passed; rendering, schemas, policies and secret scanning were NOT run.')
            return 2
        # Enforce tool versions before executing checks, including externally installed binaries.
        for name, expected in config['tools'].items():
            flag = 'version' if name in {'helm', 'gitleaks'} else '--version' if name == 'conftest' else '-v' if name == 'kubeconform' else '-version'
            actual = run([tool(name), flag], env=isolated_env())
            if not re.search(r'(?<![\d.])v?' + re.escape(expected) + r'(?![\d.])', actual):
                raise Failure(f'{name}: expected version {expected}')
        run([tool('actionlint'), ROOT / '.github/workflows/verify.yml'], env=isolated_env())
        scan_files(ROOT, documents)
        current = render_all(ROOT, charts, version, raw)
        report['schemas'] = validate_schemas(current, config, version)
        previous = []
        if args.base:
            with tempfile.TemporaryDirectory(dir=CACHE) as temp:
                base_root = Path(temp)
                report['base'] = snapshot(args.base, base_root)
                # Git files are read from snapshot; the verifier/policy always comes from candidate.
                base_config = json.loads((base_root / 'verification/config.json').read_text()) if (base_root / 'verification/config.json').exists() else config
                _, _, base_raw, base_charts = read_repo(base_root, base_config, snapshot_files=True)
                previous = render_all(base_root, base_charts, kubernetes_version(base_root), base_raw)
        report['changes'] = changes(previous, current, config)
        report['exceptions'] = policies(ROOT, apps, documents, current, previous, config)
        report['resource_count'] = len(current)
        report['result'] = 'passed'
        print(f'Verify passed: {len(apps)} Applications, {len(current)} resources. Reports: verification/reports/')
        return 0
    except (Failure, KeyError, TypeError, ValueError, OSError) as exc:
        # Only controlled Failure messages are safe to emit.
        report['error'] = str(exc) if isinstance(exc, Failure) else f'{type(exc).__name__}: malformed input or unavailable dependency'
        print(f'Verify failed: {report["error"]}', file=sys.stderr)
        return 1
    finally:
        write_report(report)


if __name__ == '__main__':
    sys.exit(main())
