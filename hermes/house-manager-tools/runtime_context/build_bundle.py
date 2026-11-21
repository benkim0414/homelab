"""Build the immutable patch recipe; never vendor full upstream Python modules."""
import argparse
import hashlib
import json
from pathlib import Path
import yaml
from .render import BASE_SHA256, render

ROOT=Path(__file__).resolve().parent


class Literal(str):pass
class Dumper(yaml.SafeDumper):pass
Dumper.add_representer(Literal,lambda d,s:d.represent_scalar('tag:yaml.org,2002:str',s,style='|'))


def bundle(source_root):
    outputs=render({name:(source_root/name).read_bytes() for name in BASE_SHA256})
    expected={name:hashlib.sha256(data).hexdigest() for name,data in outputs.items()}
    data={name:(ROOT/name).read_text() for name in ('render.py','init_overlay.py')}
    data['expected.json']=json.dumps(expected,sort_keys=True,indent=2)+'\n'
    checksum=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    name='hermes-runtime-context-'+checksum[:12]
    config={'apiVersion':'v1','kind':'ConfigMap',
            'metadata':{'name':name,'namespace':'hermes','labels':{'app.kubernetes.io/part-of':'hermes'}},
            'immutable':True,'data':{key:Literal(value) for key,value in data.items()}}
    return config,{'name':name,'checksum':checksum,'output_sha256':expected}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT/'.test-state/installed')
    parser.add_argument('--output',type=Path,default=ROOT.parents[1]/'runtime-context.yaml')
    args=parser.parse_args()
    config,receipt=bundle(args.source_root)
    args.output.write_text(yaml.dump(config,Dumper=Dumper,sort_keys=False))
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
