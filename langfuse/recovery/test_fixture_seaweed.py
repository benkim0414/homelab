"""Offline unit guards; native acceptance is fixture-seaweed.py, not these mocks."""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('seaweed_fixture', Path(__file__).with_name('fixture-seaweed.py'))
assert spec is not None and spec.loader is not None
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def lengthfield(number, value):
    assert len(value) < 128
    return bytes([number * 8 + 2, len(value)]) + value


def full_entry(extra=b''):
    attrs = b'\x08\x01'  # file_size=1
    entry = lengthfield(1, b'x') + lengthfield(4, attrs) + extra
    raw = lengthfield(1, b'/') + lengthfield(2, entry)
    return struct.pack('>I', len(raw)) + raw


class Guards(unittest.TestCase):
    def test_complete_metadata(self):
        self.assertEqual(set(fixture.records(gzip.compress(full_entry()))), {'/x'})

    def test_trailer_crc_and_frame_rejection(self):
        good = gzip.compress(full_entry())
        for bad in (good[:-8], b'not gzip', good[:-8] + b'\0' * 8,
                    gzip.compress(full_entry()[:-1]), gzip.compress(full_entry() + b'x')):
            with self.subTest(bad=bad[:12]), self.assertRaises(fixture.Refusal):
                fixture.records(bad)

    def test_final_entry_loss_valid_gzip_is_not_complete(self):
        expected = fixture.records(gzip.compress(full_entry()))
        with self.assertRaisesRegex(fixture.Refusal, 'inventory'):
            fixture.check_expected({}, expected)

    def test_unknown_remote_and_chunk_manifest_refused(self):
        # Unknown Entry field 6, remote Entry field 10, chunk-manifest flag 11.
        for extra in (lengthfield(6, b'x'), lengthfield(10, b'x'),
                      lengthfield(3, bytes([11 * 8, 1]))):
            with self.subTest(extra=extra), self.assertRaises(fixture.Refusal):
                fixture.records(gzip.compress(full_entry(extra)))

    def test_duplicate_entry_refused(self):
        with self.assertRaisesRegex(fixture.Refusal, 'duplicate'):
            fixture.records(gzip.compress(full_entry() * 2))

    def test_output_no_overwrite(self):
        # All test artifacts stay in this component's authorized private cache.
        fixture.CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix='unit-', dir=fixture.CACHE))
        path = directory / 'sentinel'
        fixture.save(path, b'sentinel')
        with self.assertRaises(FileExistsError):
            fixture.save(path, b'overwritten')
        self.assertEqual(path.read_bytes(), b'sentinel')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_ec_remote_unknown_topology_refused(self):
        node = {'Url': '127.0.0.1:8080', 'PublicUrl': '127.0.0.1:8080', 'Volumes': 1,
                'EcShards': 0, 'Max': 8, 'VolumeIds': ' 1'}
        top = {'Topology': {'Max': 8, 'Free': 7, 'DataCenters': [{'Racks': [{'DataNodes': [node]}]}],
                           'Layouts': [{'replication': '000', 'ttl': '', 'writables': [1],
                                        'collection': 'fixture', 'diskType': 'hdd'}]}}
        listing = ('remote:0\nvolume Id:1, ReplicaPlacement:000, Collection:fixture, Version:3, Ttl:,'
                   ' DeleteCount:0, DeletedByteCount:0, ReadOnly:false')
        self.assertEqual(fixture.volume_inventory(top, listing), [1])
        for key, value in (('EcShards', 1), ('Url', '192.168.0.11:8080'), ('unknown', 0)):
            mutated = copy.deepcopy(top)
            mutated['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0][key] = value
            with self.subTest(key=key), self.assertRaises(fixture.Refusal):
                fixture.volume_inventory(mutated, listing)
        for key, value in (('ttl', '1d'), ('replication', '001'), ('other', 'x')):
            mutated = copy.deepcopy(top)
            mutated['Topology']['Layouts'][0][key] = value
            with self.subTest(key=key), self.assertRaises(fixture.Refusal):
                fixture.volume_inventory(mutated, listing)


if __name__ == '__main__':
    unittest.main()
