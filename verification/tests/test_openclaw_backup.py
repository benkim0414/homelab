"""Exercise the backup controller's failure recovery and retention boundaries."""
import copy
import datetime as dt
from pathlib import Path
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[2]
MODULE = types.ModuleType('openclaw_backup')
SOURCE = yaml.safe_load((ROOT / 'openclaw/backup-configmap.yaml').read_text())['data']['backup.py']
exec(compile(SOURCE, 'openclaw/backup-configmap.yaml:backup.py', 'exec'), MODULE.__dict__)
VOLUME = 'pvc-16e9a707-6192-4a77-b55e-c59079a3ccda'


class FakeAPI:
    def __init__(self):
        self.deployment = {'metadata': {'annotations': {}},
                           'spec': {'replicas': 1}, 'status': {'readyReplicas': 1}}
        self.lease = None
        self.backups, self.snapshots, self.calls = {}, {}, []
        self.fail_snapshot = self.fail_backup = self.fail_resume = False
        self.volume = VOLUME

    def patch(self, path, body):
        return self.call('PATCH', path, body)

    def call(self, method, path, body=None, *args):
        self.calls.append((method, path, copy.deepcopy(body)))
        clean = urlsplit(path).path
        if clean == MODULE.CONTROL:
            if method == 'PATCH':
                annotations = self.deployment['metadata']['annotations']
                for key, value in body['metadata']['annotations'].items():
                    if value is None:
                        annotations.pop(key, None)
                    else:
                        annotations[key] = value
            return copy.deepcopy(self.deployment)
        if clean == MODULE.CONTROL + '/scale':
            replicas = body['spec']['replicas']
            if replicas == 1 and self.fail_resume:
                raise MODULE.ApiError(503, path)
            self.deployment['spec']['replicas'] = replicas
            return copy.deepcopy(self.deployment)
        if clean.startswith(MODULE.LEASE):
            if method == 'GET':
                if self.lease is None:
                    raise MODULE.ApiError(404, path)
                return copy.deepcopy(self.lease)
            if method == 'PUT':
                if body['metadata']['resourceVersion'] != self.lease['metadata']['resourceVersion']:
                    raise MODULE.ApiError(409, path)
            if method == 'POST' and self.lease is not None:
                raise MODULE.ApiError(409, path)
            self.lease = copy.deepcopy(body)
            self.lease['metadata']['resourceVersion'] = str(
                int(self.lease['metadata'].get('resourceVersion', 0)) + 1)
            return copy.deepcopy(self.lease)
        if clean.endswith('/persistentvolumeclaims/openclaw-data'):
            return {'spec': {'volumeName': self.volume}, 'status': {'phase': 'Bound'}}
        if clean.endswith('/backuptargets/default'):
            return {'spec': {'backupTargetURL': MODULE.TARGET}, 'status': {'available': True}}
        if clean.endswith('/volumes/' + VOLUME):
            return {'status': {'state': 'detached' if self.deployment['spec']['replicas'] == 0
                              else 'attached', 'robustness': 'healthy'}}
        if clean.endswith('/pods'):
            return {'items': []}
        for kind, store in [('snapshots', self.snapshots), ('backups', self.backups)]:
            prefix = MODULE.LONGHORN + '/' + kind
            if not clean.startswith(prefix):
                continue
            if method == 'POST':
                if (kind == 'snapshots' and self.fail_snapshot) or (kind == 'backups' and self.fail_backup):
                    raise MODULE.ApiError(503, path)
                item = copy.deepcopy(body)
                item['metadata']['uid'] = item['metadata']['name']
                if kind == 'snapshots':
                    item['status'] = {'readyToUse': True}
                else:
                    item['status'] = {'state': 'Completed', 'volumeName': VOLUME,
                        'url': MODULE.TARGET + '?backup=' + item['metadata']['name'],
                        'backupCreatedAt': '2026-10-19T04:00:00Z',
                        'snapshotName': item['spec']['snapshotName']}
                store[item['metadata']['name']] = item
                return copy.deepcopy(item)
            if clean == prefix:
                selector = parse_qs(urlsplit(path).query).get('labelSelector', [''])[0]
                expected = dict(part.split('=', 1) for part in selector.split(',') if part)
                return {'items': [copy.deepcopy(item) for item in store.values()
                    if all(item['metadata'].get('labels', {}).get(k) == v for k, v in expected.items())]}
            name = clean[len(prefix) + 1:]
            if method == 'DELETE':
                assert body['preconditions']['uid'] == store[name]['metadata']['uid']
                return store.pop(name)
            return copy.deepcopy(store[name])
        raise AssertionError((method, path))


class OpenClawBackupTests(unittest.TestCase):
    def runner(self, api):
        runner = MODULE.Runner(api, 'runner-1', VOLUME)
        self.assertTrue(runner.acquire())
        return runner

    def test_lease_excludes_concurrent_backup_and_recovery(self):
        api = FakeAPI()
        self.runner(api)
        other = MODULE.Runner(api, 'runner-2', VOLUME)
        self.assertFalse(other.acquire())
        api.lease['spec']['renewTime'] = MODULE.stamp(MODULE.utcnow() - dt.timedelta(minutes=5))
        self.assertTrue(other.acquire())

    def test_source_identity_change_does_not_pause_openclaw(self):
        api = FakeAPI()
        api.volume = 'pvc-replacement'
        runner = self.runner(api)
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            runner.backup()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertFalse(any(method == 'PATCH' for method, _, _ in api.calls))

    def test_snapshot_failure_resumes_without_deleting_backups(self):
        api = FakeAPI()
        api.fail_snapshot = True
        runner = self.runner(api)
        with self.assertRaises(MODULE.ApiError):
            runner.backup()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertEqual(api.lease['metadata']['annotations'], {})
        self.assertFalse(any(method == 'DELETE' for method, _, _ in api.calls))

    def test_failed_upload_resumes_and_keeps_existing_backups(self):
        api = FakeAPI()
        api.fail_backup = True
        runner = self.runner(api)
        with self.assertRaises(MODULE.ApiError):
            runner.backup()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertFalse(any(method == 'DELETE' for method, _, _ in api.calls))

    def test_failed_resume_keeps_marker_for_watchdog(self):
        api = FakeAPI()
        api.fail_resume = True
        runner = self.runner(api)
        with self.assertRaises(MODULE.ApiError):
            runner.backup()
        self.assertEqual(api.deployment['spec']['replicas'], 0)
        self.assertEqual(api.lease['metadata']['annotations'][MODULE.PREFIX + 'holder'], 'runner-1')

    def test_watchdog_retries_pause_after_an_earlier_recovery_crash(self):
        api = FakeAPI()
        api.deployment['spec']['replicas'] = 0
        self.runner(api)
        api.lease['metadata']['annotations'] = {
            MODULE.PREFIX + 'holder': 'original-backup', MODULE.PREFIX + 'replicas': '1'}
        api.lease['spec']['holderIdentity'] = 'crashed-watchdog'
        api.lease['spec']['renewTime'] = MODULE.stamp(MODULE.utcnow() - dt.timedelta(minutes=5))
        with patch.dict(MODULE.os.environ, {'POD_UID': 'new-watchdog', 'OPENCLAW_VOLUME': VOLUME,
                                           'BACKUP_MODE': 'recover'}), patch.object(MODULE, 'API', return_value=api), \
                patch.object(MODULE.signal, 'signal'):
            MODULE.main()
        self.assertEqual(api.deployment['spec']['replicas'], 1)
        self.assertEqual(api.lease['metadata']['annotations'], {})
        self.assertEqual(api.lease['spec']['holderIdentity'], '')

    def test_retention_keeps_seven_successes_and_other_policies(self):
        api = FakeAPI()
        labels = {'backup-volume': VOLUME, 'backup-target': 'default', MODULE.PREFIX + 'policy': MODULE.POLICY}
        for day in range(1, 9):
            name = f'older-{day:02}'
            api.backups[name] = {'metadata': {'name': name, 'uid': name, 'labels': labels},
                'spec': {'snapshotName': name}, 'status': {'state': 'Completed', 'volumeName': VOLUME,
                    'url': MODULE.TARGET + '?backup=' + name, 'backupCreatedAt': f'2026-10-{day:02}T04:00:00Z'}}
            api.snapshots[name] = {'metadata': {'name': name, 'uid': name,
                'labels': {MODULE.PREFIX + 'policy': MODULE.POLICY}}, 'spec': {'volume': VOLUME}}
        api.backups['manual'] = {'metadata': {'name': 'manual', 'uid': 'manual', 'labels': {}}, 'spec': {}}
        api.backups['pending'] = {'metadata': {'name': 'pending', 'uid': 'pending', 'labels': labels},
                                  'spec': {}, 'status': {'state': 'Pending'}}
        self.runner(api).backup()
        self.assertNotIn('older-01', api.backups)
        self.assertNotIn('older-02', api.backups)
        self.assertNotIn('older-01', api.snapshots)
        self.assertNotIn('older-02', api.snapshots)
        self.assertIn('manual', api.backups)
        self.assertIn('pending', api.backups)
        self.assertEqual(len(api.backups), 9)  # Seven successes plus unrelated/pending entries.
        calls = api.calls
        resumed = next(i for i, (m, p, b) in enumerate(calls)
                       if m == 'PATCH' and p.endswith('/scale') and b['spec']['replicas'] == 1)
        deleted = next(i for i, (m, _, _) in enumerate(calls) if m == 'DELETE')
        self.assertLess(resumed, deleted)


if __name__ == '__main__':
    unittest.main()
