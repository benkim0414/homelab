"""Read-only recovery baseline contracts; no live authentication or database I/O."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('langfuse_recovery_preflight',
                                             ROOT / 'langfuse/recovery/preflight.py')
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def baseline():
    claims = []
    volumes = []
    for name, (uid, size) in preflight.CLAIMS.items():
        claims.append({'name': name, 'uid': uid, 'volume': 'pvc-' + uid,
                       'size': size, 'requested': size, 'phase': 'Bound', 'class': 'longhorn',
                       'owners': '<none>', 'deleting': '<none>'})
        volumes.append({'name': 'pvc-' + uid, 'claim': name, 'namespace': 'langfuse',
                        'claim_uid': uid, 'handle': 'pvc-' + uid, 'driver': 'driver.longhorn.io',
                        'phase': 'Bound', 'size': size, 'reclaim': 'Delete'})
    return {'pods': [{'name': 'fixture-' + name, 'containers': name, 'phase': 'Running',
                      'images': 'fixture@sha256:' + preflight.IMAGE_DIGESTS[name],
                      'image_ids': 'fixture@sha256:' + preflight.IMAGE_DIGESTS[name],
                      'ready': 'true', 'restarts': '0', 'initialized': 'True',
                      'pod_ready': 'True', 'deleting': '<none>'}
                     for name in sorted(preflight.CONTAINERS)],
            'claims': claims, 'volumes': volumes, 'sync': 'Synced', 'health': 'Healthy',
            'sync_policy': {'syncOptions': ['CreateNamespace=true']}, 'operation_active': False,
            'readiness': {'status': 'OK', 'version': '4.77.0'}, 'jobs': [], 'cronjobs': [],
            'nas': {'destination_exists': False, 'mounted': True}}


class RecoveryPreflightTests(unittest.TestCase):
    def test_positive_baseline(self):
        self.assertEqual(preflight.validate(baseline()), [])

    def test_each_storage_identity_and_lifecycle_contradiction(self):
        for key, value in [('uid', 'different'), ('volume', 'different'), ('size', '5Gi'),
                           ('requested', '5Gi'), ('phase', 'Pending'), ('class', 'other'),
                           ('owners', 'deletion-owner'), ('deleting', '2026-11-21')]:
            with self.subTest(key=key):
                snapshot = baseline()
                snapshot['claims'][0][key] = value
                self.assertTrue(preflight.validate(snapshot))
        for key in ['name', 'claim', 'namespace', 'claim_uid', 'handle', 'driver',
                    'phase', 'size', 'reclaim']:
            with self.subTest(volume=key):
                snapshot = baseline()
                snapshot['volumes'][0][key] = 'different'
                self.assertTrue(preflight.validate(snapshot))

    def test_missing_duplicate_extra_workloads_and_claims_fail(self):
        for kind in ['pods', 'claims']:
            for change in ['missing', 'duplicate']:
                snapshot = baseline()
                if change == 'missing':
                    snapshot[kind].pop()
                else:
                    snapshot[kind].append(copy.deepcopy(snapshot[kind][0]))
                self.assertTrue(preflight.validate(snapshot))

    def test_not_ready_deleting_or_restarted_pod_fails(self):
        for key, value in [('phase', 'Pending'), ('ready', 'false'), ('restarts', '1'),
                           ('initialized', 'False'), ('pod_ready', 'Unknown'),
                           ('deleting', '2026-11-21')]:
            snapshot = baseline()
            snapshot['pods'][0][key] = value
            self.assertTrue(preflight.validate(snapshot))

    def test_unknown_image_or_unresolved_platform_identity_is_not_accepted(self):
        for field in ['images', 'image_ids']:
            snapshot = baseline()
            snapshot['pods'][0][field] = 'fixture@sha256:' + '0' * 64
            self.assertTrue(preflight.validate(snapshot))

    def test_operation_automation_destination_and_health_contradictions(self):
        for key, value in [('operation_active', True), ('sync', 'OutOfSync'),
                           ('health', 'Progressing'), ('sync_policy', {'automated': {}}),
                           ('jobs', [{'name': 'unexpected'}]),
                           ('cronjobs', [{'name': 'unexpected'}]),
                           ('readiness', {'status': 'OK', 'version': 'other'})]:
            snapshot = baseline()
            snapshot[key] = value
            self.assertTrue(preflight.validate(snapshot))
        for key, value in [('destination_exists', True), ('mounted', False)]:
            snapshot = baseline()
            snapshot['nas'][key] = value
            self.assertTrue(preflight.validate(snapshot))

    def test_table_requests_only_selected_metadata_and_refuses_bad_shape(self):
        with mock.patch.object(preflight, 'command', return_value='one uid') as run:
            self.assertEqual(preflight.table('pvc', [('name', '.metadata.name'),
                                                     ('uid', '.metadata.uid')]),
                             [{'name': 'one', 'uid': 'uid'}])
            args = run.call_args.args[0]
            self.assertIn('get', args)
            self.assertNotIn('secret', ' '.join(args).lower())
        with mock.patch.object(preflight, 'command', return_value='one uid extra'):
            with self.assertRaises(preflight.PreflightError):
                preflight.table('pvc', [('name', '.metadata.name')])

    def test_raw_command_diagnostics_are_never_propagated(self):
        result = subprocess.CompletedProcess(['fixture'], 1, 'PRIVATE', 'PRIVATE')
        with mock.patch.object(preflight.subprocess, 'run', return_value=result):
            with self.assertRaises(preflight.PreflightError) as exc:
                preflight.command(['fixture'])
            self.assertNotIn('PRIVATE', str(exc.exception))

    def test_receipts_are_private_non_overwriting_and_never_accept_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'verification/cache'
            cache.mkdir(parents=True)
            output = cache / 'receipt.json'
            snapshot = baseline()
            snapshot.update(issues=[], baseline_passed=True, recovery_accepted=False)
            with mock.patch.object(preflight, 'ROOT', root), \
                    mock.patch.object(preflight, 'collect', return_value=snapshot), \
                    mock.patch('sys.argv', ['preflight', '--output', str(output)]), \
                    mock.patch('sys.stdout', new_callable=io.StringIO), \
                    mock.patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(preflight.main(), 0)
                original = output.read_bytes()
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertFalse(json.loads(original)['recovery_accepted'])
                self.assertEqual(preflight.main(), 1)
                self.assertEqual(output.read_bytes(), original)

    def test_output_outside_cache_or_symlink_is_rejected_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'verification/cache'
            cache.mkdir(parents=True)
            target = root / 'outside'
            link = cache / 'link'
            link.symlink_to(target)
            for output in [target, link, cache / '..' / 'outside.json']:
                with mock.patch.object(preflight, 'ROOT', root), \
                        mock.patch.object(preflight, 'collect') as collect, \
                        mock.patch('sys.argv', ['preflight', '--output', str(output)]), \
                        mock.patch('sys.stderr', new_callable=io.StringIO):
                    with self.assertRaises(SystemExit):
                        preflight.main()
                    collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
