"""Exercise the isolated inspector with synthetic fixtures only."""
import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest


class InspectorTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'inspector', Path(__file__).with_name('inspect_clone.py'))
        assert spec is not None and spec.loader is not None
        self.inspector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.inspector)

    def fixture(self, root):
        with closing(sqlite3.connect(root / 'state.db')) as connection:
            connection.execute('create table synthetic (value text)')
            connection.execute('insert into synthetic values (?)', ('not private data',))
            connection.commit()

    def test_integrity_and_credential_unlink_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'auth.json').write_text('synthetic token')
            (root / 'outside').write_text('do not delete target')
            (root / '.env').symlink_to(root / 'outside')
            result = self.inspector.inspect(root)
            self.assertEqual(result, {'sqlite_integrity': 'ok',
                                     'credential_files_removed': 2,
                                     'hermes_started': False})
            self.assertEqual((root / 'outside').read_text(), 'do not delete target')
            self.assertFalse((root / 'auth.json').exists())
            self.assertFalse((root / '.env').is_symlink())

    def test_database_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state.db').symlink_to(root / 'outside')
            with self.assertRaises(ValueError):
                self.inspector.inspect(root)

    def test_native_profile_layout_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'profiles').mkdir()
            with self.assertRaises(ValueError):
                self.inspector.inspect(root)


if __name__ == '__main__':
    unittest.main()
