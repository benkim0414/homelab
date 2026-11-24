#!/usr/bin/env python3
"""Exercise exact PostgreSQL export producer commands on generated native state.

No production kubectl execution. Uses the already-reviewed rootless OCI helper
and pins, generated SCRAM credentials, a bounded systemd scope and offline image.
Native output is generated fixture data only; it is not a production recovery set.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any
import uuid

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'verification/cache/langfuse-recovery/postgres-export'


def load(name, path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


shared = load('pg_export_fixture_shared', Path(__file__).with_name('fixture-pg-valkey.py'))
exports = load('pg_export_producers', Path(__file__).with_name('postgres_exports.py'))


def fixture_script():
    source = {'name': exports.POD, 'container': exports.CONTAINER, 'image': exports.IMAGE,
              'ready': 'true', 'phase': 'Running', 'deleting': '<none>',
              'uid': '00000000-0000-0000-0000-000000000001'}
    database, globals_export = exports.build(source)
    return r'''set -eu
export PATH=/usr/lib/postgresql/18/bin:$PATH
umask 077
printf '%s\n' 'fixture-only' > fixture.password
initdb -D /tmp/fixture/source --auth-local=trust --auth-host=scram-sha-256 --username=postgres --pwfile=fixture.password --no-locale > init.log
pg_ctl -D /tmp/fixture/source -l source.log -o "-k /tmp/fixture -c listen_addresses='127.0.0.1' -c shared_buffers=32MB" -w start
trap 'pg_ctl -D /tmp/fixture/source -m fast stop >/dev/null 2>&1 || true; pg_ctl -D /tmp/fixture/restored -m fast stop >/dev/null 2>&1 || true' EXIT
psql -h /tmp/fixture -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE fixture_owner NOLOGIN;
CREATE DATABASE langfuse OWNER fixture_owner;
SQL
psql -h /tmp/fixture -U postgres -d langfuse -v ON_ERROR_STOP=1 <<'SQL'
SET ROLE fixture_owner;
CREATE TABLE fixture_rows (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, value text NOT NULL);
INSERT INTO fixture_rows(value) SELECT 'generated-'||i FROM generate_series(1,1000) i;
SQL
export POSTGRES_DB=langfuse POSTGRES_PASSWORD=fixture-only
''' + shlex.join(database.container_argv) + r''' > database.dump
''' + shlex.join(globals_export.container_argv) + r''' > globals.sql
# Missing configured authentication must fail without prompting.
if POSTGRES_PASSWORD='' ''' + shlex.join(database.container_argv) + r''' > missing-auth.incomplete 2>/dev/null; then exit 1; fi
if POSTGRES_DB=other ''' + shlex.join(database.container_argv) + r''' > wrong-database.incomplete 2>/dev/null; then exit 1; fi
# Exported role auth is intentionally omitted; stable auth restoration is separate.
if grep -q 'PASSWORD' globals.sql; then exit 1; fi
pg_restore --file=/dev/null database.dump
head -c 100 database.dump > truncated.dump
if pg_restore --file=/dev/null truncated.dump > /dev/null 2>&1; then exit 1; fi
psql -XAt -h /tmp/fixture -U postgres -d langfuse -c "SELECT count(*),md5(string_agg(id::text||value,'' ORDER BY id)) FROM fixture_rows" > expected.txt
pg_ctl -D /tmp/fixture/source -m fast -w stop
initdb -D /tmp/fixture/restored --auth=trust --username=restore_admin --no-locale > restore-init.log
pg_ctl -D /tmp/fixture/restored -l restore.log -o "-k /tmp/fixture -c listen_addresses='' -c shared_buffers=32MB" -w start
psql -h /tmp/fixture -U restore_admin -d postgres -v ON_ERROR_STOP=1 -f globals.sql > globals-restore.log
pg_restore -h /tmp/fixture -U restore_admin -d postgres --create --exit-on-error database.dump
psql -XAt -h /tmp/fixture -U restore_admin -d langfuse -c "SELECT count(*),md5(string_agg(id::text||value,'' ORDER BY id)) FROM fixture_rows" > actual.txt
cmp expected.txt actual.txt
pg_amcheck -h /tmp/fixture -U restore_admin -d langfuse --install-missing > amcheck.log
pg_ctl -D /tmp/fixture/restored -m fast -w stop
trap - EXIT
printf 'POSTGRES_NATIVE_RESTORE_PASS\n'
'''


def main():
    os.umask(0o077)
    shared.private_dir(CACHE)
    shared.require(CACHE.stat().st_mode & 0o077 == 0, 'cache must be private')
    if len(sys.argv) == 4 and sys.argv[1] == '--worker':
        root, run = map(Path, sys.argv[2:])
        if (run.parent != CACHE or run.is_symlink() or root.parent != shared.CACHE / 'postgres'
                or not re.fullmatch(r'run-[0-9a-f]{32}', run.name)
                or not re.fullmatch(r'rootfs-[0-9a-f]{32}', root.name)
                or {p.name for p in run.iterdir()} != {'image.json', 'attempt.json'}):
            raise ValueError('worker paths not admitted')
        shared.PG_SCRIPT = fixture_script()
        shared.worker('postgres', root, run)
        return 0
    if len(sys.argv) != 1:
        return 2
    root, image = shared.prepare('postgres')
    before = shared.tree_hash(root)
    run = CACHE / ('run-' + uuid.uuid4().hex)
    run.mkdir(mode=0o700)
    shared.save(run / 'image.json', json.dumps(image, indent=2).encode())
    unit = 'langfuse-postgres-export-' + uuid.uuid4().hex + '.scope'
    shared.save(run / 'attempt.json', json.dumps({'status': 'INCOMPLETE', 'scope': unit,
                'started_utc': datetime.now(timezone.utc).isoformat()}, indent=2).encode())
    argv = ['systemd-run', '--user', '--scope', '--quiet', '--unit=' + unit,
            '-p', 'MemoryMax=1G', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%', '-p', 'TasksMax=96',
            sys.executable, '-B', str(Path(__file__).resolve()), '--worker', str(root), str(run)]
    try:
        result = subprocess.run(argv, timeout=210, stdin=subprocess.DEVNULL)
        if result.returncode or shared.tree_hash(root) != before:
            raise ValueError('generated native exporter fixture failed')
        receipt = json.loads((run / 'receipt.json').read_text())
        if receipt['status'] != 'PASS':
            raise ValueError('native receipt did not pass')
        for name, metadata in receipt['artifacts'].items():
            path = run / name
            if shared.sha(path) != metadata['sha256'] or path.stat().st_size != metadata['bytes']:
                raise ValueError('native artifact changed')
        verification = {'status': 'PASS', 'synthetic_only': True, 'source_auth': 'generated SCRAM',
                        'helper_sha256': shared.sha(Path(__file__)),
                        'producer_sha256': shared.sha(Path(__file__).with_name('postgres_exports.py')),
                        'shared_sha256': shared.sha(Path(__file__).with_name('fixture-pg-valkey.py')),
                        'receipt_sha256': shared.sha(run / 'receipt.json'),
                        'image_tree_sha256': before, 'includes_production_auth_material': False}
        shared.save(run / 'verified.json', json.dumps(verification, indent=2).encode())
        print(json.dumps({'status': 'PASS', 'verified': str(run / 'verified.json'), 'synthetic_only': True}))
        return 0
    except Exception:
        shared.save(run / 'failure.json', b'{"status":"FAILED","reason":"generated exporter fixture failed"}\n')
        print('Generated exporter fixture failed; attempt preserved.', file=sys.stderr)
        return 1
    finally:
        subprocess.run(['systemctl', '--user', 'stop', unit], timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    sys.exit(main())
