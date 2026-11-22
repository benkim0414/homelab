#!/usr/bin/env python3
"""Operator-private cluster key entry; publish only strict ciphertext, never apply."""
import base64
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import warnings

_spec = importlib.util.spec_from_file_location('langfuse_bootstrap', Path(__file__).with_name('seal-bootstrap.py'))
assert _spec is not None and _spec.loader is not None
bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bootstrap)

DESTINATION = 'langfuse-sealed-secret.yaml'
PROJECT_URL = 'https://langfuse.tailbd291c.ts.net/api/public/projects'
REASONS = {
    'key': 'expected unmodified pk-lf-/sk-lf- project keys without whitespace',
    'repeat': 'secret key confirmation does not match',
    'project': 'keys must belong only to the hermes-cluster project; nothing published',
}


class ClientError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the project Authorization header to another destination.
        return None


def verify_project(public, secret):
    authorization = base64.b64encode(f'{public}:{secret}'.encode()).decode()
    request = urllib.request.Request(PROJECT_URL, headers={
        'Authorization': 'Basic ' + authorization,
        'Accept': 'application/json',
    }, method='GET')
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=15) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ClientError('project')
    projects = json.loads(raw).get('data')
    if (not isinstance(projects, list) or len(projects) != 1
            or not isinstance(projects[0], dict)
            or projects[0].get('name') != 'hermes-cluster'):
        raise ClientError('project')


def provision(directory):
    bootstrap.require_absent(directory, [DESTINATION])
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        public = getpass.getpass('hermes-cluster public key (hidden): ')
        secret = getpass.getpass('hermes-cluster secret key (hidden): ')
        repeat = getpass.getpass('Repeat cluster secret key: ')
    if (not re.fullmatch(r'pk-lf-[A-Za-z0-9_-]{8,250}', public)
            or not re.fullmatch(r'sk-lf-[A-Za-z0-9_-]{8,250}', secret)):
        raise ClientError('key')
    if secret != repeat:
        raise ClientError('repeat')
    verify_project(public, secret)
    ciphertext = bootstrap.seal('hermes-langfuse', {
        'public-key': public, 'secret-key': secret,
    }, namespace='hermes')
    bootstrap.publish(directory, {DESTINATION: ciphertext})


def main(argv=None):
    parser = bootstrap.PrivateArgumentParser(description=(
        'Private terminal only: verify the hermes-cluster project key pair over '
        'HTTPS, then seal it as hermes/hermes-langfuse. Writes only '
        'hermes/profiles/house-manager/langfuse-sealed-secret.yaml; refuses symlinks and existing files. '
        'No credential arguments, plaintext files or cluster apply.'))
    parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SystemExit('Refusing noninteractive provisioning; use a private terminal')
    previous_umask = os.umask(0o077)
    directory = None
    try:
        directory = bootstrap.open_directory(Path(__file__).absolute().parent.parent / 'hermes/profiles/house-manager')
        provision(directory)
    except ClientError as exc:
        raise SystemExit('Client provisioning failed: ' + REASONS.get(str(exc), 'validation failed') +
                         '. Keys and response details withheld.') from None
    except bootstrap.BootstrapError as exc:
        raise SystemExit('Client provisioning failed: ' + bootstrap.FAILURES.get(exc.code, 'sealing validation failed') +
                         '. Keys and subprocess output withheld.') from None
    except urllib.error.HTTPError:
        raise SystemExit('Client provisioning failed: project API rejected the request. '
                         'Check the cluster project key pair and server; response details withheld.') from None
    except (urllib.error.URLError, TimeoutError):
        raise SystemExit('Client provisioning failed: private HTTPS project check failed. '
                         'Check endpoint connectivity/TLS; details withheld.') from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError,
            EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise SystemExit('Client provisioning failed; keys and details withheld. '
                         'No existing files overwritten.') from None
    finally:
        if directory is not None:
            os.close(directory)
        os.umask(previous_umask)
    print('Sealed Hermes cluster client credentials; no plaintext files created or resources applied')


if __name__ == '__main__':
    main()
