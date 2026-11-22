#!/usr/bin/env python3
"""Private hermes-cluster replacement only; never create/revoke keys or apply.

Run from this task worktree in a private terminal after creating a replacement
hermes-cluster project pair in the private UI. Do not rerun server bootstrap or
initial client provisioning. Review/publish/deploy the ciphertext separately.
For the potential-disclosure workflow, tracing is paused: privately revoke the
old project pair promptly; this helper itself never creates or revokes keys.

Reuse provision() in an empty private staging directory, NOT over the existing
manifest: it owns hidden prompts, validation, fixed HTTPS project verification,
strict namespace-explicit sealing and validated no-overwrite staging publication.
Only ciphertext reaches disk. The previous ciphertext is retained in ignored
verification/cache/rotation-*/previous-ciphertext.yaml, not an app source.

Directory flock serializes this helper; stat+SHA256 guards detect other writers
before replacement. As with any stat-then-rename guard, unrelated writers must
not edit the target in the final check/rename interval (not an OS-level CAS).
"""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import sys

_spec = importlib.util.spec_from_file_location(
    'langfuse_rotation_client', Path(__file__).with_name('seal-hermes-client.py'))
assert _spec is not None and _spec.loader is not None
client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(client)
bootstrap = client.bootstrap
DESTINATION = client.DESTINATION
BACKUP = 'previous-ciphertext.yaml'
LIMIT = 1024 * 1024


class RotationError(ValueError):
    pass


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def snapshot(directory, name):
    """Read a bounded regular file without following symlinks or blocking on FIFO."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > LIMIT:
            raise RotationError()
        data = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    if (len(data) > LIMIT or identity(before) != identity(after)
            or identity(after) != identity(os.stat(name, dir_fd=directory, follow_symlinks=False))):
        raise RotationError()
    return (identity(after), hashlib.sha256(data).digest()), data


def validate_ciphertext(data):
    """Defence in depth: fixed identity/keyset, strict scope, no plaintext fields."""
    doc = json.loads(data)
    if (set(doc) != {'apiVersion', 'kind', 'metadata', 'spec'}
            or doc['apiVersion'] != 'bitnami.com/v1alpha1' or doc['kind'] != 'SealedSecret'):
        raise RotationError()
    spec = doc['spec']
    if (set(spec) != {'encryptedData', 'template'}
            or set(spec['template']) != {'metadata', 'type'}
            or spec['template']['type'] != 'Opaque'
            or set(spec['encryptedData']) != {'public-key', 'secret-key'}):
        raise RotationError()
    for metadata in (doc['metadata'], spec['template']['metadata']):
        if (set(metadata) - {'name', 'namespace', 'annotations'}
                or metadata['name'] != 'hermes-langfuse' or metadata['namespace'] != 'hermes'
                or any(bootstrap.ANNOTATIONS.get(k) != v
                       for k, v in metadata.get('annotations', {}).items())):
            raise RotationError()
    for value in spec['encryptedData'].values():
        if not isinstance(value, str) or len(base64.b64decode(value, validate=True)) < 32:
            raise RotationError()


def write_backup(directory, data):
    fd = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(directory)


def rotate(root):
    """Return the old ciphertext backup path only after atomic replacement."""
    directory = bootstrap.open_directory(root / 'hermes/profiles/house-manager')
    staging = cache = verification = None
    try:
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_guard, original = snapshot(directory, DESTINATION)
        validate_ciphertext(original)
        # This fixed cache is excluded by verification/.gitignore (/cache/).
        verification = bootstrap.open_directory(root / 'verification')
        try:
            os.mkdir('cache', 0o700, dir_fd=verification)
        except FileExistsError:
            pass
        cache = bootstrap.open_directory(root / 'verification/cache')
        name = 'rotation-' + secrets.token_hex(16)
        os.mkdir(name, 0o700, dir_fd=cache)
        staging = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=cache)
        os.fchmod(staging, 0o700)
        backup_path = root / 'verification/cache' / name / BACKUP
        # Safe reuse: an empty directory, never the existing app destination.
        client.provision(staging)
        staged_guard, replacement = snapshot(staging, DESTINATION)
        validate_ciphertext(replacement)
        if snapshot(directory, DESTINATION)[0] != original_guard:
            raise RotationError()
        write_backup(staging, original)
        # Recheck immediately before publication, including changes during backup.
        if (snapshot(directory, DESTINATION)[0] != original_guard
                or snapshot(staging, DESTINATION)[0] != staged_guard):
            raise RotationError()
        os.replace(DESTINATION, DESTINATION, src_dir_fd=staging, dst_dir_fd=directory)
        os.fsync(directory)
        os.fsync(staging)
        # Read back the exact target before declaring successful publication.
        if snapshot(directory, DESTINATION)[1] != replacement:
            raise RotationError()
        return backup_path
    finally:
        # Keep any ciphertext-only staging/backup on failure for private inspection.
        for fd in (staging, cache, verification, directory):
            if fd is not None:
                os.close(fd)


def main(argv=None):
    parser = bootstrap.PrivateArgumentParser(description=(
        'Private hermes-cluster project key rotation only. Replaces only '
        'hermes/profiles/house-manager/langfuse-sealed-secret.yaml after HTTPS verification and strict '
        'sealing; retains old ciphertext in ignored verification/cache/rotation-*. '
        'No credential arguments, plaintext files, key revocation or cluster apply.'))
    args = list(sys.argv[1:] if argv is None else argv)
    # Reject even --help + sensitive/unknown tokens before argparse can print them.
    if args not in ([], ['--help'], ['-h']):
        parser.error('unsupported arguments')
    parser.parse_args(args)
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SystemExit('Refusing noninteractive rotation; use a private terminal')
    previous_umask = os.umask(0o077)
    try:
        backup = rotate(Path(__file__).absolute().parent.parent)
    except (Exception, KeyboardInterrupt):
        # Never stringify arbitrary input, network exceptions or kubeseal stderr.
        # A durability/readback failure can occur after rename: never claim unchanged.
        raise SystemExit('Client rotation failed; keys and details withheld. '
                         'Inspect target and ignored verification/cache/rotation-* ciphertext '
                         'before retrying; no resources applied.') from None
    finally:
        os.umask(previous_umask)
    print('Replaced Hermes cluster client ciphertext; no plaintext files created or resources applied.')
    print('Previous ciphertext backup: ' + str(backup))


if __name__ == '__main__':
    main()
