"""Focused checks for the reset milestone, not model/provider acceptance."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class LearningCoachCliTests(unittest.TestCase):
    def setUp(self):
        self.resources = list(yaml.safe_load_all((ROOT / 'hermes/profiles/learning-coach/resources.yaml').read_text()))
        self.deployment = next(r for r in self.resources if r['kind'] == 'Deployment')
        self.pod = self.deployment['spec']['template']['spec']
        self.container = self.pod['containers'][0]

    def test_only_one_cli_workload_and_its_storage(self):
        self.assertEqual([r['kind'] for r in self.resources], ['Namespace', 'PersistentVolumeClaim', 'Deployment'])
        self.assertEqual(self.deployment['metadata']['namespace'], 'learning-coach')
        self.assertEqual(self.deployment['spec']['replicas'], 1)
        self.assertEqual(self.deployment['spec']['strategy']['type'], 'Recreate')
        self.assertEqual(self.container['args'], ['sleep', 'infinity'])
        self.assertNotIn('command', self.container)
        self.assertNotIn('ports', self.container)

    def test_fresh_state_without_shared_credentials(self):
        self.assertFalse(self.pod['automountServiceAccountToken'])
        self.assertEqual(self.pod['volumes'], [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'learning-coach-data'}}])
        self.assertEqual(self.container['volumeMounts'], [{'name': 'data', 'mountPath': '/opt/data'}])
        self.assertEqual({v['name'] for v in self.container['env']}, {'HERMES_HOME', 'HERMES_WRITE_SAFE_ROOT'})
        self.assertNotIn('envFrom', self.container)
        self.assertNotIn('initContainers', self.pod)

    def test_pinned_official_runtime_and_bootstrap(self):
        self.assertEqual(self.container['image'], 'nousresearch/hermes-agent:v0.23.2@sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459')
        self.assertFalse(self.container['securityContext']['allowPrivilegeEscalation'])
        self.assertEqual(self.container['securityContext']['capabilities']['drop'], ['ALL'])
        self.assertEqual(self.container['readinessProbe']['exec']['command'], ['/command/s6-setuidgid', 'hermes', '/bin/test', '-w', '/opt/data'])

    def test_manual_gitops_and_complete_raw_selection(self):
        app = yaml.safe_load((ROOT / 'argocd/apps/learning-coach.yaml').read_text())
        self.assertEqual(app['spec']['source']['targetRevision'], 'main')
        self.assertEqual(app['spec']['source']['path'], 'hermes/profiles/learning-coach')
        self.assertEqual(app['spec']['source']['directory']['include'], 'resources.yaml')
        self.assertNotIn('automated', app['spec']['syncPolicy'])
        self.assertNotIn('finalizers', app['metadata'])

    def test_claim_is_not_automatically_pruned(self):
        pvc = self.resources[1]
        self.assertEqual(pvc['metadata']['namespace'], 'learning-coach')
        self.assertEqual(pvc['metadata']['annotations']['argocd.argoproj.io/sync-options'], 'Prune=false,Delete=false')
        self.assertEqual(pvc['spec']['accessModes'], ['ReadWriteOnce'])
        self.assertEqual(pvc['spec']['storageClassName'], 'longhorn')


if __name__ == '__main__':
    unittest.main()
