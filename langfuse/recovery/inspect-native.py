#!/usr/bin/env python3
"""Read-only native authentication/recovery metadata; never exports production data.

Credentials are consumed only through already configured in-container native
interfaces. No Secret requests, password arguments, ACL/config-file extraction,
logs, records, backup commands, writes or credential changes are implemented.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('recovery_preflight', Path(__file__).with_name('preflight.py'))
assert _spec and _spec.loader
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)

PG_BASE_SQL = """SELECT current_setting('server_version_num'),
 CASE WHEN pg_is_in_recovery() THEN 1 ELSE 0 END,
 CASE WHEN current_database()='langfuse' THEN 1 ELSE 0 END,
 CASE WHEN to_regclass('public._prisma_migrations') IS NOT NULL THEN 1 ELSE 0 END,
 (SELECT count(*) FROM information_schema.columns WHERE table_schema='public'
 AND table_name='_prisma_migrations' AND column_name IN ('finished_at','rolled_back_at'))"""
PG_MIGRATION_SQL = """SELECT count(*), count(*) FILTER
 (WHERE finished_at IS NULL AND rolled_back_at IS NULL)
 FROM public._prisma_migrations"""
CH_BASE_SQL = """SELECT version(), currentUser()='langfuse',
 (SELECT count() FROM system.tables WHERE database='default' AND name='schema_migrations'),
 (SELECT count() FROM system.columns WHERE database='default' AND table='schema_migrations'
 AND name IN ('version','dirty','sequence')) FORMAT TSV"""
CH_MIGRATION_SQL = """SELECT version,dirty FROM default.schema_migrations
 ORDER BY sequence DESC LIMIT 1 FORMAT TSV"""
PG_SHELL = ('set +x; test -n "${POSTGRES_PASSWORD:-}"; '
            'PGPASSWORD="$POSTGRES_PASSWORD" '
            'PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=3000" '
            'exec psql -X -w -qAt -F "|" -h 127.0.0.1 -U postgres -d "$POSTGRES_DB" '
            '--set=ON_ERROR_STOP=1 --command "$1"')
CH_OPTIONS = ['clickhouse-client', '--host', '127.0.0.1', '--readonly', '1',
              '--max_execution_time', '10', '--max_threads', '1',
              '--max_result_rows', '10', '--max_result_bytes', '1024',
              '--result_overflow_mode', 'throw', '--query']


class ProbeError(Exception):
    pass


def execute(pod, container, command):
    args = ['kubectl', '--request-timeout=20s', '-n', 'langfuse', 'exec',
            pod, '-c', container, '--'] + command
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=25, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeError('native-probe-unavailable') from None
    # Do not expose raw diagnostics; unexpected responses are rejected in memory.
    if result.returncode or len(result.stdout) > 4096:
        raise ProbeError('native-probe-failed')
    return result.stdout.strip()


def parse_pg_base(text):
    if not re.fullmatch(r'[0-9]{6}\|[01]\|[01]\|[01]\|[0-9]+', text):
        raise ProbeError('postgres-metadata-format')
    version, recovery, correct_db, migration_table, columns = map(int, text.split('|'))
    if not 180000 <= version < 190000 or recovery or not correct_db or migration_table != 1 or columns != 2:
        raise ProbeError('postgres-capture-schema-not-admitted')
    return {'server_version_num': version, 'in_recovery': False,
            'expected_database': True, 'migration_schema_admitted': True}


def parse_pg_migrations(text):
    if not re.fullmatch(r'[0-9]+\|[0-9]+', text):
        raise ProbeError('postgres-migration-format')
    total, unfinished = map(int, text.split('|'))
    if total < 1 or unfinished > total:
        raise ProbeError('postgres-migration-contradiction')
    return {'migration_records': total, 'unfinished_migrations': unfinished,
            'migrations_clean': unfinished == 0}


def parse_ch_base(text):
    if not re.fullmatch(r'26\.8\.36\.3\t[01]\t[0-9]+\t[0-9]+', text):
        raise ProbeError('clickhouse-metadata-format')
    version, user, tables, columns = text.split('\t')
    if (user, tables, columns) != ('1', '1', '3'):
        raise ProbeError('clickhouse-capture-schema-not-admitted')
    return {'version': version, 'configured_native_user_verified': True,
            'migration_schema_admitted': True}


def parse_ch_migration(text):
    if not re.fullmatch(r'[0-9]+\t[01]', text):
        raise ProbeError('clickhouse-migration-format')
    version, dirty = map(int, text.split('\t'))
    return {'latest_migration_version': version, 'latest_migration_dirty': bool(dirty),
            'migrations_clean': dirty == 0}


def parse_valkey(text):
    if text == 'PONG':
        return {'native_ping': 'passed', 'authentication_required_verified': False,
                'capture_authentication_admitted': False,
                'reason': 'unexpected-unauthenticated-access-requires-review'}
    if text in {'NOAUTH Authentication required.', '(error) NOAUTH Authentication required.'}:
        return {'native_ping': 'authentication-required', 'authentication_required_verified': True,
                'capture_authentication_admitted': False,
                'reason': 'no-preconfigured-native-client-credential-source-verified'}
    raise ProbeError('valkey-response-not-admitted')


def parse_valkey_authenticated(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProbeError('valkey-duplicate-summary-field')
            result[key] = value
        return result
    try:
        result = json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise ProbeError('valkey-summary-not-json') from None
    expected = {'configured_native_authentication_verified', 'client', 'native_ping',
                'aof_enabled', 'persistence_layout_verified', 'loading',
                'rewrite_in_progress', 'last_rewrite_ok', 'last_write_ok',
                'database_keys', 'writer_exclusion_verified', 'queue_drain_verified'}
    if not isinstance(result, dict) or set(result) != expected:
        raise ProbeError('valkey-summary-fields-not-admitted')
    booleans = expected - {'client', 'native_ping', 'database_keys'}
    if (any(type(result[key]) is not bool for key in booleans)
            or type(result['database_keys']) is not int or result['database_keys'] < 0
            or result['client'] != 'worker-installed-ioredis' or result['native_ping'] != 'passed'
            or not result['configured_native_authentication_verified']
            or not result['aof_enabled'] or not result['persistence_layout_verified']
            or result['writer_exclusion_verified'] or result['queue_drain_verified']):
        raise ProbeError('valkey-summary-values-not-admitted')
    return result


def probe_workloads():
    rows = preflight.table('pods', [('name', '.metadata.name'), ('uid', '.metadata.uid'),
                                   ('container', '.spec.containers[*].name'),
                                   ('image', '.spec.containers[*].image'),
                                   ('ready', '.status.containerStatuses[*].ready'),
                                   ('phase', '.status.phase'),
                                   ('deleting', '.metadata.deletionTimestamp')])
    expected = {'postgresql': 'langfuse-postgresql-0', 'clickhouse': 'langfuse-clickhouse-0'}
    selected = {}
    for container in ['postgresql', 'clickhouse', 'langfuse-redis', 'langfuse-worker']:
        matches = [row for row in rows if row['container'] == container]
        if len(matches) != 1:
            raise ProbeError('workload-selection-not-unique')
        row = matches[0]
        if (row['ready'] != 'true' or row['phase'] != 'Running' or row['deleting'] != '<none>'
                or not row['image'].endswith('@sha256:' + preflight.IMAGE_DIGESTS[container])
                or (container in expected and row['name'] != expected[container])):
            raise ProbeError('workload-baseline-differs')
        selected[container] = row
    return selected


def inspect_transport():
    # Generated bytes only. Remote sha256sum reads stdin and writes no NAS file.
    payload = os.urandom(1024 * 1024)
    expected = hashlib.sha256(payload).hexdigest()
    args = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', 'nas', 'sha256sum']
    try:
        result = subprocess.run(args, input=payload, capture_output=True, timeout=25, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return {'status': 'blocked', 'reason': 'configured-nas-transport-unavailable'}
    if result.returncode or result.stdout.strip() != (expected + '  -').encode():
        return {'status': 'blocked', 'reason': 'generated-stream-hash-not-verified'}
    return {'status': 'passed', 'generated_bytes': len(payload), 'sha256': expected,
            'configured_ssh_host_verification': True, 'nas_file_created': False,
            'archive_publication_verified': False}


def collect():
    before = probe_workloads()
    results = {}
    for name in ['postgresql', 'clickhouse', 'langfuse-redis']:
        row = before[name]
        try:
            if name == 'postgresql':
                result = parse_pg_base(execute(row['name'], name,
                    ['/bin/sh', '-ec', PG_SHELL, 'recovery-readonly', PG_BASE_SQL]))
                result.update(parse_pg_migrations(execute(row['name'], name,
                    ['/bin/sh', '-ec', PG_SHELL, 'recovery-readonly', PG_MIGRATION_SQL])))
                result['configured_native_authentication_verified'] = True
            elif name == 'clickhouse':
                # Exact pinned Client.cpp consumes CLICKHOUSE_USER/PASSWORD directly.
                # Never transfer their values to the host or put them in argv.
                result = parse_ch_base(execute(row['name'], name, CH_OPTIONS + [CH_BASE_SQL]))
                result.update(parse_ch_migration(execute(row['name'], name, CH_OPTIONS + [CH_MIGRATION_SQL])))
                result['configured_native_authentication_verified'] = True
            else:
                # No credential extraction from generated ACL or mounted Secret.
                # PING is harmless but rc0 alone does not establish authentication.
                result = parse_valkey(execute(row['name'], name,
                    ['valkey-cli', '-h', '127.0.0.1', '-t', '5', '--raw', 'PING']))
                if result['authentication_required_verified']:
                    worker = before['langfuse-worker']
                    script = Path(__file__).with_name('inspect-valkey.js').read_text()
                    authenticated = parse_valkey_authenticated(execute(
                        worker['name'], 'langfuse-worker', ['node', '-e', script + '\nmain();']))
                    result = {**authenticated, 'unauthenticated_ping_rejected': True}
            results[name] = result
        except ProbeError as error:
            results[name] = {'status': 'blocked', 'reason': str(error)}
    if before != probe_workloads():
        raise ProbeError('workload-changed-during-probe')
    return {'observed_at': datetime.now(timezone.utc).isoformat(),
            'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'preflight_sha256': hashlib.sha256(Path(__file__).with_name('preflight.py').read_bytes()).hexdigest(),
            'valkey_probe_sha256': hashlib.sha256(Path(__file__).with_name('inspect-valkey.js').read_bytes()).hexdigest(),
            'workloads': before, 'results': results, 'nas_transport': inspect_transport(),
            'recovery_accepted': False,
            'capture_ready': False,
            'limitations': ['Read-only native metadata only; no confidential export or database records.',
                            'No production recipient/custody or stable-identity restore path verified.',
                            'No writer exclusion, queue drain, restore acceptance or migration-image comparison.',
                            'Native in-container loopback auth only, not authenticated archive transport.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.absolute()
    try:
        output.parent.resolve(strict=True).relative_to((ROOT / 'verification/cache').resolve())
        if output.is_symlink():
            raise ValueError
    except (OSError, ValueError):
        parser.error('new output must be under an existing worktree verification/cache directory')
    try:
        receipt = collect()
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        print('Read-only metadata collection failed; no capture acceptance.', file=sys.stderr)
        return 1
    print(json.dumps({'receipt': str(output), 'results': receipt['results'],
                      'capture_ready': False, 'recovery_accepted': False}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
