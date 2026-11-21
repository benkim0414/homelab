"""Same-image init: verify pristine upstream bytes and render read-only overlays.

Mount no PVC or credentials in this container. The upstream image must be the
same immutable digest as the main container. Never overlay the init's source.
"""
import hashlib
import json
import os
from pathlib import Path
import re

if __package__:
    from .render import render, BASE_SHA256
else:
    from render import render, BASE_SHA256


def prepare(source_root, bundle_root, output_root):
    expected=json.loads((bundle_root/'expected.json').read_text())
    if (not isinstance(expected,dict) or set(expected)!=set(BASE_SHA256)
            or not all(isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) for v in expected.values())):
        raise ValueError('Invalid reviewed output inventory')
    outputs=render({name:(source_root/name).read_bytes() for name in BASE_SHA256})
    actual={name:hashlib.sha256(data).hexdigest() for name,data in outputs.items()}
    if actual!=expected:
        raise ValueError('Rendered bytes differ from reviewed output')
    # Validate the whole set before creating anything. Only disposable emptyDir
    # output is writable; no running-image or persistent-profile edits occur.
    for name in outputs:
        target=output_root/name
        if target.is_symlink() or target.parent.is_symlink() or output_root.is_symlink():
            raise ValueError('Overlay symlink refused')
        if target.exists() and target.read_bytes()!=outputs[name]:
            raise ValueError('Existing scratch output differs')
    for name,data in outputs.items():
        target=output_root/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
        if hashlib.sha256(target.read_bytes()).hexdigest()!=expected[name]:
            raise ValueError('Overlay verification failed')
    return actual


def main():
    actual=prepare(Path('/opt/hermes'),Path('/runtime-patch'),Path('/runtime-overlay'))
    print(json.dumps({'runtime_overlay':'verified','files':actual,'credential_access':False},sort_keys=True))


if __name__=='__main__':main()
