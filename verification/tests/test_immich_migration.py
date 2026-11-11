"""Exercise deferred cutover and restore refusal paths without cluster access."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cutover', ROOT / 'immich/migration/prepare-cutover.py')
cutover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cutover)


class CutoverTests(unittest.TestCase):
    def fixture(self, root):
        for name in ('immich/postgresql.yaml', 'immich/postgresql16.yaml',
                     'immich/pg-backup-cronjob.yaml', 'renovate.json5'):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)

    def test_preparation_and_cutover_preserve_volume_templates(self):
        old, service = list(yaml.safe_load_all((ROOT / 'immich/postgresql.yaml').read_text()))
        target, target_service = list(yaml.safe_load_all((ROOT / 'immich/postgresql16.yaml').read_text()))
        active = service['spec']['selector']['app']
        self.assertIn(active, ('immich-postgres', 'immich-postgres16'))
        self.assertEqual(old['spec']['replicas'], int(active == 'immich-postgres'))
        self.assertEqual(target['spec']['replicas'], int(active == 'immich-postgres16'))
        self.assertEqual(old['spec']['volumeClaimTemplates'], target['spec']['volumeClaimTemplates'])
        self.assertNotEqual(old['metadata']['name'], target['metadata']['name'])
        self.assertEqual(target_service['spec']['selector'], target['spec']['selector']['matchLabels'])
        self.assertEqual(target_service['spec']['clusterIP'], 'None')

    def test_cutover_is_complete_and_rejects_repeat(self):
        if '  replicas: 0' in (ROOT / 'immich/postgresql.yaml').read_text():
            self.skipTest('Cutover already committed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            result = cutover.changes(root)
            old, service = list(yaml.safe_load_all(result['immich/postgresql.yaml']))
            target, _ = list(yaml.safe_load_all(result['immich/postgresql16.yaml']))
            self.assertEqual(old['spec']['replicas'], 0)
            self.assertEqual(target['spec']['replicas'], 1)
            self.assertEqual(service['spec']['selector'], {'app': 'immich-postgres16'})
            self.assertIn('postgres:14-', result['immich/postgresql.yaml'])
            self.assertIn('postgres:16-', result['immich/pg-backup-cronjob.yaml'])
            self.assertIn('/^16(?:', result['renovate.json5'])
            self.assertIn('["immich/postgresql.yaml", "immich/migration/**"]', result['renovate.json5'])
            for name, text in result.items():
                (root / name).write_text(text)
            with self.assertRaises(ValueError):
                cutover.changes(root)

    def test_unexpected_input_never_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'renovate.json5').write_text('{}')
            before = (root / 'immich/postgresql.yaml').read_bytes()
            with self.assertRaises(ValueError):
                cutover.changes(root)
            self.assertEqual(before, (root / 'immich/postgresql.yaml').read_bytes())


class RestoreTests(unittest.TestCase):
    def test_refuses_unsafe_inputs_before_database_access(self):
        baseline = dict(PGHOST='immich-postgres16', RESTORE_CONFIRM='immich-postgres16-empty',
                        RESTORE_FILE='/backups/migrations/test.dump', RESTORE_SHA256='a' * 64)
        cases = (
            ({'PGHOST': 'immich-postgres'}, 'unexpected restore host'),
            ({'RESTORE_CONFIRM': ''}, 'confirmation missing'),
            ({'RESTORE_FILE': '/backups/scheduled/test.dump'}, 'migration backups'),
            ({'RESTORE_FILE': '/backups/migrations/../scheduled/test.dump'}, 'Invalid archive path'),
            ({'RESTORE_SHA256': ''}, 'SHA256 is required'),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                result = subprocess.run(['bash', str(ROOT / 'immich/migration/restore.sh')],
                                        env={'PATH': os.environ['PATH'], **baseline, **overrides},
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_job_has_no_retry_and_readonly_archive(self):
        job = yaml.safe_load((ROOT / 'immich/migration/restore-job.yaml').read_text())
        self.assertEqual(job['spec']['backoffLimit'], 0)
        pod = job['spec']['template']['spec']
        self.assertEqual(pod['restartPolicy'], 'Never')
        self.assertFalse(pod['automountServiceAccountToken'])
        for mount in pod['containers'][0]['volumeMounts']:
            self.assertTrue(mount['readOnly'])
        self.assertNotIn('annotations', job['metadata'])


if __name__ == '__main__':
    unittest.main()
