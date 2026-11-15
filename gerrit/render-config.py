#!/usr/bin/env python3
"""Render the Gerrit ConfigMap from reviewed source files (requires PyYAML)."""
import argparse
import hashlib
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parent
SOURCES = ('start.sh', 'gerrit.config', 'nginx.conf')


def render():
    return yaml.safe_dump({
        'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': 'gerrit-config', 'namespace': 'gerrit'},
        'data': {name: (ROOT / name).read_text() for name in SOURCES},
    }, sort_keys=False, width=1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = render()
    target = ROOT / 'configmap.yaml'
    workload = ROOT / 'statefulset.yaml'
    checksum = hashlib.sha256(b''.join((ROOT / name).read_bytes() for name in SOURCES)).hexdigest()
    old_workload = workload.read_text()
    new_workload, count = re.subn(r'(checksum/gerrit-config: )[0-9a-f]{64}',
                                 lambda match: match[1] + checksum, old_workload)
    if count != 1:
        sys.exit('Expected exactly one Gerrit workload config checksum')
    if args.check:
        if not target.exists() or target.read_text() != expected or new_workload != old_workload:
            sys.exit('Gerrit ConfigMap is stale; run gerrit/render-config.py')
        print('Gerrit ConfigMap matches source files')
    else:
        target.write_text(expected)
        workload.write_text(new_workload)
        print('Rendered gerrit/configmap.yaml')


if __name__ == '__main__':
    main()
