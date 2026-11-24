"""Synthetic-only admission negatives; no cluster contact in tests."""
import copy
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('seaweed_inventory', ROOT / 'langfuse/recovery/inspect-seaweed.py')
assert spec is not None and spec.loader is not None
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)


def fixture() -> Any:
    v = dict(Id=1, Size=100, ReplicaPlacement={}, Ttl=dict(Count=0, Unit=0),
             DiskType='', DiskId=0, Collection='langfuse', Version=3, FileCount=1,
             DeleteCount=0, DeletedByteCount=0, ReadOnly=False, CompactRevision=0,
             ModifiedAtSecond=0, RemoteStorageName='', RemoteStorageKey='')
    ver = '30GB 4.23 73fc9e383'
    d = dict(Version=ver, TopologyId='synthetic', Topology=dict(Max=16, Free=15,
        DataCenters=[dict(Id='dc', Racks=[dict(Id='rack', DataNodes=[dict(
            Url='127.0.0.2:8080', PublicUrl='127.0.0.2:8080', Volumes=1,
            EcShards=0, Max=16, VolumeIds=' 1')])])],
        Layouts=[dict(replication='000', ttl='', writables=[1], collection='langfuse', diskType='hdd')]))
    m = dict(Version=ver, Volumes=dict(Max=16, Free=15,
             DataCenters={'dc': {'rack': {'127.0.0.2:8080': [copy.deepcopy(v)]}}}))
    local = dict(Version=ver, DiskStatuses=[{}], Volumes=[v])
    return d, m, local


def master(m):
    return m['Volumes']['DataCenters']['dc']['rack']['127.0.0.2:8080']


class AdmissionTests(unittest.TestCase):
    def check(self, data):
        return sw.inspect(*data, '127.0.0.2')

    def test_supported_topology(self):
        result = self.check(fixture())
        self.assertEqual(result['normal_volume_count'], 1)
        self.assertEqual(result['ec_shard_count'], 0)
        self.assertNotIn('langfuse', json.dumps(result))
        self.assertNotIn('127.0.0.2', json.dumps(result))

    def test_every_required_top_level_field_and_unknown_field(self):
        for index, obj in enumerate(fixture()):
            for key in obj:
                with self.subTest(index=index, key=key):
                    data = fixture(); del data[index][key]
                    with self.assertRaises(sw.Rejected): self.check(data)
            data = fixture(); data[index]['unexpected'] = 'private'
            with self.assertRaises(sw.Rejected): self.check(data)

    def test_every_volume_field_required(self):
        for index in (1, 2):
            for key in fixture()[2]['Volumes'][0]:
                data = fixture()
                v = master(data[1])[0] if index == 1 else data[2]['Volumes'][0]
                del v[key]
                with self.subTest(index=index, key=key), self.assertRaises(sw.Rejected): self.check(data)

    def test_every_nested_topology_field_required(self):
        paths = [('Topology',), ('Topology', 'DataCenters', 0),
                 ('Topology', 'DataCenters', 0, 'Racks', 0),
                 ('Topology', 'DataCenters', 0, 'Racks', 0, 'DataNodes', 0),
                 ('Topology', 'Layouts', 0)]
        for path in paths:
            original = fixture()[0]
            for key in path: original = original[key]
            for field in original:
                data = fixture(); obj = data[0]
                for key in path: obj = obj[key]
                del obj[field]
                with self.subTest(path=path, field=field), self.assertRaises(sw.Rejected): self.check(data)

    def test_unsupported_volume_policy(self):
        variants = [('ReplicaPlacement', {'node': 1}), ('ReplicaPlacement', None),
                    ('ReplicaPlacement', {'unknown': 0}), ('Ttl', None),
                    ('Ttl', {'Count': 0}), ('Ttl', {'Count': 1, 'Unit': 1}),
                    ('Ttl', {'Count': 0, 'Unit': 1}), ('Collection', 'private-other'),
                    ('RemoteStorageName', 'remote'), ('RemoteStorageKey', 'private'),
                    ('DiskType', 'ssd'), ('Version', 2), ('Id', True),
                    ('ReadOnly', 0), ('Size', -1), ('Id', 0)]
        for field, value in variants:
            data = fixture()
            data[2]['Volumes'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(sw.Rejected): self.check(data)

    def test_explicit_replication_zero_omission(self):
        data = fixture()
        for v in (master(data[1])[0], data[2]['Volumes'][0]):
            v['ReplicaPlacement'] = {'node': 0, 'rack': 0, 'dc': 0}
        self.check(data)

    def test_volume_ranges_fail_closed(self):
        for value in ('1 ...', '1-999999999999', '1 1', '2-1', '0', '2', '1-', '01', '1 private'):
            data = fixture()
            data[0]['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0]['VolumeIds'] = value
            with self.subTest(value=value), self.assertRaises(sw.Rejected): self.check(data)

    def test_fixture_unproved_delete_compaction_readonly_state(self):
        for field, value in [('DeleteCount', 1), ('DeletedByteCount', 1),
                             ('CompactRevision', 1), ('ReadOnly', True)]:
            data = fixture()
            for v in (master(data[1])[0], data[2]['Volumes'][0]): v[field] = value
            with self.subTest(field=field), self.assertRaises(sw.Rejected): self.check(data)

    def test_version_pin_and_malformed_types(self):
        for version in ('4.23', 'prefix 30GB 4.23 73fc9e383 linux amd64', '30GB 4.24 73fc9e383 linux amd64'):
            data = fixture(); data[0]['Version'] = version
            with self.assertRaises(sw.Rejected): self.check(data)
        for value in ([{}], [True], ['1'], None):
            data = fixture(); data[0]['Topology']['Layouts'][0]['writables'] = value
            with self.assertRaises(sw.Rejected): self.check(data)

    def test_volume_mismatch_duplicate_missing_and_layout_contradiction(self):
        for variant in ('missing', 'duplicate', 'collection', 'readonly', 'compaction', 'layout'):
            data = fixture()
            if variant == 'missing': data[2]['Volumes'] = None
            elif variant == 'duplicate': data[2]['Volumes'] *= 2
            elif variant == 'collection': data[2]['Volumes'][0]['Collection'] = ''
            elif variant == 'readonly': data[2]['Volumes'][0]['ReadOnly'] = True
            elif variant == 'compaction': data[2]['Volumes'][0]['CompactRevision'] = 1
            else: data[0]['Topology']['Layouts'][0]['writables'] = [2]
            with self.subTest(variant=variant), self.assertRaises(sw.Rejected): self.check(data)

    def test_ec_nodes_capacity_and_layout_negatives(self):
        for key, value in [('EcShards', 1), ('EcShards', None), ('Volumes', 2),
                           ('Url', 'private:8080'), ('Max', 17)]:
            data = fixture()
            data[0]['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0][key] = value
            with self.subTest(key=key), self.assertRaises(sw.Rejected): self.check(data)
        for key, value in [('replication', '001'), ('ttl', '1d'), ('collection', 'other'),
                           ('diskType', 'ssd'), ('writables', [1, 1])]:
            data = fixture(); data[0]['Topology']['Layouts'][0][key] = value
            with self.subTest(key=key), self.assertRaises(sw.Rejected): self.check(data)
        data = fixture(); data[1]['Volumes']['Free'] = 16
        with self.assertRaises(sw.Rejected): self.check(data)
        data = fixture(); data[0]['Topology']['Layouts'] = None
        with self.assertRaises(sw.Rejected): self.check(data)

    def test_empty_topology_slices_explicit_only(self):
        data = fixture()
        node = data[0]['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0]
        node.update(Volumes=0, VolumeIds=' ')
        data[0]['Topology'].update(Free=16, Layouts=None)
        data[1]['Volumes']['Free'] = 16
        data[2]['Volumes'] = None
        data[1]['Volumes']['DataCenters']['dc']['rack']['127.0.0.2:8080'] = None
        self.assertEqual(self.check(data)['normal_volume_count'], 0)

    def test_json_malformed_duplicates_trailing_nan_and_bounds(self):
        for raw in [b'', b'not-json private error', b'{"x":1,"x":2}', b'{}{}',
                    b'{"x":NaN}', b'\xff', b' ' * (sw.MAX_BYTES + 1), b'[' * 2000]:
            with self.subTest(raw_length=len(raw)), self.assertRaises(sw.Rejected): sw.decode(raw)
        self.assertEqual(sw.decode(b'{}'), {})

    def test_native_output_bound_and_failure_suppression(self):
        with patch.object(sw, 'MAX_BYTES', 100):
            with self.assertRaisesRegex(sw.Rejected, '^output_bound$'):
                sw.run([sys.executable, '-c', 'print("private"*100)'])
        with self.assertRaisesRegex(sw.Rejected, '^native_command_failed$'):
            sw.run([sys.executable, '-c', 'import sys;sys.stderr.write("private");sys.exit(1)'])
        with self.assertRaisesRegex(sw.Rejected, '^command_timeout$'):
            sw.run([sys.executable, '-c', 'import time;time.sleep(2)'], timeout=.1)

    def test_fetch_exact_read_only_loopback(self):
        with patch.object(sw, 'run', return_value=b'{}') as run:
            sw.fetch('synthetic-pod', 9333, '/vol/status')
            argv = run.call_args.args[0]
            self.assertIn('/bin/busybox', argv)
            self.assertEqual(argv[-1], 'http://127.0.0.1:9333/vol/status')
            self.assertNotIn('-i', argv)
            with self.assertRaises(sw.Rejected): sw.fetch('synthetic', 9333, '/vol/grow')

    def test_receipt_private_no_overwrite_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'verification/cache') as tmp:
            folder = Path(tmp) / 'receipts'
            with patch.object(sw, 'RECEIPTS', folder):
                first = sw.save({'summary': 1}); second = sw.save({'summary': 2})
                self.assertNotEqual(first, second)
                self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
                folder.chmod(0o755)
                with self.assertRaises(sw.Rejected): sw.save({})
            link = Path(tmp) / 'link'; link.symlink_to(folder)
            with patch.object(sw, 'RECEIPTS', link), self.assertRaises(sw.Rejected): sw.save({})

    def test_cli_failure_receipt_no_raw_errors(self):
        receipts = []
        with patch.object(sys, 'argv', ['inspect-seaweed.py']), \
             patch.object(sw, 'identity', side_effect=OSError('private-canary')), \
             patch.object(sw, 'save', side_effect=lambda r: receipts.append(r) or ROOT / 'receipt.json'), \
             patch('builtins.print') as output:
            self.assertEqual(sw.main(), 1)
        self.assertFalse(receipts[0]['capture_ready'])
        self.assertNotIn('private-canary', json.dumps(receipts))
        self.assertNotIn('private-canary', str(output.call_args))

    def test_cli_stable_success_and_changed_topology_workload(self):
        for changed in ('none', 'topology', 'workload'):
            receipts = []
            a, b = {'pod': 'synthetic', 'uid': 'first'}, {'pod': 'synthetic', 'uid': 'first'}
            if changed == 'workload': b['uid'] = 'second'
            summaries = [{'normal_volume_count': 1}, {'normal_volume_count': 1}]
            if changed == 'topology': summaries[1]['normal_volume_count'] = 2
            with patch.object(sys, 'argv', ['inspect-seaweed.py']), \
                 patch.object(sw, 'identity', side_effect=[(a, 'ip'), (b, 'ip')]), \
                 patch.object(sw, 'fetch', return_value={}), \
                 patch.object(sw, 'inspect', side_effect=summaries), \
                 patch.object(sw, 'save', side_effect=lambda r: receipts.append(r) or ROOT / 'receipt.json'), \
                 patch('builtins.print'):
                self.assertEqual(sw.main(), 0 if changed == 'none' else 1)
            self.assertEqual(receipts[0]['status'], 'admitted' if changed == 'none' else 'rejected')
            self.assertFalse(receipts[0]['capture_ready'])

if __name__ == '__main__':
    unittest.main()
