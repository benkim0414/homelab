#!/usr/bin/env python3
"""Offline contract checks; native acceptance requires fixture-clickhouse.py."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ch_fixture', HERE / 'fixture-clickhouse.py')
assert spec is not None and spec.loader is not None
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class ClickHouseFixtureContracts(unittest.TestCase):
    def test_literal_allowed_path_no_disk(self):
        root = ET.fromstring(fixture.CONFIG)
        self.assertEqual(root.findtext('backups/allowed_path'), 'backups')
        self.assertIsNone(root.find('backups/allowed_disk'))
        self.assertEqual(root.findtext('listen_host'), '127.0.0.1')

    def test_scripts_parse(self):
        for script in (fixture.SOURCE, fixture.RESTORE, fixture.CORRUPT):
            result = subprocess.run(['/bin/bash', '-n'], input=fixture.PROLOGUE + script + fixture.END, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_independent_restore_not_reseeded(self):
        self.assertNotIn('CREATE DATABASE', fixture.RESTORE)
        self.assertNotIn('INSERT INTO', fixture.RESTORE)
        self.assertIn('RESTORE DATABASE recovery_fixture', fixture.RESTORE)
        self.assertIn("WHERE name='recovery_fixture'", fixture.RESTORE)
        self.assertIn('archive writable', fixture.RESTORE)

    def test_negatives_have_semantic_errors(self):
        for expected in ('BACKUP_ALREADY_EXISTS', 'not allowed for backups', 'INVALID_CONFIG_PARAMETER'):
            self.assertIn(expected, fixture.SOURCE)
        self.assertIn('ARGUMENT_OUT_OF_BOUND', fixture.CORRUPT)

    def test_cache_and_exact_pin(self):
        self.assertEqual(fixture.shared.CACHE, fixture.CACHE)
        self.assertIn(fixture.PIN.removeprefix('docker.io/'), (fixture.REPO / 'langfuse/clickhouse.yaml').read_text())


if __name__ == '__main__':
    unittest.main()
