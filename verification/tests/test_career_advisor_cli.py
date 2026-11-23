"""Manifest checks only. These do not establish Grok entitlement or inference."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class CareerAdvisorCliTests(unittest.TestCase):
    def setUp(self):
        self.resources = list(yaml.safe_load_all((ROOT / 'hermes/profiles/career-advisor/resources.yaml').read_text()))
        self.deployment = self.resources[2]
        self.pod = self.deployment['spec']['template']['spec']
        self.container = self.pod['containers'][0]

    def test_single_isolated_cli(self):
        self.assertEqual([r['kind'] for r in self.resources], ['Namespace', 'PersistentVolumeClaim', 'Deployment'])
        self.assertEqual(self.resources[0]['metadata']['name'], 'career-advisor')
        self.assertEqual(self.deployment['metadata']['namespace'], 'career-advisor')
        self.assertEqual(self.deployment['metadata']['annotations']['homelab/display-name'], 'Career advisor')
        self.assertEqual(self.deployment['spec']['replicas'], 1)
        self.assertEqual(self.deployment['spec']['strategy']['type'], 'Recreate')
        self.assertEqual(self.container['args'], ['sleep', 'infinity'])
        self.assertNotIn('command', self.container)
        self.assertNotIn('ports', self.container)

    def test_no_shared_credentials_or_authority(self):
        self.assertFalse(self.pod['automountServiceAccountToken'])
        self.assertEqual(self.pod['volumes'], [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'career-advisor-data'}}])
        self.assertEqual(self.container['volumeMounts'], [{'name': 'data', 'mountPath': '/opt/data'}])
        self.assertEqual(self.container['env'], [{'name': 'HERMES_HOME', 'value': '/opt/data'}, {'name': 'HERMES_WRITE_SAFE_ROOT', 'value': '/opt/data'}])
        self.assertNotIn('envFrom', self.container)
        self.assertNotIn('initContainers', self.pod)

    def test_pinned_official_runtime(self):
        self.assertEqual(self.container['image'], 'nousresearch/hermes-agent:v0.23.2@sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459')
        self.assertFalse(self.container['securityContext']['allowPrivilegeEscalation'])
        self.assertEqual(self.container['securityContext']['capabilities']['drop'], ['ALL'])
        self.assertEqual(self.container['readinessProbe']['exec']['command'], ['/command/s6-setuidgid', 'hermes', '/bin/test', '-w', '/opt/data'])

    def test_manual_gitops(self):
        app = yaml.safe_load((ROOT / 'argocd/apps/career-advisor.yaml').read_text())
        self.assertEqual(app['spec']['source']['targetRevision'], 'main')
        self.assertEqual(app['spec']['source']['path'], 'hermes/profiles/career-advisor')
        self.assertEqual(app['spec']['source']['directory']['include'], '{resources.yaml,backup-*.yaml}')
        self.assertEqual(app['spec']['destination']['namespace'], 'career-advisor')
        self.assertNotIn('automated', app['spec']['syncPolicy'])
        self.assertNotIn('finalizers', app['metadata'])

    def test_storage_preservation(self):
        pvc = self.resources[1]
        self.assertEqual(pvc['metadata']['namespace'], 'career-advisor')
        self.assertEqual(pvc['metadata']['annotations']['argocd.argoproj.io/sync-options'], 'Prune=false,Delete=false')
        self.assertEqual(pvc['spec']['accessModes'], ['ReadWriteOnce'])
        self.assertEqual(pvc['spec']['storageClassName'], 'longhorn')
        self.assertEqual(pvc['spec']['resources']['requests']['storage'], '2Gi')


if __name__ == '__main__':
    unittest.main()
