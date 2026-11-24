#!/usr/bin/env python3
"""Read-only, metadata-only Langfuse recovery baseline; never authorizes capture.

Uses configured kubectl/SSH authentication. Does not request Secret objects,
logs, Pod environment, database records, keys or application credentials.
A passing baseline is NOT a backup/restore acceptance result.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CLAIMS = {
    'postgres-data-langfuse-postgresql-0': ('dbfbc0a0-97e4-4d3d-b6ae-e4d9c581ea7f', '10Gi'),
    'langfuse-clickhouse-data': ('e82ce5a4-cd40-4353-a02a-d54a3d96203b', '30Gi'),
    'langfuse-redis': ('d8f49983-f38d-4de2-8651-283d16a732b4', '5Gi'),
    'langfuse-s3-data': ('26a2ea71-3030-4d2d-b894-b8f8cf5627f9', '20Gi'),
}
CONTAINERS = {'clickhouse', 'postgresql', 'langfuse-redis', 'seaweedfs', 'langfuse-web', 'langfuse-worker'}
IMAGE_DIGESTS = {
    'clickhouse': 'd426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7',
    'postgresql': '2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc',
    'langfuse-redis': '04b9002ae24bbe66687fb025052ed9bcebb54f8da3937338eb718d98d362887f',
    'seaweedfs': 'c6d6fb84b081f1f09bb089184ff4b45d2f163a1bfa8b354d04cf400c6e06f242',
    'langfuse-web': '2b47d0ae63ae737996a58cc03536a73230c809a2371c230c9bea4b7653a0b6a0',
    'langfuse-worker': '1bc3597ff4c953e98ff9ee474a7d634e97664e4df298fdf20f13ecc834c89438',
}
NAS_PATH = '/storage/k3s/langfuse/recovery/first-20261120'
ENDPOINT = 'https://langfuse.tailbd291c.ts.net/api/public/ready'


class PreflightError(Exception):
    pass


def command(args):
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise PreflightError('command unavailable or timed out') from None
    if result.returncode:
        # Raw stderr can contain environment- or credential-specific diagnostics.
        raise PreflightError('read-only command failed; raw output withheld')
    if len(result.stdout) > 1024 * 1024:
        raise PreflightError('unexpectedly large metadata response')
    return result.stdout.strip()


def table(resource, columns, namespace: str | None = 'langfuse'):
    args = ['kubectl', '--request-timeout=20s']
    if namespace:
        args += ['-n', namespace]
    text = command(args + ['get', resource, '--no-headers', '-o',
                            'custom-columns=' + ','.join(f'{key}:{value}' for key, value in columns)])
    rows = []
    for line in text.splitlines():
        values = line.split()
        if len(values) != len(columns):
            raise PreflightError('malformed metadata table')
        rows.append(dict(zip((key for key, _ in columns), values)))
    return rows


def validate(snapshot):
    issues = []
    pods = snapshot['pods']
    names = [name for pod in pods for name in pod['containers'].split(',')]
    if len(pods) != 6 or len(names) != len(set(names)) or set(names) != CONTAINERS:
        issues.append('unexpected workload/container inventory')
    for pod in pods:
        if (pod['phase'] != 'Running' or pod['ready'] != 'true'
                or pod['deleting'] != '<none>' or pod['restarts'] != '0'
                or pod['initialized'] != 'True' or pod['pod_ready'] != 'True'):
            issues.append('pod not at clean ready baseline: ' + pod['name'])
        digest = IMAGE_DIGESTS.get(pod['containers'])
        if (not digest or not pod['images'].endswith('@sha256:' + digest)
                or not pod['image_ids'].endswith('@sha256:' + digest)):
            # A platform-specific imageID needs explicit index resolution/review,
            # not automatic normalization into an accepted index identity.
            issues.append('image identity differs from captured-version baseline: ' + pod['name'])
    claims = snapshot['claims']
    if {row['name'] for row in claims} != set(CLAIMS) or len(claims) != len(CLAIMS):
        issues.append('unexpected claim inventory')
    for claim in claims:
        expected = CLAIMS.get(claim['name'])
        if not expected:
            continue
        uid, size = expected
        if (claim['uid'] != uid or claim['volume'] != 'pvc-' + uid
                or claim['size'] != size or claim['requested'] != size
                or claim['phase'] != 'Bound' or claim['class'] != 'longhorn'
                or claim['owners'] != '<none>' or claim['deleting'] != '<none>'):
            issues.append('claim identity/size/retention differs: ' + claim['name'])
    volumes = {row['name']: row for row in snapshot['volumes']}
    if len(volumes) != len(CLAIMS) or len(snapshot['volumes']) != len(CLAIMS):
        issues.append('unexpected volume inventory')
    for name, (uid, size) in CLAIMS.items():
        row = volumes.get('pvc-' + uid)
        if not row or any(row[key] != value for key, value in {
                'claim': name, 'namespace': 'langfuse', 'claim_uid': uid,
                'handle': 'pvc-' + uid, 'driver': 'driver.longhorn.io', 'phase': 'Bound',
                'size': size, 'reclaim': 'Delete'}.items()):
            issues.append('bound volume differs: ' + name)
    if snapshot['sync'] != 'Synced' or snapshot['health'] != 'Healthy':
        issues.append('Application is not Synced/Healthy')
    policy = snapshot['sync_policy']
    if 'automated' in policy:
        issues.append('automated sync policy present')
    if snapshot['operation_active']:
        issues.append('Application operation active')
    if snapshot['readiness'] != {'status': 'OK', 'version': '4.77.0'}:
        issues.append('readiness differs from captured-version baseline')
    if snapshot['jobs'] or snapshot['cronjobs']:
        issues.append('Job/CronJob inventory requires review')
    if snapshot['nas']['destination_exists']:
        issues.append('proposed destination already exists; must not overwrite')
    if not snapshot['nas']['mounted']:
        issues.append('NAS dataset is not mounted')
    return issues


def collect():
    snapshot: dict[str, Any] = {'observed_at': datetime.now(timezone.utc).isoformat(),
                'source_revision': command(['git', 'rev-parse', 'HEAD'])}
    snapshot['pods'] = table('pods', [
        ('name', '.metadata.name'), ('uid', '.metadata.uid'), ('node', '.spec.nodeName'),
        ('phase', '.status.phase'), ('containers', '.spec.containers[*].name'),
        ('images', '.spec.containers[*].image'), ('image_ids', '.status.containerStatuses[*].imageID'),
        ('ready', '.status.containerStatuses[*].ready'),
        ('restarts', '.status.containerStatuses[*].restartCount'),
        ('initialized', '.status.conditions[?(@.type=="Initialized")].status'),
        ('pod_ready', '.status.conditions[?(@.type=="Ready")].status'),
        ('deleting', '.metadata.deletionTimestamp')])
    snapshot['claims'] = table('pvc', [
        ('name', '.metadata.name'), ('uid', '.metadata.uid'), ('volume', '.spec.volumeName'),
        ('phase', '.status.phase'), ('size', '.status.capacity.storage'),
        ('requested', '.spec.resources.requests.storage'), ('class', '.spec.storageClassName'),
        ('owners', '.metadata.ownerReferences[*].uid'), ('deleting', '.metadata.deletionTimestamp')])
    all_volumes = table('pv', [
        ('name', '.metadata.name'), ('claim', '.spec.claimRef.name'),
        ('namespace', '.spec.claimRef.namespace'), ('claim_uid', '.spec.claimRef.uid'),
        ('phase', '.status.phase'), ('size', '.spec.capacity.storage'),
        ('reclaim', '.spec.persistentVolumeReclaimPolicy'), ('driver', '.spec.csi.driver'),
        ('handle', '.spec.csi.volumeHandle')], namespace=None)
    snapshot['volumes'] = [row for row in all_volumes if row['namespace'] == 'langfuse']
    snapshot['jobs'] = table('jobs', [('name', '.metadata.name')])
    snapshot['cronjobs'] = table('cronjobs', [('name', '.metadata.name')])
    app = ['kubectl', '--request-timeout=20s', '-n', 'argocd', 'get', 'application', 'langfuse', '-o']
    for field, expression in [('sync', '.status.sync.status'), ('health', '.status.health.status')]:
        snapshot[field] = command(app + ['jsonpath={' + expression + '}'])
    snapshot['sync_policy'] = json.loads(command(app + ['jsonpath={.spec.syncPolicy}']) or '{}')
    snapshot['operation_active'] = bool(command(app + ['jsonpath={.operation}']))
    # Fixed HTTPS host, normal certificate validation, and no credential retrieval.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(ENDPOINT, timeout=20) as response:
            snapshot['readiness'] = json.loads(response.read(4096))
    except Exception:
        raise PreflightError('fixed HTTPS readiness check failed; raw error withheld') from None
    # No sudo, provisioning, file content reads, export changes or key discovery.
    script = ('set -eu; id -u; id -g; stat -c "%u:%g:%a" /storage/k3s; '
              f'if test -e {NAS_PATH} || test -L {NAS_PATH}; then printf "exists\\n"; '
              'else printf "absent\\n"; fi; '
              'zfs get -Hp -o value available,mounted storage/k3s')
    lines = command(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                     '-o', 'ConnectTimeout=10', 'nas', script]).splitlines()
    if len(lines) != 6 or lines[3] not in {'exists', 'absent'}:
        raise PreflightError('unexpected NAS metadata response')
    snapshot['nas'] = {'writer_uid': int(lines[0]), 'writer_gid': int(lines[1]),
                       'dataset_owner_group_mode': lines[2],
                       'destination_exists': lines[3] == 'exists',
                       'available_bytes': int(lines[4]), 'mounted': lines[5] == 'yes'}
    snapshot['issues'] = validate(snapshot)
    snapshot['baseline_passed'] = not snapshot['issues']
    snapshot['recovery_accepted'] = False
    snapshot['limitations'] = [
        'Read-only baseline only, not authorization to pause or capture.',
        'No encryption recipient/custody, native recovery or original-identity proof.',
        'No writer exclusion, queue/migration, placement/capacity reservation or restore proof.',
        'Expected claims/sizes are the first-recovery plan; drift requires review, not correction.',
    ]
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='New JSON receipt under this worktree verification/cache; never overwritten')
    args = parser.parse_args()
    cache = (ROOT / 'verification/cache').resolve()
    output = args.output.absolute()
    try:
        output.parent.resolve(strict=True).relative_to(cache)
        if output.is_symlink():
            raise ValueError
    except (OSError, ValueError):
        parser.error('output parent must already exist under this worktree verification/cache')
    try:
        snapshot = collect()
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(snapshot, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    except (PreflightError, OSError, ValueError, KeyError):
        print('Preflight failed; no acceptance claimed. Raw diagnostics withheld.', file=sys.stderr)
        return 1
    print(json.dumps({'baseline_passed': snapshot['baseline_passed'],
                      'recovery_accepted': False, 'issues': snapshot['issues'], 'receipt': str(output)}))
    return 0 if snapshot['baseline_passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
