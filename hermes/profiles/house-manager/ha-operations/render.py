"""Render broker including mandatory HA config-check gate; require non-secret bot ID."""
import argparse
import hashlib
from pathlib import Path
import re
import sys

import yaml

HERE = Path(__file__).resolve().parent


def render(bot_id):
    if re.fullmatch('[0-9a-f]{32}', bot_id) is None:
        raise ValueError('Exact HA bot user ID required (not a token)')
    source = (HERE / 'broker.py').read_text()
    resources = list(yaml.safe_load_all((HERE / 'resources.yaml.in').read_text()))
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap',
              'metadata': {'name': 'ha-operations', 'namespace': 'hermes'},
              'data': {'broker.py': source}}
    for item in resources:
        if item['kind'] == 'Deployment':
            template = item['spec']['template']
            template['metadata']['annotations'] = {
                'checksum/source': hashlib.sha256(source.encode()).hexdigest()}
            template['spec']['containers'][0]['env'][0]['value'] = bot_id
    # Policies precede workload creation; caller must still stage live acceptance.
    resources.insert(-1, config)
    return resources


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bot-user-id', required=True)
    args = parser.parse_args()
    yaml.safe_dump_all(render(args.bot_user_id), sys.stdout, sort_keys=False)
