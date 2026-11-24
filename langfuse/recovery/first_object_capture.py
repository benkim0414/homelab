"""Fixed first-capture ClickHouse/SeaweedFS fragments; import never performs IO.

Source basis: ClickHouse b47359294fe0f498ee19c5e31f18a9155b6dedae and
SeaweedFS 73fc9e3833cfff2c259e0239ed6c0444e1c1890a. See RECOVERY-FIRST.md.
No CLI, retries, cleanup, pod creation, auth extraction or production execution.

The parent owns authorization, continuous writer exclusion, fresh workload/PVC
identity checks before/after EVERY command, deadlines and direct age encryption.
Only producer stdout is a confidential byte stream; stderr must always be
DEVNULL, including kubectl transport errors. Do not log callback results/errors.
A command builder is not evidence that its prerequisites exist on production.

Seaweed application recovery is scoped to one leveldb2 filer with no peer/event
replay consumers. Native fs.meta.save deliberately omits historical metadata
change-log children, not application entries. This does NOT exempt any source
volume or background write from capture/stability validation. Original static
S3 identity/config remain required through the approved six-Secret bundle.
"""
from dataclasses import dataclass
import hashlib
import importlib.util
import io
import re
import shlex
import tarfile
from pathlib import Path
from typing import Any

CH_IMAGE = 'clickhouse/clickhouse-server:26.8.36.3@sha256:d426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7'
SW_IMAGE = 'chrislusf/seaweedfs:4.23@sha256:c6d6fb84b081f1f09bb089184ff4b45d2f163a1bfa8b354d04cf400c6e06f242'
SEAWEED_SCOPE = {'filer_count': 1, 'metadata_store': 'leveldb2',
                 'peer_replay_consumers': 0, 'external_event_sinks': 0,
                 'identity_bundle': 'six-secret-first-20261120',
                 'restore_goal': 'langfuse_application_s3_not_change_log_replay'}


class Refused(ValueError):
    """Only fixed reason codes cross the parent reporting boundary."""


def need(ok, code):
    if not ok:
        raise Refused(code)


def _load(name):
    spec = importlib.util.spec_from_file_location('first_object_' + name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(source, image, container):
    need(source.get('image') == image and source.get('container') == container
         and source.get('ready') == 'true' and source.get('phase') == 'Running'
         and source.get('deleting') == '<none>'
         and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', source.get('uid', '')),
         'source_not_admitted')
    name = source.get('name', '')
    need(name == 'langfuse-clickhouse-0' if container == 'clickhouse'
         else re.fullmatch(r'langfuse-s3-[a-z0-9]+-[a-z0-9]+', name), 'source_name_mismatch')
    return ('kubectl', '--request-timeout=30s', '-n', 'langfuse', 'exec', name,
            '-c', container, '--')


def _token(token, budget):
    need(re.fullmatch(r'[0-9a-f]{32}', token or '') is not None, 'capture_token_invalid')
    need(type(budget) is int and 1048576 <= budget <= 32 * 1024**3, 'space_budget_invalid')


def _shell(script):
    # Both source and transport stderr MUST also be suppressed by the parent.
    return ('/bin/sh', '-ec', 'set +x; exec 2>/dev/null; set -eu; umask 077;\n' + script)


@dataclass(frozen=True)
class Fragment:
    source_uid: str
    source_image: str
    source_directory: str
    stage_argv: tuple
    validate_argv: tuple
    producer_argv: tuple
    container_stage_argv: tuple
    container_validate_argv: tuple
    container_producer_argv: tuple
    blockers: tuple = ()


def _private_path_checks(path):
    # No symlink components, owner-only leaf, current effective service UID.
    parts = Path(path).parts
    script = ''
    for i in range(2, len(parts) + 1):
        parent = str(Path(*parts[:i]))
        script += f'test ! -L {shlex.quote(parent)};\n'
    script += f'test -d {path}; test "$(stat -c %u {path})" = "$(id -u)"; test "$(stat -c %a {path})" = 700;\n'
    return script


def _new_private_directory(path):
    """Normalize inherited setgid ONLY after exclusive creation of our new leaf.

    Never repair an existing source/stage. Ancestors must not be symlinks; mkdir
    without -p remains the exclusive-creation gate even after the absence tests.
    """
    q = shlex.quote
    parts = Path(path).parts
    script = ''.join(f'test ! -L {q(str(Path(*parts[:i])))};\n'
                     for i in range(2, len(parts) + 1))
    script += (f'test ! -e {q(path)}; test ! -L {q(path)};\n'
               f'mkdir -m 700 {q(path)}\n'
               # mkdir mode does not clear setgid inherited from a parent.
               # Five-digit numeric mode also clears setgid with GNU chmod;
               # plain 700 can preserve directory setgid.
               f'chmod 00700 {q(path)}\n')
    return script + _private_path_checks(path)


def _ch_scripts(directory, budget, database='default', data_root='/var/lib/clickhouse', config='/etc/clickhouse-server/config.xml'):
    """Private fixture equivalence seam; public builder never overrides these."""
    need(database in ('default', 'recovery_fixture'), 'database_not_fixed')
    q = shlex.quote
    relative = Path(directory).name + '/native.tar'
    archive = directory + '/native.tar'
    cli = 'clickhouse client --host=127.0.0.1 --port=9000 '
    # Native CLICKHOUSE_USER/PASSWORD are consumed by the pinned client; no secret
    # literals, password flags or environment scraping. Query status is internal.
    stage = f'''test "$(id -u)" = 101
for tool in clickhouse stat df mkdir chmod sha256sum wc tar cat tail awk cut; do command -v "$tool" >/dev/null; done
test "$(clickhouse extract-from-config --config-file={q(config)} --key path)" = {q(data_root + '/')}
test "$(clickhouse extract-from-config --config-file={q(config)} --key backups.allowed_path)" = backups
test "$( {cli}--query 'SELECT version()')" = 26.8.36.3
'''
    backups = data_root + '/backups'
    # Do not create or alter the backup parent silently: existing owner-only
    # allowed-path parent is an explicit source prerequisite.
    stage += _private_path_checks(backups)
    stage += f'''test "$(df -Pk {q(backups)} | tail -n 1 | awk '{{print $4}}')" -ge {(budget + 1023)//1024}
'''
    stage += _new_private_directory(directory)
    stage += f'''status=$({cli}--query {q("BACKUP DATABASE " + database + " TO File('" + relative + "') FORMAT TabSeparated")})
case "$status" in *"$(printf '\\t')BACKUP_CREATED") ;; *) exit 1 ;; esac
chmod 600 {q(archive)}
test -s {q(archive)}; test ! -L {q(archive)}
test "$(stat -c %h {q(archive)})" = 1
test "$(wc -c < {q(archive)})" -le {budget}
tar -tf {q(archive)} >/dev/null
'''
    validate = _private_path_checks(directory) + f'''test ! -L {q(archive)}; test -f {q(archive)}
test "$(stat -c %u {q(archive)})" = "$(id -u)"
test "$(stat -c %a {q(archive)})" = 600; test "$(stat -c %h {q(archive)})" = 1
test "$(wc -c < {q(archive)})" -le {budget}
tar -tf {q(archive)} >/dev/null
wc -c < {q(archive)}
sha256sum {q(archive)} | cut -d ' ' -f 1
'''
    producer = _private_path_checks(directory) + f'''test -f {q(archive)}; test ! -L {q(archive)}
test "$(stat -c %u {q(archive)})" = "$(id -u)"
test "$(stat -c %a {q(archive)})" = 600; test "$(stat -c %h {q(archive)})" = 1
exec cat {q(archive)}
'''
    return tuple(map(_shell, (stage, validate, producer)))


def build_clickhouse(source, capture_id, staging_budget_bytes):
    """Build fixed default-DB native File backup, validation and opaque producer.

    Caller must prove all application tables are in default and config-managed
    user identity is covered by the exact original Secret/config bundle. This is
    NOT an access-entity backup: mutable SQL users/roles require refusal by parent.
    Source /var/lib/clickhouse/backups must already be owner-only (101), nonsymlink.
    Budget is required free space AND a maximum native archive size, not a size
    estimate or reservation. Retain staging on any failure; never reuse token.
    """
    prefix = _source(source, CH_IMAGE, 'clickhouse')
    _token(capture_id, staging_budget_bytes)
    directory = '/var/lib/clickhouse/backups/first-' + capture_id
    stage, validate, producer = _ch_scripts(directory, staging_budget_bytes)
    checks = ['test "${CLICKHOUSE_USER:-}" = langfuse; test -n "${CLICKHOUSE_PASSWORD:-}";']
    # Backing up default must never silently omit a newly added DB or mutable
    # access entity. Config-managed identities instead come from the original
    # six-Secret bundle + pinned source configuration, never a new credential.
    queries = ["SELECT count() FROM system.databases WHERE name NOT IN ('default','system','information_schema','INFORMATION_SCHEMA')",
               "SELECT count() FROM system.users WHERE storage != 'users_xml'",
               "SELECT count() FROM system.roles",
               "SELECT count() FROM system.settings_profiles WHERE storage != 'users_xml'",
               "SELECT count() FROM system.quotas WHERE storage != 'users_xml'"]
    for query in queries:
        checks.append('test "$(clickhouse client --host=127.0.0.1 --port=9000 --query '
                      + shlex.quote(query) + ')" = 0;')
    stage = _shell('\n'.join(checks) + '\n' + stage[2])
    return Fragment(source['uid'], CH_IMAGE, directory, prefix + stage,
                    prefix + validate, prefix + producer, stage, validate, producer)


def parse_archive_receipt(raw):
    """Parse only the source size/digest projection; never expose raw failures."""
    try:
        size, digest = raw.decode('ascii').splitlines()
        need(re.fullmatch(r'[1-9][0-9]*', size) is not None
             and re.fullmatch(r'[0-9a-f]{64}', digest) is not None, 'archive_receipt_invalid')
        return {'bytes': int(size), 'sha256': digest}
    except (ValueError, UnicodeError):
        raise Refused('archive_receipt_invalid') from None


def validate_clickhouse_archive(blob):
    """Full generated/decrypted native tar parse + every regular member hash.

    Confidential member names/metadata stay in the returned private mapping;
    never print it. Feed only a bounded stream to this in-memory validator. Native
    isolated RESTORE remains mandatory: a tar parse is not CH semantic recovery.
    """
    try:
        need(len(blob) >= 1024 and len(blob) % 512 == 0, 'native_tar_invalid')
        files = {}; directories = {}; names = set(); end = 0
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            for member in archive:
                name = member.name
                need(name not in names and not name.startswith('/') and '..' not in name.split('/'), 'native_tar_path')
                names.add(name)
                need(member.isfile() or member.isdir(), 'native_tar_type')
                metadata = {'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                            'uname': member.uname, 'gname': member.gname,
                            'mtime': member.mtime, 'pax_headers': member.pax_headers}
                if member.isdir():
                    directories[name] = metadata
                end = max(end, member.offset_data + ((member.size + 511)//512)*512)
                if member.isfile():
                    stream = archive.extractfile(member)
                    need(stream is not None, 'native_tar_invalid')
                    assert stream is not None
                    body = stream.read()
                    need(len(body) == member.size, 'native_tar_truncated')
                    files[name] = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(), **metadata}
        need('.backup' in files and files['.backup']['bytes'] > 0, 'native_metadata_missing')
        need(len(blob) - end >= 1024 and not any(blob[end:]), 'native_tar_tail')
        return {'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(),
                'members': files, 'directories': directories}
    except Refused:
        raise
    except Exception:
        raise Refused('native_tar_invalid') from None


def admit_seaweed(directory_status, master_status, volume_status, pod_ip) -> dict[str, Any]:
    """Same strict pinned admission as inspect-seaweed; retain FULL local status.

    Unlike topology-only inspection, the returned guard retains Size/FileCount/
    ModifiedAtSecond and ALL policy fields, so background writes cannot disappear
    in a reduced policy digest. Guard values are private, not public receipts.
    """
    inspector = _load('inspect-seaweed')
    try:
        summary = inspector.inspect(directory_status, master_status, volume_status, pod_ip)
        need(summary['normal_volume_count'] > 0, 'seaweed_empty_topology')
        for disk in volume_status['DiskStatuses']:
            need(set(disk) == {'dir','all','used','free','percent_free','percent_used'}
                 and isinstance(disk['dir'],str) and type(disk['all']) is int
                 and disk['all'] > 0, 'seaweed_disk_status_unsupported')
        # Go map iteration makes topology/layout/volume slice order nondeterministic.
        # Compare complete multisets, never reduced policy projections; retain all
        # field values and duplicates (duplicates are rejected by admission above).
        import json
        def canonical(value) -> Any:
            if isinstance(value, dict):
                return {k: canonical(v) for k,v in value.items()}
            if isinstance(value, list):
                return sorted((canonical(v) for v in value), key=lambda v:json.dumps(v,sort_keys=True))
            return value
        return canonical({'directory': directory_status, 'master': master_status, 'local': volume_status})
    except Refused:
        raise
    except Exception:
        raise Refused('seaweed_topology_not_supported') from None


def _seaweed_state(sample):
    # Only host filesystem utilization is telemetry rather than captured service
    # state: our own staging necessarily changes free/used bytes. Keep disk path
    # and total capacity; never omit any native volume counter/policy/hash.
    import copy
    state = copy.deepcopy(sample)
    for disk in state['local']['DiskStatuses']:
        for key in ('used','free','percent_free','percent_used'):
            del disk[key]
    return state


def require_seaweed_stable(before, after, source_files_before, source_files_after,
                           metadata_before, metadata_after):
    """No exceptions for log8/default collection/heartbeat write/unknown volumes.

    Source-files maps must include complete native dat/idx/vif inventories and
    streaming hashes of every source volume, not just metadata mtimes. Parent
    must sample both while the SAME writer fence remains continuously valid.
    """
    need(_seaweed_state(before) == _seaweed_state(after), 'seaweed_source_changed')
    volumes = before['local']['Volumes']
    expected = {((v['Collection'] + '_') if v['Collection'] else '') + str(v['Id']) + '.' + suffix
                for v in volumes for suffix in ('dat', 'idx', 'vif')}
    need(set(source_files_before) == set(source_files_after) == expected, 'seaweed_source_inventory_changed')
    for evidence in (source_files_before, source_files_after):
        for value in evidence.values():
            need(isinstance(value, dict) and set(value) == {'bytes', 'sha256'}
                 and type(value['bytes']) is int and value['bytes'] >= 0
                 and re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is not None,
                 'seaweed_file_evidence_invalid')
    need(source_files_before == source_files_after, 'seaweed_background_write')
    need(metadata_before == metadata_after, 'seaweed_filer_changed')


def seaweed_review_commands(capture_id, staging_budget_bytes, admitted):
    """Individual native commands, also exercised by generated fixtures.

    Retains every topology volume including default-collection/internal logs.
    Native rc0 is NOT success: require exact success marker + exact file inventory,
    parse every gzip frame and volume index, compare source/copied bytes/hashes,
    then isolated native restore. Parent must use build_seaweed for integration.
    """
    _token(capture_id, staging_budget_bytes)
    directory = '/data/first-' + capture_id
    volumes = admitted['local']['Volumes']
    stage = 'test ! -L /data; test -d /data;\n'
    stage += f'''test "$(id -u)" = 10000
test "$(df -Pk /data | tail -n 1 | awk '{{print $4}}')" -ge {(staging_budget_bytes + 1023)//1024}
'''
    stage += _new_private_directory(directory)
    stage += _new_private_directory(directory + '/volumes')
    commands = [_shell(stage)]
    meta = f'fs.meta.save -o {directory}/filer.meta.gz /\n'
    commands.append(_shell('out=$(printf %s ' + shlex.quote(meta) + ' | /usr/bin/weed shell -master=127.0.0.1:9333 -filer=127.0.0.1:8888 2>&1)\n'
                           'case "$out" in *error:*|*failed*|*Failed*) exit 1;; esac\n'
                           'case "$out" in *"is saved to"*) ;; *) exit 1;; esac\n'
                           f'test -s {directory}/filer.meta.gz; test "$(stat -c %a {directory}/filer.meta.gz)" = 600\n'))
    for volume in sorted(volumes, key=lambda v: v['Id']):
        need(volume['Collection'] in ('', 'langfuse'), 'seaweed_collection_not_supported')
        vid = volume['Id']; need(type(vid) is int and vid > 0, 'seaweed_volume_invalid')
        command = ['/usr/bin/weed', 'backup', '-master=127.0.0.1:9333',
                   '-collection=' + volume['Collection'], '-dir=' + directory + '/volumes', '-volumeId=' + str(vid)]
        commands.append(_shell('out=$(' + shlex.join(command) + ' 2>&1)\n'
                               'case "$out" in *Failed*|*failed*|*error:*) exit 1;; esac\n'
                               f'case "$out" in *"Successfully backed up volume {vid} "*) ;; *) exit 1;; esac\n'))
    return {'directory': directory, 'container_commands': tuple(commands)}


def build_seaweed(source, capture_id, staging_budget_bytes, *, admitted, scope):
    """Fixed complete application-metadata/all-volume native export.

    scope must be the exact SEAWEED_SCOPE mapping, verified by the parent against
    source workloads/config and identity custody; it is not inferred from volume
    topology. It excludes peer/event replay, NOT app settings, IAM or any volume.
    A fresh topology admission + source UID/PVC/writer fence must bracket every
    command. After decryption call validate_seaweed_archive with both admitted
    snapshots. Never accept native exit/size/hash alone as application recovery.

    Requires source shell, weed, wget, stat, df, tail, awk, sort, cmp, sha256sum,
    wc, cat, cut, mkdir, mv and tar. Budget must include all native volume bytes,
    both metadata exports and the outer tar (roughly twice native data plus
    metadata/headroom); free-space check is not a capacity reservation.
    """
    prefix = _source(source, SW_IMAGE, 'seaweedfs')
    _token(capture_id, staging_budget_bytes)
    need(scope == SEAWEED_SCOPE, 'seaweed_recovery_scope_not_supported')
    need(isinstance(admitted, dict) and set(admitted) == {'directory','master','local'}, 'seaweed_admission_missing')
    # Re-admit caller material rather than trusting arbitrary IDs/collection names.
    node = admitted['directory']['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0]
    ip = node['Url'].removesuffix(':8080')
    admitted = admit_seaweed(admitted['directory'], admitted['master'], admitted['local'], ip)
    review = seaweed_review_commands(capture_id, staging_budget_bytes, admitted)
    directory = review['directory']; q = shlex.quote
    names = sorted(((v['Collection']+'_') if v['Collection'] else '') + str(v['Id']) + '.' + suffix
                   for v in admitted['local']['Volumes'] for suffix in ('dat','idx','vif'))
    inventory = ' '.join(q('/data/' + n) for n in names)
    # Glob equality discovers orphan/extra normal native files as well as topology
    # changes. No hardcoded "log8" exception or post-capture exclusion exists.
    capture_files = (f'printf "%s\\n" ' + ' '.join(q(n) for n in names) + f' | sort > {directory}/expected.names\n'
                     f'for p in /data/*.dat /data/*.idx /data/*.vif; do test -f "$p"; test ! -L "$p"; '
                     f'printf "%s\\n" "${{p##*/}}"; done | sort > {directory}/actual.names\n'
                     f'cmp {directory}/expected.names {directory}/actual.names >/dev/null\n')
    stage = review['container_commands'][0][2] + '\n' + capture_files
    stage += f'sha256sum {inventory} > {directory}/source-before.sha256\n'
    # before/after native JSON is confidential outer-archive evidence, not stdout.
    for label in ('before',):
        for port, endpoint, name in ((9333,'/dir/status','directory'),(9333,'/vol/status','master'),(8080,'/status','local')):
            stage += f'wget -q -T 5 -O {directory}/{label}-{name}.json http://127.0.0.1:{port}{endpoint}\n'
    for command in review['container_commands'][1:]:
        stage += shlex.join(command) + '\n'
    stage += f'mv {directory}/filer.meta.gz {directory}/filer-before.meta.gz\n'
    second = review['container_commands'][1][2].replace('/filer.meta.gz','/filer-after.meta.gz')
    stage += shlex.join(_shell(second)) + '\n'
    stage += capture_files
    stage += f'sha256sum {inventory} > {directory}/source-after.sha256\n'
    stage += f'cmp {directory}/source-before.sha256 {directory}/source-after.sha256 >/dev/null\n'
    for port, endpoint, name in ((9333,'/dir/status','directory'),(9333,'/vol/status','master'),(8080,'/status','local')):
        stage += f'wget -q -T 5 -O {directory}/after-{name}.json http://127.0.0.1:{port}{endpoint}\n'
    for name in names:
        p = directory + '/volumes/' + name
        stage += f'test -f {q(p)}; test ! -L {q(p)}; test "$(stat -c %a {q(p)})" = 600\n'
        if name.endswith(('.dat','.idx')):
            stage += f'cmp {q("/data/"+name)} {q(p)} >/dev/null\n'
        if name.endswith('.idx'):
            stage += f'test "$(( $(wc -c < {q(p)}) % 16 ))" = 0\n'
    members = ('filer-before.meta.gz filer-after.meta.gz source-before.sha256 source-after.sha256 '
               'before-directory.json before-master.json before-local.json after-directory.json after-master.json after-local.json')
    members += ' ' + ' '.join('volumes/' + name for name in names)
    stage += f'test ! -e {directory}/native.tar; tar -cf {directory}/native.tar -C {directory} {members}\n'
    validate = _private_path_checks(directory) + f'''test -f {directory}/native.tar; test ! -L {directory}/native.tar
test "$(stat -c %u {directory}/native.tar)" = "$(id -u)"
test "$(stat -c %a {directory}/native.tar)" = 600; test "$(stat -c %h {directory}/native.tar)" = 1
test "$(wc -c < {directory}/native.tar)" -le {staging_budget_bytes}
tar -tf {directory}/native.tar >/dev/null
wc -c < {directory}/native.tar
sha256sum {directory}/native.tar | cut -d ' ' -f 1
'''
    # May be rerun after all four stores to reject even internal log/background
    # volume writes after staging. Never excuse them because history is optional.
    validate = (f'sha256sum {inventory} | cmp {directory}/source-before.sha256 - >/dev/null\n'
                f'for p in /data/*.dat /data/*.idx /data/*.vif; do test -f "$p"; test ! -L "$p"; '
                f'printf "%s\\n" "${{p##*/}}"; done | sort | cmp {directory}/expected.names - >/dev/null\n'
                + validate)
    producer = _private_path_checks(directory) + f'''test -f {directory}/native.tar; test ! -L {directory}/native.tar
test "$(stat -c %u {directory}/native.tar)" = "$(id -u)"
test "$(stat -c %a {directory}/native.tar)" = 600; test "$(stat -c %h {directory}/native.tar)" = 1
exec cat {directory}/native.tar
'''
    stage, validate, producer = map(_shell, (stage, validate, producer))
    return Fragment(source['uid'], SW_IMAGE, directory, prefix+stage, prefix+validate,
                    prefix+producer, stage, validate, producer)


def validate_seaweed_archive(blob, *, before, after):
    """Fixed production /data archive validation; no path override in this API."""
    return _validate_seaweed_archive(blob, before=before, after=after, source_root='/data')


def _validate_seaweed_archive(blob, *, before, after, source_root):
    """Validate a bounded decrypted outer archive; returned metadata stays private.

    Source and staged native dat/idx bytes must agree exactly for EVERY topology
    volume, including historical log volumes. Application metadata is byte-exact
    except the pinned synthetic virtual-root clock attributes. No log history is
    reconstructed or claimed; all ordinary entries, .etc/IAM content and extended
    bucket/object settings remain mandatory. Native restore + cold readback are
    separate acceptance, never inferred from this structural check.
    """
    import json
    fixture = _load('fixture-seaweed')
    inspector = _load('inspect-seaweed')
    try:
        need(len(blob) >= 1024 and len(blob) % 512 == 0, 'seaweed_tar_invalid')
        members = {}; headers = {}; end = 0
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            for member in archive:
                name = member.name
                need(member.isfile() and member.mode == 0o600 and member.uid == 10000
                     and name not in members and not name.startswith('/')
                     and '..' not in name.split('/'), 'seaweed_tar_member_invalid')
                stream = archive.extractfile(member)
                assert stream is not None
                body = stream.read()
                need(len(body) == member.size, 'seaweed_tar_truncated')
                members[name] = body
                headers[name] = {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                                 'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                                 'mtime': member.mtime, 'pax_headers': member.pax_headers}
                end = max(end, member.offset_data + ((member.size + 511)//512)*512)
        need(len(blob)-end >= 1024 and not any(blob[end:]), 'seaweed_tar_tail')
        volumes = before['local']['Volumes']
        names = {((v['Collection']+'_') if v['Collection'] else '') + str(v['Id']) + '.' + suffix
                 for v in volumes for suffix in ('dat','idx','vif')}
        expected = {'filer-before.meta.gz','filer-after.meta.gz','source-before.sha256','source-after.sha256'}
        expected |= {label+'-'+kind+'.json' for label in ('before','after') for kind in ('directory','master','local')}
        expected |= {'volumes/'+name for name in names}
        need(set(members) == expected, 'seaweed_archive_inventory')
        for label, externally_admitted in (('before',before),('after',after)):
            sample = {kind: inspector.decode(members[label+'-'+kind+'.json']) for kind in ('directory','master','local')}
            node = sample['directory']['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0]
            sample = admit_seaweed(sample['directory'],sample['master'],sample['local'],node['Url'].removesuffix(':8080'))
            need(_seaweed_state(sample) == _seaweed_state(externally_admitted), 'seaweed_topology_capture_changed')
        def source_map(raw):
            result = {}
            for line in raw.decode('ascii').splitlines():
                match = re.fullmatch(r'([0-9a-f]{64})  '+re.escape(source_root)+r'/([a-z0-9_.]+)',line)
                need(match is not None, 'seaweed_source_hash_invalid')
                assert match is not None
                digest,name = match.groups()
                need(name not in result and name in names, 'seaweed_source_hash_invalid')
                result[name] = digest
            need(set(result) == names, 'seaweed_source_hash_inventory')
            return result
        source_before = source_map(members['source-before.sha256'])
        source_after = source_map(members['source-after.sha256'])
        need(source_before == source_after, 'seaweed_background_write')
        source_evidence = {}
        for name in names:
            body = members['volumes/'+name]
            digest = hashlib.sha256(body).hexdigest()
            if name.endswith(('.dat','.idx')):
                need(source_before[name] == digest, 'seaweed_native_copy_mismatch')
            if name.endswith('.dat'):
                need(len(body) >= 8 and body[0] == 3, 'seaweed_native_volume_invalid')
            if name.endswith('.idx'):
                need(len(body)%16 == 0, 'seaweed_native_index_partial')
            if name.endswith('.vif'):
                need(inspector.decode(body) == {'files': [], 'version': 3, 'replication': '',
                     'bytesOffset': 4, 'datFileSize': '0', 'expireAtSec': '0',
                     'readOnly': False, 'ecShardConfig': None}, 'seaweed_native_volume_info_unsupported')
            source_evidence[name] = {'bytes': len(body), 'sha256': source_before[name]}
        metadata_before = fixture.records(members['filer-before.meta.gz'], application_state=True)
        metadata_after = fixture.records(members['filer-after.meta.gz'], application_state=True)
        require_seaweed_stable(before, after, source_evidence, source_evidence,
                               metadata_before, metadata_after)
        # Ensure metadata cannot reference an omitted normal/remote/EC volume.
        ids = {v['Id'] for v in volumes}
        for path, raw in metadata_before.items():
            if path == '/':
                continue
            full = fixture.wire(raw,{1,2})
            entry = fixture.wire(fixture.single(full,2),{1,2,3,4,5,7,8,9,10,11,12})
            for raw_chunk in entry.get(3,[]):
                chunk = fixture.wire(raw_chunk,set(range(1,14)))
                fid = fixture.single(chunk,1,b'')
                need(isinstance(fid,bytes) and re.fullmatch(rb'[1-9][0-9]*,[0-9a-f]+',fid) is not None
                     and int(fid.split(b',')[0]) in ids, 'seaweed_chunk_volume_missing')
                if 7 in chunk:
                    native_fid = fixture.wire(fixture.single(chunk,7),{1,2,3})
                    need(fixture.single(native_fid,1) == int(fid.split(b',')[0]), 'seaweed_chunk_volume_conflict')
        return {'bytes':len(blob),'sha256':hashlib.sha256(blob).hexdigest(),
                'members':headers,'application_metadata':metadata_before,
                'normal_volume_count':len(volumes),'historical_change_log_replay':False}
    except Refused:
        raise
    except Exception:
        raise Refused('seaweed_archive_invalid_or_unsupported') from None
