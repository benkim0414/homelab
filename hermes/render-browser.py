"""Regenerate the browser ConfigMap and rollout checksums from reviewed sources."""
import hashlib
from pathlib import Path

import yaml


class Literal(str):
    pass


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(Literal, lambda d, s: d.represent_scalar('tag:yaml.org,2002:str', s, style='|'))
root = Path(__file__).resolve().parents[1]
source = (root / 'hermes/browser-server.py').read_bytes()
config = {
    'apiVersion': 'v1', 'kind': 'ConfigMap',
    'metadata': {'name': 'hermes-browser', 'namespace': 'hermes'},
    'data': {'browser-server.py': Literal(source.decode())},
}
(root / 'hermes/browser-configmap.yaml').write_text(yaml.dump(config, Dumper=Dumper, sort_keys=False))
path = root / 'hermes/browser.yaml'
resources = list(yaml.safe_load_all(path.read_text()))
annotations = resources[0]['spec']['template']['metadata'].setdefault('annotations', {})
annotations['checksum/server'] = hashlib.sha256(source).hexdigest()
profile = root / 'k3s-ansible/files/hermes-browser-amd64.json'
annotations['checksum/seccomp'] = hashlib.sha256(profile.read_bytes()).hexdigest()
path.write_text(yaml.safe_dump_all(resources, sort_keys=False))
