"""Exercise the real pinned chart, using the repository verifier's render path.

Run the full verifier first to populate its chart cache. These tests use no cluster
credentials and never display generated Secret values or full rendered objects.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('langfuse_verify', ROOT / 'scripts/verify.py')
assert SPEC is not None and SPEC.loader is not None
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)


class LangfuseRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = hashlib.sha256(
            b'https://langfuse.github.io/langfuse-k8s/langfuse@2.2.4').hexdigest()
        if not (v.CACHE / 'bin/helm').is_file() or not (
                v.CACHE / 'charts' / key / 'chart.tgz').is_file():
            raise unittest.SkipTest('run bootstrap and full verifier to populate pinned chart cache')
        _, _, raw, charts = v.read_repo(ROOT, json.loads(v.CONFIG.read_text()))
        cls.inputs = [entry for entry in charts if entry[0]['metadata']['name'] == 'langfuse']
        cls.raw = [entry['resource'] for entry in raw if entry['app'] == 'langfuse']
        cls.version = v.kubernetes_version(ROOT)
        cls.docs = [entry['resource'] for entry in v.render(ROOT, cls.inputs, cls.version)]

    def test_render_is_deterministic(self):
        second = [entry['resource'] for entry in v.render(ROOT, self.inputs, self.version)]
        self.assertTrue(self.docs == second, 'chart render changes between identical invocations')

    def test_all_workload_images_are_immutable(self):
        for doc in self.docs + self.raw:
            if doc['kind'] not in {'Deployment', 'StatefulSet', 'Job'}:
                continue
            pod = doc['spec']['template']['spec']
            for container in pod.get('containers', []) + pod.get('initContainers', []):
                with self.subTest(workload=doc['metadata']['name'], container=container['name']):
                    self.assertRegex(container['image'], r'@sha256:[0-9a-f]{64}$')

    def test_no_generated_credential_payloads_or_cluster_operators(self):
        for doc in self.docs:
            with self.subTest(kind=doc['kind'], name=doc['metadata']['name']):
                if doc['kind'] == 'Secret':
                    self.assertFalse(bool(doc.get('data')), 'unexpected generated Secret data')
                    self.assertFalse(bool(doc.get('stringData')), 'unexpected generated Secret stringData')
                self.assertNotIn(doc['kind'], {
                    'ClickHouseCluster', 'KeeperCluster', 'CustomResourceDefinition',
                    'CronJob', 'ClusterRole', 'ClusterRoleBinding'})
                if doc['kind'] == 'Service':
                    self.assertEqual(doc['spec'].get('type', 'ClusterIP'), 'ClusterIP')

    def test_web_worker_have_scoped_secret_references(self):
        deployments = {d['metadata']['name']: d for d in self.docs if d['kind'] == 'Deployment'}
        for name in ('langfuse-web', 'langfuse-worker'):
            pod = deployments[name]['spec']['template']['spec']
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertEqual(pod['securityContext']['seccompProfile']['type'], 'RuntimeDefault')
            # A container securityContext belongs in the container, never PodSpec.
            self.assertNotIn('capabilities', pod['securityContext'])
            container = pod['containers'][0]
            self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
            self.assertEqual(container['securityContext']['capabilities']['drop'], ['ALL'])
            env = {entry['name']: entry for entry in container['env']}
            for variable, key in [('SALT', 'salt'), ('ENCRYPTION_KEY', 'encryption-key'),
                                  ('NEXTAUTH_SECRET', 'nextauth-secret')]:
                if variable == 'NEXTAUTH_SECRET' and name.endswith('worker'):
                    continue
                self.assertEqual(env[variable]['valueFrom']['secretKeyRef'],
                                 {'name': 'langfuse-app-credentials', 'key': key})
            self.assertEqual(env['CLICKHOUSE_CLUSTER_ENABLED']['value'], 'false')
            if name.endswith('worker'):
                self.assertNotIn('LANGFUSE_INIT_USER_PASSWORD', env)
            else:
                self.assertEqual(env['LANGFUSE_INIT_USER_PASSWORD']['valueFrom']['secretKeyRef'],
                                 {'name': 'langfuse-bootstrap', 'key': 'password'})

    def test_four_persistent_longhorn_stores(self):
        claims = [d for d in self.docs + self.raw if d['kind'] == 'PersistentVolumeClaim']
        for doc in self.docs:
            if doc['kind'] == 'StatefulSet':
                claims.extend(doc['spec'].get('volumeClaimTemplates', []))
        self.assertEqual(len(claims), 4)
        self.assertEqual(sorted(c['spec']['resources']['requests']['storage'] for c in claims),
                         ['10Gi', '20Gi', '30Gi', '5Gi'])
        for claim in claims:
            self.assertEqual(claim['spec']['storageClassName'], 'longhorn')

    def test_ingress_matches_web_labels_and_internal_only(self):
        web = next(d for d in self.docs if d['kind'] == 'Deployment'
                   and d['metadata']['name'] == 'langfuse-web')
        labels = web['spec']['template']['metadata']['labels']
        self.assertTrue(all(labels.get(k) == value for k, value in {
            'app.kubernetes.io/name': 'langfuse',
            'app.kubernetes.io/instance': 'langfuse',
            'app.kubernetes.io/component': 'web'}.items()))
        ingresses = [d for d in self.docs + self.raw if d['kind'] == 'Ingress']
        self.assertEqual(len(ingresses), 1)
        self.assertEqual(ingresses[0]['spec']['ingressClassName'], 'tailscale')
        self.assertEqual(ingresses[0]['spec']['defaultBackend']['service']['name'], 'langfuse-web')


if __name__ == '__main__':
    unittest.main()
