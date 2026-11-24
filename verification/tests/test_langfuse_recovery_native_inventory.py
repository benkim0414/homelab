"""Native read-only recovery metadata contracts; fake auth only, no live calls."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('native_recovery_metadata',
                                             ROOT / 'langfuse/recovery/inspect-native.py')
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def valkey_summary():
    return {'configured_native_authentication_verified': True,
            'client': 'worker-installed-ioredis', 'native_ping': 'passed',
            'aof_enabled': True, 'persistence_layout_verified': True,
            'loading': False, 'rewrite_in_progress': False,
            'last_rewrite_ok': True, 'last_write_ok': True, 'database_keys': 2,
            'writer_exclusion_verified': False, 'queue_drain_verified': False}


def workload_rows():
    names = {'postgresql': 'langfuse-postgresql-0', 'clickhouse': 'langfuse-clickhouse-0',
             'langfuse-redis': 'fixture-redis', 'langfuse-worker': 'fixture-worker'}
    return [{'name': name, 'uid': 'fixture-uid-' + kind, 'container': kind,
             'image': 'public-image@sha256:' + probe.preflight.IMAGE_DIGESTS[kind],
             'ready': 'true', 'phase': 'Running', 'deleting': '<none>'}
            for kind, name in names.items()]


class NativeRecoveryInspectionTests(unittest.TestCase):
    def test_postgres_native_scalar_admission_and_migration_state(self):
        self.assertEqual(probe.parse_pg_base('180007|0|1|1|2')['server_version_num'], 180007)
        self.assertTrue(probe.parse_pg_migrations('470|0')['migrations_clean'])
        self.assertFalse(probe.parse_pg_migrations('470|1')['migrations_clean'])
        for bad in ['180007|0|1|1|3', '180007|1|1|1|2', '180007|0|0|1|2',
                    '180007|0|1|0|2', '170001|0|1|1|2', 'RAW', '180007|0|1|1|2\nRAW']:
            with self.subTest(bad=bad), self.assertRaises(probe.ProbeError):
                probe.parse_pg_base(bad)
        for bad in ['0|0', '1|2', '-1|0', '2|0|EXTRA']:
            with self.assertRaises(probe.ProbeError):
                probe.parse_pg_migrations(bad)

    def test_clickhouse_exact_schema_and_latest_dirty_semantics(self):
        self.assertTrue(probe.parse_ch_base('26.8.36.3\t1\t1\t3')['configured_native_user_verified'])
        self.assertTrue(probe.parse_ch_migration('56\t0')['migrations_clean'])
        self.assertFalse(probe.parse_ch_migration('56\t1')['migrations_clean'])
        for bad in ['26.8.42.13\t1\t1\t3', '26.8.36.3\t0\t1\t3',
                    '26.8.36.3\t1\t0\t3', '26.8.36.3\t1\t1\t2', 'RAW']:
            with self.assertRaises(probe.ProbeError):
                probe.parse_ch_base(bad)
        for bad in ['56\t2', '-1\t0', '56\t0\n55\t1']:
            with self.assertRaises(probe.ProbeError):
                probe.parse_ch_migration(bad)

    def test_valkey_noauth_or_unexpected_open_access_never_admits_capture(self):
        for text in ['NOAUTH Authentication required.', '(error) NOAUTH Authentication required.', 'PONG']:
            self.assertFalse(probe.parse_valkey(text)['capture_authentication_admitted'])
        for text in ['', 'OK', 'PONG\nRAW', 'NOAUTH something else']:
            with self.assertRaises(probe.ProbeError):
                probe.parse_valkey(text)

    def test_authenticated_summary_is_strict_and_never_proves_writer_exclusion(self):
        good = valkey_summary()
        self.assertEqual(probe.parse_valkey_authenticated(json.dumps(good)), good)
        for field, value in [('database_keys', True), ('database_keys', -1),
                             ('aof_enabled', False), ('native_ping', 'OTHER'),
                             ('client', 'other'), ('loading', 0),
                             ('writer_exclusion_verified', True), ('queue_drain_verified', True),
                             ('configured_native_authentication_verified', False)]:
            bad = dict(good, **{field: value})
            with self.subTest(field=field), self.assertRaises(probe.ProbeError):
                probe.parse_valkey_authenticated(json.dumps(bad))
        for text in [json.dumps(dict(good, unexpected='payload')), '[]', '{',
                     json.dumps(good)[:-1] + ',"client":"worker-installed-ioredis"}']:
            with self.assertRaises(probe.ProbeError):
                probe.parse_valkey_authenticated(text)

    def test_native_errors_and_timeouts_are_sanitized(self):
        for result in [subprocess.CompletedProcess([], 1, 'PRIVATE', 'PRIVATE'),
                       subprocess.CompletedProcess([], 0, 'x' * 4097, '')]:
            with mock.patch.object(probe.subprocess, 'run', return_value=result):
                with self.assertRaises(probe.ProbeError) as error:
                    probe.execute('fixture', 'fixture', ['command'])
                self.assertNotIn('PRIVATE', str(error.exception))
        with mock.patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('PRIVATE', 25)):
            with self.assertRaises(probe.ProbeError) as error:
                probe.execute('fixture', 'fixture', ['command'])
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_workload_ambiguity_image_readiness_and_name_drift_refused(self):
        good = workload_rows()
        with mock.patch.object(probe.preflight, 'table', return_value=good):
            self.assertEqual(len(probe.probe_workloads()), 4)
        cases = [good[:-1], good + [copy.deepcopy(good[0])]]
        for field, value in [('image', 'other'), ('ready', 'false'), ('deleting', 'timestamp'),
                             ('phase', 'Pending'), ('name', 'other-postgres')]:
            bad = copy.deepcopy(good)
            bad[0][field] = value
            cases.append(bad)
        for rows in cases:
            with mock.patch.object(probe.preflight, 'table', return_value=rows):
                with self.assertRaises(probe.ProbeError):
                    probe.probe_workloads()

    def test_commands_use_readonly_modes_not_secret_arguments_or_exports(self):
        self.assertIn('default_transaction_read_only=on', probe.PG_SHELL)
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', probe.PG_SHELL)
        self.assertIn('--readonly', probe.CH_OPTIONS)
        for query in [probe.PG_BASE_SQL, probe.PG_MIGRATION_SQL, probe.CH_BASE_SQL, probe.CH_MIGRATION_SQL]:
            self.assertTrue(query.lstrip().startswith('SELECT'))
        self.assertNotIn('--password', probe.CH_OPTIONS)
        self.assertNotIn('pg_dump', probe.PG_SHELL)

    def test_nas_transport_uses_only_generated_stream_and_strict_host_auth(self):
        payload = b'fixture-generated'
        expected = probe.hashlib.sha256(payload).hexdigest()
        response = subprocess.CompletedProcess([], 0, (expected + '  -\n').encode(), b'')
        with mock.patch.object(probe.os, 'urandom', return_value=payload), \
                mock.patch.object(probe.subprocess, 'run', return_value=response) as run:
            result = probe.inspect_transport()
            self.assertEqual(result['status'], 'passed')
            self.assertFalse(result['nas_file_created'])
            self.assertFalse(result['archive_publication_verified'])
            self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][-2:], ['nas', 'sha256sum'])
            self.assertEqual(run.call_args.kwargs['input'], payload)
        for response in [subprocess.CompletedProcess([], 1, b'PRIVATE', b'PRIVATE'),
                         subprocess.CompletedProcess([], 0, b'other  -', b'')]:
            with mock.patch.object(probe.subprocess, 'run', return_value=response):
                result = probe.inspect_transport()
                self.assertEqual(result['status'], 'blocked')
                self.assertNotIn('PRIVATE', json.dumps(result))

    @unittest.skipUnless(shutil.which('node'), 'Node required for client probe pure-function tests')
    def test_client_destination_and_private_metadata_validation(self):
        script = r'''
const assert=require('node:assert/strict');
const p=require(process.argv[1]);
const good={REDIS_CONNECTION_STRING:'redis://default@langfuse-redis:6379/0',REDIS_PASSWORD:'fixture-only'};
assert.equal(p.connectionOptions(good).host,'langfuse-redis');
assert.equal(p.connectionOptions(good).password,'fixture-only');
for(const url of ['redis://external.example:6379','rediss://langfuse-redis',
                  'redis://langfuse-redis:6380','redis://other@langfuse-redis',
                  'redis://langfuse-redis/1','redis://langfuse-redis/?x=1']){
 assert.throws(()=>p.connectionOptions({...good,REDIS_CONNECTION_STRING:url}));
}
assert.throws(()=>p.connectionOptions({...good,REDIS_PASSWORD:''}));
assert.throws(()=>p.connectionOptions({...good,REDIS_TLS_ENABLED:'true'}));
const info='loading:0\r\naof_enabled:1\r\naof_rewrite_in_progress:0\r\naof_last_bgrewrite_status:ok\r\naof_last_write_status:ok\r\nunknown:PRIVATE-FIXTURE\r\n';
const config={appendonly:'yes',dir:'/data',appendfilename:'appendonly.aof',appenddirname:'appendonlydir',dbfilename:'dump.rdb'};
const result=p.persistenceSummary(info,config,2);
assert.equal(result.database_keys,2);assert.equal(result.writer_exclusion_verified,false);
assert.ok(!JSON.stringify(result).includes('PRIVATE-FIXTURE'));
assert.throws(()=>p.persistenceSummary(info,{...config,appendonly:'no'},2));
assert.throws(()=>p.persistenceSummary(info+'loading:0\r\n',config,2));
assert.throws(()=>p.persistenceSummary(info,config,-1));
console.log('pure-client-contracts-passed');
'''
        result = subprocess.run(['node', '-e', script,
                                 str(ROOT / 'langfuse/recovery/inspect-valkey.js')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, 'pure client contract test failed')
        self.assertEqual(result.stdout.strip(), 'pure-client-contracts-passed')


if __name__ == '__main__':
    unittest.main()
