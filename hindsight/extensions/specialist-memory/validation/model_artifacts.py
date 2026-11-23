"""Download only hash-pinned public BGE ONNX/tokenizer data, never model code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import urllib.request

MODEL_ID = 'BAAI/bge-small-en-v1.5'
REVISION = '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'
# Published revision metadata: LFS sha256 for ONNX; Git blob SHA1 otherwise.
FILES = {
    'config.json': (743, 'git-sha1', '3992bf890728a92476c700e6e657fd696eb94160'),
    'onnx/model.onnx': (133093490, 'sha256', '828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35'),
    'special_tokens_map.json': (125, 'git-sha1', 'a8b3208c2884c4efb86e49300fdd3dc877220cdf'),
    'tokenizer.json': (711396, 'git-sha1', '688882a79f44442ddc1f60d70334a7ff5df0fb47'),
    'tokenizer_config.json': (366, 'git-sha1', '37fca74771bc76a8e01178ce3a6055a0995f8093'),
    'vocab.txt': (231508, 'git-sha1', 'fb140275c155a9c7c5a3b3e0e77a9e839594a938'),
}


def verify_file(path, size, kind, expected):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            return False
        digest = hashlib.sha256() if kind == 'sha256' else hashlib.sha1()
        if kind == 'git-sha1':
            digest.update(b'blob '+str(size).encode()+b'\0')
        with path.open('rb') as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == expected
    except OSError:
        return False


def prepare(directory):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('invalid artifact directory')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, (size, kind, expected) in FILES.items():
        path = directory / name
        if path.exists() or path.is_symlink():
            if not verify_file(path, size, kind, expected):
                raise ValueError('existing artifact integrity mismatch')
            continue
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise ValueError('invalid artifact parent')
        partial = path.with_name(path.name+'.partial')
        # Retain failed partial downloads. Never overwrite or relabel one accepted.
        with partial.open('xb') as output:
            request = urllib.request.Request(f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}')
            with urllib.request.urlopen(request, timeout=30) as response:
                count = 0
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > size:
                        raise ValueError('artifact byte limit exceeded')
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not verify_file(partial, size, kind, expected):
            raise ValueError('downloaded artifact integrity mismatch')
        partial.rename(path)
    return {'model_id': MODEL_ID, 'revision': REVISION, 'verified_files': len(FILES)}


def main():
    parser = argparse.ArgumentParser(description='Prepare pinned public ONNX model data for isolated validation')
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.directory)
    except Exception as error:
        # Do not print redirect URLs, headers, auth material or exception messages.
        print(json.dumps({'passed':False, 'stage':'public-model-preparation', 'error_type':type(error).__name__}))
        return 1
    print(json.dumps({'passed':True, **result}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
