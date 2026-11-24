"""Keep image publication explicit and separate from deployment."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/specialist-memory-image.yml'


class PublicationWorkflowTests(unittest.TestCase):
    def workflow(self):
        return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)

    def test_only_manual_main_revision_bound_publication(self):
        data = self.workflow()
        self.assertEqual(set(data['on']), {'workflow_dispatch'})
        self.assertEqual(data['permissions'], {'contents': 'read'})
        job = data['jobs']['publish']
        self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        self.assertIn('inputs.expected_sha == github.sha', job['if'])
        self.assertEqual(job['permissions'], {'contents': 'read', 'packages': 'write'})
        self.assertEqual(job['runs-on'], 'ubuntu-24.04')

    def test_acceptance_precedes_login_and_publishes_exact_image(self):
        steps = self.workflow()['jobs']['publish']['steps']
        names = [step.get('name', '') for step in steps]
        self.assertLess(names.index('Real isolated acceptance'), names.index('Publish and verify registry copy'))
        text = WORKFLOW.read_text()
        self.assertIn('acceptance_is_valid(report)', text)
        self.assertIn("report['images']['api']", text)
        self.assertIn('docker tag "$IMAGE_ID" "$IMAGE"', text)
        self.assertIn('docker pull "$published"', text)
        self.assertIn('test "$(docker image inspect "$published"', text)
        self.assertNotIn('kubectl', text)
        self.assertNotIn('argocd', text)
        self.assertNotIn('contents: write', text)
        self.assertNotIn('secrets: inherit', text)

    def test_credentials_not_persisted_or_uploaded(self):
        steps = self.workflow()['jobs']['publish']['steps']
        checkout = steps[0]
        self.assertRegex(checkout['uses'], r'^actions/checkout@[0-9a-f]{40}$')
        self.assertEqual(checkout['with']['persist-credentials'], 'false')
        upload = [step for step in steps if step.get('uses', '').startswith('actions/upload-artifact@')][0]
        self.assertEqual(upload['with']['path'], 'verification/cache/publication/*.json')
        text = WORKFLOW.read_text()
        self.assertIn('--password-stdin', text)
        self.assertIn('docker logout ghcr.io', text)
        self.assertNotIn('set -x', text)

    def test_public_models_are_readable_across_host_and_container_uids(self):
        steps = self.workflow()['jobs']['publish']['steps']
        preparation = next(s['run'] for s in steps if s.get('name') ==
                           'Prepare isolated client and pinned model data')
        self.assertIn('chmod 0755 "$models" "$models/onnx"', preparation)
        self.assertIn('chmod 0644 "$models"/{config.json,special_tokens_map.json,tokenizer.json,tokenizer_config.json,vocab.txt,onnx/model.onnx}', preparation)
        self.assertNotIn('chmod -R', preparation)


if __name__ == '__main__':
    unittest.main()
