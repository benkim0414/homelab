"""Static contracts for the private Langfuse installation."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


class LangfuseTests(unittest.TestCase):
    def test_manual_application_and_explicit_sources(self):
        app = load('argocd/apps/langfuse.yaml')
        self.assertNotIn('finalizers', app['metadata'])
        self.assertNotIn('automated', app['spec'].get('syncPolicy', {}))
        sources = app['spec']['sources']
        chart = next(s for s in sources if 'chart' in s)
        self.assertEqual(chart['chart'], 'langfuse')
        self.assertEqual(chart['targetRevision'], '2.2.4')
        self.assertEqual(chart['helm']['releaseName'], 'langfuse')
        self.assertEqual(chart['helm']['valueFiles'], ['$repo/langfuse/values.yaml'])
        raw = next(s for s in sources if s.get('path') == 'langfuse')
        self.assertEqual(raw['directory']['include'],
                         '{namespace.yaml,clickhouse.yaml,objectstore.yaml,network-policy.yaml,tailscale-ingress.yaml,*-sealed-secret.yaml}')

    def test_stable_secrets_and_private_single_node_stores(self):
        values = load('langfuse/values.yaml')
        app = values['langfuse']
        for item in (app['salt'], app['encryptionKey'], app['nextauth']['secret']):
            self.assertEqual(item['secretKeyRef']['name'], 'langfuse-app-credentials')
            self.assertNotIn('value', item)
        self.assertTrue(app['features']['signUpDisabled'])
        self.assertFalse(app['features']['telemetryEnabled'])
        self.assertFalse(app['gateway']['enabled'])
        self.assertFalse(app['ingress']['enabled'])
        self.assertTrue(app['nextauth']['url'].startswith('https://langfuse.'))
        self.assertFalse(values['clickhouse']['deploy'])
        self.assertFalse(values['clickhouse']['cluster']['enabled'])
        self.assertEqual(values['postgresql']['auth']['existingSecret'], 'langfuse-postgresql-auth')
        self.assertEqual(values['redis']['auth']['existingSecret'], 'langfuse-redis-auth')
        self.assertIn('noeviction', values['redis']['valkeyConfig'])
        self.assertTrue(values['redis']['dataStorage']['keepPvc'])
        self.assertFalse(values['s3']['mediaUpload']['enabled'])
        self.assertFalse(values['s3']['batchExport']['enabled'])
        self.assertFalse(values['s3']['deploy'])
        self.assertEqual(values['s3']['endpoint'], 'http://langfuse-s3:8333')
        self.assertEqual(values['s3']['mediaUpload']['maxContentLength'], '1000000000')
        self.assertEqual(values['redis']['deploymentStrategy'], 'Recreate')

    def test_objectstore_has_no_cluster_permissions_or_generated_credentials(self):
        docs = list(yaml.safe_load_all((ROOT / 'langfuse/objectstore.yaml').read_text()))
        self.assertEqual({d['kind'] for d in docs},
                         {'ConfigMap', 'PersistentVolumeClaim', 'Service', 'Deployment', 'Job'})
        deployment = next(d for d in docs if d['kind'] == 'Deployment')
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        pod = deployment['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertTrue(pod['securityContext']['runAsNonRoot'])
        container = pod['containers'][0]
        self.assertIn('-s3.config=/etc/sw/s3/seaweedfs_s3_config', container['args'])
        self.assertFalse(any('sftp' in arg for arg in container['args']))
        self.assertEqual(container['securityContext']['capabilities']['drop'], ['ALL'])
        job = next(d for d in docs if d['kind'] == 'Job')
        self.assertEqual(job['metadata']['annotations']['argocd.argoproj.io/hook'], 'Sync')
        self.assertFalse(job['spec']['template']['spec']['automountServiceAccountToken'])

    def test_clickhouse_volume_and_sandbox(self):
        docs = list(yaml.safe_load_all((ROOT / 'langfuse/clickhouse.yaml').read_text()))
        claim = next(d for d in docs if d['kind'] == 'PersistentVolumeClaim')
        self.assertEqual(claim['metadata']['name'], 'langfuse-clickhouse-data')
        self.assertEqual(claim['spec']['storageClassName'], 'longhorn')
        self.assertEqual(claim['metadata']['annotations']['argocd.argoproj.io/sync-options'],
                         'Prune=false,Delete=false')
        sts = next(d for d in docs if d['kind'] == 'StatefulSet')
        pod = sts['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['nodeSelector']['kubernetes.io/arch'], 'amd64')
        self.assertEqual(pod['containers'][0]['securityContext']['capabilities']['drop'], ['ALL'])

    def test_bucket_hook_is_idempotent_and_checks_creation(self):
        docs = list(yaml.safe_load_all((ROOT / 'langfuse/objectstore.yaml').read_text()))
        job = next(d for d in docs if d['kind'] == 'Job')
        script = job['spec']['template']['spec']['containers'][0]['args'][0]
        subprocess.run(['/bin/bash', '-n'], input=script, text=True, check=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weed = root / 'weed'
            weed.write_text(
                '#!/bin/sh\nread -r command\n'
                'case "$command" in\n'
                '  "s3.bucket.list") if [ -f "$STATE" ]; then printf "langfuse\\n"; fi;;\n'
                '  "s3.bucket.create --name langfuse") '
                'printf "create\\n" >> "$CALLS"; '
                'if [ "$FAIL_CREATE" = 0 ]; then : > "$STATE"; fi;;\n'
                '  *) exit 1;;\nesac\n')
            wget = root / 'wget'
            wget.write_text('#!/bin/sh\nexit 0\n')
            weed.chmod(0o700)
            wget.chmod(0o700)
            environment = dict(os.environ, PATH=f'{root}:/usr/bin:/bin',
                               STATE=str(root / 'state'), CALLS=str(root / 'calls'), FAIL_CREATE='0')
            script = script.replace('/usr/bin/weed', str(weed))
            for _ in range(2):
                result = subprocess.run(['/bin/bash', '-ec', script], env=environment,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0)
                self.assertIn('Langfuse bucket verified', result.stdout)
            self.assertEqual((root / 'calls').read_text().splitlines(), ['create'])
            (root / 'state').unlink()
            environment['FAIL_CREATE'] = '1'
            result = subprocess.run(['/bin/bash', '-ec', script], env=environment,
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Bucket creation not verified', result.stdout)

    def test_hermes_launch_configuration(self):
        documents = list(yaml.safe_load_all((ROOT / 'hermes/deployment.yaml').read_text()))
        deployment = next(d for d in documents if d['kind'] == 'Deployment')
        container = next(c for c in deployment['spec']['template']['spec']['containers']
                         if c['name'] == 'hermes')
        env = {entry['name']: entry for entry in container['env']}
        expected = {
            'HERMES_LANGFUSE_BASE_URL': 'http://langfuse-web.langfuse.svc.cluster.local:3000',
            'HERMES_LANGFUSE_CAPTURE': 'metadata',
            'HERMES_LANGFUSE_ENV': 'homelab-cluster',
            'HERMES_LANGFUSE_SAMPLE_RATE': '1',
            'OTEL_SERVICE_NAME': 'hermes-cluster',
        }
        for name, value in expected.items():
            self.assertEqual(env[name]['value'], value)
        for name, key in [('HERMES_LANGFUSE_PUBLIC_KEY', 'public-key'),
                          ('HERMES_LANGFUSE_SECRET_KEY', 'secret-key')]:
            self.assertEqual(env[name]['valueFrom']['secretKeyRef'],
                             {'name': 'hermes-langfuse', 'key': key})
        include = load('argocd/apps/hermes.yaml')['spec']['source']['directory']['include']
        self.assertIn('langfuse-sealed-secret.yaml', include.strip('{}').split(','))

    def test_hermes_has_only_web_endpoint_exception(self):
        policy = load('hermes/network-policy.yaml')
        rules = [r for r in policy['spec']['egress'] if any(
            p.get('namespaceSelector', {}).get('matchLabels', {}).get(
                'kubernetes.io/metadata.name') == 'langfuse' for p in r.get('to', []))]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['ports'], [{'protocol': 'TCP', 'port': 3000}])
        self.assertEqual(rules[0]['to'][0]['podSelector']['matchLabels'], {
            'app.kubernetes.io/instance': 'langfuse',
            'app.kubernetes.io/name': 'langfuse',
            'app.kubernetes.io/component': 'web'})


if __name__ == '__main__':
    unittest.main()
