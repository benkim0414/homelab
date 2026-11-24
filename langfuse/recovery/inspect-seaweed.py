#!/usr/bin/env python3
"""Bounded read-only SeaweedFS 4.23 topology admission; never a capture tool.

Source basis (immutable image OCI revision 73fc9e3833cfff2c259e0239ed6c0444e1c1890a):
weed/server/{master_server.go,master_server_handlers_admin.go,volume_server.go,
volume_server_handlers_admin.go}; weed/topology/{topology_info.go,data_node.go,
data_center.go,rack.go,volume_layout.go}; weed/storage/{volume_info.go,store.go},
super_block/replica_placement.go and needle/volume_ttl.go, in seaweedfs/seaweedfs.
GET master /dir/status calls ToInfo (including explicit EcShards per node);
GET master /vol/status calls ToVolumeMap (all normal volumes, no EC);
GET volume /status calls Store.VolumeInfos (normal volumes + remote flags).
ReplicaPlacement's zero fields are explicitly json omitempty; {} means 000
ONLY for this pinned struct. All other missing admission fields fail closed.
No filer/object/IAM enumeration, filesystem access, backup or writer exclusion.
Two samples test stable topology/policy, NOT atomicity or writer quiescence.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
import selectors
import subprocess
import time
import uuid

REVISION = '73fc9e3833cfff2c259e0239ed6c0444e1c1890a'
IMAGE = 'chrislusf/seaweedfs:4.23@sha256:c6d6fb84b081f1f09bb089184ff4b45d2f163a1bfa8b354d04cf400c6e06f242'
ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / 'verification/cache/langfuse-recovery/production-inventory'
MAX_BYTES = 2 * 1024 * 1024

class Rejected(Exception):
    """Only static allowlisted codes may cross the privacy boundary."""


def require(ok, code='schema_unknown'):
    if not ok:
        raise Rejected(code)


def shape(value: Any, fields) -> Any:
    require(type(value) is dict and set(value) == set(fields))
    return value


def integer(value):
    require(type(value) is int and 0 <= value <= 2**64 - 1)
    return value


def string(value):
    require(type(value) is str and len(value) <= 1024)
    return value


def array(value, nullable=False):
    if nullable and value is None:
        return []  # pinned Go nil slice, only at explicitly reviewed slice sites
    require(type(value) is list and len(value) <= 1024)
    return value


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'malformed_json')
            result[key] = value
        return result
    try:
        require(len(raw) <= MAX_BYTES, 'output_bound')
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, 'malformed_json'))
    except (ValueError, UnicodeError, RecursionError):
        raise Rejected('malformed_json') from None


def version(v):
    # util/version.Version() is VERSION + space + COMMIT; unlike the CLI
    # version command it does not append runtime OS/architecture.
    require(v == '30GB 4.23 73fc9e383', 'version_mismatch')


def volume(v):
    shape(v, 'Id Size ReplicaPlacement Ttl DiskType DiskId Collection Version FileCount DeleteCount DeletedByteCount ReadOnly CompactRevision ModifiedAtSecond RemoteStorageName RemoteStorageKey'.split())
    for key in 'Id Size DiskId Version FileCount DeleteCount DeletedByteCount CompactRevision ModifiedAtSecond'.split():
        integer(v[key])
    require(v['Id'] > 0 and v['Version'] == 3, 'volume_version_unsupported')
    require(type(v['ReadOnly']) is bool)
    require(not v['ReadOnly'], 'readonly_unsupported')
    require(v['DeleteCount'] == 0 and v['DeletedByteCount'] == 0, 'deletes_unsupported')
    require(v['CompactRevision'] == 0, 'compaction_unsupported')
    rp = v['ReplicaPlacement']
    require(type(rp) is dict and set(rp) <= {'node', 'rack', 'dc'})
    for count in rp.values():
        require(integer(count) == 0, 'replication_unsupported')
    shape(v['Ttl'], ['Count', 'Unit'])
    require(integer(v['Ttl']['Count']) == 0 and integer(v['Ttl']['Unit']) == 0, 'ttl_unsupported')
    require(string(v['RemoteStorageName']) == '' and string(v['RemoteStorageKey']) == '', 'remote_unsupported')
    require(string(v['DiskType']) == '', 'disk_unsupported')
    # Narrow declared bucket and default collection only. Default is not proof
    # that these are solely internal logs; no object-level claim is made.
    require(string(v['Collection']) in ('langfuse', ''), 'collection_unsupported')
    return {k: v[k] for k in ('Id', 'Collection', 'Version', 'DiskType', 'DiskId', 'ReadOnly', 'CompactRevision')}


def inspect(d: Any, m: Any, local: Any, pod_ip):
    shape(d, ['Version', 'TopologyId', 'Topology']); version(d['Version']); string(d['TopologyId'])
    shape(m, ['Version', 'Volumes']); version(m['Version'])
    shape(local, ['Version', 'DiskStatuses', 'Volumes']); version(local['Version'])
    require(len(array(local['DiskStatuses'])) == 1, 'disk_unsupported')
    t = shape(d['Topology'], ['Max', 'Free', 'DataCenters', 'Layouts'])
    require(integer(t['Max']) == 16 and integer(t['Free']) <= 16, 'capacity_mismatch')
    dcs = array(t['DataCenters']); require(len(dcs) == 1, 'topology_unsupported')
    dc = shape(dcs[0], ['Id', 'Racks']); string(dc['Id'])
    racks = array(dc['Racks']); require(len(racks) == 1, 'topology_unsupported')
    rack = shape(racks[0], ['Id', 'DataNodes']); string(rack['Id'])
    nodes = array(rack['DataNodes']); require(len(nodes) == 1, 'topology_unsupported')
    node = shape(nodes[0], ['Url', 'PublicUrl', 'Volumes', 'EcShards', 'Max', 'VolumeIds'])
    require(node['Url'] == pod_ip + ':8080' and node['PublicUrl'] == node['Url'], 'node_identity_mismatch')
    require(integer(node['EcShards']) == 0, 'ec_unsupported')
    require(integer(node['Max']) == 16, 'capacity_mismatch')
    vm = shape(m['Volumes'], ['Max', 'Free', 'DataCenters'])
    require(vm['Max'] == t['Max'] and vm['Free'] == t['Free'], 'topology_contradiction')
    require(type(vm['DataCenters']) is dict and set(vm['DataCenters']) == {dc['Id']}, 'topology_contradiction')
    mr = vm['DataCenters'][dc['Id']]
    require(type(mr) is dict and set(mr) == {rack['Id']}, 'topology_contradiction')
    mn = mr[rack['Id']]
    require(type(mn) is dict and set(mn) == {node['Url']}, 'topology_contradiction')
    master = {}; actual = {}
    for target, values in ((master, mn[node['Url']]), (actual, local['Volumes'])):
        for v in array(values, nullable=True):
            policy = volume(v); vid = policy['Id']
            require(vid not in target, 'duplicate_volume'); target[vid] = policy
    require(master == actual and len(master) == integer(node['Volumes']), 'volume_contradiction')
    # disk.GetVolumeIds -> util.HumanReadableIntsMax(100); max16 means no
    # truncation is supported. Bounded expansion rejects ellipsis/overlaps.
    ids = set()
    for token in string(node['VolumeIds']).split():
        require(re.fullmatch(r'[1-9][0-9]*(?:-[1-9][0-9]*)?', token) is not None, 'volume_range_unknown')
        ends = [int(x) for x in token.split('-')]
        start, end = ends[0], ends[-1]
        require(start <= end <= 2**32 - 1 and end - start < 16, 'volume_range_unknown')
        for vid in range(start, end + 1):
            require(vid not in ids, 'duplicate_volume'); ids.add(vid)
        require(len(ids) <= 16, 'volume_range_unknown')
    require(ids == set(master), 'volume_contradiction')
    require(t['Free'] == 16 - len(master), 'capacity_mismatch')
    layouts = set()
    for l in array(t['Layouts'], nullable=True):
        shape(l, ['replication', 'ttl', 'writables', 'collection', 'diskType'])
        require(l['replication'] == '000', 'replication_unsupported')
        require(l['ttl'] == '', 'ttl_unsupported')
        require(l['diskType'] == 'hdd', 'disk_unsupported')
        require(l['collection'] in ('', 'langfuse'), 'collection_unsupported')
        require(l['collection'] not in layouts, 'topology_contradiction'); layouts.add(l['collection'])
        writables = array(l['writables'], nullable=True)
        for vid in writables:
            integer(vid)
            require(vid in master and master[vid]['Collection'] == l['collection'] and not master[vid]['ReadOnly'], 'layout_contradiction')
        require(len(set(writables)) == len(writables), 'duplicate_volume')
        require(set(writables) == {vid for vid, v in master.items() if v['Collection'] == l['collection']}, 'layout_contradiction')
    require(layouts == {v['Collection'] for v in master.values()}, 'layout_contradiction')
    policy_hash = hashlib.sha256(json.dumps(sorted(master.values(), key=lambda v: v['Id']), sort_keys=True).encode()).hexdigest()
    return {'normal_volume_count': len(master), 'collection_count': len(layouts),
            'data_node_count': 1, 'ec_shard_count': 0, 'remote_volume_count': 0,
            'policy_sha256': policy_hash}


def run(argv, timeout=20):
    """Bound both stdout and stderr in memory; never echo arbitrary errors."""
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
        assert p.stdout is not None and p.stderr is not None
        sel = selectors.DefaultSelector()
        for stream in (p.stdout, p.stderr): sel.register(stream, selectors.EVENT_READ)
        out = bytearray(); total = 0; deadline = time.monotonic() + timeout
        try:
            while sel.get_map():
                require(time.monotonic() < deadline, 'command_timeout')
                for key, _ in sel.select(0.1):
                    chunk = os.read(key.fd, 65536)
                    if not chunk: sel.unregister(key.fileobj); continue
                    total += len(chunk); require(total <= MAX_BYTES, 'output_bound')
                    if key.fileobj is p.stdout: out.extend(chunk)
            require(p.wait(timeout=1) == 0, 'native_command_failed')
            return bytes(out)
        finally:
            sel.close()
            if p.poll() is None: p.kill(); p.wait()


def identity():
    # Targeted projection: no spec/env/Secret/auth values are retrieved.
    fields = ['.metadata.name', '.metadata.uid', '.status.podIP', '.spec.containers[0].image',
              '.status.containerStatuses[0].ready', '.status.containerStatuses[0].restartCount']
    expr = '{range .items[*]}' + '{"\\t"}'.join('{' + x + '}' for x in fields) + '{"\\n"}{end}'
    raw = run(['kubectl', '--request-timeout=10s', '-n', 'langfuse', 'get', 'pods', '-l', 'app=langfuse-s3', '-o', 'jsonpath=' + expr])
    lines = raw.decode().splitlines(); require(len(lines) == 1, 'workload_identity_unavailable')
    parts = lines[0].split('\t'); require(len(parts) == 6, 'workload_identity_unavailable')
    name, uid, ip, image, ready, restarts = parts
    require(image == IMAGE and ready == 'true', 'workload_not_admitted')
    require(all(c.isalnum() or c in '.:-' for c in ip) and ip, 'workload_identity_unavailable')
    require(name.startswith('langfuse-s3-') and len(uid) == 36, 'workload_identity_unavailable')
    return {'namespace': 'langfuse', 'pod': name, 'uid': uid, 'image': image,
            'restart_count': int(restarts)}, ip


def fetch(pod, port, path):
    require((port, path) in ((9333, '/dir/status'), (9333, '/vol/status'), (8080, '/status')))
    return decode(run(['kubectl', '--request-timeout=10s', '-n', 'langfuse', 'exec', pod, '-c', 'seaweedfs', '--',
                       '/bin/busybox', 'wget', '-q', '-T', '5', '-O', '-', f'http://127.0.0.1:{port}{path}']))


def save(receipt):
    # Fixed ignored directory; refuse symlinks and insecure pre-existing directory.
    for p in [RECEIPTS, *RECEIPTS.parents]:
        require(not p.is_symlink(), 'receipt_path_unsafe')
    RECEIPTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = RECEIPTS.stat(); require(st.st_uid == os.getuid() and st.st_mode & 0o077 == 0, 'receipt_path_unsafe')
    path = RECEIPTS / ('seaweed-topology-' + uuid.uuid4().hex + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(receipt, f, indent=2); f.write('\n')
    return path


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    receipt = {'schema': 1, 'scope': 'topology_admission_only', 'source_revision': REVISION,
               'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'capture_ready': False, 'object_inventory_verified': False,
               'writer_exclusion_verified': False, 'identity_recovery_verified': False,
               'status': 'rejected'}
    try:
        before, ip = identity(); receipt['workload'] = before
        samples = [inspect(fetch(before['pod'], 9333, '/dir/status'),
                           fetch(before['pod'], 9333, '/vol/status'),
                           fetch(before['pod'], 8080, '/status'), ip) for _ in range(2)]
        after, ip_after = identity()
        require(before == after and ip == ip_after, 'workload_changed')
        require(samples[0] == samples[1], 'topology_changed')
        receipt.update(status='admitted', summary=samples[0], stable_samples=2)
    except Rejected as e:
        receipt['blocker'] = str(e)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        receipt['blocker'] = 'inspection_unavailable_or_malformed'
    path = save(receipt)
    print(json.dumps({'status': receipt['status'], 'receipt': str(path.relative_to(ROOT)),
                      'blocker': receipt.get('blocker')}))
    return 0 if receipt['status'] == 'admitted' else 1

if __name__ == '__main__':
    raise SystemExit(main())
