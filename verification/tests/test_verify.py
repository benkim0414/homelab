"""Behavior tests for repository selection, policies, rendering and reporting."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('verify', Path(__file__).resolve().parents[2] / 'scripts/verify.py')
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
v.CACHE.mkdir(parents=True, exist_ok=True)


def resource(kind='PersistentVolumeClaim', name='database', spec=None):
    return {'apiVersion': 'apps/v1' if kind == 'StatefulSet' else 'v1', 'kind': kind,
            'metadata': {'name': name, 'namespace': 'app'}, 'spec': spec or {}}


def entry(doc):
    return {'resource': doc, 'namespace': 'app', 'app': 'app', 'file': 'fixture.yaml'}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=v.CACHE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = copy.deepcopy(json.loads(v.CONFIG.read_text()))
        self.config['excluded'] = {}
        self.config['root'] = 'root.yaml'
        self.write('root.yaml', {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
            'metadata': {'name': 'apps', 'namespace': 'argocd'}, 'spec': {'project': 'default',
            'source': {'repoURL': self.config['repository'], 'targetRevision': 'main', 'path': 'apps',
                       'directory': {'include': '*.yaml'}},
            'destination': {'server': self.config['destination'], 'namespace': 'argocd'}}})
        self.app = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application', 'metadata': {'name': 'app', 'namespace': 'argocd'},
            'spec': {'project': 'default', 'destination': {'server': self.config['destination'], 'namespace': 'app'},
            'sources': [{'repoURL': 'ghcr.io/example/charts', 'chart': 'example', 'targetRevision': '1.2.3',
                         'helm': {'valueFiles': ['$repo/app/values.yaml'], 'releaseName': 'preserved-name'}},
                        {'repoURL': self.config['repository'], 'targetRevision': 'main', 'ref': 'repo'},
                        {'repoURL': self.config['repository'], 'targetRevision': 'main', 'path': 'app',
                         'directory': {'include': '{service.yaml,storage.yaml}'}}]}}
        self.write('apps/app.yaml', self.app)
        self.write('app/values.yaml', {'replicas': 1})
        self.write('app/service.yaml', resource('Service', 'api'))
        self.write('app/storage.yaml', resource())

    def write(self, name, doc):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(v.yaml.safe_dump(doc))

    def read(self):
        return v.read_repo(self.root, self.config, snapshot_files=True)

    def test_multisource_brace_selection_and_release(self):
        apps, _, raw, charts = self.read()
        self.assertEqual(len(apps), 2)
        self.assertEqual(len(charts), 1)
        self.assertEqual({r['file'] for r in raw}, {'root.yaml', 'apps/app.yaml', 'app/service.yaml', 'app/storage.yaml'})
        self.assertEqual(charts[0][1]['helm']['releaseName'], 'preserved-name')

    def test_missing_value_file_fails(self):
        (self.root / 'app/values.yaml').unlink()
        with self.assertRaisesRegex(v.Failure, 'missing or unsafe'):
            self.read()

    def test_unselected_manifest_fails(self):
        self.write('app/forgotten.yaml', resource('Service', 'forgotten'))
        with self.assertRaisesRegex(v.Failure, 'unclassified'):
            self.read()

    def test_excluded_activation_fails(self):
        self.config['excluded']['app/storage.yaml'] = 'Disabled until migration'
        with self.assertRaisesRegex(v.Failure, 'excluded resource activated'):
            self.read()

    def test_unpinned_chart_fails(self):
        self.app['spec']['sources'][0]['targetRevision'] = '*'
        self.write('apps/app.yaml', self.app)
        with self.assertRaisesRegex(v.Failure, 'exact version'):
            self.read()

    def test_unsupported_source_does_not_silently_skip(self):
        self.app['spec']['sources'][0]['plugin'] = {'name': 'example'}
        self.write('apps/app.yaml', self.app)
        with self.assertRaisesRegex(v.Failure, 'unsupported source'):
            self.read()

    def test_path_traversal_fails(self):
        with self.assertRaises(v.Failure):
            v.safe_path(self.root, '../../AGENTS.md')

    def test_multidocument_apps(self):
        path = self.root / 'apps/app.yaml'
        other = copy.deepcopy(self.app)
        other['metadata']['name'] = 'second'
        other['spec']['sources'] = other['spec']['sources'][:2]
        path.write_text(v.yaml.safe_dump_all([self.app, other]))
        self.assertEqual(len(self.read()[0]), 3)

    def test_unstaged_deletion_and_rename_reach_storage_checks(self):
        for args in (['git', 'init', '--quiet'], ['git', 'add', '.']):
            subprocess.run(args, cwd=self.root, check=True, capture_output=True)
        _, _, before, _ = v.read_repo(self.root, self.config)
        (self.root / 'app/storage.yaml').unlink()
        (self.root / 'app/service.yaml').rename(self.root / 'app/renamed.yaml')
        self.app['spec']['sources'][2]['directory']['include'] = '{renamed.yaml,storage.yaml}'
        self.write('apps/app.yaml', self.app)
        _, documents, after, _ = v.read_repo(self.root, self.config)
        self.assertNotIn('app/storage.yaml', documents)
        self.assertNotIn('app/service.yaml', documents)
        self.assertIn('app/renamed.yaml', documents)
        self.assertEqual(v.storage_changes(before, after), [
            {'rule': 'storage-removal', 'resource': '/PersistentVolumeClaim/app/database'}])
        if (v.CACHE / 'bin/gitleaks').exists():
            v.scan_files(self.root, documents)
        # Deleted value files must still fail at their live reference.
        (self.root / 'app/values.yaml').unlink()
        with self.assertRaisesRegex(v.Failure, 'missing or unsafe repository path: app/values.yaml'):
            v.read_repo(self.root, self.config)

    def test_real_helm_inline_values_match_argocd(self):
        if not (v.CACHE / 'bin/helm').exists():
            self.skipTest('bootstrap required for Helm integration')
        import hashlib, io, tarfile
        _, _, _, charts = self.read()
        _, source, _ = charts[0]
        cache = self.root / 'helm-cache'
        key = hashlib.sha256(f"{source['repoURL']}/{source['chart']}@{source['targetRevision']}".encode()).hexdigest()
        directory = cache / 'charts' / key
        directory.mkdir(parents=True)
        files = {'example/Chart.yaml': 'apiVersion: v2\nname: example\nversion: 1.2.3\n',
                 'example/values.yaml': 'replicas: 1\nlegacy: default\n',
                 'example/templates/cm.yaml': 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: fixture\ndata:\n  replicas: {{ .Values.replicas | quote }}\n  legacy: {{ .Values.legacy | quote }}\n'}
        with tarfile.open(directory / 'chart.tgz', 'w:gz') as archive:
            for name, content in files.items():
                data = content.encode()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        source['helm']['values'] = 'replicas: 2\nlegacy: from-inline\n'
        binary = v.tool('helm')
        for object_value, expected in [({'replicas': 3}, {'replicas': '3', 'legacy': 'default'}),
                                       ({}, {'replicas': '1', 'legacy': 'default'}),
                                       (None, {'replicas': '2', 'legacy': 'from-inline'})]:
            with self.subTest(valuesObject=object_value):
                source['helm']['valuesObject'] = object_value
                with patch.object(v, 'CACHE', cache), patch.object(v, 'tool', return_value=binary):
                    rendered = v.render(self.root, charts, '1.36.5')
                self.assertEqual(rendered[0]['resource']['data'], expected)

    def test_oci_and_value_precedence_render_arguments(self):
        _, _, _, charts = self.read()
        app, source, values = charts[0]
        source['helm'].update({'values': 'replicas: 2', 'valuesObject': {'replicas': 3},
                               'parameters': [{'name': 'replicas', 'value': '4', 'forceString': True}]})
        calls = []
        def fake_run(args, **kwargs):
            calls.append([str(a) for a in args])
            if 'pull' in args:
                import io, tarfile
                destination = Path(args[args.index('--destination') + 1]) / 'arbitrary-filename.tgz'
                data = b'name: example\nversion: 1.2.3\n'
                with tarfile.open(destination, 'w:gz') as archive:
                    member = tarfile.TarInfo('example/Chart.yaml')
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            return v.yaml.safe_dump(resource('Service', 'rendered')) if 'template' in args else ''
        with patch.object(v, 'CACHE', self.root / 'cache'), patch.object(v, 'run', side_effect=fake_run), patch.object(v, 'tool', return_value=Path('/tools/helm')):
            result = v.render(self.root, charts, '1.36.5')
        pull, template = calls
        self.assertIn('oci://ghcr.io/example/charts/example', pull)
        self.assertEqual(template[2], 'preserved-name')
        self.assertLess(template.index(str(values[0])), template.index('--set-string'))
        self.assertEqual(template[-1], 'replicas=4')
        self.assertEqual(result[0]['app'], 'app')


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(v.CONFIG.read_text())

    def test_invalid_yaml_and_duplicate_keys(self):
        for text in ('spec: [', 'spec: {}\nspec: {}'):
            with self.assertRaises(v.Failure):
                v.parse(text, 'fixture')
        self.assertEqual(v.parse('on: {push: {}}', 'workflow')[0], {'on': {'push': {}}})

    def test_duplicate_ownership_fails(self):
        with self.assertRaisesRegex(v.Failure, 'duplicate resource identity'):
            v.normalize_namespaces([entry(resource()), entry(resource())])

    def test_storage_deletion_and_rename_fail(self):
        old = [entry(resource())]
        for new in ([], [entry(resource(name='renamed'))]):
            self.assertEqual(v.storage_changes(old, new)[0]['rule'], 'storage-removal')

    def test_statefulset_claim_and_retention_changes_fail(self):
        old = [entry(resource('StatefulSet', spec={'volumeClaimTemplates': [{'metadata': {'name': 'data'}}]}))]
        for spec in ({'volumeClaimTemplates': []}, {'volumeClaimTemplates': [{'metadata': {'name': 'data'}}],
                                                      'persistentVolumeClaimRetentionPolicy': {'whenDeleted': 'Delete'}}):
            self.assertEqual(v.storage_changes(old, [entry(resource('StatefulSet', spec=spec))])[0]['rule'], 'storage-identity')

    def test_exception_requires_document_and_exact_match(self):
        config = copy.deepcopy(self.config)
        config['exceptions'] = [{'rule': 'storage-removal', 'resource': '/PersistentVolumeClaim/app/database',
                                 'reason': 'Migration reviewed', 'document': 'argocd/README.md'}]
        violation = {'rule': 'storage-removal', 'resource': '/PersistentVolumeClaim/app/database'}
        self.assertEqual(len(v.apply_exceptions([violation], config, v.ROOT)), 1)
        with self.assertRaisesRegex(v.Failure, 'unmatched'):
            v.apply_exceptions([], config, v.ROOT)

    def test_secret_redaction_and_deletion_visibility(self):
        secret = resource('Secret', 'credential')
        secret['data'] = {'token': 'FAKE_TEST_PAYLOAD'}
        sanitized = json.dumps(v.sanitize(secret, self.config))
        self.assertNotIn('FAKE_TEST_PAYLOAD', sanitized)
        report = v.changes([entry(secret)], [], self.config)
        self.assertEqual(report[0]['change'], 'removed')
        self.assertNotIn('FAKE_TEST_PAYLOAD', json.dumps(report))

    def test_generated_field_normalization_is_narrow(self):
        doc = resource('Deployment', 'kube-prometheus-stack-grafana', {'template': {'metadata': {'annotations': {
            'checksum/secret': 'generated', 'keep': 'visible'}}}})
        doc['metadata']['namespace'] = 'monitoring'
        normalized = v.sanitize(doc, self.config)
        self.assertEqual(normalized['spec']['template']['metadata']['annotations'], {'keep': 'visible'})

    def test_environment_does_not_inherit_credentials(self):
        with patch.dict(v.os.environ, {'KUBECONFIG': '/private/config', 'AWS_SECRET_ACCESS_KEY': 'fake', 'HELM_PLUGINS': '/plugins'}):
            env = v.isolated_env()
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)
        self.assertNotEqual(env['KUBECONFIG'], '/private/config')
        self.assertNotEqual(env['HELM_PLUGINS'], '/plugins')

    def test_real_policies_catch_unsafe_inputs(self):
        if not (v.CACHE / 'bin/conftest').exists():
            self.skipTest('bootstrap required for policy integration')
        app = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
               'metadata': {'name': 'test', 'namespace': 'argocd'}, 'spec': {}}
        self.assertEqual(v.policies(v.ROOT, [app], {}, [], [], self.config), [])
        for policy in ({'automated': {}}, {'syncOptions': ['Force=true']}, {'syncOptions': ['Replace=true']}):
            candidate = copy.deepcopy(app)
            candidate['spec']['syncPolicy'] = policy
            with self.assertRaisesRegex(v.Failure, 'policy violations'):
                v.policies(v.ROOT, [candidate], {}, [], [], self.config)
        secret = resource('Secret', 'plaintext')
        secret['stringData'] = {'password': 'fake'}
        with self.assertRaisesRegex(v.Failure, 'committed-secret'):
            v.policies(v.ROOT, [], {'fixture': [secret]}, [], [], self.config)
        monitoring = copy.deepcopy(app)
        monitoring['metadata']['name'] = 'kube-prometheus-stack'
        with self.assertRaisesRegex(v.Failure, 'monitoring-ignore'):
            v.policies(v.ROOT, [monitoring], {}, [], [], self.config)

    def test_nested_applications_are_rejected_before_policy_evaluation(self):
        app = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
               'metadata': {'name': 'nested', 'namespace': 'argocd'}, 'spec': {}}
        for origin in ('fixture.yaml', 'chart:argo-cd'):
            for automated in (False, True):
                with self.subTest(origin=origin, automated=automated):
                    candidate = copy.deepcopy(app)
                    if automated:
                        candidate['spec']['syncPolicy'] = {'automated': {'prune': True, 'selfHeal': True}}
                    rendered = entry(candidate)
                    rendered['file'] = origin
                    with self.assertRaisesRegex(v.Failure, 'unsupported nested Application: argoproj.io/Application/argocd/nested'):
                        v.policies(v.ROOT, [], {origin: [candidate]}, [rendered], [], self.config)

    def test_scanner_detects_secret_and_keeps_output_redacted(self):
        if not (v.CACHE / 'bin/gitleaks').exists():
            self.skipTest('bootstrap required for scanner integration')
        with tempfile.TemporaryDirectory(dir=v.CACHE) as temp:
            root = Path(temp)
            # Synthetic test token assembled at runtime; never a real credential.
            token = 'ghp_' + 'aB3dE6fG9hJ2kL5mN8pQ1rS4tU7vW0xY3zA6bC9d'
            (root / 'fixture.txt').write_text('api_key = "' + token + '"\n')
            with self.assertRaisesRegex(v.Failure, 'secret scanning failed') as caught:
                v.scan_files(root, {}, ['fixture.txt'])
            self.assertNotIn(token, str(caught.exception))
            self.assertIn('fixture.txt', str(caught.exception))

    def test_secret_rotation_is_visible_without_payload(self):
        old = resource('Secret', 'credential')
        old['data'] = {'token': 'fake-before'}
        new = copy.deepcopy(old)
        new['data']['token'] = 'fake-after'
        result = v.changes([entry(old)], [entry(new)], self.config)
        self.assertEqual(result[0]['change'], 'modified')
        self.assertNotIn('fake-', json.dumps(result))

    def test_missing_schema_and_unavailable_download_fail(self):
        custom = {'apiVersion': 'unknown.example/v1', 'kind': 'Widget', 'metadata': {'name': 'fixture'}}
        with tempfile.TemporaryDirectory(dir=v.CACHE) as temp, patch.object(v, 'schemas', return_value=(Path(temp), {})), patch.object(v, 'fetch', side_effect=v.Failure('dependency download failed')):
            with self.assertRaisesRegex(v.Failure, 'dependency download failed'):
                v.validate_schemas([entry(custom)], self.config, '1.36.5')

    def test_chart_schema_paths_cannot_escape_cache(self):
        for group, kind, version in [('../../outside', 'Widget', 'v1'), ('example.com', '../Widget', 'v1'), ('example.com', 'Widget', '../../v1')]:
            with self.assertRaisesRegex(v.Failure, 'unsafe or invalid schema'):
                v.schema_filename(group, kind, version)
        self.assertEqual(v.schema_filename('', 'Service', 'v1'), 'v1_service_v1.json')

    def test_schema_property_names_are_not_treated_as_schema_keywords(self):
        schema = {'type': 'object', 'properties': {
            'anyOf': {'type': 'array', 'items': {'type': 'object'}},
            'x-kubernetes-int-or-string': {'type': 'boolean'},
            'x-kubernetes-validations': {'type': 'array', 'items': {'type': 'object'}},
            'port': {'x-kubernetes-int-or-string': True}}}
        converted = v.convert_schema(schema)
        self.assertIsInstance(converted['properties']['anyOf'], dict)
        self.assertIn('x-kubernetes-validations', converted['properties'])
        self.assertEqual(converted['properties']['x-kubernetes-int-or-string']['type'], 'boolean')
        self.assertEqual(converted['properties']['port']['anyOf'], [{'type': 'integer'}, {'type': 'string'}])

    def test_kubeconform_core_schema_lookup_and_unknown_fields(self):
        if not (v.CACHE / 'bin/kubeconform').exists():
            self.skipTest('bootstrap required for schema integration')
        config = copy.deepcopy(self.config)
        config['external_crds'] = []
        valid = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'fixture'}, 'spec': {}}
        schema = {'type': 'object', 'properties': {'apiVersion': {'type': 'string'}, 'kind': {'type': 'string'},
                  'metadata': {'type': 'object'}, 'spec': {'type': 'object', 'additionalProperties': False}}}
        with tempfile.TemporaryDirectory(dir=v.CACHE) as temp:
            directory = Path(temp)
            (directory / 'v1_service_v1.json').write_text(json.dumps(schema))
            with patch.object(v, 'schemas', return_value=(directory, {('', 'v1', 'Service'): schema})):
                self.assertEqual(v.validate_schemas([entry(valid)], config, '1.36.5')['valid'], 1)
                valid['spec']['typo'] = True
                with self.assertRaisesRegex(v.Failure, 'schema validation failed'):
                    v.validate_schemas([entry(valid)], config, '1.36.5')

    def test_kubeconform_rejects_invalid_custom_resource(self):
        if not (v.CACHE / 'bin/kubeconform').exists():
            self.skipTest('bootstrap required for schema integration')
        crd = {'apiVersion': 'apiextensions.k8s.io/v1', 'kind': 'CustomResourceDefinition',
               'spec': {'group': 'test.example', 'names': {'kind': 'Widget'}, 'versions': [{
                   'name': 'v1', 'schema': {'openAPIV3Schema': {'type': 'object', 'properties': {
                       'spec': {'type': 'object', 'properties': {'replicas': {'type': 'integer'}}}}}}}]}}
        config = copy.deepcopy(self.config)
        config['external_crds'] = []
        widget = {'apiVersion': 'test.example/v1', 'kind': 'Widget', 'metadata': {'name': 'fixture'}, 'spec': {'replicas': 'wrong'}}
        with tempfile.TemporaryDirectory(dir=v.CACHE) as temp, patch.object(v, 'CACHE', Path(temp)):
            directory, _ = v.schemas([entry(crd)], config)
            with patch.object(v, 'schemas', return_value=(directory, {('test.example', 'v1', 'Widget'): {}})), patch.object(v, 'tool', return_value=v.ROOT / 'verification/cache/bin/kubeconform'):
                valid = copy.deepcopy(widget)
                valid['spec']['replicas'] = 2
                self.assertEqual(v.validate_schemas([entry(valid)], config, '1.36.5')['valid'], 1)
                with self.assertRaisesRegex(v.Failure, 'schema validation failed'):
                    v.validate_schemas([entry(widget)], config, '1.36.5')


if __name__ == '__main__':
    unittest.main()
