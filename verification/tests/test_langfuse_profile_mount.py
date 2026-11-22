"""Contracts for the approved scoped Langfuse credential mount."""
from pathlib import Path
import importlib.util
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class LangfuseProfileMountTests(unittest.TestCase):
    def test_approved_storage_growth_preserves_claim_contract(self):
        claim = yaml.safe_load((ROOT / 'hermes/profiles/house-manager/storage.yaml').read_text())
        self.assertEqual(claim['metadata']['name'], 'hermes-data')
        self.assertEqual(claim['metadata']['namespace'], 'hermes')
        self.assertEqual(claim['metadata']['annotations']['argocd.argoproj.io/sync-options'],
                         'Prune=false,Delete=false')
        self.assertEqual(claim['spec']['storageClassName'], 'longhorn')
        self.assertEqual(claim['spec']['accessModes'], ['ReadWriteOnce'])
        self.assertEqual(claim['spec']['resources']['requests']['storage'], '20Gi')

    def test_constructor_settings_are_scoped_not_ambient_only(self):
        spec = importlib.util.spec_from_file_location('scoped_source', ROOT / 'hermes/profiles/house-manager/langfuse-key-source.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.SCOPED_SETTINGS, {
            'HERMES_LANGFUSE_BASE_URL': 'http://langfuse-web.langfuse.svc.cluster.local:3000',
            'HERMES_LANGFUSE_CAPTURE': 'metadata',
            'HERMES_LANGFUSE_ENV': 'homelab-cluster',
            'HERMES_LANGFUSE_SAMPLE_RATE': '1',
        })
        docs = list(yaml.safe_load_all((ROOT / 'hermes/profiles/house-manager/deployment.yaml').read_text()))
        deployment = next(d for d in docs if d['kind'] == 'Deployment')
        container = next(c for c in deployment['spec']['template']['spec']['containers']
                         if c['name'] == 'hermes')
        env = {entry['name']: entry.get('value') for entry in container['env']}
        for name, value in module.SCOPED_SETTINGS.items():
            self.assertEqual(env[name], value)

    def test_read_only_mounts_preserve_existing_storage(self):
        docs = list(yaml.safe_load_all((ROOT / 'hermes/profiles/house-manager/deployment.yaml').read_text()))
        deployment = next(d for d in docs if d['kind'] == 'Deployment')
        pod = deployment['spec']['template']['spec']
        volumes = {v['name']: v for v in pod['volumes']}
        self.assertEqual(volumes['langfuse-credentials']['secret'], {
            'secretName': 'hermes-langfuse', 'defaultMode': 0o440,
            'items': [{'key': 'public-key', 'path': 'public-key'},
                      {'key': 'secret-key', 'path': 'secret-key'}],
        })
        self.assertEqual(volumes['langfuse-key-source']['configMap'], {
            'name': 'hermes-langfuse-key-source', 'defaultMode': 0o444,
            'items': [{'key': 'langfuse-key-source.py', 'path': 'langfuse-key-source.py'}],
        })
        self.assertEqual(volumes['data']['persistentVolumeClaim']['claimName'], 'hermes-data')
        container = next(c for c in pod['containers'] if c['name'] == 'hermes')
        mounts = {m['name']: m for m in container['volumeMounts']}
        for name, path in [('langfuse-credentials', '/var/run/hermes-langfuse'),
                           ('langfuse-key-source', '/langfuse-key-source')]:
            self.assertEqual(mounts[name], {'name': name, 'mountPath': path, 'readOnly': True})
        for container in pod.get('initContainers', []):
            self.assertFalse(any(m['name'].startswith('langfuse-')
                                 for m in container.get('volumeMounts', [])))
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        self.assertFalse(pod['automountServiceAccountToken'])

    def test_helper_configmap_matches_tested_source_and_is_selected(self):
        source = ROOT / 'hermes/profiles/house-manager/langfuse-key-source.py'
        manifest = yaml.safe_load((ROOT / 'hermes/profiles/house-manager/langfuse-key-source.yaml').read_text())
        self.assertEqual(manifest['kind'], 'ConfigMap')
        self.assertEqual(manifest['metadata'], {
            'name': 'hermes-langfuse-key-source', 'namespace': 'hermes'})
        self.assertEqual(manifest['data'], {'langfuse-key-source.py': source.read_text()})
        app = yaml.safe_load((ROOT / 'argocd/apps/hermes.yaml').read_text())
        self.assertIn('langfuse-key-source.yaml',
                      app['spec']['source']['directory']['include'].strip('{}').split(','))
        self.assertNotIn('automated', app['spec']['syncPolicy'])


if __name__ == '__main__':
    unittest.main()
