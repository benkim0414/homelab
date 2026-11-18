#!/usr/bin/env python3
"""Operator-only bootstrap: plaintext stays in memory and kubeseal stdin.

Requires explicit credential-provisioning approval; never run for routine checks.
JSON ciphertext is also valid YAML. No existing Kubernetes Secret is read.
Publication is atomic per file, not a crash-atomic six-file transaction: after an
interruption inspect the ciphertext set; never delete it and blindly regenerate.
"""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import warnings

NAMES = ('langfuse-app-credentials', 'langfuse-bootstrap', 'langfuse-postgresql-auth',
         'langfuse-redis-auth', 'langfuse-clickhouse-auth', 'langfuse-s3-auth')
ANNOTATIONS = {'argocd.argoproj.io/sync-wave': '-2',
               'argocd.argoproj.io/sync-options': 'Prune=false,Delete=false'}
FAILURES = {
    'email': 'owner email is not a valid address',
    'password-length': 'owner password must contain at least 20 characters',
    'password-mismatch': 'owner passwords do not match',
    'password-characters': 'owner password must be nonblank and contain no control characters',
    'existing': 'a ciphertext destination already exists; no files overwritten',
    'sealing': 'kubeseal exited unsuccessfully; check API/controller connectivity (stderr withheld)',
    'sealed-output': 'kubeseal output failed structural validation',
    'sealed-payload': 'kubeseal output has unexpected encrypted keys or template fields',
    'sealed-identity': 'kubeseal output has the wrong namespace or name',
    'sealed-scope': 'kubeseal output has an unexpected sealing scope',
    'ciphertext': 'kubeseal output has invalid ciphertext encoding',
}


class BootstrapError(ValueError):
    """A controlled reason code, never an input value or subprocess diagnostic."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse otherwise echoes unknown arguments, which might contain keys.
        raise SystemExit('Provisioning accepts only --help; enter credentials at private prompts, never in arguments')


def random_key():
    return secrets.token_hex(32)


def open_directory(path):
    """Pin the output directory; refuse symlinks in every path component."""
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def require_absent(directory, destinations):
    for name in destinations:
        try:
            os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise BootstrapError('existing')


def seal(name, values, namespace='langfuse'):
    metadata = {'name': name, 'namespace': namespace, 'annotations': ANNOTATIONS}
    manifest = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': metadata, 'stringData': values}
    result = subprocess.run([
        'kubeseal', '--controller-name', 'sealed-secrets-controller',
        '--controller-namespace', 'kube-system', '--scope', 'strict', '--format', 'json'],
        input=json.dumps(manifest).encode(), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=60)
    if result.returncode:
        raise BootstrapError('sealing')
    document = json.loads(result.stdout)
    # Allowlist the serialized output so neither plaintext Secret payloads nor
    # arbitrary kubeseal output can be published, even on a zero exit status.
    if (document.get('apiVersion') != 'bitnami.com/v1alpha1'
            or document.get('kind') != 'SealedSecret'
            or set(document) - {'apiVersion', 'kind', 'metadata', 'spec', 'status'}):
        raise BootstrapError('sealed-output')
    spec = document['spec']
    encrypted = spec['encryptedData']
    template = spec['template']
    if (set(spec) != {'encryptedData', 'template'}
            or set(template) - {'metadata', 'type'}
            or template.get('type') != 'Opaque'
            or set(encrypted) != set(values)
            or not all(isinstance(v, str) and v.strip() for v in encrypted.values())):
        raise BootstrapError('sealed-payload')
    for item in (document['metadata'], template['metadata']):
        if item.get('name') != name or item.get('namespace') != namespace:
            raise BootstrapError('sealed-identity')
        if item.get('annotations', {}).get('sealedsecrets.bitnami.com/cluster-wide') == 'true' \
                or item.get('annotations', {}).get('sealedsecrets.bitnami.com/namespace-wide') == 'true':
            raise BootstrapError('sealed-scope')
    for ciphertext in encrypted.values():
        if len(base64.b64decode(ciphertext, validate=True)) < 32:
            raise BootstrapError('ciphertext')
    # Rebuild only reviewed fields; discard status, timestamps and other metadata.
    safe = {'apiVersion': 'bitnami.com/v1alpha1', 'kind': 'SealedSecret',
            'metadata': metadata, 'spec': {'encryptedData': encrypted,
                                         'template': {'metadata': metadata, 'type': 'Opaque'}}}
    return (json.dumps(safe, indent=2) + '\n').encode()


def publish(directory, sealed):
    """Stage only ciphertext, hard-link without replacement, roll back on errors."""
    staged = {}
    published = []
    try:
        require_absent(directory, sealed)
        for index, (destination, ciphertext) in enumerate(sealed.items()):
            temporary = f'.seal-bootstrap-{os.getpid()}-{index}.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            staged[destination] = temporary
            with os.fdopen(fd, 'wb') as stream:
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
        for destination, temporary in staged.items():
            os.link(temporary, destination, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
            published.append(destination)
        os.fsync(directory)
    except BaseException:
        for destination in reversed(published):
            # Do not remove a concurrently replaced operator file.
            current = os.stat(destination, dir_fd=directory, follow_symlinks=False)
            original = os.stat(staged[destination], dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino):
                os.unlink(destination, dir_fd=directory)
        raise
    finally:
        for temporary in staged.values():
            os.unlink(temporary, dir_fd=directory)


def bootstrap(directory):
    destinations = [name + '-sealed-secret.yaml' for name in NAMES]
    require_absent(directory, destinations)
    email = input('Initial owner email: ').strip()
    with warnings.catch_warnings():
        # Never fall back to echoed password input if /dev/tty cannot be used.
        warnings.simplefilter('error', getpass.GetPassWarning)
        password = getpass.getpass('Initial owner password (at least 20 characters; store in your vault): ')
        repeat = getpass.getpass('Repeat password: ')
    if (not re.fullmatch(r'[^\s@\x00-\x1f\x7f]+@[^\s@\x00-\x1f\x7f]+\.[^\s@\x00-\x1f\x7f]+', email)
            or len(email) > 254):
        raise BootstrapError('email')
    if len(password) < 20:
        raise BootstrapError('password-length')
    if password != repeat:
        raise BootstrapError('password-mismatch')
    if not password.strip() or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise BootstrapError('password-characters')
    postgres_password, app_password = random_key(), random_key()
    access, s3_password = 'lf' + secrets.token_hex(12), random_key()
    iam = {'identities': [{'name': 'langfuse', 'credentials': [
        {'accessKey': access, 'secretKey': s3_password}],
        'actions': ['Admin', 'Read', 'Write', 'List', 'Tagging']}]}
    payloads = {
        NAMES[0]: {'salt': random_key(), 'encryption-key': random_key(),
                   'nextauth-secret': random_key()},
        NAMES[1]: {'email': email, 'password': password},
        NAMES[2]: {'POSTGRES_USER': 'postgres', 'POSTGRES_PASSWORD': postgres_password,
                   'POSTGRES_DB': 'langfuse', 'USERDB_USER': 'langfuse',
                   'USERDB_PASSWORD': app_password},
        NAMES[3]: {'default': random_key()},
        NAMES[4]: {'password': random_key()},
        NAMES[5]: {'accessKey': access, 'secretKey': s3_password,
                   'seaweedfs_s3_config': json.dumps(iam)},
    }
    # All subprocesses must succeed and validate before any ciphertext is written.
    sealed = {name + '-sealed-secret.yaml': seal(name, values)
              for name, values in payloads.items()}
    publish(directory, sealed)


def main(argv=None):
    parser = PrivateArgumentParser(description=(
        'Approved operator-only interactive bootstrap. Creates six new SealedSecrets '
        'beside this script; refuses symlinks and existing files. Requires kubeseal '
        'and a private terminal. The owner password must contain at least 20 '
        'characters; store it in your vault first. '
        'No credential arguments or noninteractive provisioning are supported.'))
    parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SystemExit('Refusing noninteractive provisioning; use a private terminal')
    previous_umask = os.umask(0o077)
    directory = None
    try:
        directory = open_directory(Path(__file__).absolute().parent)
        bootstrap(directory)
    except BootstrapError as exc:
        reason = FAILURES.get(exc.code, 'validation failed')
        raise SystemExit(f'Bootstrap failed: {reason}. Plaintext withheld. '
                         'Existing files preserved; inspect ciphertext before retrying.') from None
    except subprocess.TimeoutExpired:
        raise SystemExit('Bootstrap failed: kubeseal timed out; check API/controller '
                         'connectivity. Plaintext and subprocess output withheld.') from None
    except FileNotFoundError:
        raise SystemExit('Bootstrap failed: required directory or kubeseal executable '
                         'not found. Check the command PATH. Details withheld.') from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            subprocess.SubprocessError, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise SystemExit('Bootstrap failed; details and plaintext withheld. '
                         'Existing files preserved; inspect ciphertext before retrying.') from None
    finally:
        if directory is not None:
            os.close(directory)
        os.umask(previous_umask)
    print('Sealed six new Langfuse secrets; no plaintext files created')


if __name__ == '__main__':
    main()
