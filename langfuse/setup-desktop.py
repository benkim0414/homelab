#!/usr/bin/env python3
"""Private operator key entry, fixed desktop project, no plugin activation.

Uses Hermes' native credential writer. Stores only project keys in the selected
profile's normal plaintext credential file (not encrypted); no extra copies.
Run separately for each profile. Never run concurrently with credential edits.
"""
import base64
import getpass
import json
import os
from pathlib import Path
import re
import ssl
import stat
import sys
import urllib.request
import warnings

PROFILES = ('homelab-scientist', 'default')
PROJECT_URL = 'https://langfuse.tailbd291c.ts.net/api/public/projects'
KEYS = ('HERMES_LANGFUSE_PUBLIC_KEY', 'HERMES_LANGFUSE_SECRET_KEY')


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_project(public, secret):
    header = base64.b64encode(f'{public}:{secret}'.encode()).decode()
    request = urllib.request.Request(PROJECT_URL, headers={
        'Authorization': 'Basic ' + header, 'Accept': 'application/json'}, method='GET')
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=15) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise SetupError('Project response exceeded the safe limit.')
    data = json.loads(raw).get('data')
    if (not isinstance(data, list) or len(data) != 1
            or not isinstance(data[0], dict) or data[0].get('name') != 'hermes-desktop'):
        raise SetupError('Keys do not identify only the hermes-desktop project.')


class NativeBackend:
    def __init__(self, profile):
        # This helper is intentionally run with the inspected Hermes interpreter.
        root = Path(sys.prefix).parent
        if not (root / 'hermes_cli/config.py').is_file():
            raise SetupError('Use the Hermes venv interpreter shown in the instructions.')
        sys.path.insert(0, str(root))
        from hermes_cli.profiles import resolve_profile_env
        os.environ['HERMES_HOME'] = resolve_profile_env(profile)
        from hermes_cli import config
        from hermes_cli.plugins_cmd import _get_enabled_set
        self.config = config
        self.enabled = _get_enabled_set

    def preflight(self):
        path = self.config.get_env_path()
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                raise SetupError('Credential file must be an owner-only regular file; nothing changed.')
        if {'langfuse', 'observability/langfuse', 'homelab-langfuse-desktop'} & self.enabled():
            raise SetupError('Disable this profile Langfuse plugin first; nothing changed.')
        if any(self.config.load_env().get(key) for key in KEYS):
            raise SetupError('Desktop credentials already exist; refusing replacement.')

    def save(self, public, secret):
        # Native writes preserve unrelated entries; the pair is two writes, not
        # an atomic transaction. On any failure keep plugins disabled and inspect
        # privately before retrying. Never back up unrelated credentials here.
        self.preflight()
        for key, value in zip(KEYS, (public, secret)):
            self.config.save_env_value(key, value)
        self.config.invalidate_env_cache()
        saved = self.config.load_env()
        if any(saved.get(key) != value for key, value in zip(KEYS, (public, secret))):
            raise SetupError('Credential readback failed; keep tracing disabled.')
        if {'langfuse', 'observability/langfuse', 'homelab-langfuse-desktop'} & self.enabled():
            raise SetupError('Plugin state changed concurrently; stop and inspect privately.')


def provision(backend, prompt=getpass.getpass, verify=verify_project):
    backend.preflight()
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        public = prompt('hermes-desktop public key (hidden): ')
        secret = prompt('hermes-desktop secret key (hidden): ')
        repeat = prompt('Repeat desktop secret key (hidden): ')
    if (not re.fullmatch(r'pk-lf-[A-Za-z0-9_-]{8,250}', public)
            or not re.fullmatch(r'sk-lf-[A-Za-z0-9_-]{8,250}', secret)):
        raise SetupError('Invalid project key format; no keys saved.')
    if secret != repeat:
        raise SetupError('Secret confirmation differs; no keys saved.')
    verify(public, secret)
    backend.save(public, secret)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['--help']:
        print('Usage: setup-desktop.py homelab-scientist|default\n'
              'Private hidden prompts; verifies hermes-desktop over fixed HTTPS.\n'
              'Stores project keys via Hermes native credential writer; never enables tracing.')
        return 0
    if len(argv) != 1 or argv[0] not in PROFILES:
        print('Choose exactly homelab-scientist or default; credential arguments are forbidden.', file=sys.stderr)
        return 2
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print('Use a private interactive terminal; nothing changed.', file=sys.stderr)
        return 2
    previous = os.umask(0o077)
    try:
        provision(NativeBackend(argv[0]))
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt):
        print('Setup failed; details and keys withheld. Keep tracing disabled; '
              'a write failure may leave a partial pair. Do not retry blindly.', file=sys.stderr)
        return 1
    finally:
        os.umask(previous)
    print('Desktop project verified; credentials saved and read back. Tracing remains disabled.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
