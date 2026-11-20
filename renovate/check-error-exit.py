#!/usr/bin/env python3
"""Exercise real Renovate error exits with an isolated, credential-free fixture.

Usage: python3 renovate/check-error-exit.py /absolute/path/to/renovate
The reserved .invalid registry deliberately fails; no GitHub writes occur.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check(binary):
    binary = str(Path(binary).absolute())
    results = []
    with tempfile.TemporaryDirectory(prefix='renovate-exit-fixture-') as temporary:
        root = Path(temporary)
        repo = root / 'repo'
        repo.mkdir()
        home = root / 'home'
        home.mkdir()
        env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'LANG': 'C.UTF-8',
               'LOG_FORMAT': 'json', 'LOG_LEVEL': 'debug',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'}
        (repo / 'deployment.yaml').write_text('''apiVersion: apps/v1
kind: Deployment
metadata:
  name: synthetic-error-fixture
spec:
  template:
    spec:
      containers:
        - name: fixture
          image: renovate-failure.invalid/fixture:1.0.0
''')
        for args in [['init', '-b', 'main'], ['add', 'deployment.yaml'],
                     ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-m', 'Synthetic fixture']]:
            subprocess.run(['git', *args], cwd=repo, env=env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for enabled in [False, True]:
            config = {
                'platform': 'local', 'dryRun': 'lookup', 'onboarding': False,
                'requireConfig': 'ignored', 'exitCodeForErrors': enabled,
                'cacheDir': str(root / ('cache-' + str(enabled))),
                'enabledManagers': ['kubernetes'],
                'kubernetes': {'managerFilePatterns': ['/^deployment\\.yaml$/']},
                'hostRules': [{'hostType': 'docker',
                               'matchHost': 'renovate-failure.invalid',
                               'abortOnError': True, 'timeout': 1000}],
            }
            config_path = root / 'config.json'
            config_path.write_text(json.dumps(config))
            run = subprocess.run([binary], cwd=repo,
                                 env={**env, 'RENOVATE_CONFIG_FILE': str(config_path)},
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, timeout=90)
            events = []
            for line in run.stdout.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
            finished = [e for e in events if e.get('msg') == 'Repository finished']
            if len(finished) != 1:
                raise RuntimeError('Fixture did not complete repository processing')
            event = finished[0]
            result = {'exitCodeForErrors': enabled, 'processExit': run.returncode,
                      'repositoryResult': event.get('result'),
                      'repositoryExit': event.get('exitCode')}
            results.append(result)
            if event.get('result') != 'external-host-error' or event.get('exitCode') != 7:
                raise RuntimeError('Fixture failed for an unexpected reason: ' + json.dumps(result))
            if run.returncode != (7 if enabled else 0):
                raise RuntimeError('Incorrect process error propagation: ' + json.dumps(result))
    print(json.dumps({'verified': True, 'results': results}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Provide the absolute path to the pinned Renovate executable')
    check(sys.argv[1])
