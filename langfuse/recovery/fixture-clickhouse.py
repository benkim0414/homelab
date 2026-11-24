#!/usr/bin/env python3
"""Generated-state ClickHouse native recovery probe, never a production backup.

Run python3 -B langfuse/recovery/fixture-clickhouse.py. Anonymous public OCI
retrieval, normalized rootless extraction, all cache below clickhouse/. Requires
Linux, bwrap and delegated systemd user scopes. Native server bypasses entrypoint
and production authentication. No cluster, Docker credentials or host data mounts.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
CACHE = REPO / 'verification/cache/langfuse-recovery/clickhouse'
PIN = 'docker.io/clickhouse/clickhouse-server:26.8.36.3@sha256:d426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7'
SPEC = importlib.util.spec_from_file_location('fixture_shared', HERE.with_name('fixture-pg-valkey.py'))
assert SPEC is not None and SPEC.loader is not None
shared: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shared)
shared.CACHE = CACHE
shared.PINS = {'clickhouse': PIN}
require, save, sha = shared.require, shared.save, shared.sha

CONFIG = '''<clickhouse>
<logger><level>warning</level><console>true</console></logger>
<path>/tmp/fixture/data/</path><tmp_path>/tmp/fixture/tmp/</tmp_path>
<user_files_path>/tmp/fixture/user_files/</user_files_path>
<format_schema_path>/tmp/fixture/format_schemas/</format_schema_path>
<users_config>/tmp/fixture/users.xml</users_config>
<listen_host>127.0.0.1</listen_host><tcp_port>9000</tcp_port>
<max_server_memory_usage>2147483648</max_server_memory_usage>
<max_thread_pool_size>128</max_thread_pool_size>
<background_pool_size>4</background_pool_size>
<background_schedule_pool_size>4</background_schedule_pool_size>
<background_message_broker_schedule_pool_size>2</background_message_broker_schedule_pool_size>
<background_distributed_schedule_pool_size>2</background_distributed_schedule_pool_size>
<background_buffer_flush_schedule_pool_size>2</background_buffer_flush_schedule_pool_size>
<merge_tree><max_bytes_to_merge_at_max_space_in_pool>1073741824</max_bytes_to_merge_at_max_space_in_pool>
<number_of_free_entries_in_pool_to_execute_mutation>2</number_of_free_entries_in_pool_to_execute_mutation>
<number_of_free_entries_in_pool_to_lower_max_size_of_merge>2</number_of_free_entries_in_pool_to_lower_max_size_of_merge>
<number_of_free_entries_in_pool_to_execute_optimize_entire_partition>2</number_of_free_entries_in_pool_to_execute_optimize_entire_partition></merge_tree>
<backups><allowed_path>backups</allowed_path></backups>
</clickhouse>
'''
USERS = '''<clickhouse><profiles><default><max_threads>2</max_threads>
<max_memory_usage>1073741824</max_memory_usage>
</default></profiles><users><default><password></password><networks><ip>127.0.0.1</ip></networks>
<profile>default</profile><quota>default</quota><access_management>1</access_management></default></users>
<quotas><default><interval><duration>3600</duration><queries>0</queries><errors>0</errors>
<result_rows>0</result_rows><read_rows>0</read_rows><execution_time>0</execution_time></interval></default></quotas></clickhouse>'''
PROLOGUE = r'''set -eu
umask 077
id > identity.txt
test "$(id -u)" = 101; test "$(id -g)" = 101
if touch /etc/fixture-write-denied 2>/dev/null; then exit 1; fi
cat /proc/net/route > network-routes.txt
cat /proc/net/dev > network-interfaces.txt
test "$(wc -l < /proc/net/route)" -eq 1
test "$(grep -c ':' /proc/net/dev)" -eq 1
grep -q 'lo:' /proc/net/dev
for endpoint in 1.1.1.1/443 192.168.0.40/2049 192.168.0.11/6443 10.43.0.1/443; do
 if timeout 2 /bin/bash -c "echo probe > /dev/tcp/$endpoint" 2>/dev/null; then exit 1; fi
done
clickhouse extract-from-config --config-file config.xml --key backups.allowed_path > allowed-path.txt
test "$(cat allowed-path.txt)" = backups
clickhouse server --config-file=config.xml >server.log 2>&1 & server=$!
trap 'kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true' EXIT
cli() { clickhouse client --host 127.0.0.1 --port 9000 --query "$1"; }
i=0
until cli 'SELECT 1' >ready.txt 2>/dev/null; do
 i=$((i+1)); test "$i" -lt 150; kill -0 "$server"; sleep 0.2
done
test "$(cli 'SELECT version()')" = 26.8.36.3
negative() {
 label=$1; query=$2; pattern=$3
 if cli "$query" >"$label.txt" 2>&1; then echo "unexpected success $label" >&2; exit 1; fi
 grep -E "$pattern" "$label.txt"
}
inventory() {
 cli "SELECT name, engine, create_table_query FROM system.tables WHERE database='recovery_fixture' ORDER BY name FORMAT TSV" > ddl.txt
 cli "SELECT engine FROM system.databases WHERE name='recovery_fixture'" > database.txt
 cli 'SELECT * FROM recovery_fixture.events ORDER BY id FORMAT TSV' > rows.txt
 cli 'SELECT * FROM recovery_fixture.event_ids ORDER BY id FORMAT TSV' > view.txt
 cli 'SELECT * FROM recovery_fixture.schema_migrations ORDER BY sequence FORMAT TSV' > migrations.txt
 cli 'SELECT version,dirty FROM recovery_fixture.schema_migrations ORDER BY sequence DESC LIMIT 1 FORMAT TSV' > latest-migration.txt
 test "$(cat database.txt)" = Atomic
 test "$(cat latest-migration.txt)" = "$(printf '42\t0')"
}
'''
SOURCE = r'''
cli 'CREATE DATABASE recovery_fixture ENGINE=Atomic'
cli 'CREATE TABLE recovery_fixture.events (id UInt64, value String) ENGINE=MergeTree ORDER BY id'
cli "INSERT INTO recovery_fixture.events SELECT number, concat('synthetic-',toString(number)) FROM numbers(1000)"
cli 'CREATE VIEW recovery_fixture.event_ids AS SELECT id FROM recovery_fixture.events'
cli 'CREATE TABLE recovery_fixture.schema_migrations (sequence UInt64, version Int64, dirty UInt8) ENGINE=MergeTree ORDER BY sequence'
cli 'INSERT INTO recovery_fixture.schema_migrations VALUES (1,42,1),(2,42,0)'
inventory
cli "BACKUP DATABASE recovery_fixture TO File('fixture.tar')" > backup.txt
grep -q BACKUP_CREATED backup.txt
test -s data/backups/fixture.tar
test ! -e backups/fixture.tar
negative existing "BACKUP DATABASE recovery_fixture TO File('fixture.tar')" 'BACKUP_ALREADY_EXISTS'
negative escape "BACKUP DATABASE recovery_fixture TO File('../escape.tar')" 'not allowed for backups'
negative absolute "BACKUP DATABASE recovery_fixture TO File('/tmp/escape.tar')" 'not allowed for backups'
negative disk "BACKUP DATABASE recovery_fixture TO Disk('default','fixture.tar')" 'INVALID_CONFIG_PARAMETER'
test ! -e data/escape.tar; test ! -e /tmp/escape.tar
'''
RESTORE = r'''
test "$(cli \"SELECT count() FROM system.databases WHERE name='recovery_fixture'\")" = 0
if touch data/backups/fixture.tar 2>/dev/null; then echo 'archive writable' >&2; exit 1; fi
cli "RESTORE DATABASE recovery_fixture FROM File('fixture.tar')" > restore.txt
grep -q RESTORED restore.txt
inventory
'''.replace('\\"', '"')
CORRUPT = r'''
test "$(cli \"SELECT count() FROM system.databases WHERE name='recovery_fixture'\")" = 0
negative corrupt "RESTORE DATABASE recovery_fixture FROM File('fixture.tar')" 'ARGUMENT_OUT_OF_BOUND'
'''.replace('\\"', '"')
END = r'''
kill -TERM "$server"
wait "$server"
trap - EXIT
printf 'NATIVE_PHASE_PASS\n'
'''

def bounds():
    rel = Path('/proc/self/cgroup').read_text().strip().split(':', 2)[2]
    cg = Path('/sys/fs/cgroup' + rel)
    names = ('memory.max', 'memory.swap.max', 'cpu.max', 'pids.max', 'memory.events', 'pids.events', 'cgroup.procs')
    state = {n: (cg / n).read_text().strip() for n in names}
    require([state[n] for n in names[:4]] == ['4294967296', '0', '200000 100000', '256'], 'resource limits mismatch')
    return state

def phase(root, directory, mode, archive=None):
    shared.private_dir(directory)
    for sub in ('data/backups', 'tmp', 'user_files', 'format_schemas'):
        shared.private_dir(directory / sub)
    for name, content in [('config.xml', CONFIG), ('users.xml', USERS), ('fixture.sh', PROLOGUE + {'source': SOURCE, 'restore': RESTORE, 'corrupt': CORRUPT}[mode] + END)]:
        save(directory / name, content.encode())
    image_env = dict(x.split('=', 1) for x in json.loads((root.parent / 'config.json').read_text())['config'].get('Env', []))
    image_env.update(HOME='/tmp/fixture', LANG='C', TMPDIR='/tmp/fixture/tmp')
    cmd = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL', '--uid', '101', '--gid', '101', '--ro-bind', str(root), '/', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run', '--bind', str(directory), '/tmp/fixture']
    if archive:
        save(directory / 'data/backups/fixture.tar', b'')
        cmd += ['--ro-bind', str(archive), '/tmp/fixture/data/backups/fixture.tar']
    cmd += ['--chdir', '/tmp/fixture', '--clearenv']
    cmd += [arg for k, v in image_env.items() for arg in ('--setenv', k, v)]
    cmd += ['/bin/bash', '/tmp/fixture/fixture.sh']
    save(directory / 'sandbox-command.json', json.dumps(cmd, indent=2).encode())
    with (directory / 'native.log').open('xb') as log:
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=240)
    require(result.returncode == 0 and 'NATIVE_PHASE_PASS' in (directory / 'native.log').read_text(), 'native phase failed: ' + str(directory))

def worker(root, run):
    before = bounds()
    accounts = [x.split(':') for x in (root / 'etc/passwd').read_text().splitlines() if x.startswith('clickhouse:')]
    require(len(accounts) == 1 and accounts[0][2:4] == ['101', '101'], 'image service identity mismatch')
    phase(root, run / 'source', 'source')
    archive = run / 'native-archive.tar'
    with (run / 'source/data/backups/fixture.tar').open('rb') as src, archive.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    phase(root, run / 'restore', 'restore', archive)
    for name in ('ddl.txt', 'database.txt', 'rows.txt', 'view.txt', 'migrations.txt', 'latest-migration.txt'):
        require((run / 'source' / name).read_bytes() == (run / 'restore' / name).read_bytes(), 'inventory mismatch: ' + name)
    corrupt = run / 'corrupt-archive.tar'
    save(corrupt, archive.read_bytes()[:100])
    phase(root, run / 'corrupt', 'corrupt', corrupt)
    after = bounds()
    for name in ('memory.events', 'pids.events'):
        require(before[name] == after[name], 'resource failure counter changed')
    require(after['cgroup.procs'].splitlines() == [str(os.getpid())], 'unexpected remaining scope processes')
    artifacts = {str(p.relative_to(run)): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in run.rglob('*') if p.is_file() and not p.is_symlink()}
    save(run / 'receipt.json', json.dumps({'status': 'PASS', 'synthetic_only': True, 'fixture_code_sha256': sha(HERE), 'shared_code_sha256': sha(Path(shared.__file__)), 'completed_utc': datetime.now(timezone.utc).isoformat(), 'cgroup_before': before, 'cgroup_after_payload_quiescence': after, 'artifacts': artifacts, 'limits': 'AMD64 native diagnostic only; no ARM64, production authentication/data, encryption custody, coordinated recovery, Langfuse startup or owner login. Native commands bypass original entrypoint using generated loopback-only empty-password user configuration.'}, indent=2).encode())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    require(os.getuid() == os.geteuid() != 0 and platform.machine() == 'x86_64', 'requires unprivileged native AMD64 caller')
    shared.private_dir(CACHE)
    if args.worker:
        root, run = map(Path, args.worker)
        require(root.parent == CACHE / 'clickhouse' and run.parent == CACHE and re.fullmatch(r'rootfs-[0-9a-f]{32}', root.name) and re.fullmatch(r'run-[0-9a-f]{32}', run.name), 'worker paths refused')
        require({p.name for p in run.iterdir()} == {'attempt.json', 'image.json'}, 'fresh reservation required')
        worker(root, run)
        return
    require(PIN.removeprefix('docker.io/') in (REPO / 'langfuse/clickhouse.yaml').read_text(), 'production pin changed')
    for exe in ('bwrap', 'systemd-run', 'systemctl'):
        require(shutil.which(exe), 'missing prerequisite: ' + exe)
    root, metadata = shared.prepare('clickhouse')
    run = CACHE / ('run-' + uuid.uuid4().hex)
    shared.private_dir(run)
    save(run / 'image.json', json.dumps(metadata, indent=2).encode())
    original_hash, code_hash, shared_hash = shared.tree_hash(root), sha(HERE), sha(Path(shared.__file__))
    unit = 'langfuse-clickhouse-' + uuid.uuid4().hex + '.scope'
    save(run / 'attempt.json', json.dumps({'status': 'INCOMPLETE', 'scope': unit, 'fixture_code_sha256': code_hash, 'shared_code_sha256': shared_hash, 'started_utc': datetime.now(timezone.utc).isoformat()}, indent=2).encode())
    start = time.monotonic()
    try:
        result = subprocess.run(['systemd-run', '--user', '--scope', '--quiet', '--unit=' + unit, '-p', 'MemoryMax=4G', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=200%', '-p', 'TasksMax=256', sys.executable, '-B', str(HERE), '--worker', str(root), str(run)], stdin=subprocess.DEVNULL, timeout=750)
        require(result.returncode == 0 and (run / 'receipt.json').is_file(), 'worker failed: ' + str(run))
        require(shared.tree_hash(root) == original_hash and sha(HERE) == code_hash and sha(Path(shared.__file__)) == shared_hash, 'image/code changed')
        save(run / 'verified.json', json.dumps({'status': 'PASS', 'image_tree_before_after_sha256': original_hash, 'fixture_code_sha256': code_hash, 'shared_code_sha256': shared_hash, 'receipt_sha256': sha(run / 'receipt.json'), 'scope_exit': result.returncode, 'seconds': round(time.monotonic()-start, 3)}, indent=2).encode())
        print('CLICKHOUSE_NATIVE_RESTORE_PASS ' + str(run), flush=True)
    except Exception as exc:
        save(run / 'failure.json', json.dumps({'status': 'FAILED', 'reason': str(exc), 'image_tree_unchanged': shared.tree_hash(root) == original_hash}, indent=2).encode())
        raise
    finally:
        subprocess.run(['systemctl', '--user', 'stop', unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('REFUSED/FAILED: ' + str(exc), file=sys.stderr)
        sys.exit(1)
