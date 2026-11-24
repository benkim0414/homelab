#!/usr/bin/env python3
"""Offline synthetic SeaweedFS 4.23 acceptance, NOT a production backup adapter.

Run from this worktree: python langfuse/recovery/fixture-seaweed.py
Requires the anonymously verified ch-seaweed/image cache (image.py prepares it),
bwrap, nsenter and a delegated systemd user scope. No cluster or credentials.
Every run reserves a new private directory; nothing is overwritten or deleted.

The loader's stdin remains open until an independent full metadata export equals
our pre-export expected inventory AND every object and every chunk reads back.
Polling is bounded by a monotonic deadline, not an assumed completion sleep.
On failure it is terminated, never released as accepted. This deliberately only
accepts the generated two-object, replication000, local non-EC fixture shape.
The virtual '/' entry's clock-generated attributes are normalized only after an
exact shape check; all persistent entry bytes must agree. Shutdown can generate
an additional internal log volume 8 AFTER the export point: it is inventoried
and explicitly excluded, not claimed recovered. Unknown post-capture volumes
are rejected. This is application-object acceptance, not whole-service recovery.

Production blockers: exhaustive independently authoritative collection/normal,
EC and remote topology; chunk manifests, TTL/deletes/compaction, versioned/S3
multipart objects and policy/IAM/config/system-log/identity recovery; authenticated
private transport, writer exclusion, encrypted no-overwrite publication/custody,
ARM64 runtime and coordinated four-store isolated Langfuse/owner-login acceptance.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / 'verification/cache/langfuse-recovery/seaweed-hardened'
ENGINE = REPO / 'verification/cache/langfuse-recovery/ch-seaweed'
INDEX = 'sha256:c6d6fb84b081f1f09bb089184ff4b45d2f163a1bfa8b354d04cf400c6e06f242'
MANIFEST = 'sha256:5189cf43bced06e1e64ec704170e11a93a005d36e9e833f9ac5e99c4c15947ff'
OBJECTS = {'/buckets/fixture/fixture.txt': b'synthetic-seaweed-recovery-fixture-v1\n',
           '/buckets/fixture/large.bin': b'X' * (3 * 1048576) + b'chunk-tail\n'}


class Refusal(RuntimeError):
    pass


def need(ok, reason):
    if not ok:
        raise Refusal(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    """Exclusive publication even for diagnostics; caller owns private parent."""
    if isinstance(data, str):
        data = data.encode()
    with path.open('xb') as f:
        os.chmod(path, 0o600)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def jsave(path, value):
    save(path, json.dumps(value, indent=2, sort_keys=True) + '\n')


def tree(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        h.update(str(p.relative_to(root)).encode())
        h.update(str(p.lstat().st_mode).encode())
        if p.is_symlink():
            h.update(os.readlink(p).encode())
        elif p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def varint(data, pos):
    n = 0
    for shift in range(0, 70, 7):
        need(pos < len(data), 'protobuf-truncated')
        b = data[pos]
        pos += 1
        n |= (b & 127) << shift
        if not b & 128:
            return n, pos
    raise Refusal('protobuf-varint')


def wire(data, allowed):
    """Minimal strict wire parser; unknown fields/types fail closed."""
    pos, fields = 0, {}
    while pos < len(data):
        tag, pos = varint(data, pos)
        number, kind = tag >> 3, tag & 7
        need(number in allowed, 'protobuf-unknown-field')
        if kind == 0:
            value, pos = varint(data, pos)
        elif kind in (1, 5):
            size = 8 if kind == 1 else 4
            value = data[pos:pos + size]
            pos += size
            need(len(value) == size, 'protobuf-truncated')
        elif kind == 2:
            size, pos = varint(data, pos)
            value = data[pos:pos + size]
            pos += size
            need(len(value) == size, 'protobuf-truncated')
        else:
            raise Refusal('protobuf-wire-type')
        fields.setdefault(number, []).append(value)
    return fields


def single(fields, key, default=None):
    values = fields.get(key, [default])
    need(len(values) == 1, 'protobuf-duplicate')
    return values[0]


def _encode_entry_wire(fields):
    """Canonical FullEntry/Entry/map wire order; these have no fixed32/64 fields."""
    def vint(n):
        out = bytearray()
        while n > 127:
            out.append((n & 127) | 128); n >>= 7
        out.append(n)
        return bytes(out)
    out = bytearray()
    for number, values in sorted(fields.items()):
        for value in values:
            if isinstance(value, bytes):
                out.extend(vint(number*8+2)+vint(len(value))+value)
            else:
                need(type(value) is int and value >= 0, 'metadata-wire-value')
                out.extend(vint(number*8)+vint(value))
    return bytes(out)


def records(blob, *, application_state=False):
    """Validate complete gzip CRC/trailer and every length-prefixed FullEntry."""
    try:
        raw = gzip.decompress(blob)
    except (OSError, EOFError, ValueError):
        raise Refusal('metadata-gzip') from None
    need(0 < len(raw) < 1048576, 'metadata-size')
    out, pos = {}, 0
    while pos < len(raw):
        need(pos + 4 <= len(raw), 'metadata-frame-header')
        size = struct.unpack('>I', raw[pos:pos + 4])[0]
        pos += 4
        need(0 < size <= 65536 and pos + size <= len(raw), 'metadata-frame-body')
        data = raw[pos:pos + size]
        pos += size
        f = wire(data, {1, 2})
        directory = single(f, 1).decode()
        entry = wire(single(f, 2), {1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12})
        name = single(entry, 1, b'').decode()
        need(directory.startswith('/') and '..' not in directory.split('/') and
             name not in ('.', '..') and '/' not in name, 'metadata-path')
        path = directory.rstrip('/') + '/' + name
        need(path not in out, 'metadata-duplicate')
        need(not any(entry.get(k) for k in ((7, 8, 10, 11, 12) if application_state else (5, 7, 8, 9, 10, 11, 12))),
             'metadata-unsupported-state')
        if application_state:
            # S3 bucket ownership/settings, object metadata and inline .etc/IAM
            # entries are application state, not optional change-log history.
            keys = set()
            extended = []
            for item in entry.get(5, []):
                kv = wire(item, {1, 2})
                key = single(kv, 1)
                need(isinstance(key, bytes) and key not in keys, 'metadata-extended-map')
                keys.add(key)
                need(isinstance(single(kv, 2, b''), bytes), 'metadata-extended-map')
                extended.append((key, _encode_entry_wire(kv)))
            if 5 in entry:
                entry[5] = [value for key,value in sorted(extended)]
                # Protobuf maps have no ordering semantics and native proto.Marshal
                # randomizes their iteration. Preserve every key/value byte, not
                # the incidental wire ordering; never normalize app attributes.
                data = _encode_entry_wire({1:f[1],2:[_encode_entry_wire(entry)]})
            if 9 in entry:
                need(isinstance(single(entry, 9), bytes) and not entry.get(3), 'metadata-inline-and-chunks')
        attrs = wire(single(entry, 4), {1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 16, 17, 18, 19, 20, 21})
        need(not any(attrs.get(k) for k in (10, 11, 12, 13, 16)), 'metadata-unsupported-attributes')
        for chunk in entry.get(3, []):
            c = wire(chunk, set(range(1, 14)))
            need(not any(c.get(k) for k in (6, 8, 9, 11, 12, 13)), 'metadata-unsupported-chunk')
            if c.get(7):
                wire(single(c, 7), {1, 2, 3})
        if path == '/':
            # GetEntry('/') synthesizes a virtual root with current clock values;
            # it is not a persistent filer record. Check the exact supported shape
            # and compare all stable fields, retaining the raw export as evidence.
            need(set(entry) == {2, 4} and single(entry, 2) == 1 and
                 set(attrs) == {2, 3, 4, 5, 6, 18, 19}, 'unsupported-virtual-root')
            stable = {k: v for k, v in attrs.items() if k not in (2, 6, 19)}
            out[path] = json.dumps(stable, sort_keys=True).encode()
        else:
            out[path] = data
    return out


def check_expected(actual, expected):
    need(actual == expected, 'metadata-inventory-mismatch')


def volume_inventory(topology, listing):
    """Only this fixture's explicit single-node/simple-layout topology is supported.

    Not a general production discovery algorithm. No host filesystem glob is a
    topology source. Cross-check master JSON, native listing and volume status.
    """
    t = topology['Topology']
    need(set(t) == {'Max', 'Free', 'DataCenters', 'Layouts'}, 'unknown-topology')
    dcs = t['DataCenters']
    need(len(dcs) == 1 and len(dcs[0]['Racks']) == 1, 'unsupported-topology')
    nodes = dcs[0]['Racks'][0]['DataNodes']
    need(len(nodes) == 1, 'unsupported-nodes')
    node = nodes[0]
    need(set(node) == {'Url', 'PublicUrl', 'Volumes', 'EcShards', 'Max', 'VolumeIds'}, 'unknown-node')
    need(node['EcShards'] == 0 and node['Url'] == node['PublicUrl'] == '127.0.0.1:8080', 'ec-or-remote')
    need(len(t['Layouts']) == 1, 'unsupported-layouts')
    layout = t['Layouts'][0]
    need(set(layout) == {'replication', 'ttl', 'writables', 'collection', 'diskType'}, 'unknown-layout')
    need({k: layout[k] for k in ('replication', 'ttl', 'collection', 'diskType')} ==
         {'replication': '000', 'ttl': '', 'collection': 'fixture', 'diskType': 'hdd'}, 'unsupported-layout')
    ids = set()
    for token in node['VolumeIds'].split():
        need(re.fullmatch(r'\d+(?:-\d+)?', token), 'unknown-volume-range')
        ends = list(map(int, token.split('-')))
        need(len(ends) == 1 or ends[0] <= ends[1] <= 32, 'volume-range-bound')
        ids.update(range(ends[0], ends[-1] + 1))
    need(ids and len(ids) <= 8 and node['Volumes'] == len(ids) and set(layout['writables']) == ids,
         'topology-inventory-mismatch')
    found = set(map(int, re.findall(r'volume Id:(\d+),', listing)))
    need(found == ids and len(re.findall(r'volume Id:', listing)) == len(ids), 'listing-inventory-mismatch')
    need('remote:0' in listing and 'ec shard' not in listing.lower(), 'unsupported-listing')
    for line in listing.splitlines():
        if 'volume Id:' in line:
            need('ReplicaPlacement:000, Collection:fixture, Version:3, Ttl:,' in line and
                 'DeleteCount:0, DeletedByteCount:0, ReadOnly:false' in line, 'unsupported-volume')
    return sorted(ids)


class Sandbox:
    def __init__(self, run, label, root, *, application_s3=False):
        self.run, self.label, self.root = run, label, root
        self.directory = run / label
        self.directory.mkdir(mode=0o700)
        self.log = (run / (label + '-sandbox.log')).open('xb')
        self.p = None
        self.application_s3 = application_s3

    def start(self):
        config = self.directory / 'filer.toml'
        save(config, '[leveldb2]\nenabled = true\ndir = "/data/' + self.label + '/filerldb2"\n')
        script = self.run / (self.label + '-start.sh')
        extra = ' -s3 -s3.port=8333 -s3.config=/data/generated-s3.json' if self.application_s3 else ''
        save(script, '#!/bin/sh\nset -eu\numask 077\ncd /data/' + self.label + '\nexec /usr/bin/weed server -dir=. -master -volume -filer -ip=127.0.0.1 -ip.bind=127.0.0.1 -master.port=9333 -master.volumeSizeLimitMB=16 -volume.port=8080 -volume.max=' + ('16' if self.application_s3 else '8') + ' -filer.port=8888' + extra + '\n')
        r, w = os.pipe()
        cmd = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
               '--uid', '10000', '--gid', '10000', '--ro-bind', str(self.root), '/', '--proc', '/proc',
               '--dev', '/dev', '--tmpfs', '/tmp', '--bind', str(self.run), '/data', '--chdir', '/data',
               '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
               '--info-fd', str(w), '/bin/sh', '/data/' + script.name]
        try:
            self.p = subprocess.Popen(cmd, pass_fds=(w,), stdout=self.log, stderr=subprocess.STDOUT)
        finally:
            os.close(w)
        with os.fdopen(r) as f:
            info = json.load(f)
        self.pid = info['child-pid']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            need(self.p.poll() is None, 'sandbox-start-failed')
            try:
                target = Path('/proc') / str(self.pid)
                need(target.stat().st_uid == os.getuid(), 'sandbox-owner')
                a, b = (target / 'root').stat(), self.root.stat()
                if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino):
                    break
            except FileNotFoundError:
                pass
            time.sleep(.05)
        else:
            raise Refusal('sandbox-root-timeout')
        self.prefix = ['nsenter', '--target', str(self.pid), '--user', '--mount', '--net', '--pid',
                       '--root', '--wdns=/', '--preserve-credentials', '/usr/bin/env', '-i',
                       'HOME=/tmp', 'PATH=/usr/bin:/bin']
        self.wait(lambda: self.http('http://127.0.0.1:8888/'), 45)
        return self

    def command(self, args, data=None, timeout=15):
        p = subprocess.run(self.prefix + args, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
        return p

    def http(self, url):
        need(re.fullmatch(r'http://127\.0\.0\.1:(8888|8080|9333)/[^\s]*', url), 'nonlocal-url')
        p = self.command(['/usr/bin/wget', '-q', '-T', '2', '-O', '-', url], timeout=4)
        need(p.returncode == 0, 'http-readback')
        return p.stdout

    def shell(self, text):
        p = self.command(['/usr/bin/weed', 'shell', '-master=127.0.0.1:9333', '-filer=127.0.0.1:8888'], text.encode())
        need(p.returncode == 0 and b'error:' not in p.stdout + p.stderr, 'shell-error')
        return p.stdout + p.stderr

    def wait(self, fn, timeout):
        assert self.p is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            need(self.p.poll() is None, 'server-exited')
            try:
                return fn()
            except (Refusal, subprocess.TimeoutExpired):
                time.sleep(.1)  # backoff only; success requires authoritative reconciliation
        raise Refusal('reconciliation-timeout')

    def export_meta(self, label):
        path = self.run / (label + '.meta.gz')
        need(not path.exists(), 'no-overwrite')
        log = self.shell('fs.meta.save -o /data/' + path.name + ' /\n')
        save(self.run / (label + '.log'), log)
        need(b'is saved to' in log and path.is_file(), 'metadata-export-failed')
        need(path.stat().st_mode & 0o777 == 0o600, 'metadata-not-private')
        return records(path.read_bytes(), application_state=self.application_s3)

    def stop(self):
        if self.p is not None and self.p.poll() is None:
            # Signal the namespace's actual weed process, not bwrap's supervisor.
            p = self.command(['/bin/sh', '-c', 'id; ps; kill -TERM $(pidof weed)'])
            save(self.run / (self.label + '-stop.log'), p.stdout + p.stderr)
            need(p.returncode == 0, 'server-signal-failed')
            try:
                self.p.wait(timeout=45)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(timeout=5)
                raise Refusal('server-stop-timeout')
        self.log.close()


def metadata_json(sandbox, path):
    raw = sandbox.shell('fs.meta.cat ' + path + '\n')
    obj, _ = json.JSONDecoder().raw_decode(raw.decode())
    need(set(obj) == {'name', 'isDirectory', 'chunks', 'attributes', 'extended', 'hardLinkId',
                     'hardLinkCounter', 'content', 'remoteEntry', 'quota', 'wormEnforcedAtTsNs'}, 'unknown-object')
    need(not any(obj[k] for k in ('extended', 'hardLinkId', 'hardLinkCounter', 'content', 'remoteEntry')) and
         obj['quota'] == obj['wormEnforcedAtTsNs'] == '0', 'unsupported-object')
    return obj


def reconcile_bytes(sandbox, expected_metadata, ids):
    evidence = {}
    for path, content in OBJECTS.items():
        need(sandbox.http('http://127.0.0.1:8888' + path) == content, 'object-content')
        meta = metadata_json(sandbox, path)
        need(meta == expected_metadata[path], 'object-metadata')
        offset, chunks = 0, []
        for chunk in meta['chunks']:
            need(set(chunk) == {'fileId', 'offset', 'size', 'modifiedTsNs', 'eTag', 'sourceFileId', 'fid',
                               'sourceFid', 'cipherKey', 'isCompressed', 'isChunkManifest', 'sseType', 'sseMetadata'}, 'unknown-chunk')
            need(not any(chunk[k] for k in ('sourceFileId', 'sourceFid', 'cipherKey', 'isChunkManifest', 'sseMetadata'))
                 and chunk['sseType'] == 'NONE', 'unsupported-chunk')
            fid = chunk['fileId']
            need(re.fullmatch(r'\d+,[0-9a-f]+', fid) and int(fid.split(',')[0]) in ids and
                 chunk['fid']['volumeId'] == int(fid.split(',')[0]), 'chunk-volume')
            size = int(chunk['size'])
            need(int(chunk['offset']) == offset and size > 0, 'chunk-gap-or-overlap')
            body = sandbox.http('http://127.0.0.1:8080/' + fid)
            need(body == content[offset:offset + size], 'chunk-content')
            chunks.append({'fid': fid, 'offset': offset, 'bytes': size, 'sha256': sha(body)})
            offset += size
        need(offset == len(content) and len(chunks) == (4 if path.endswith('large.bin') else 1), 'chunk-inventory')
        evidence[path] = {'bytes': len(content), 'sha256': sha(content), 'chunks': chunks}
    return evidence


def load_reconciled(sandbox, archive, expected, metadata, ids, timeout=12):
    """Keep SAME native loader alive until external inventory/content proof.

    Never treat native rc0 or its 'loaded' count as success. Each attempt exports
    to a fresh path. On deadline/error terminate loader with stdin still open;
    only a reconciled loader is permitted graceful EOF. Expected is retained
    independently of the input archive (essential for final-record-loss tests).
    """
    logpath = sandbox.run / (sandbox.label + '-loader.log')
    with logpath.open('xb') as log:
        p = subprocess.Popen(sandbox.prefix + ['/usr/bin/weed', 'shell', '-master=127.0.0.1:9333',
                              '-filer=127.0.0.1:8888'], stdin=subprocess.PIPE,
                             stdout=log, stderr=subprocess.STDOUT)
        assert p.stdin is not None
        count = 0
        try:
            p.stdin.write(('fs.meta.load -v=false /data/' + archive.name + '\n').encode())
            p.stdin.flush()
            def check():
                nonlocal count
                need(p.poll() is None, 'loader-exited-before-reconciliation')
                count += 1
                check_expected(sandbox.export_meta(sandbox.label + '-readback-' + str(count)), expected)
                result = reconcile_bytes(sandbox, metadata, ids)
                need(p.poll() is None, 'loader-exited-before-reconciliation')
                return result
            result = sandbox.wait(check, timeout)
            # Validate the entire input too; partial valid prefixes cannot pass.
            check_expected(records(archive.read_bytes(), application_state=sandbox.application_s3), expected)
            p.stdin.close()
            need(p.wait(timeout=5) == 0, 'loader-exit')
            need(b'error:' not in logpath.read_bytes(), 'loader-native-error')
            return {'attempts': count, 'stdin_held_until_full_readback': True, 'objects': result}
        finally:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
            if not p.stdin.closed:
                p.stdin.close()


def verify_export(directory, ids, receipts):
    expected = {f'fixture_{i}.{suffix}' for i in ids for suffix in ('dat', 'idx', 'vif')}
    need({p.name for p in directory.iterdir()} == expected, 'volume-file-inventory')
    result = {}
    for i in ids:
        need(i in receipts and receipts[i]['rc'] == 0 and
             f'Successfully backed up volume {i} '.encode() in receipts[i]['output'] and
             b'Failed' not in receipts[i]['output'], 'volume-export-status')
        for suffix in ('dat', 'idx', 'vif'):
            p = directory / f'fixture_{i}.{suffix}'
            need(p.is_file() and not p.is_symlink() and p.stat().st_mode & 0o077 == 0, 'volume-file-mode')
            body = p.read_bytes()
            need(suffix == 'idx' or body, 'volume-empty')
            if suffix == 'idx':
                need(len(body) % 16 == 0, 'volume-index-partial')
            if suffix == 'vif':
                vif = json.loads(body)
                need(vif == {'files': [], 'version': 3, 'replication': '', 'bytesOffset': 4,
                             'datFileSize': '0', 'expireAtSec': '0', 'readOnly': False,
                             'ecShardConfig': None}, 'unsupported-volume-info')
            result[p.name] = {'bytes': len(body), 'sha256': sha(body)}
    return result


def verify_needles(directory, ids, metadata):
    """Independent .idx/.dat v3 scan: every indexed needle is an expected chunk.

    Reject deletes, duplicate IDs, unexplained/overlapping records and trailing
    bytes. Compare decoded native stored data, not only a filer's assembled GET.
    Native readback additionally verifies the supported server's checksums.
    """
    expected = {}
    for path, meta in metadata.items():
        for chunk in meta['chunks']:
            fid = chunk['fileId']
            vid, keycookie = fid.split(',')
            key, cookie = int(keycookie[:-8], 16), int(keycookie[-8:], 16)
            offset, size = int(chunk['offset']), int(chunk['size'])
            expected[(int(vid), key)] = (cookie, OBJECTS[path][offset:offset + size])
    found = {}
    for vid in ids:
        dat = (directory / f'fixture_{vid}.dat').read_bytes()
        idx = (directory / f'fixture_{vid}.idx').read_bytes()
        need(len(dat) >= 8 and dat[0] == 3 and len(idx) % 16 == 0, 'unsupported-native-volume')
        end = 8
        for pos in range(0, len(idx), 16):
            key, offset, size = struct.unpack('>QII', idx[pos:pos + 16])
            offset *= 8
            need(offset == end and size < 10485760 and (vid, key) in expected and
                 (vid, key) not in found, 'native-needle-inventory')
            cookie, native_key, native_size = struct.unpack('>IQI', dat[offset:offset + 16])
            need((native_key, native_size) == (key, size), 'native-needle-header')
            body = dat[offset + 16:offset + 16 + size]
            need(len(body) == size and size >= 5, 'native-needle-truncated')
            data_size = struct.unpack('>I', body[:4])[0]
            need(4 + data_size < size, 'native-needle-data-length')
            payload = body[4:4 + data_size]
            flags = body[4 + data_size]
            if flags & 1:  # native FlagIsCompressed
                payload = gzip.decompress(payload)
            need((cookie, payload) == expected[(vid, key)], 'native-needle-content')
            found[(vid, key)] = sha(payload)
            # v3 tail: checksum(4), append timestamp(8), then 8-byte alignment.
            end = ((offset + 16 + size + 4 + 8 + 7) // 8) * 8
        need(end == len(dat), 'native-volume-trailing-or-unindexed-data')
    need(set(found) == set(expected), 'native-chunk-inventory')
    return {f'{vid},{key}': digest for (vid, key), digest in sorted(found.items())}


def execute(run, root):
    source = Sandbox(run, 'source', root)
    receipts, negative = {}, {}
    try:
        source.start()
        save(run / 'version.txt', source.command(['/usr/bin/weed', 'version']).stdout)
        need(b'4.23 73fc9e383 linux amd64' in (run / 'version.txt').read_bytes(), 'native-version')
        # Verify private networking and immutable image using native commands.
        p = source.command(['/bin/sh', '-c', 'touch /usr/bin/fixture-must-not-exist'])
        need(p.returncode != 0, 'image-writable')
        for host in ('1.1.1.1', '192.168.0.11', '192.168.0.40'):
            p = source.command(['/usr/bin/wget', '-T', '1', '-q', '-O', '/dev/null', 'http://' + host])
            need(p.returncode != 0, 'network-escape')
        for path, body in OBJECTS.items():
            name = path.rsplit('/', 1)[1]
            request = (b'--fixture-boundary\r\nContent-Disposition: form-data; name="file"; filename="' +
                       name.encode() + b'"\r\nContent-Type: application/octet-stream\r\n\r\n' + body + b'\r\n--fixture-boundary--\r\n')
            save(run / (name + '.multipart'), request)
            p = source.command(['/usr/bin/wget', '-q', '-T', '20', '--header=Content-Type: multipart/form-data; boundary=fixture-boundary',
                                '--post-file=/data/' + name + '.multipart', '-O', '-', 'http://127.0.0.1:8888' + path + '?maxMB=1'], timeout=30)
            need(p.returncode == 0, 'seed-upload')
        metadata = {p: metadata_json(source, p) for p in OBJECTS}
        expected = source.export_meta('source-before')
        need(set(expected) == {'/', '/buckets', '/buckets/fixture', '/buckets/fixture/fixture.txt', '/buckets/fixture/large.bin'}, 'generated-entry-inventory')
        listing = source.shell('volume.list\n').decode()
        topo = json.loads(source.http('http://127.0.0.1:9333/dir/status'))
        save(run / 'volume-list.txt', listing)
        jsave(run / 'topology.json', topo)
        ids = volume_inventory(topo, listing)
        original = reconcile_bytes(source, metadata, ids)
        jsave(run / 'expected-objects.json', {'metadata': metadata, 'readback': original})
        export = run / 'export'
        export.mkdir(mode=0o700)
        for i in ids:
            p = source.command(['/usr/bin/weed', 'backup', '-master=127.0.0.1:9333', '-collection=fixture',
                                '-dir=/data/export', '-volumeId=' + str(i)], timeout=30)
            receipts[i] = {'rc': p.returncode, 'output': p.stdout + p.stderr}
            save(run / f'backup-{i}.log', receipts[i]['output'])
        inventory = verify_export(export, ids, receipts)
        needles = verify_needles(export, ids, metadata)
        check_expected(source.export_meta('source-after'), expected)
        need(volume_inventory(json.loads(source.http('http://127.0.0.1:9333/dir/status')),
                              source.shell('volume.list\n').decode()) == ids, 'source-topology-changed')
        need(reconcile_bytes(source, metadata, ids) == original, 'source-content-changed')
        # Native false-success error and independently rejected output, not mocked rc.
        p = source.command(['/usr/bin/weed', 'backup', '-master=127.0.0.1:9333', '-collection=fixture',
                            '-dir=/data/no-such-parent/out', '-volumeId=' + str(ids[0])])
        save(run / 'failed-export.log', p.stdout + p.stderr)
        need(b'Failed to backup volume' in p.stdout + p.stderr, 'failed-export-not-exercised')
        empty = run / 'failed-export-empty'
        empty.mkdir(mode=0o700)
        try:
            verify_export(empty, ids, {ids[0]: {'rc': p.returncode, 'output': p.stdout + p.stderr}})
        except Refusal as e:
            negative['failed-export'] = {'native_rc': p.returncode, 'accepted': False, 'reason': str(e)}
        else:
            raise Refusal('failed-export-accepted')
    finally:
        source.stop()
    # The filer may generate internal log volume(s) during shutdown AFTER the
    # accepted export point. They are not app-object chunks; retain and inventory
    # them explicitly, never silently present this fixture as whole-service backup.
    post_stop = {}
    for p in source.directory.iterdir():
        if p.suffix in ('.dat', '.idx', '.vif'):
            post_stop[p.name] = {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
    for name, proof in inventory.items():
        if name.endswith(('.dat', '.idx')):
            need(post_stop[name] == proof, 'source-volume-drift')
    extras = set(post_stop) - set(inventory)
    need(not extras or (ids == list(range(1, 8)) and extras == {'8.dat', '8.idx', '8.vif'}),
         'unsupported-post-capture-volume-state')
    if extras:
        need((source.directory / '8.dat').read_bytes()[0] == 3 and
             (source.directory / '8.idx').stat().st_size % 16 == 0 and
             json.loads((source.directory / '8.vif').read_bytes()) ==
             {'files': [], 'version': 3, 'replication': '', 'bytesOffset': 4,
              'datFileSize': '0', 'expireAtSec': '0', 'readOnly': False,
              'ecShardConfig': None}, 'unsupported-post-capture-log-volume')
    # Validate copies independently without altering the successful export.
    def rejected(fn, label):
        try:
            fn()
        except (Refusal, OSError, ValueError) as e:
            negative[label] = {'accepted': False, 'reason': str(e) if isinstance(e, Refusal) else type(e).__name__}
        else:
            raise Refusal('negative-accepted-' + label)
    partial = run / 'partial-export'
    partial.mkdir(mode=0o700)
    for name in inventory:
        save(partial / name, (export / name).read_bytes()[:3] if name.endswith('.idx') and (export / name).stat().st_size else (export / name).read_bytes())
    rejected(lambda: verify_export(partial, ids, receipts), 'partial-export')
    # Valid gzip with final record removed exercises authoritative expected inventory,
    # unlike gzip CRC/trailer checks alone. All variants use native load in fresh stores.
    raw = gzip.decompress((run / 'source-before.meta.gz').read_bytes())
    pos, last = 0, 0
    while pos < len(raw):
        last = pos
        pos += 4 + struct.unpack('>I', raw[pos:pos + 4])[0]
    variants = {'positive': (run / 'source-before.meta.gz').read_bytes(),
                'truncated-metadata': (run / 'source-before.meta.gz').read_bytes()[:-8],
                'corrupt-metadata': b'not-a-gzip-stream',
                'final-entry-loss': gzip.compress(raw[:last]),
                'missing-volume': (run / 'source-before.meta.gz').read_bytes()}
    restore_results = {}
    for label, blob in variants.items():
        archive = run / (label + '.meta.gz')
        save(archive, blob)
        target = Sandbox(run, 'restore-' + label, root)
        for name in inventory:
            if label == 'missing-volume' and name.startswith('fixture_' + str(original['/buckets/fixture/fixture.txt']['chunks'][0]['fid'].split(',')[0]) + '.'):
                continue
            save(target.directory / name, (export / name).read_bytes())
        try:
            target.start()
            fn = lambda: load_reconciled(target, archive, expected, metadata, ids, timeout=4 if label != 'positive' else 15)
            if label == 'positive':
                restore_results[label] = fn()
            else:
                rejected(fn, label)
        finally:
            target.stop()
    # A second cold restart proves persistence after loader EOF, not source reseeding.
    cold = Sandbox(run, 'cold-verify', root)
    for p in (run / 'restore-positive').iterdir():
        if p.name == 'filerldb2' or p.name in inventory:
            if p.is_dir():
                shutil.copytree(p, cold.directory / p.name)
            else:
                save(cold.directory / p.name, p.read_bytes())
    try:
        cold.start()
        check_expected(cold.export_meta('cold-readback'), expected)
        need(reconcile_bytes(cold, metadata, ids) == original, 'cold-readback')
    finally:
        cold.stop()
    need(set(negative) == {'failed-export', 'partial-export', 'truncated-metadata', 'corrupt-metadata', 'final-entry-loss', 'missing-volume'}, 'negative-coverage')
    return {'volume_ids': ids, 'volume_files': inventory, 'native_needles': needles,
            'source_post_stop_volume_files': post_stop,
            'excluded_post_capture_files': sorted(set(post_stop) - set(inventory)),
            'system_log_recovery_proven': False, 'entries': sorted(expected),
            'restore': restore_results, 'negatives': negative, 'cold_restart': True,
            'production_ready': False, 'scope': 'generated local non-EC replication000 AMD64 only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside-scope', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(not CACHE.is_symlink() and CACHE.stat().st_mode & 0o077 == 0, 'cache-not-private')
    if args.inside_scope is None:
        run = CACHE / ('run-' + str(time.time_ns()))
        run.mkdir(mode=0o700)
        unit = 'langfuse-seaweed-hardened-' + str(os.getpid())
        with (run / 'scope.log').open('xb') as log:
            p = subprocess.run(['systemd-run', '--user', '--quiet', '--wait', '--pipe', '--unit=' + unit,
                                '-p', 'MemoryMax=1G', '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=100%',
                                '-p', 'TasksMax=128', '-p', 'RuntimeMaxSec=300', sys.executable,
                                str(Path(__file__).resolve()), '--inside-scope', str(run)], stdout=log, stderr=subprocess.STDOUT)
        print(json.dumps({'run': str(run.relative_to(REPO)), 'rc': p.returncode}))
        return p.returncode
    run = args.inside_scope.resolve()
    need(run.parent == CACHE and run.is_dir(), 'invalid-run')
    cgroup = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split(':', 2)[2].lstrip('/')
    counters = {k: (cgroup / k).read_text().strip() for k in ('memory.max', 'memory.swap.max', 'cpu.max', 'pids.max', 'memory.events')}
    need(counters['memory.max'] == '1073741824' and counters['memory.swap.max'] == '0' and
         counters['cpu.max'] == '100000 100000' and counters['pids.max'] == '128', 'resource-bounds')
    root = ENGINE / 'image/root'
    meta = json.loads((ENGINE / 'image/metadata.json').read_bytes())
    need(meta['index'] == INDEX and meta['manifest'] == MANIFEST, 'image-pin')
    # Revalidate saved anonymous registry bytes, config, compressed blobs and diffIDs.
    def obj(d):
        b = (ENGINE / 'image' / d.split(':')[1]).read_bytes()
        need('sha256:' + sha(b) == d, 'oci-digest')
        return b
    index = json.loads(obj(INDEX))
    need(any(m['digest'] == MANIFEST and m['platform']['architecture'] == 'amd64' and m['platform']['os'] == 'linux'
             for m in index['manifests']), 'oci-platform')
    manifest = json.loads(obj(MANIFEST))
    config = json.loads(obj(manifest['config']['digest']))
    need(len(manifest['layers']) == len(config['rootfs']['diff_ids']), 'oci-layer-count')
    for layer, diff in zip(manifest['layers'], config['rootfs']['diff_ids']):
        b = obj(layer['digest'])
        need('sha256:' + sha(gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b) == diff, 'oci-diffid')
    before = tree(root)
    code = sha(Path(__file__).read_bytes())
    receipt = {'status': 'incomplete', 'helper_sha256': code, 'index': INDEX, 'manifest': MANIFEST,
               'config': manifest['config']['digest'], 'image_tree_before': before, 'limits': counters}
    rc = 1
    try:
        receipt['results'] = execute(run, root)
        rc = 0
    except Exception as e:
        receipt['failure'] = str(e) if isinstance(e, Refusal) else type(e).__name__
    finally:
        receipt['image_tree_after'] = tree(root)
        receipt['helper_sha256_after'] = sha(Path(__file__).read_bytes())
        receipt['quiescent_scope_pids'] = (cgroup / 'cgroup.procs').read_text().split()
        receipt['memory_events_after'] = (cgroup / 'memory.events').read_text().strip()
        events = dict(line.split() for line in receipt['memory_events_after'].splitlines())
        if (receipt['image_tree_after'] != before or receipt['helper_sha256_after'] != code or
            receipt['quiescent_scope_pids'] != [str(os.getpid())] or int(events['oom']) or int(events['oom_kill'])):
            rc = 1
            receipt['finalization_failure'] = 'identity-or-resource-coverage'
        # Bind every retained artifact to this run/code. No shared receipt overwrite.
        receipt['artifacts'] = {str(p.relative_to(run)): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                                for p in run.rglob('*') if p.is_file() and p.name != 'scope.log'}
        receipt['status'] = 'synthetic-accepted' if rc == 0 else 'incomplete'
        jsave(run / 'receipt.json', receipt)
    return rc


if __name__ == '__main__':
    sys.exit(main())
