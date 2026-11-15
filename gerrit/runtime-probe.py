#!/usr/bin/env python3
"""Exercise pinned, unpacked images in private rootless namespaces, never the cluster.

Run inside a bounded systemd user scope; see README.md. Images must be unpacked
with umoci --rootless, with empty /site and /config mount points (/auth for proxy).
Fixture state/logs stay in ignored verification/cache and are never production data.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, env=ENV, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    args = parser.parse_args()
    cgroup = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1].lstrip('/')
    assert int((cgroup / 'memory.max').read_text()) == 5 * 1024 ** 3
    assert (cgroup / 'memory.swap.max').read_text().strip() == '0'
    quota, period = (cgroup / 'cpu.max').read_text().split()
    assert int(quota) == 2 * int(period)
    assert int((cgroup / 'pids.max').read_text()) == 512
    fixture = args.fixture.resolve()
    fixture.mkdir(mode=0o700, parents=True, exist_ok=False)
    site, auth, clients = (fixture / n for n in ('site', 'auth', 'clients'))
    for path in (site, auth, clients):
        path.mkdir(mode=0o700)
    image = ROOT / 'verification/cache/gerrit-bundle/rootfs'
    proxy_image = ROOT / 'verification/cache/gerrit-nginx-bundle/rootfs'
    # Normalized unpack ownership is not OCI UID proof. Set the namespace UID
    # explicitly below to the actual declared Gerrit and proxy UIDs.
    for root, mounts in ((image, ('site', 'config')), (proxy_image, ('config', 'auth'))):
        for mount in mounts:
            assert (root / mount).is_dir(), f'missing prepared mount point: {mount}'
    credentials = {name: secrets.token_urlsafe(24) for name in ('lab-admin', 'lab-user')}
    hashes = []
    for name, password in credentials.items():
        hashed = run(['openssl', 'passwd', '-6', '-stdin'], input=(password + '\n').encode()).stdout.decode().strip()
        hashes.append(f'{name}:{hashed}\n')
        path = clients / name
        path.write_text(f'user = "{name}:{password}"\n')
        path.chmod(0o600)
    (auth / 'htpasswd').write_text(''.join(hashes))
    (clients / 'wrong').write_text('user = "lab-user:' + secrets.token_urlsafe(24) + '"\n')
    (clients / 'wrong').chmod(0o600)
    (auth / 'identities.conf').write_text('map $remote_user $gerrit_email {\n default "";\n lab-admin admin@gerrit.invalid;\n lab-user user@gerrit.invalid;\n}\n')
    # Separate rootless UID maps map both container UIDs to the same invoking
    # host user. Kubernetes Secret fsGroup access is checked structurally instead.
    logs = []
    processes = []
    gerrit_logs = {}
    targets = []

    def start_gerrit():
        read_fd, write_fd = os.pipe()
        log = (fixture / f'gerrit-{len(logs)}.log').open('wb')
        logs.append(log)
        command = ['bwrap', '--unshare-all', '--uid', '1000', '--gid', '1000',
                   '--cap-drop', 'ALL', '--die-with-parent', '--new-session', '--as-pid-1',
                   '--info-fd', str(write_fd), '--ro-bind', str(image), '/',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--bind', str(site), '/site', '--ro-bind', str(ROOT / 'gerrit'), '/config',
                   '--ro-bind', str(clients), '/tmp/clients', '--clearenv',
                   '--setenv', 'HOME', '/site', '--setenv', 'GERRIT_TMP', '/tmp/gerrit',
                   '--setenv', 'PATH', '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                   '--', '/bin/bash', '/config/start.sh']
        proc = subprocess.Popen(command, stdout=log, stderr=log, env=ENV, pass_fds=(write_fd,))
        processes.append(proc)
        gerrit_logs[proc] = log.name
        os.close(write_fd)
        with os.fdopen(read_fd) as info:
            data = json.load(info)
        pid = data['child-pid']
        assert Path(f'/proc/{pid}').stat().st_uid == os.getuid()
        expected = os.stat(image)
        for _ in range(100):
            actual = os.stat(f'/proc/{pid}/root')
            if (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino):
                break
            time.sleep(0.02)
        else:
            raise RuntimeError('Sandbox root identity not established')
        targets.append(pid)
        return proc, pid

    def inside(pid, command, data=None, check=True):
        assert Path(f'/proc/{pid}').stat().st_uid == os.getuid()
        actual, expected = os.stat(f'/proc/{pid}/root'), os.stat(image)
        assert (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino)
        return subprocess.run(['nsenter', '--target', str(pid), '--user', '--mount', '--net', '--pid',
                               '--root', '--wdns=/', '--preserve-credentials', '--', '/usr/bin/env', '-i',
                               'HOME=/tmp', 'PATH=/usr/bin:/bin', *command],
                              input=data, capture_output=True, check=check, env=ENV)

    def request(pid, path, user=None, method='GET', body=None, extra=()):
        command = ['/usr/bin/curl', '--silent', '--show-error', '--max-time', '15',
                   '--write-out', '\n%{http_code}', '--request', method]
        if user:
            command += ['--config', '/tmp/clients/' + user]
        command += list(extra)
        data = None
        if body is not None:
            command += ['--header', 'Content-Type: application/json', '--data-binary', '@-']
            data = json.dumps(body).encode()
        command += ['http://127.0.0.1:8080' + path]
        result = inside(pid, command, data).stdout.decode()
        content, status = result.rsplit('\n', 1)
        return int(status), content

    def api(pid, path, user='lab-admin', method='GET', body=None) -> Any:
        status, content = request(pid, path, user, method, body)
        if status not in (200, 201, 204):
            # Response errors from disposable data only; do not expose logs/keys.
            raise AssertionError(f'API {method} {path}: HTTP {status}: {content[:300]}')
        return json.loads(content.removeprefix(")]}'\n")) if content else None

    def await_backend(proc, pid):
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError('Gerrit stopped; inspect fixture log privately')
            result = inside(pid, ['/usr/bin/curl', '--fail', '--silent', '--max-time', '2',
                                  'http://127.0.0.1:8081/config/server/version'], check=False)
            if result.returncode == 0 and b'"3.14.6"' in result.stdout:
                return
            time.sleep(1)
        raise TimeoutError('Gerrit backend did not become ready')

    def start_proxy(pid):
        log = (fixture / f'proxy-{len(logs)}.log').open('wb')
        logs.append(log)
        command = ['nsenter', '--target', str(pid), '--user', '--net', '--preserve-credentials', '--',
                   '/usr/bin/bwrap', '--unshare-user', '--uid', '101', '--gid', '101',
                   '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--cap-drop', 'ALL',
                   '--die-with-parent', '--new-session', '--ro-bind', str(proxy_image), '/',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--ro-bind', str(ROOT / 'gerrit'), '/config', '--ro-bind', str(auth), '/auth',
                   '--clearenv', '--setenv', 'PATH', '/usr/sbin:/usr/bin:/sbin:/bin',
                   '--', '/usr/sbin/nginx', '-c', '/config/nginx.conf', '-g', 'daemon off;']
        proc = subprocess.Popen(command, stdout=log, stderr=log, env=ENV)
        processes.append(proc)
        for _ in range(30):
            if proc.poll() is not None:
                raise RuntimeError('Proxy stopped; inspect fixture log privately')
            try:
                if request(pid, '/')[0] == 401:
                    return proc
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.2)
        raise TimeoutError('Proxy did not become ready')

    def stop_gerrit(proc, pid):
        inside(pid, ['/bin/kill', '-TERM', '1'], check=False)
        proc.wait(timeout=120)
        # HotSpot normally exits 128+SIGTERM after running shutdown hooks.
        assert proc.returncode in (0, 143, -15), proc.returncode
        shutdown = Path(gerrit_logs[proc]).read_text()
        assert 'caught shutdown, cleaning up' in shutdown
        assert 'Stopped oejs.ServerConnector' in shutdown

    try:
        proc, pid = start_gerrit()
        await_backend(proc, pid)
        proxy = start_proxy(pid)
        assert request(pid, '/')[0] == 401
        assert request(pid, '/', 'wrong')[0] == 401
        assert request(pid, '/', extra=('--header', 'X-Gerrit-User: lab-admin'))[0] == 401
        status, _ = request(pid, '/login/', 'lab-admin')
        assert status in (200, 302), status
        admin = api(pid, '/a/accounts/self')
        assert admin['username'] == 'lab-admin'
        assert 'Administrators' in [g['name'] for g in api(pid, '/a/accounts/self/groups')]
        status, content = request(pid, '/', 'lab-admin')
        assert status == 200 and '<html' in content.lower()
        status, _ = request(pid, '/login/', 'lab-user')
        assert status in (200, 302), status
        user = api(pid, '/a/accounts/self', user='lab-user')
        assert user['username'] == 'lab-user'
        assert 'Administrators' not in [g['name'] for g in api(pid, '/a/accounts/self/groups', user='lab-user')]
        status, content = request(pid, '/a/accounts/self', 'lab-user', extra=(
            '--header', 'X-Gerrit-User: lab-admin', '--header', 'X-Gerrit-Email: admin@gerrit.invalid'))
        assert status == 200 and json.loads(content.removeprefix(")]}'\n"))['username'] == 'lab-user'
        print('PASS: private image startup, proxy authentication and identity-spoof rejection', flush=True)
        project = 'gerrit-playground'
        api(pid, '/a/projects/' + project, method='PUT', body={'create_empty_commit': True, 'branches': ['main']})
        group = api(pid, '/a/groups/Lab-Reviewers', method='PUT', body={})
        gid = group['id']
        api(pid, '/a/groups/' + gid + '/members/lab-user', method='PUT')
        # REST uses URL-encoded group id, permissions use the actual UUID.
        uuid = unquote(gid)
        api(pid, f'/a/projects/{project}/access', method='POST', body={'add': {
            'refs/heads/*': {'permissions': {
                'read': {'rules': {uuid: {'action': 'ALLOW'}}},
                'label-Code-Review': {'rules': {uuid: {'action': 'ALLOW', 'min': -2, 'max': 2}}},
                'submit': {'rules': {uuid: {'action': 'ALLOW'}}},
                'push': {'rules': {uuid: {'action': 'BLOCK'}}},
            }},
            'refs/for/refs/heads/*': {'permissions': {'push': {'rules': {uuid: {'action': 'ALLOW'}}}}},
        }})
        api(pid, f'/a/projects/{project}/submit_requirements/Code-Review', method='PUT', body={
            'submittability_expression': 'label:Code-Review=MAX AND -label:Code-Review=MIN',
            'can_override_in_child_projects': True})
        api(pid, f'/a/projects/{project}/submit_requirements/Resolved-Comments', method='PUT', body={
            'submittability_expression': '-has:unresolved'})
        shell = '''set -euo pipefail
mkdir /tmp/work
cd /tmp/work
cat > /tmp/askpass <<'ASK'
#!/bin/bash
case "$1" in *Username*) printf '%s\\n' lab-user;; *) sed -n 's/^user = "lab-user:\\(.*\\)"$/\\1/p' /tmp/clients/lab-user;; esac
ASK
chmod 700 /tmp/askpass
export GIT_ASKPASS=/tmp/askpass GIT_TERMINAL_PROMPT=0
git -c credential.helper= clone http://127.0.0.1:8080/gerrit-playground repo
cd repo
git config user.name 'Lab User'
git config user.email user@gerrit.invalid
curl --fail --silent http://127.0.0.1:8081/tools/hooks/commit-msg -o .git/hooks/commit-msg
chmod 700 .git/hooks/commit-msg
printf 'first revision\\n' > lesson.txt
git add lesson.txt
git commit -m 'Learn patch sets'
git -c credential.helper= push origin HEAD:refs/for/main
before=$(git rev-parse origin/main)
if git -c credential.helper= push origin HEAD:main >/tmp/direct-push.log 2>&1; then exit 21; fi
printf 'second revision\\n' > lesson.txt
git add lesson.txt
git commit --amend --no-edit
git -c credential.helper= push origin HEAD:refs/for/main
test "$before" = "$(git -c credential.helper= ls-remote origin refs/heads/main | cut -f1)"
'''
        inside(pid, ['/bin/bash', '-c', shell])
        changes = api(pid, '/a/changes/?q=project:gerrit-playground&o=ALL_REVISIONS', user='lab-user')
        assert len(changes) == 1 and len(changes[0]['revisions']) == 2
        change = changes[0]['_number']
        api(pid, f'/a/changes/{change}/revisions/current/review', user='lab-user', method='POST', body={
            'labels': {'Code-Review': 2},
            'comments': {'lesson.txt': [{'line': 1, 'message': 'Exercise unresolved comments', 'unresolved': True}]}})
        status, _ = request(pid, f'/a/changes/{change}/submit', 'lab-user', method='POST', body={})
        assert status == 409, status
        comments = api(pid, f'/a/changes/{change}/comments', user='lab-user')['lesson.txt']
        api(pid, f'/a/changes/{change}/revisions/current/review', user='lab-user', method='POST', body={
            'comments': {'lesson.txt': [{'line': 1, 'message': 'Resolved during walkthrough',
                                        'in_reply_to': comments[0]['id'], 'unresolved': False}]}})
        submitted = api(pid, f'/a/changes/{change}/submit', user='lab-user', method='POST', body={})
        assert submitted['status'] == 'MERGED'
        status, content = request(pid, '/plugins/gitiles/gerrit-playground/+/refs/heads/main/', 'lab-user')
        assert status == 200 and 'lesson.txt' in content
        print('PASS: non-admin clone/upload, direct-push rejection, two patch sets, comments, +2 and submit', flush=True)
        stack_shell = '''set -euo pipefail
export GIT_ASKPASS=/tmp/askpass GIT_TERMINAL_PROMPT=0
cd /tmp/work/repo
git -c credential.helper= fetch origin
git checkout -b stack origin/main
test "$(cat lesson.txt)" = 'second revision'
printf 'stack base\\n' > base.txt
git add base.txt && git commit -m 'Stack base'
printf 'dependent change\\n' > dependent.txt
git add dependent.txt && git commit -m 'Stack dependent'
git -c credential.helper= push origin HEAD:refs/for/main
old_second=$(git rev-parse HEAD)
git checkout HEAD~1
printf 'revised stack base\\n' > base.txt
git add base.txt && git commit --amend --no-edit
git cherry-pick "$old_second"
git -c credential.helper= push origin HEAD:refs/for/main
'''
        inside(pid, ['/bin/bash', '-c', stack_shell])
        stack = api(pid, '/a/changes/?q=project:gerrit-playground+status:open&o=ALL_REVISIONS', user='lab-user')
        assert len(stack) == 2 and all(len(c['revisions']) == 2 for c in stack)
        for item in sorted(stack, key=lambda c: c['_number']):
            number = item['_number']
            api(pid, f'/a/changes/{number}/revisions/current/review', user='lab-user', method='POST',
                body={'labels': {'Code-Review': 2}})
            assert api(pid, f'/a/changes/{number}/submit', user='lab-user', method='POST', body={})['status'] == 'MERGED'
        print('PASS: fetched submitted content; revised and rebased two stacked changes, then submitted in order', flush=True)
        # Test the same production start path against the same complete site.
        proxy.terminate()
        proxy.wait(timeout=10)
        stop_gerrit(proc, pid)
        proc, pid = start_gerrit()
        await_backend(proc, pid)
        proxy = start_proxy(pid)
        assert api(pid, f'/a/changes/{change}', user='lab-user')['status'] == 'MERGED'
        assert len(api(pid, f'/a/changes/{change}/comments', user='lab-user')['lesson.txt']) == 2
        assert (site / '.homelab-version').read_text().strip() == '3.14.6'
        # Image roots are mounted read-only; verify no writable root shortcut.
        assert inside(pid, ['/bin/touch', '/root-write-test'], check=False).returncode != 0
        assert inside(pid, ['/usr/bin/curl', '--silent', '--connect-timeout', '2', 'https://example.com'], check=False).returncode != 0
        print('PASS: restart preserves submitted change/review metadata; read-only root and no external network', flush=True)
        proxy.terminate()
        proxy.wait(timeout=10)
        stop_gerrit(proc, pid)
        backup = fixture / 'cold-backup'
        shutil.copytree(site, backup, symlinks=True)
        site = fixture / 'restored-site'
        shutil.copytree(backup, site, symlinks=True)
        proc, pid = start_gerrit()
        await_backend(proc, pid)
        proxy = start_proxy(pid)
        restored = api(pid, '/a/changes/?q=project:gerrit-playground+status:merged', user='lab-user')
        assert len(restored) == 3
        assert len(api(pid, f'/a/changes/{change}/comments', user='lab-user')['lesson.txt']) == 2
        print('PASS: isolated cold-backup restore preserves all three merged changes and review comments', flush=True)
        events = dict(line.split() for line in (cgroup / 'memory.events').read_text().splitlines())
        assert events['oom'] == '0' and events['oom_kill'] == '0'
        peak = int((cgroup / 'memory.peak').read_text())
        (fixture / 'result.json').write_text(json.dumps({'status': 'passed', 'version': '3.14.6',
            'change': change, 'patch_sets': 2, 'restart_preserved': True,
            'stacked_changes': 2, 'cold_restore_verified': True,
            'scope_memory_peak_bytes': peak, 'scope_oom_events': 0}, indent=2) + '\n')
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
