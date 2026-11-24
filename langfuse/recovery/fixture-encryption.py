#!/usr/bin/env python3
"""Generated-only age archive round trip. Never selects a production recipient.

Creates new disposable fixture keys in an ignored owner-only cache. No external
key/recipient/input arguments exist. Existing key stores and production data are
never accessed. Download checksum is from the official v1.3.2 GitHub asset API;
this is integrity checking, not release-signature verification.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'verification/cache/langfuse-recovery/encryption'
URL = 'https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz'
SHA256 = 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10'
MAX_ARCHIVE = 4 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def new_file(path, data, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def private_directory(path):
    # Parent path components must be real directories, not aliases to other state.
    path.relative_to(ROOT)
    current = ROOT
    for component in path.relative_to(ROOT).parts:
        current /= component
        if not current.exists() and not current.is_symlink():
            current.mkdir(mode=0o700)
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ValueError('unsafe fixture directory')
    if path.stat().st_mode & 0o077:
        raise ValueError('fixture directory is not owner-only')


def tools():
    private_directory(CACHE)
    archive = CACHE / 'age-v1.3.2-linux-amd64.tar.gz'
    if not archive.exists() and not archive.is_symlink():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024 or digest(data) != SHA256:
            raise ValueError('official age artifact checksum mismatch')
        new_file(archive, data)
    if archive.is_symlink() or not archive.is_file() or digest(archive.read_bytes()) != SHA256:
        raise ValueError('cached age artifact mismatch')
    binaries = {}
    with tarfile.open(fileobj=io.BytesIO(archive.read_bytes()), mode='r:gz') as package:
        for name in ['age', 'age-keygen']:
            member = package.getmember('age/' + name)
            if not member.isfile() or member.size > 32 * 1024 * 1024:
                raise ValueError('unexpected executable in age package')
            source = package.extractfile(member)
            if source is None:
                raise ValueError('missing executable')
            data = source.read()
            path = CACHE / name
            if not path.exists() and not path.is_symlink():
                new_file(path, data, mode=0o700)
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise ValueError('cached age executable mismatch')
            binaries[name] = path
    return binaries


def native(binaries, state, name, args, output=None):
    # Statically linked official Go tools need no host libraries/config/key stores.
    cmd = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
           '--cap-drop', 'ALL', '--ro-bind', str(binaries['age']), '/age',
           '--ro-bind', str(binaries['age-keygen']), '/age-keygen',
           '--tmpfs', '/tmp', '--proc', '/proc', '--dev', '/dev',
           '--bind', str(state), '/fixture', '--chdir', '/fixture', '--clearenv',
           '--setenv', 'HOME', '/tmp', '/' + name] + args
    if output is None:
        return subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        result = subprocess.run(cmd, stdout=stream, stderr=subprocess.PIPE,
                                timeout=30, check=False)
        stream.flush()
        os.fsync(stream.fileno())
    return result


def require_success(result):
    if result.returncode:
        raise ValueError('native fixture command failed; diagnostics withheld')


def archive_inventory(path):
    if path.stat().st_size > MAX_ARCHIVE:
        raise ValueError('oversized fixture archive')
    data = path.read_bytes()
    if len(data) % 512 or len(data) < 1024 or data[-1024:] != bytes(1024):
        raise ValueError('incomplete tar termination')
    inventory = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        for member in archive:
            if (not member.isfile() or member.name not in {'schema.txt', 'data.bin'}
                    or member.name in inventory):
                raise ValueError('unexpected fixture archive member')
            total += member.size
            if total > MAX_ARCHIVE:
                raise ValueError('oversized fixture member')
            source = archive.extractfile(member)
            if source is None:
                raise ValueError('missing fixture archive member')
            content = source.read()
            if len(content) != member.size:
                raise ValueError('short fixture archive member')
            inventory[member.name] = {'bytes': len(content), 'sha256': digest(content)}
        if any(data[archive.offset:]):
            raise ValueError('unparsed trailing archive content')
    if set(inventory) != {'schema.txt', 'data.bin'}:
        raise ValueError('incomplete fixture inventory')
    return inventory


def main():
    if len(sys.argv) != 1 or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        print('Generated-only fixture supports Linux x86_64 and no arguments.', file=sys.stderr)
        return 2
    os.umask(0o077)
    try:
        binaries = tools()
    except Exception:
        print('Fixture tool preparation failed; no acceptance claimed.', file=sys.stderr)
        return 1
    state = CACHE / ('run-' + uuid.uuid4().hex)
    state.mkdir(mode=0o700)
    start = time.monotonic()
    receipt = {'status': 'INCOMPLETE', 'production_recipient_selected': False,
               'production_custody_verified': False,
               'scope': 'generated-only offline age round trip',
               'code_sha256': digest(Path(__file__).read_bytes()),
               'age_archive_sha256': SHA256, 'state': str(state)}
    try:
        version = native(binaries, state, 'age', ['--version'])
        require_success(version)
        if version.stdout.strip() != b'v1.3.2':
            raise ValueError('unexpected native age version')
        for name in ['fixture', 'wrong']:
            require_success(native(binaries, state, 'age-keygen', ['-o', name + '.identity']))
        recipient_result = native(binaries, state, 'age-keygen', ['-y', 'fixture.identity'])
        require_success(recipient_result)
        recipient = recipient_result.stdout.decode('ascii').strip()
        if not recipient.startswith('age1') or not recipient.isalnum():
            raise ValueError('unexpected generated public recipient')
        payload = {'schema.txt': b'GENERATED FIXTURE ONLY\nversion=1\n',
                   'data.bin': os.urandom(1024 * 1024 + 17)}
        with tarfile.open(state / 'source.tar', 'x:') as archive:
            for name, content in payload.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mode = 0o600
                archive.addfile(member, io.BytesIO(content))
        expected = archive_inventory(state / 'source.tar')
        require_success(native(binaries, state, 'age', ['-r', recipient, 'source.tar'],
                               state / 'archive.age'))
        require_success(native(binaries, state, 'age',
                               ['-d', '-i', 'fixture.identity', 'archive.age'],
                               state / 'restored.incomplete'))
        if archive_inventory(state / 'restored.incomplete') != expected:
            raise ValueError('decrypted full archive inventory differs')
        os.link(state / 'restored.incomplete', state / 'accepted.tar')
        encrypted = (state / 'archive.age').read_bytes()
        new_file(state / 'truncated.age', encrypted[:-33])
        corrupt = bytearray(encrypted)
        corrupt[-20] ^= 1
        new_file(state / 'corrupt.age', corrupt)
        rejected = []
        for label, key, source in [('wrong-identity', 'wrong.identity', 'archive.age'),
                                   ('truncated-ciphertext', 'fixture.identity', 'truncated.age'),
                                   ('corrupt-ciphertext', 'fixture.identity', 'corrupt.age')]:
            output = state / (label + '.incomplete')
            result = native(binaries, state, 'age', ['-d', '-i', key, source], output)
            if result.returncode == 0:
                raise ValueError('negative ciphertext case was accepted')
            # Partial plaintext may exist; no accepted path is ever published.
            if (state / (label + '.accepted')).exists():
                raise ValueError('failed ciphertext published as accepted')
            rejected.append(label)
        new_file(state / 'bad-inventory.tar', (state / 'source.tar').read_bytes()[:1000])
        try:
            archive_inventory(state / 'bad-inventory.tar')
        except (ValueError, tarfile.TarError):
            rejected.append('incomplete-plain-archive')
        else:
            raise ValueError('truncated plaintext archive accepted')
        try:
            native(binaries, state, 'age', ['-r', recipient, 'source.tar'], state / 'archive.age')
        except FileExistsError:
            rejected.append('output-overwrite')
        else:
            raise ValueError('existing output was overwritten')
        receipt.update(status='PASS', version='v1.3.2', archive_inventory=expected,
                       source_sha256=digest((state / 'source.tar').read_bytes()),
                       restored_sha256=digest((state / 'accepted.tar').read_bytes()),
                       ciphertext_sha256=digest(encrypted), ciphertext_bytes=len(encrypted),
                       negatives_rejected=rejected, seconds=round(time.monotonic() - start, 3),
                       binary_sha256={name: digest(path.read_bytes()) for name, path in binaries.items()})
    except Exception:
        receipt['status'] = 'FAILED'
        receipt['error'] = 'fixture failed; no production acceptance or key selection'
    new_file(state / 'receipt.json', (json.dumps(receipt, indent=2) + '\n').encode())
    print(json.dumps({'status': receipt['status'], 'receipt': str(state / 'receipt.json'),
                      'production_recipient_selected': False, 'production_custody_verified': False}))
    return 0 if receipt['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
