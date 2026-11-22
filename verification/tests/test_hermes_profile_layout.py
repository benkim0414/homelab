"""Repository profiles remain separate Kubernetes workloads, not shared state."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class HermesProfileLayoutTests(unittest.TestCase):
    def test_application_paths_preserve_runtime_namespaces(self):
        for application, profile, namespace in (
            ('hermes', 'house-manager', 'hermes'),
            ('learning-coach', 'learning-coach', 'learning-coach'),
            ('career-advisor', 'career-advisor', 'career-advisor'),
        ):
            with self.subTest(profile=profile):
                app = yaml.safe_load((ROOT / f'argocd/apps/{application}.yaml').read_text())
                self.assertEqual(app['metadata']['name'], application)
                self.assertEqual(app['spec']['source']['path'], f'hermes/profiles/{profile}')
                self.assertEqual(app['spec']['source']['targetRevision'], 'main')
                self.assertEqual(app['spec']['destination']['namespace'], namespace)
                self.assertNotIn('automated', app['spec']['syncPolicy'])
                self.assertNotIn('finalizers', app['metadata'])
                self.assertTrue((ROOT / f'hermes/profiles/{profile}/README.md').is_file())

    def test_specialists_retain_independent_claims(self):
        for profile in ('learning-coach', 'career-advisor'):
            with self.subTest(profile=profile):
                docs = list(yaml.safe_load_all((ROOT / f'hermes/profiles/{profile}/resources.yaml').read_text()))
                claim = next(doc for doc in docs if doc['kind'] == 'PersistentVolumeClaim')
                deployment = next(doc for doc in docs if doc['kind'] == 'Deployment')
                self.assertEqual(claim['metadata']['name'], f'{profile}-data')
                self.assertEqual(claim['metadata']['namespace'], profile)
                self.assertEqual(deployment['metadata']['namespace'], profile)
                self.assertEqual(deployment['spec']['template']['spec']['volumes'], [
                    {'name': 'data', 'persistentVolumeClaim': {'claimName': f'{profile}-data'}}
                ])

    def test_ci_uses_existing_profile_working_directories(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/verify.yml').read_text())
        steps = workflow['jobs']['checks']['steps']
        approval_step = next(step for step in steps if step.get('name') == 'Test house-manager approval boundaries')
        self.assertEqual(approval_step['working-directory'], 'hermes/profiles/house-manager/tools')
        for step in steps:
            directory = step.get('working-directory')
            if directory:
                self.assertTrue((ROOT / directory).is_dir(), directory)

    def test_no_old_top_level_profile_directories(self):
        self.assertFalse((ROOT / 'learning-coach').exists())
        self.assertFalse((ROOT / 'career-advisor').exists())
        self.assertFalse((ROOT / 'hermes/house-manager-tools').exists())
        self.assertFalse((ROOT / 'hermes/deployment.yaml').exists())
        self.assertTrue((ROOT / 'hermes/profiles/house-manager/tools').is_dir())


if __name__ == '__main__':
    unittest.main()
