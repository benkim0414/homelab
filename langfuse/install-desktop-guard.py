#!/usr/bin/env python3
"""Install reviewed local guard assets only; never enable plugins or touch keys."""
import ast
import json
import os
from pathlib import Path

import stat
import sys
import tempfile

NAME = 'homelab-langfuse-desktop'
PROFILES = ('homelab-scientist', 'default')


def checked_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Expected an owned nonsymlink directory')


def source_assets(source):
    checked_directory(source)
    assets = {}
    for path in source.iterdir():
        if path.name == '__pycache__':
            continue
        if not stat.S_ISREG(path.lstat().st_mode) or (path.suffix not in ('.py', '.yaml') and path.name != 'README.md'):
            raise ValueError('Unexpected plugin asset')
        data = path.read_bytes()
        if path.suffix == '.py':
            ast.parse(data)
        assets[path.name] = data
    if not {'__init__.py', 'plugin.yaml'} <= set(assets):
        raise ValueError('Incomplete plugin source')
    return assets


def install(source, home):
    assets = source_assets(source)
    checked_directory(home)
    plugins = home / 'plugins'
    plugins.mkdir(mode=0o700, exist_ok=True)
    checked_directory(plugins)
    target = plugins / NAME
    if target.exists() or target.is_symlink():
        checked_directory(target)
        if source_assets(target) != assets:
            raise ValueError('Existing guard differs; refusing replacement')
        return target
    # Stage outside the discovery root. No credentials are read or copied.
    with tempfile.TemporaryDirectory(prefix='.langfuse-guard-stage-', dir=home) as stage:
        stage_path = Path(stage)
        for name, content in assets.items():
            path = stage_path / name
            with path.open('xb') as output:
                os.chmod(path, 0o600)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        if target.exists() or target.is_symlink():
            raise ValueError('Concurrent installation detected')
        os.rename(stage_path, target)
        # TemporaryDirectory's original staging name no longer exists.
    if source_assets(target) != assets:
        raise ValueError('Installed asset readback differs')
    return target


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['--help']:
        print('Usage: install-desktop-guard.py homelab-scientist|default\n'
              'Copies only local guard code; never enables plugins or reads keys.')
        return 0
    if len(argv) != 1 or argv[0] not in PROFILES:
        print('Choose exactly homelab-scientist or default.', file=sys.stderr)
        return 2
    previous = os.umask(0o077)
    try:
        root = Path(sys.prefix).parent
        if not (root / 'hermes_cli/profiles.py').is_file():
            raise ValueError('Use the inspected Hermes interpreter')
        sys.path.insert(0, str(root))
        from hermes_cli.profiles import resolve_profile_env
        home = Path(resolve_profile_env(argv[0]))
        source = Path(__file__).absolute().parent / 'plugins' / NAME
        target = install(source, home)
        print(json.dumps({'profile': argv[0], 'installed': NAME,
                          'assetsVerified': True, 'activationChanged': False}))
    except Exception:
        print('Guard installation failed; details withheld. No credentials or '
              'plugin configuration changed. Inspect task-owned guard files before retrying.', file=sys.stderr)
        return 1
    finally:
        os.umask(previous)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
