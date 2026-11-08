#!/usr/bin/env python3
"""Download pinned verification tools into this worktree, without local secrets.

Linux x86_64 is the supported verification environment (including GitHub CI).
Network access is needed to GitHub, get.helm.sh and PyPI.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import urllib.request
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'cache'


def download(url):
    try:
        with urllib.request.urlopen(url, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # Some release-download CDN paths return 5xx while the official asset
        # API remains available. Preserve the same release/name and checksum.
        match = re.fullmatch(r'https://github.com/([^/]+)/([^/]+)/releases/download/([^/]+)/([^/]+)', url)
        if exc.code < 500 or not match:
            raise
        owner, repo, tag, asset = match.groups()
        base = f'https://api.github.com/repos/{owner}/{repo}'
        with urllib.request.urlopen(f'{base}/releases/tags/{tag}', timeout=90) as response:
            release = json.load(response)
        candidates = [a for a in release['assets']
                      if a['name'] == urllib.parse.unquote(asset)]
        if len(candidates) != 1 or not isinstance(candidates[0]['id'], int):
            raise RuntimeError('official release asset missing or ambiguous') from exc
        request = urllib.request.Request(f"{base}/releases/assets/{candidates[0]['id']}",
                                         headers={'Accept': 'application/octet-stream'})
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()


def install(name, version):
    binary = CACHE / 'bin' / name
    if binary.exists():
        return
    projects = {'kubeconform': 'yannh/kubeconform', 'conftest': 'open-policy-agent/conftest',
                'gitleaks': 'gitleaks/gitleaks', 'actionlint': 'rhysd/actionlint'}
    if name == 'helm':
        asset = f'helm-v{version}-linux-amd64.tar.gz'
        url = f'https://get.helm.sh/{asset}'
        checksums = download(url + '.sha256sum').decode()
        member = 'linux-amd64/helm'
    else:
        asset = {'kubeconform': 'kubeconform-linux-amd64.tar.gz',
                 'conftest': f'conftest_{version}_Linux_x86_64.tar.gz',
                 'gitleaks': f'gitleaks_{version}_linux_x64.tar.gz',
                 'actionlint': f'actionlint_{version}_linux_amd64.tar.gz'}[name]
        base = f'https://github.com/{projects[name]}/releases/download/v{version}'
        url = f'{base}/{asset}'
        checksum_file = {'kubeconform': 'CHECKSUMS', 'conftest': 'checksums.txt',
                         'gitleaks': f'gitleaks_{version}_checksums.txt',
                         'actionlint': f'actionlint_{version}_checksums.txt'}[name]
        checksums = download(f'{base}/{checksum_file}').decode()
        member = name
    expected = next((line.split()[0] for line in checksums.splitlines() if line.split()[-1].lstrip('*') == asset), None)
    data = download(url)
    if expected != hashlib.sha256(data).hexdigest():
        raise RuntimeError(f'{name}: checksum mismatch or checksum missing')
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError(f'{name}: executable missing in archive')
        binary.write_bytes(source.read())
    binary.chmod(0o755)
    print(f'Installed {name} {version}', flush=True)


def main():
    if platform.system() != 'Linux' or platform.machine() not in {'x86_64', 'AMD64'}:
        sys.exit('Verification bootstrap currently supports Linux x86_64 only.')
    (CACHE / 'bin').mkdir(parents=True, exist_ok=True)
    # Avoid inherited pip settings, credential stores and registry configuration.
    home = CACHE / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(home),
           'PIP_CONFIG_FILE': os.devnull, 'PIP_CACHE_DIR': str(CACHE / 'pip'), 'LANG': 'C.UTF-8'}
    venv = ROOT / 'venv'
    if not (venv / 'bin/python').exists():
        subprocess.run([sys.executable, '-m', 'venv', venv], check=True, env=env)
    subprocess.run([venv / 'bin/python', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                    '--require-hashes', '-r', ROOT / 'requirements.txt'], check=True, env=env)
    for name, version in json.loads((ROOT / 'config.json').read_text())['tools'].items():
        install(name, version)


if __name__ == '__main__':
    main()
