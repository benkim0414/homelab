"""Local filesystem fixtures; no real profiles or credentials."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('guard_install', ROOT / 'langfuse/install-desktop-guard.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class GuardInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'; self.home.mkdir()
        self.source = self.root / 'source'; self.source.mkdir()
        (self.source / '__init__.py').write_text('def register(ctx): pass\n')
        (self.source / 'plugin.yaml').write_text('name: homelab-langfuse-desktop\n')
        (self.source / 'README.md').write_text('Reviewed guard documentation.\n')

    def test_verified_private_install_is_idempotent(self):
        target = m.install(self.source, self.home)
        self.assertEqual(m.source_assets(target), m.source_assets(self.source))
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        for path in target.iterdir():self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(m.install(self.source, self.home), target)
        self.assertFalse((self.home / '.env').exists())
        self.assertFalse((self.home / 'config.yaml').exists())
        self.assertFalse(list(self.home.glob('.langfuse-guard-stage-*')))

    def test_different_existing_guard_is_preserved(self):
        target = m.install(self.source, self.home)
        (target / '__init__.py').write_text('original = True\n')
        with self.assertRaises(ValueError):m.install(self.source, self.home)
        self.assertEqual((target / '__init__.py').read_text(), 'original = True\n')

    def test_rejects_symlinked_discovery_directory(self):
        (self.home / 'plugins').symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):m.install(self.source, self.home)

    def test_rejects_symlinked_asset(self):
        (self.source / 'extra.py').symlink_to(self.source / '__init__.py')
        with self.assertRaises(ValueError):m.install(self.source, self.home)
        self.assertFalse((self.home / 'plugins').exists())

    def test_rejects_unexpected_asset(self):
        (self.source / 'unexpected.txt').write_text('not copied')
        with self.assertRaises(ValueError):m.install(self.source, self.home)
        self.assertFalse((self.home / 'plugins').exists())

    def test_rejects_missing_manifest(self):
        (self.source / 'plugin.yaml').unlink()
        with self.assertRaises(ValueError):m.install(self.source, self.home)


if __name__ == '__main__':
    unittest.main()
