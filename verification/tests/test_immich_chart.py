"""Validate the actual pinned chart's runtime contract using cached render inputs."""
import importlib.util
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('verify_immich', ROOT / 'scripts/verify.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class ImmichChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (verify.CACHE / 'bin/helm').exists():
            raise unittest.SkipTest('Run verification/bootstrap.py first')
        config = json.loads(verify.CONFIG.read_text())
        _, _, _, inputs = verify.read_repo(ROOT, config)
        inputs = [entry for entry in inputs if entry[0]['metadata']['name'] == 'immich']
        cls.resources = {(e['resource']['kind'], e['resource']['metadata']['name']): e['resource']
                         for e in verify.render(ROOT, inputs, verify.kubernetes_version(ROOT))}

    def test_server_image_credentials_storage_and_probes(self):
        server = self.resources['Deployment', 'immich-server']
        self.assertEqual(server['spec']['strategy']['type'], 'Recreate')
        pod = server['spec']['template']['spec']
        container = pod['containers'][0]
        values = yaml.safe_load((ROOT / 'immich/values.yaml').read_text())
        pin = values['controllers']['main']['containers']['main']['image']['tag']
        self.assertEqual(container['image'], f'ghcr.io/immich-app/immich-server:{pin}')
        env = {e['name']: e for e in container['env']}
        self.assertEqual(env['DB_HOSTNAME']['value'], 'immich-postgres')
        self.assertEqual(env['REDIS_HOSTNAME']['value'], 'immich-valkey')
        for name, key in [('DB_USERNAME', 'POSTGRES_USER'), ('DB_PASSWORD', 'POSTGRES_PASSWORD'),
                          ('DB_DATABASE_NAME', 'POSTGRES_DB')]:
            self.assertEqual(env[name]['valueFrom']['secretKeyRef'],
                             {'name': 'immich-db-credentials', 'key': key})
        self.assertEqual(container['startupProbe']['failureThreshold'], 60)
        mount = next(m for m in container['volumeMounts'] if m['mountPath'] == '/data')
        volume = next(v for v in pod['volumes'] if v['name'] == mount['name'])
        self.assertEqual(volume['persistentVolumeClaim']['claimName'], 'immich-library')

    def test_exposure_and_queue(self):
        service = self.resources['Service', 'immich-server']['spec']
        self.assertEqual(service['type'], 'LoadBalancer')
        self.assertEqual(service['loadBalancerIP'], '192.168.0.201')
        self.assertEqual(service['ports'][0]['port'], 2283)
        labels = self.resources['Deployment', 'immich-server']['spec']['template']['metadata']['labels']
        self.assertTrue(all(labels.get(k) == v for k, v in service['selector'].items()))
        self.assertFalse(any('machine-learning' in name for _, name in self.resources))
        pod = self.resources['Deployment', 'immich-valkey']['spec']['template']['spec']
        self.assertTrue(any('emptyDir' in v for v in pod['volumes']))
        self.assertEqual(pod['containers'][0]['resources']['limits']['memory'], '128Mi')


if __name__ == '__main__':
    unittest.main()
