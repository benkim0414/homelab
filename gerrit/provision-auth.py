#!/usr/bin/env python3
"""Privately prompt for new Gerrit lab credentials and write only a SealedSecret.

No cluster writes. Uses normal kubeseal authentication to fetch the public
controller certificate. Run in your private terminal, not through agent tools.
"""
import argparse
import base64
import getpass
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


class ProvisionError(Exception):
    """A fixed, credential-free operational diagnostic safe for the terminal."""


def validate_password(password):
    if len(password) < 16:
        raise ValueError('Password must contain at least 16 characters; please try again.')
    if any(c in password for c in '\r\n\x00'):
        raise ValueError('Password must not contain line breaks or NUL; please try again.')


def prompt_password():
    while True:
        password = getpass.getpass('New lab password (at least 16 characters): ')
        try:
            validate_password(password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            continue
        if password != getpass.getpass('Confirm password: '):
            print('Passwords differ; please try again.', file=sys.stderr)
            continue
        return password


def check_sealer(executable):
    try:
        result = subprocess.run([executable, '--controller-name', 'sealed-secrets-controller',
                                 '--controller-namespace', 'kube-system', '--fetch-cert'],
                                capture_output=True, check=True, timeout=45)
    except subprocess.CalledProcessError as exc:
        raise ProvisionError(f'Controller public-certificate lookup failed (kubeseal exit {exc.returncode}). Check your current Kubernetes context and controller access.') from None
    except (OSError, subprocess.TimeoutExpired):
        raise ProvisionError('Controller public-certificate lookup could not run or timed out. Check kubeseal and cluster connectivity.') from None
    if b'-----BEGIN CERTIFICATE-----' not in result.stdout:
        raise ProvisionError('Controller lookup did not return a public certificate.')


def validate_identity(username, email):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', username):
        raise ValueError('Username must start with a lowercase letter; use at most 32 lowercase letters, digits, _ or -')
    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email):
        raise ValueError('Use a plain email address without quotes or whitespace')


def build_secret(accounts):
    if not accounts or len({name for name, _, _ in accounts}) != len(accounts):
        raise ValueError('At least one account and distinct usernames are required')
    password_file = []
    mapping = ['map $remote_user $gerrit_email {', '    default "";']
    for username, email, password in accounts:
        validate_identity(username, email)
        validate_password(password)
        try:
            result = subprocess.run(['openssl', 'passwd', '-6', '-stdin'],
                                    input=(password + '\n').encode(), capture_output=True, check=True, timeout=15)
        except subprocess.CalledProcessError as exc:
            raise ProvisionError(f'Password hashing failed (OpenSSL exit {exc.returncode}). Check local OpenSSL support for passwd -6.') from None
        except (OSError, subprocess.TimeoutExpired):
            raise ProvisionError('Password hashing could not run or timed out. Check local OpenSSL installation.') from None
        hashed = result.stdout.decode().strip()
        if not hashed.startswith('$6$'):
            raise ValueError('Unexpected password hash format')
        password_file.append(f'{username}:{hashed}\n')
        mapping.append(f'    "{username}" "{email}";')
    mapping.append('}')
    values = {'htpasswd': ''.join(password_file), 'identities.conf': '\n'.join(mapping) + '\n'}
    return {'apiVersion': 'v1', 'kind': 'Secret',
            'metadata': {'name': 'gerrit-auth', 'namespace': 'gerrit'}, 'type': 'Opaque',
            'data': {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}}


def seal(secret, executable):
    try:
        result = subprocess.run([executable, '--controller-name', 'sealed-secrets-controller',
                                 '--controller-namespace', 'kube-system', '--scope', 'strict',
                                 '--format', 'json'], input=json.dumps(secret).encode(),
                                capture_output=True, check=True, timeout=45)
    except subprocess.CalledProcessError as exc:
        raise ProvisionError(f'Credential sealing failed (kubeseal exit {exc.returncode}). Check the current Kubernetes context, controller access and kubeseal version.') from None
    except (OSError, subprocess.TimeoutExpired):
        raise ProvisionError('Credential sealing could not run or timed out. Check kubeseal and cluster connectivity.') from None
    try:
        document = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise ProvisionError('Sealer returned invalid JSON; sensitive subprocess output was withheld.') from None
    if (document.get('kind') != 'SealedSecret'
            or document.get('metadata', {}).get('name') != 'gerrit-auth'
            or document.get('metadata', {}).get('namespace') != 'gerrit'
            or set(document.get('spec', {}).get('encryptedData', {})) != {'htpasswd', 'identities.conf'}):
        raise ValueError('Sealer returned unexpected identity or encrypted fields')
    return json.dumps(document, indent=2) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeseal', default=str(ROOT.parent / 'verification/cache/bin/kubeseal'))
    parser.add_argument('--accounts', type=int, choices=(1, 2), default=1)
    parser.add_argument('--output', type=Path, default=ROOT / 'auth-sealed-secret.yaml')
    parser.add_argument('--check', action='store_true', help='Test hashing and sealing with synthetic credentials; no prompts, files or cluster writes')
    args = parser.parse_args()
    if not args.check and (not sys.stdin.isatty() or not sys.stderr.isatty()):
        sys.exit('Run interactively in your private terminal; never supply passwords through agent tools')
    if not args.check and args.output.exists():
        sys.exit('Output exists; explicit rotation/replacement review required (no overwrite)')
    if not shutil.which(args.kubeseal) or not shutil.which('openssl'):
        sys.exit('Pinned kubeseal and openssl are required; see gerrit/README.md')
    try:
        check_sealer(args.kubeseal)
        if args.check:
            seal(build_secret([('fixture', 'fixture@example.invalid', secrets.token_urlsafe(24))]), args.kubeseal)
            print('Public-certificate lookup, hashing and sealing passed with synthetic credentials; no files or cluster resources written.')
            return
    except (ProvisionError, ValueError) as exc:
        sys.exit(str(exc) + ' No credentials printed or cluster writes performed.')
    accounts = []
    print('Bootstrap with ONE operator account. Add a non-admin learning account only after the administrator is verified.')
    for number in range(args.accounts):
        username = input(f'Account {number + 1} username: ').strip()
        email = input('Commit email: ').strip()
        try:
            validate_identity(username, email)
        except ValueError as exc:
            sys.exit(str(exc) + '; nothing written')
        password = prompt_password()
        accounts.append((username, email, password))
    try:
        encrypted = seal(build_secret(accounts), args.kubeseal)
    except (ProvisionError, ValueError) as exc:
        sys.exit(str(exc) + ' No credentials printed or cluster writes performed.')
    # JSON is valid YAML. Exclusive creation preserves any existing ciphertext.
    with args.output.open('x') as output:
        output.write(encrypted)
    print(f'Wrote encrypted SealedSecret: {args.output.resolve()}')
    print('No cluster changes made. Keep passwords privately in your vault; do not paste them in chat.')


if __name__ == '__main__':
    main()
