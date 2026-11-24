#!/usr/bin/env python3
"""Offline safety tests; all generated files remain in the fixture-only cache.
Run: python3 -B langfuse/recovery/pg-valkey-tests.py
Native positive/negative archive checks additionally run in fixture-pg-valkey.py.
"""
import importlib.util
import io
import os
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch
import uuid

spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('fixture-pg-valkey.py'))
assert spec is not None and spec.loader is not None
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Safety(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.base = fixture.CACHE / ('unit-' + uuid.uuid4().hex)
        fixture.private_dir(self.base)
        self.root = self.base / 'root'
        self.root.mkdir(mode=0o700)

    def archive(self, members):
        path = self.base / ('layer-' + uuid.uuid4().hex + '.tar')
        with tarfile.open(path, 'w') as archive:
            for name, kind, data in members:
                entry = tarfile.TarInfo(name)
                if kind == 'file':
                    entry.size = len(data)
                    entry.mode = 0o6755
                    archive.addfile(entry, io.BytesIO(data))
                else:
                    entry.type = tarfile.SYMTYPE if kind == 'sym' else tarfile.LNKTYPE
                    entry.linkname = data
                    archive.addfile(entry)
        return path

    def test_parent_traversal_refused(self):
        archive = self.archive([('../escape', 'file', b'bad')])
        with self.assertRaises(RuntimeError):
            fixture.extract_layer(archive, self.root)
        self.assertFalse((self.base / 'escape').exists())

    def test_absolute_member_refused(self):
        archive = self.archive([('/escape', 'file', b'bad')])
        with self.assertRaises(RuntimeError):
            fixture.extract_layer(archive, self.root)

    def test_image_absolute_symlink_stays_in_root(self):
        archive = self.archive([('alias', 'sym', '/inside'), ('alias/item', 'file', b'fixture')])
        fixture.extract_layer(archive, self.root)
        self.assertEqual((self.root / 'inside/item').read_bytes(), b'fixture')
        self.assertEqual((self.root / 'inside/item').stat().st_mode & 0o7000, 0)

    def test_escape_symlink_refused(self):
        archive = self.archive([('alias', 'sym', '../../outside'), ('alias/item', 'file', b'bad')])
        with self.assertRaises(RuntimeError):
            fixture.extract_layer(archive, self.root)
        self.assertFalse((self.base / 'outside').exists())

    def test_escape_hardlink_refused(self):
        archive = self.archive([('alias', 'hard', '../outside')])
        with self.assertRaises(RuntimeError):
            fixture.extract_layer(archive, self.root)

    def test_whiteout_before_additions(self):
        (self.root / 'replaced').write_bytes(b'old')
        # Deliberately put whiteout after replacement in archive order.
        archive = self.archive([('replaced', 'file', b'new'), ('.wh.replaced', 'file', b'')])
        fixture.extract_layer(archive, self.root)
        self.assertEqual((self.root / 'replaced').read_bytes(), b'new')

    def test_reserved_whiteout_targets_refused_before_deletion(self):
        sentinel = self.base / 'outside-sentinel'
        sentinel.write_bytes(b'untouched')
        (self.root / 'nested').mkdir()
        for prefix in ('', 'nested/'):
            for basename in ('.wh.', '.wh..', '.wh...'):
                with self.subTest(member=prefix + basename):
                    archive = self.archive([(prefix + basename, 'file', b'')])
                    with patch.object(fixture, 'remove_image_path') as remove:
                        with self.assertRaisesRegex(RuntimeError, 'invalid whiteout target'):
                            fixture.extract_layer(archive, self.root)
                        remove.assert_not_called()
                    self.assertEqual(sentinel.read_bytes(), b'untouched')

    def test_whiteout_parent_escape_refused_before_deletion(self):
        for member in ('../.wh.victim', '/.wh.victim'):
            with self.subTest(member=member):
                archive = self.archive([(member, 'file', b'')])
                with patch.object(fixture, 'remove_image_path') as remove:
                    with self.assertRaises(RuntimeError):
                        fixture.extract_layer(archive, self.root)
                    remove.assert_not_called()

    def test_whiteout_unlinks_final_symlink_not_its_destination(self):
        outside = self.base / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_bytes(b'untouched')
        (self.root / 'alias').symlink_to(outside, target_is_directory=True)
        fixture.extract_layer(self.archive([('.wh.alias', 'file', b'')]), self.root)
        self.assertFalse((self.root / 'alias').is_symlink())
        self.assertEqual(sentinel.read_bytes(), b'untouched')

    def test_opaque_whiteout_removes_only_image_directory_children(self):
        sentinel = self.base / 'outside-sentinel'
        sentinel.write_bytes(b'untouched')
        directory = self.root / 'nested'
        directory.mkdir()
        (directory / 'old').write_bytes(b'old')
        (directory / 'alias').symlink_to(sentinel)
        archive = self.archive([('nested/new', 'file', b'new'),
                                ('nested/.wh..wh..opq', 'file', b'')])
        fixture.extract_layer(archive, self.root)
        self.assertEqual([p.name for p in directory.iterdir()], ['new'])
        self.assertEqual((directory / 'new').read_bytes(), b'new')
        self.assertEqual(sentinel.read_bytes(), b'untouched')

    def test_cached_digest_corruption_refused(self):
        path = self.base / 'bad.blob'
        path.write_bytes(b'corrupted')
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'):
            fixture.download('https://invalid.example/not-contacted', path, 'sha256:' + '0' * 64)

    def test_symlink_cache_directory_refused(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.root)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            fixture.private_dir(alias)


if __name__ == '__main__':
    unittest.main(verbosity=2)
