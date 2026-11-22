"""Capture only fixed public installed Python sources, never profile/session/auth state.

Read-only kubectl exec; all writes are local ignored fixtures. Stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

from render import BASE_SHA256

FIXTURE_SHA256 = {
    **BASE_SHA256,
    'gateway/run_inbound_hooks.py': '9cad7328d60a9335c856b65039679154558e082d0c9f6c513f1ec78acfe98202',
    'hermes_cli/plugin_session.py': '4311b653262e9bed2b73cebd23824b83d943c5df99e1aa0ee88d711f8d7efe74',
    'hermes_cli/plugin_command_dispatch.py': '4edddae7ee09357f99b1dd610d90fd3aeb737fe971e98283c5d465b05e3623cc',
    'gateway/executor_context.py': 'f6f84fc3f3a3ed63d1db2475498bca5acc68cbac74b398721882879b6c57bdfd',
}


UPSTREAM_COMMIT = 'ae2a81ccc00e9b7c06301523e5bb09608397149c'


def capture(upstream=False) -> dict[str, bytes]:
    names = [p for p in FIXTURE_SHA256 if p != 'gateway/executor_context.py'] + ['gateway/run.py']
    if upstream:
        # Public immutable dependencies work after production has an overlay,
        # without cluster/auth access. The SAME byte hashes remain mandatory.
        texts = {}
        for name in names:
            url=f'https://raw.githubusercontent.com/NousResearch/hermes-agent/{UPSTREAM_COMMIT}/{name}'
            with urllib.request.urlopen(url,timeout=30) as response:
                texts[name]=response.read().decode('utf-8')
    else:
        script = ('from pathlib import Path; import json; root=Path("/opt/hermes"); '
                  f'print(json.dumps({{p:(root/p).read_bytes().decode("utf-8") for p in {names!r}}}))')
        result = subprocess.run(['kubectl', '-n', 'hermes', 'exec', 'deploy/hermes', '-c', 'hermes',
                                 '--', 'python', '-c', script], capture_output=True, text=True, check=True)
        texts = json.loads(result.stdout)
    run = texts.pop('gateway/run.py')
    nodes = [n for n in ast.walk(ast.parse(run))
             if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_in_executor_with_context']
    if len(nodes) != 1:
        raise ValueError('installed executor definition is missing or ambiguous')
    snippet = ast.get_source_segment(run, nodes[0])
    assert snippet is not None
    texts['gateway/executor_context.py'] = snippet + '\n'
    data = {name: text.encode('utf-8') for name, text in texts.items()}
    for name, expected in FIXTURE_SHA256.items():
        if hashlib.sha256(data[name]).hexdigest() != expected:
            raise ValueError(f'fixture differs from reviewed installed source: {name}')
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=Path(__file__).parent / '.test-state/installed')
    parser.add_argument('--upstream', action='store_true', help='capture hash-pinned public commit; no cluster/auth needed')
    args = parser.parse_args()
    for name, data in capture(upstream=args.upstream).items():
        target = args.output_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f'{hashlib.sha256(data).hexdigest()}  {name}')


if __name__ == '__main__':
    main()
