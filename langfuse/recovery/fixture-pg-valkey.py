#!/usr/bin/env python3
"""Synthetic-only native recovery fixtures. No Docker daemon/config, cluster or secrets.

Run from this worktree: python3 -B langfuse/recovery/fixture-pg-valkey.py
Requires Linux AMD64/ARM64, bwrap, systemd user scope delegation, Python >=3.11.
Only writes below verification/cache/langfuse-recovery/pg-valkey/. Downloads use
anonymous Docker Hub token exchange; SHA256 is integrity, not signature proof.
Native binaries deliberately bypass production entrypoints/credentials: UID/GID
from image passwd (postgres/valkey), private Unix sockets, generated trust-only
state, no application startup.
Extraction normalizes ownership to the caller, adds owner rw/rwx for files/dirs,
and strips privileged mode bits;
no device/FIFO/xattr/capability restoration. Not a production recovery helper.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid
from typing import BinaryIO, cast

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / 'verification/cache/langfuse-recovery/pg-valkey'
PINS = {
    'postgres': 'docker.io/library/postgres:18@sha256:2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc',
    'valkey': 'docker.io/valkey/valkey:8.0@sha256:04b9002ae24bbe66687fb025052ed9bcebb54f8da3937338eb718d98d362887f',
}

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def private_dir(path):
    # Refuse every symlink ancestor, including an existing cache root.
    for part in [path, *path.parents]:
        require(not part.is_symlink(), 'symlink directory refused')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(path.is_dir() and path.stat().st_uid == os.getuid(), 'unsafe directory owner/type')
    if path == CACHE or CACHE in path.parents:
        require(path.stat().st_mode & 0o077 == 0, 'cache directory must be private')

def save(path, content):
    with path.open('xb') as f:
        f.write(content)

def download(url, path, digest=None, token=None):
    if path.exists():
        require(not path.is_symlink() and path.is_file(), 'unsafe cached artifact')
    else:
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json',
            **({'Authorization': 'Bearer ' + token} if token else {}),
        })
        # No local auth files are read. urllib drops Authorization on neither
        # same nor cross-host redirects; only anonymous public pull token used.
        with urllib.request.urlopen(req, timeout=120) as source, path.open('xb') as out:
            shutil.copyfileobj(source, out, 1024 * 1024)
    if digest:
        require(sha(path) == digest.removeprefix('sha256:'), 'download digest mismatch')
    return path

def confined(root, name):
    parts = list(PurePosixPath(name).parts)
    require(not name.startswith('/') and '..' not in parts, 'archive traversal refused')
    current = root
    pending = parts[:]
    links = 0
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            require(current != root, 'link escapes image')
            current = current.parent
            continue
        candidate = current / part
        if candidate.is_symlink():
            links += 1
            require(links < 64, 'symlink loop')
            target = os.readlink(candidate)
            if target.startswith('/'):
                current = root
            pending = list(PurePosixPath(target).parts)[int(target.startswith('/')):] + pending
        else:
            current = candidate
    require(current == root or root in current.parents, 'path escapes image')
    return current

def remove_image_path(p):
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)

def extract_layer(archive, root):
    with tarfile.open(archive, 'r:') as tf:
        members = tf.getmembers()
        # Whiteouts precede additions. Only the fresh, owned image tree changes.
        for m in members:
            name = PurePosixPath(m.name)
            if name.name.startswith('.wh.'):
                parent = confined(root, str(name.parent))
                if name.name == '.wh..wh..opq':
                    if parent.is_dir():
                        for child in parent.iterdir():
                            remove_image_path(child)
                else:
                    basename = name.name[4:]
                    require(basename not in ('', '.', '..'), 'invalid whiteout target')
                    target = parent / basename
                    require(target != root and root in target.parents, 'whiteout escapes image')
                    # Confine the parent, but unlink a final symlink itself;
                    # following it could delete its destination instead.
                    remove_image_path(target)
        for m in members:
            if PurePosixPath(m.name).name.startswith('.wh.'):
                continue
            # Resolve parents, not the final component being replaced.
            name = PurePosixPath(m.name)
            require(not m.name.startswith('/') and '..' not in name.parts, 'unsafe member')
            parent = confined(root, str(name.parent))
            p = parent / name.name
            if p == root or str(name) == '.':
                continue
            parent.mkdir(parents=True, exist_ok=True)
            if m.isdir():
                if p.is_symlink() or (p.exists() and not p.is_dir()):
                    remove_image_path(p)
                p.mkdir(exist_ok=True)
                p.chmod((m.mode & 0o777) | 0o700)
            elif m.isfile():
                remove_image_path(p)
                src = tf.extractfile(m)
                require(src is not None, 'missing regular member content')
                assert src is not None
                with src, p.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                p.chmod((m.mode & 0o777) | 0o600)
            elif m.issym():
                remove_image_path(p)
                # Absolute links remain image-absolute inside bwrap.
                os.symlink(m.linkname, p)
            elif m.islnk():
                target = confined(root, m.linkname)
                require(target.is_file() and not target.is_symlink(), 'unsafe hardlink')
                remove_image_path(p)
                os.link(target, p)
            # Skip device nodes, sockets, FIFOs.

def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        s = p.lstat()
        h.update(str(p.relative_to(root)).encode() + b'\0')
        h.update(str(stat.S_IMODE(s.st_mode)).encode() + b'\0')
        if p.is_symlink():
            h.update(os.readlink(p).encode())
        elif p.is_file():
            h.update(sha(p).encode())
    return h.hexdigest()

def prepare(name):
    reference, index_digest = PINS[name].split('@sha256:')
    repo = reference.removeprefix('docker.io/').rsplit(':', 1)[0]
    dest = CACHE / name
    private_dir(dest)
    # Token is anonymous, ephemeral, in memory only; no configured Docker auth.
    with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:' + repo + ':pull', timeout=30) as response:
        token = json.load(response)['token']
    base = 'https://registry-1.docker.io/v2/' + repo
    index_path = download(base + '/manifests/sha256:' + index_digest, dest / 'index.json', index_digest, token)
    index = json.loads(index_path.read_bytes())
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}[platform.machine()]
    choices = [m for m in index['manifests'] if m.get('platform', {}).get('os') == 'linux' and m['platform']['architecture'] == arch]
    require(len(choices) == 1, 'ambiguous platform')
    manifest_digest = choices[0]['digest']
    manifest_path = download(base + '/manifests/' + manifest_digest, dest / 'manifest.json', manifest_digest, token)
    manifest = json.loads(manifest_path.read_bytes())
    config_path = download(base + '/blobs/' + manifest['config']['digest'], dest / 'config.json', manifest['config']['digest'], token)
    config = json.loads(config_path.read_bytes())
    require(config['architecture'] == arch and config['os'] == 'linux', 'config platform mismatch')
    require(len(config['rootfs']['diff_ids']) == len(manifest['layers']), 'diffID count mismatch')
    archives = []
    for layer, diffid in zip(manifest['layers'], config['rootfs']['diff_ids']):
        digest = layer['digest'].removeprefix('sha256:')
        packed = download(base + '/blobs/' + layer['digest'], dest / (digest + '.blob'), layer['digest'], token)
        require(packed.stat().st_size == layer['size'], 'blob size mismatch')
        unpacked = dest / (digest + '.tar')
        if not unpacked.exists():
            require('gzip' in layer['mediaType'] or layer['mediaType'].endswith('.tar'), 'unsupported layer compression')
            src = gzip.open(packed, 'rb') if 'gzip' in layer['mediaType'] else packed.open('rb')
            with src, unpacked.open('xb') as out:
                shutil.copyfileobj(cast(BinaryIO, src), out, 1024 * 1024)
        require(not unpacked.is_symlink() and sha(unpacked) == diffid.removeprefix('sha256:'), 'uncompressed diffID mismatch')
        archives.append(unpacked)
    # Fresh root every invocation; no reuse of an incompletely extracted tree.
    root = dest / ('rootfs-' + uuid.uuid4().hex)
    private_dir(root)
    for archive in archives:
        extract_layer(archive, root)
    metadata = {'image': repo, 'index_digest': 'sha256:' + sha(index_path),
                'platform_digest': 'sha256:' + sha(manifest_path), 'config_digest': 'sha256:' + sha(config_path),
                'architecture': arch, 'original_runtime': config['config'],
                'verified_layers': len(archives), 'rootfs': str(root)}
    return root, metadata

PG_SCRIPT = r'''set -eu
export PATH=/usr/lib/postgresql/18/bin:$PATH
initdb -D /tmp/fixture/source --auth=trust --username=fixture_admin --no-locale >init-source.log
pg_ctl -D /tmp/fixture/source -l source.log -o "-k /tmp/fixture -c listen_addresses='' -c shared_buffers=32MB" -w start
trap 'pg_ctl -D /tmp/fixture/source -m fast stop >/dev/null 2>&1 || true; pg_ctl -D /tmp/fixture/restored -m fast stop >/dev/null 2>&1 || true' EXIT
psql -h /tmp/fixture -U fixture_admin -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE fixture_owner NOLOGIN;
CREATE DATABASE fixture OWNER fixture_owner;
SQL
psql -h /tmp/fixture -U fixture_admin -d fixture -v ON_ERROR_STOP=1 <<'SQL'
SET ROLE fixture_owner;
CREATE SCHEMA sample AUTHORIZATION fixture_owner;
CREATE TABLE sample.events (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, payload jsonb NOT NULL, body bytea NOT NULL);
INSERT INTO sample.events(payload,body) SELECT jsonb_build_object('id',i,'synthetic',true),decode(md5(i::text),'hex') FROM generate_series(1,1000) i;
CREATE TABLE sample.migrations(version text PRIMARY KEY);
INSERT INTO sample.migrations VALUES ('synthetic-001');
CREATE VIEW sample.event_ids AS SELECT id FROM sample.events;
SQL
pg_dumpall -h /tmp/fixture -U fixture_admin --globals-only --no-role-passwords > globals.sql
pg_dump -h /tmp/fixture -U fixture_admin -d fixture -Fc --create -f fixture.dump
pg_restore --list fixture.dump > archive-list.txt
# Parse every archived block to SQL, independently of the restore execution.
pg_restore --file=archive-expanded.sql fixture.dump
# A truncated custom archive must not pass complete block parsing.
head -c 100 fixture.dump > truncated.dump
if pg_restore --file=/dev/null truncated.dump > truncated-check.txt 2>&1; then exit 1; fi
cat > inventory.sql <<'SQL'
SELECT 'version='||current_setting('server_version');
SELECT 'extension='||extname||':'||extversion FROM pg_extension ORDER BY 1;
SELECT 'schema='||nspname||':'||pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='sample' ORDER BY 1;
SELECT 'relation='||relname||':'||relkind::text||':'||pg_get_userbyid(relowner) FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='sample' ORDER BY 1;
SELECT 'rows='||count(*)||',digest='||md5(string_agg(id::text||payload::text||encode(body,'hex'),'' ORDER BY id)) FROM sample.events;
SELECT 'migration='||version FROM sample.migrations ORDER BY 1;
SELECT 'sequence='||last_value FROM sample.events_id_seq;
SELECT 'role='||rolname||':'||rolcanlogin::text FROM pg_roles WHERE rolname='fixture_owner';
SQL
psql -XAt -h /tmp/fixture -U fixture_admin -d fixture -v ON_ERROR_STOP=1 -f inventory.sql > expected.txt
pg_ctl -D /tmp/fixture/source -m fast -w stop
initdb -D /tmp/fixture/restored --auth=trust --username=restore_admin --no-locale >init-restored.log
pg_ctl -D /tmp/fixture/restored -l restored.log -o "-k /tmp/fixture -c listen_addresses='' -c shared_buffers=32MB" -w start
psql -h /tmp/fixture -U restore_admin -d postgres -v ON_ERROR_STOP=1 -f globals.sql
pg_restore -h /tmp/fixture -U restore_admin -d postgres --create --exit-on-error fixture.dump
psql -XAt -h /tmp/fixture -U restore_admin -d fixture -v ON_ERROR_STOP=1 -f inventory.sql > actual.txt
cmp expected.txt actual.txt
pg_amcheck -h /tmp/fixture -U restore_admin -d fixture --install-missing > amcheck.txt
# Identity sequence is restored, not merely table rows.
test "$(psql -XAt -h /tmp/fixture -U restore_admin -d fixture -v ON_ERROR_STOP=1 -c "INSERT INTO sample.events(payload,body) VALUES ('{}','') RETURNING id")" = "$(printf '1001\nINSERT 0 1')"
pg_ctl -D /tmp/fixture/restored -m fast -w stop
trap - EXIT
printf 'POSTGRES_NATIVE_RESTORE_PASS\n'
'''

VALKEY_SCRIPT = r'''set -eu
mkdir source restored checkpoint
cat > source.conf <<'CONF'
port 0
unixsocket /tmp/fixture/valkey.sock
unixsocketperm 700
appendonly yes
appendfsync always
save ""
maxmemory 64mb
maxmemory-policy noeviction
CONF
start() {
 valkey-server /tmp/fixture/source.conf --dir "/tmp/fixture/$1" > "$1.log" 2>&1 & server=$!
 i=0
 until test -S /tmp/fixture/valkey.sock && test "$(valkey-cli -s /tmp/fixture/valkey.sock ping 2>/dev/null)" = PONG; do
  i=$((i+1)); test "$i" -lt 100; sleep 0.1
 done
}
cli() { valkey-cli -e --raw -s /tmp/fixture/valkey.sock "$@"; }
trap 'test -z "${server:-}" || kill "$server" 2>/dev/null || true; wait 2>/dev/null || true' EXIT
start source
test "$(cli SET fixture:string synthetic)" = OK
test "$(cli RPUSH fixture:queue job-001 job-002 job-003)" = 3
test "$(cli HSET fixture:hash status waiting attempt 2)" = 2
test "$(cli ZADD fixture:delayed 100 job-004 200 job-005)" = 2
test "$(cli SADD fixture:set a b c)" = 3
cli XADD fixture:stream 1-0 type synthetic > stream-id.txt
test "$(cli SET fixture:ttl retained EX 86400)" = OK
test "$(cli BGREWRITEAOF)" = 'Background append only file rewriting started'
i=0
while cli INFO persistence | tr -d '\r' | grep -q '^aof_rewrite_in_progress:1$'; do i=$((i+1)); test "$i" -lt 100; sleep 0.1; done
cli INFO persistence | tr -d '\r' > persistence-before.txt
grep -q '^aof_last_bgrewrite_status:ok$' persistence-before.txt
grep -q '^aof_last_write_status:ok$' persistence-before.txt
# Post-rewrite writes exercise the incremental AOF, not only its RDB base.
test "$(cli RPUSH fixture:queue job-006)" = 4
test "$(cli SET fixture:after-rewrite present)" = OK
inventory() {
 cli DBSIZE
 cli GET fixture:string
 cli LRANGE fixture:queue 0 -1
 cli HGET fixture:hash status
 cli HGET fixture:hash attempt
 cli ZRANGE fixture:delayed 0 -1 WITHSCORES
 cli SMEMBERS fixture:set | sort
 cli XRANGE fixture:stream - +
 cli GET fixture:ttl
 cli GET fixture:after-rewrite
 cli DEBUG DIGEST
}
# DEBUG DIGEST disabled by default; enable explicitly for generated fixture only.
# DEBUG DIGEST covers typed values; list/zset/stream output also checks order.
inventory > expected.txt
cli SHUTDOWN NOSAVE
wait "$server"; server=''
# Shutdown closes writers before checkpoint. Preserve entire multipart directory.
cp -a source/appendonlydir checkpoint/
valkey-check-aof checkpoint/appendonlydir/appendonly.aof.manifest > aof-check.txt
grep -q 'All AOF files and manifest are valid' aof-check.txt
# Corrupt a separate synthetic copy, never repair the accepted checkpoint.
mkdir corrupt
cp -a checkpoint/appendonlydir corrupt/
incr=$(awk '$6 == "i" {print $2}' corrupt/appendonlydir/appendonly.aof.manifest)
test -n "$incr"
printf 'not-a-resp-record\n' >> "corrupt/appendonlydir/$incr"
if valkey-check-aof corrupt/appendonlydir/appendonly.aof.manifest > corrupt-check.txt 2>&1; then exit 1; fi
cp -a checkpoint/appendonlydir restored/
start restored
inventory > actual.txt
cmp expected.txt actual.txt
test "$(cli LLEN fixture:queue)" = 4
ttl=$(cli TTL fixture:ttl); test "$ttl" -gt 86000; test "$ttl" -le 86400
cli INFO persistence | tr -d '\r' > persistence-restored.txt
grep -q '^aof_last_write_status:ok$' persistence-restored.txt
cli SHUTDOWN NOSAVE
wait "$server"; server=''
trap - EXIT
printf 'VALKEY_AOF_RESTORE_PASS\n'
'''

def cgroup_state():
    rel = Path('/proc/self/cgroup').read_text().strip().split(':', 2)[2]
    path = Path('/sys/fs/cgroup' + rel)
    result = {n: (path / n).read_text().strip() for n in ('memory.max', 'memory.swap.max', 'cpu.max', 'pids.max', 'memory.events', 'pids.events')}
    require(result['memory.max'] == '1073741824' and result['memory.swap.max'] == '0' and result['pids.max'] == '96', 'resource bounds not enforced')
    require(result['cpu.max'] == '100000 100000', 'CPU quota not enforced')
    return result

def worker(name, root, run):
    before = cgroup_state()
    require(os.getuid() == os.geteuid() != 0 and os.getgid() == os.getegid(), 'must run rootless')
    script = PG_SCRIPT if name == 'postgres' else VALKEY_SCRIPT
    if name == 'valkey':
        script = script.replace('appendonly yes\n', 'appendonly yes\nenable-debug-command yes\n')
    prologue = '''set -eu
if touch /etc/fixture-write-denied 2>/dev/null; then exit 1; fi
command -v /bin/bash timeout > /tmp/fixture/network-check-tools.txt
# Network namespace must have no external route (loopback-only namespace).
cat /proc/net/route > /tmp/fixture/network-routes.txt
test "$(wc -l < /proc/net/route)" -eq 1
cat /proc/net/dev > /tmp/fixture/network-interfaces.txt
test "$(grep -c ':' /proc/net/dev)" -eq 1
grep -q 'lo:' /proc/net/dev
for endpoint in 1.1.1.1/443 192.168.0.40/2049 192.168.0.11/6443 10.43.0.1/443; do
 if timeout 2 /bin/bash -c "echo probe > /dev/tcp/$endpoint" 2>/dev/null; then
  echo 'unexpected external connectivity' >&2; exit 1
 fi
done
'''
    save(run / 'fixture.sh', (prologue + script).encode())
    account = 'postgres' if name == 'postgres' else 'valkey'
    accounts = [line.split(':') for line in (root / 'etc/passwd').read_text().splitlines()]
    selected = [entry for entry in accounts if entry[0] == account]
    require(len(selected) == 1, 'image service account missing')
    uid, gid = selected[0][2:4]
    require(uid.isdecimal() and gid.isdecimal() and int(uid) > 0 and int(gid) > 0, 'nonroot image service account required')
    config = json.loads((root.parent / 'config.json').read_text())['config']
    image_env = dict(item.split('=', 1) for item in config.get('Env', []))
    # Public image Env only; no host environment or app configuration is inherited.
    image_env.update(HOME='/tmp/fixture', LANG='C')
    env_args = [arg for key, value in image_env.items() for arg in ('--setenv', key, value)]
    cmd = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
           '--uid', uid, '--gid', gid, '--ro-bind', str(root), '/', '--proc', '/proc', '--dev', '/dev',
           '--tmpfs', '/tmp', '--tmpfs', '/run', '--bind', str(run), '/tmp/fixture',
           '--chdir', '/tmp/fixture', '--clearenv', *env_args,
           '/bin/sh', '/tmp/fixture/fixture.sh']
    save(run / 'sandbox-command.json', json.dumps(cmd, indent=2).encode())
    start = time.monotonic()
    with (run / 'native.log').open('xb') as log:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    after = cgroup_state()  # bwrap waited for the sandbox; no database descendants remain.
    for filename in ('memory.events', 'pids.events'):
        require(before[filename] == after[filename], 'resource failure counter changed')
    require(p.returncode == 0, 'native fixture failed; inspect cache native.log')
    marker = 'POSTGRES_NATIVE_RESTORE_PASS' if name == 'postgres' else 'VALKEY_AOF_RESTORE_PASS'
    require(marker in (run / 'native.log').read_text(), 'native success marker missing')
    artifacts = {str(p.relative_to(run)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
                 for p in run.rglob('*') if p.is_file() and not p.is_symlink()}
    receipt = {'status': 'PASS', 'synthetic_only': True, 'engine': name,
               'completed_utc': datetime.now(timezone.utc).isoformat(),
               'fixture_code_sha256': sha(Path(__file__)),
               'seconds': round(time.monotonic() - start, 3), 'cgroup_before': before,
               'cgroup_after_payload_quiescence': after, 'artifacts': artifacts,
               'runtime_overrides': {'command': 'native binaries, not entrypoint; generated trust-only config',
                                     'uid': uid, 'gid': gid, 'account': account,
                                     'cwd': '/tmp/fixture', 'public_image_env': image_env},
               'isolation': 'bwrap unshare-all, read-only image root, private proc/dev/tmp/run; only fixture bind',
               'limitations': 'Synthetic native restore only; not encryption, production credentials/data, Langfuse schema, cross-store consistency, owner login, or production recovery.'}
    save(run / 'receipt.json', json.dumps(receipt, indent=2).encode())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['all', *PINS], default='all')
    parser.add_argument('--worker', nargs=3, metavar=('ENGINE', 'ROOT', 'RUN'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    require(platform.system() == 'Linux' and platform.machine() in ('x86_64', 'aarch64'), 'unsupported native platform')
    require(os.getuid() != 0 and os.getuid() == os.geteuid(), 'unprivileged caller required')
    private_dir(CACHE)
    if args.worker:
        name, root, run = args.worker
        require(name in PINS, 'unknown worker engine')
        root, run = Path(root), Path(run)
        require(root.parent == CACHE / name and run.parent == CACHE / name
                and re.fullmatch(r'rootfs-[0-9a-f]{32}', root.name)
                and re.fullmatch(r'run-[0-9a-f]{32}', run.name), 'worker path outside fixed reserved cache')
        private_dir(root)
        private_dir(run)
        require({p.name for p in run.iterdir()} == {'image.json', 'attempt.json'}, 'worker requires fresh fixture directory')
        worker(name, root, run)
        return
    for executable in ('bwrap', 'systemd-run', 'systemctl'):
        require(shutil.which(executable), 'missing prerequisite: ' + executable)
    values = (REPO / 'langfuse/values.yaml').read_text()
    require(all(ref.split(':', 1)[1] in values for ref in
                (image.removeprefix('docker.io/').split('/')[-1] for image in PINS.values())),
            'production pins changed; review fixture pins')
    for name in (list(PINS) if args.engine == 'all' else [args.engine]):
        root, metadata = prepare(name)
        run = CACHE / name / ('run-' + uuid.uuid4().hex)
        private_dir(run)
        save(run / 'image.json', json.dumps(metadata, indent=2).encode())
        root_hash = tree_hash(root)
        unit = 'langfuse-pg-valkey-' + uuid.uuid4().hex + '.scope'
        cmd = ['systemd-run', '--user', '--scope', '--quiet', '--unit=' + unit,
               '-p', 'MemoryMax=1G', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%', '-p', 'TasksMax=96',
               sys.executable, '-B', str(Path(__file__).resolve()), '--worker', name, str(root), str(run)]
        save(run / 'attempt.json', json.dumps({'status': 'INCOMPLETE', 'scope': unit,
                                               'started_utc': datetime.now(timezone.utc).isoformat()}, indent=2).encode())
        try:
            result = subprocess.run(cmd, timeout=210, stdin=subprocess.DEVNULL)
            require(result.returncode == 0 and (run / 'receipt.json').is_file(), 'bounded worker failed: ' + str(run))
            require(tree_hash(root) == root_hash, 'image tree modified')
            save(run / 'verified.json', json.dumps({'status': 'PASS', 'image_tree_before_after_sha256': root_hash,
                                                    'receipt_sha256': sha(run / 'receipt.json'), 'scope_exit': result.returncode}, indent=2).encode())
            print(name + ': PASS ' + str(run / 'receipt.json'), flush=True)
        except Exception as exc:
            save(run / 'failure.json', json.dumps({'status': 'FAILED', 'reason': str(exc),
                                                   'completed_utc': datetime.now(timezone.utc).isoformat()}, indent=2).encode())
            raise
        finally:
            subprocess.run(['systemctl', '--user', 'stop', unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('REFUSED/FAILED: ' + str(exc), file=sys.stderr)
        sys.exit(1)
