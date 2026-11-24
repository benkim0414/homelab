"""Generated-only encryption fixture safety; no real keys or network access."""
import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('langfuse_encryption_fixture',
                                             ROOT / 'langfuse/recovery/fixture-encryption.py')
assert spec and spec.loader
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def archive_bytes(names=('schema.txt', 'data.bin'), symlink=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:') as archive:
        for name in names:
            entry = tarfile.TarInfo(name)
            if symlink:
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/outside'
                archive.addfile(entry)
            else:
                content = ('generated-' + name).encode()
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
    return stream.getvalue()


class EncryptionFixtureTests(unittest.TestCase):
    def inventory(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.tar'
            path.write_bytes(data)
            return fixture.archive_inventory(path)

    def test_complete_archive_inventory(self):
        rows = self.inventory(archive_bytes())
        self.assertEqual(set(rows), {'schema.txt', 'data.bin'})
        self.assertEqual(rows['data.bin']['bytes'], len(b'generated-data.bin'))

    def test_duplicate_unknown_absolute_parent_or_link_member_rejected(self):
        for names in [('schema.txt', 'data.bin', 'data.bin'), ('schema.txt',),
                      ('schema.txt', 'other'), ('schema.txt', '/data.bin'),
                      ('schema.txt', '../data.bin')]:
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.inventory(archive_bytes(names))
        with self.assertRaises(ValueError):
            self.inventory(archive_bytes(symlink=True))

    def test_truncation_and_hidden_trailing_archive_rejected(self):
        data = archive_bytes()
        for bad in [data[:1000], data[:-1], data[:512], data + archive_bytes()]:
            with self.subTest(size=len(bad)), self.assertRaises((ValueError, tarfile.TarError)):
                self.inventory(bad)

    def test_size_limit_checked_before_read(self):
        with mock.patch.object(fixture, 'MAX_ARCHIVE', 4):
            with self.assertRaises(ValueError):
                self.inventory(archive_bytes())

    def test_private_publication_never_overwrites_or_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'receipt'
            fixture.new_file(path, b'original')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                fixture.new_file(path, b'replacement')
            link = root / 'alias'
            link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                fixture.new_file(link, b'replacement')
            self.assertEqual(path.read_bytes(), b'original')

    def test_directory_alias_and_group_access_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / 'safe'
            safe.mkdir(mode=0o700)
            unsafe = root / 'unsafe'
            unsafe.mkdir(mode=0o700)
            unsafe.chmod(0o750)
            link = root / 'alias'
            link.symlink_to(safe, target_is_directory=True)
            with mock.patch.object(fixture, 'ROOT', root):
                fixture.private_directory(safe)
                for path in [unsafe, link]:
                    with self.assertRaises(ValueError):
                        fixture.private_directory(path)

    def test_external_arguments_are_rejected_without_preparing_tools(self):
        with mock.patch('sys.argv', ['fixture-encryption', '--recipient', 'anything']), \
                mock.patch.object(fixture, 'tools') as tools, \
                mock.patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(fixture.main(), 2)
            tools.assert_not_called()

    def test_tool_error_has_no_raw_diagnostics(self):
        with mock.patch('sys.argv', ['fixture-encryption']), \
                mock.patch.object(fixture.platform, 'system', return_value='Linux'), \
                mock.patch.object(fixture.platform, 'machine', return_value='x86_64'), \
                mock.patch.object(fixture, 'tools', side_effect=ValueError('RAW-DIAGNOSTIC')), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as error:
            old = os.umask(0o077)
            try:
                self.assertEqual(fixture.main(), 1)
            finally:
                os.umask(old)
            self.assertNotIn('RAW-DIAGNOSTIC', error.getvalue())


if __name__ == '__main__':
    unittest.main()
