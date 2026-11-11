#!/usr/bin/env python3
"""Prepare local Git changes AFTER restore verification; never contact the cluster.

Run in a clean task worktree, review the diff, validate, commit and obtain merge /
maintenance approval. This program cannot establish that a restore succeeded.
"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def changes(root):
    edits = {
        'immich/postgresql.yaml': [
            ('  replicas: 1', '  replicas: 0'),
            ('  selector:\n    app: immich-postgres\n', '  selector:\n    app: immich-postgres16\n'),
        ],
        'immich/postgresql16.yaml': [('  replicas: 0', '  replicas: 1')],
        'immich/pg-backup-cronjob.yaml': [('postgres:14-', 'postgres:16-')],
        'renovate.json5': [
            ('Preserve Immich PostgreSQL 14 and its vector extension variant',
             'Preserve Immich PostgreSQL 16 and its vector extension variant'),
            ('/^14(?:', '/^16(?:'),
            ('Freeze the prepared Immich PostgreSQL 16 migration target',
             'Freeze the retained Immich PostgreSQL 14 rollback workload'),
            ('["immich/postgresql16.yaml", "immich/migration/**"]',
             '["immich/postgresql.yaml", "immich/migration/**"]'),
        ],
    }
    result = {}
    for name, replacements in edits.items():
        text = (root / name).read_text()
        for old, new in replacements:
            if text.count(old) != 1:
                raise ValueError(f'{name}: expected exactly one {old!r}; no files written')
            text = text.replace(old, new, 1)
        result[name] = text
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-verified', action='store_true', required=True)
    parser.parse_args()
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    if status.strip():
        raise SystemExit('Use a clean dedicated task worktree; preserve existing work first.')
    try:
        prepared = changes(ROOT)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    for name, text in prepared.items():
        (ROOT / name).write_text(text)
    print('Local cutover changes prepared. Review and validate; nothing deployed.')


if __name__ == '__main__':
    main()
