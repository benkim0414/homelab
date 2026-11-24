"""PostgreSQL export command admission; no subprocesses, credentials or live I/O."""
from dataclasses import FrozenInstanceError
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('langfuse_postgres_exports',
                                             ROOT / 'langfuse/recovery/postgres_exports.py')
assert spec and spec.loader
exports = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = exports
spec.loader.exec_module(exports)


def source():
    return {'name': exports.POD, 'container': exports.CONTAINER, 'image': exports.IMAGE,
            'ready': 'true', 'phase': 'Running', 'deleting': '<none>',
            'uid': '00000000-0000-0000-0000-000000000001'}


class PostgresExportTests(unittest.TestCase):
    def test_fixed_two_confidential_streams_and_full_archive_parser(self):
        database, roles = exports.build(source())
        self.assertEqual(database.component, 'postgres-database')
        self.assertEqual(roles.component, 'postgres-globals')
        self.assertIn('--format=custom', database.container_argv[-1])
        self.assertIn('--create', database.container_argv[-1])
        self.assertEqual(database.complete_archive_validator, ('pg_restore', '--file=/dev/null'))
        self.assertIsNone(roles.complete_archive_validator)
        self.assertFalse(roles.includes_datastore_role_passwords)
        self.assertIn('--no-role-passwords', roles.container_argv[-1])

    def test_every_source_field_is_required_and_exact(self):
        for field in source():
            row = source()
            row.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                exports.build(row)
        for field, value in [('name', 'other'), ('container', 'other'), ('image', 'postgres:18'),
                             ('ready', 'false'), ('phase', 'Pending'), ('deleting', 'timestamp'),
                             ('uid', 'not-a-uuid')]:
            row = dict(source(), **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                exports.build(row)

    def test_native_password_interface_never_uses_password_arguments(self):
        for item in exports.build(source()):
            shell = item.container_argv[-1]
            self.assertIn('set +x', shell)
            self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', shell)
            self.assertIn('--no-password', shell)
            self.assertNotIn('--password=', shell)
            self.assertNotIn('set -x', shell)
            self.assertIn('test "${POSTGRES_DB:-}" = langfuse', shell)
            self.assertIn('default_transaction_read_only=on', shell)
            self.assertIn('statement_timeout=600000', shell)
            self.assertIn('lock_timeout=5000', shell)

    def test_commands_are_bound_to_fixed_namespace_pod_and_container(self):
        for item in exports.build(source()):
            self.assertEqual(item.kubectl_argv[:10], ('kubectl', '--request-timeout=30s',
                             '-n', 'langfuse', 'exec', exports.POD, '-c', exports.CONTAINER,
                             '--', '/bin/sh'))
            self.assertEqual(item.kubectl_argv[-3:], item.container_argv)
            self.assertEqual(item.source_uid, source()['uid'])
            self.assertEqual(item.source_image, exports.IMAGE)

    def test_result_is_immutable_and_source_changes_do_not_retarget_it(self):
        row = source()
        item = exports.build(row)[0]
        row['name'] = 'other'
        self.assertIn(exports.POD, item.kubectl_argv)
        with self.assertRaises(FrozenInstanceError):
            item.source_uid = 'other'


if __name__ == '__main__':
    unittest.main()
