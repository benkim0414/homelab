"""Probe the exact overlay recipe in the running image, using disposable scratch.

No rollout, profile reads, credential access, image edits or persistent writes.
The remote subprocess has an empty environment and runs as the Hermes user.
This verifies image compatibility, NOT actual chat UI behavior.
"""
import argparse
import json
from pathlib import Path
import subprocess

from .build_bundle import bundle

ROOT = Path(__file__).resolve().parent
REMOTE = r'''
import hashlib,json,sys,tempfile,types
from pathlib import Path
payload=json.load(sys.stdin)
assert set(payload)=={'render.py','init_overlay.py','expected.json'}
renderer=types.ModuleType('render')
renderer.__package__=''
sys.modules['render']=renderer
exec(compile(payload['render.py'],'reviewed/render.py','exec'),renderer.__dict__)
initializer=types.ModuleType('overlay_probe')
initializer.__package__=''
exec(compile(payload['init_overlay.py'],'reviewed/init_overlay.py','exec'),initializer.__dict__)
with tempfile.TemporaryDirectory(prefix='house-manager-overlay-',dir='/tmp') as directory:
    root=Path(directory)
    recipe=root/'recipe'
    recipe.mkdir()
    for name,data in payload.items():
        (recipe/name).write_text(data)
    output=root/'output'
    first=initializer.prepare(Path('/opt/hermes'),recipe,output)
    assert initializer.prepare(Path('/opt/hermes'),recipe,output)==first
    for name,digest in first.items():
        data=(output/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==digest
        assert (output/name).stat().st_mode & 0o777 == 0o444
        compile(data,name,'exec')
print(json.dumps({'runtime_image_probe':'PASS','module_count':len(first),
    'output_sha256':first,'originals_verified':True,'init_idempotent':True,
    'credential_access':False,'persistent_writes':False,'restart':False,
    'scope':'five-module-render-init-compile-not-import-or-UI-acceptance'},sort_keys=True))
'''


def probe(source_root):
    config, receipt = bundle(source_root)
    command = ['kubectl', '-n', 'hermes', 'exec', '-i', 'deployment/hermes', '-c',
               'hermes', '--', '/command/s6-setuidgid', 'hermes', 'env', '-i',
               'PATH=/usr/local/bin:/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE=1',
               '/opt/hermes/.venv/bin/python', '-c', REMOTE]
    result = subprocess.run(command, input=json.dumps(config['data']), text=True,
                            capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Image scratch probe failed; no rollout was requested')
    observed = json.loads(result.stdout)
    if (observed.get('runtime_image_probe') != 'PASS'
            or observed.get('output_sha256') != receipt['output_sha256']):
        raise RuntimeError('Image scratch probe receipt mismatch')
    return dict(observed, configmap=receipt['name'], checksum=receipt['checksum'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT/'.test-state/installed')
    args = parser.parse_args()
    print(json.dumps(probe(args.source_root), sort_keys=True))


if __name__ == '__main__':
    main()
