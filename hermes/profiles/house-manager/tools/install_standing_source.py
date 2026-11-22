#!/usr/bin/env python3
"""Task-scoped PVC source installer; check-only unless --apply. Never restarts HA.

Preserves credentials, automations, configuration values and storage identities.
Only inserts the reviewed non-secret boolean setting into the existing HA include.
Does not publish Git, deploy the broker, or change Hermes configuration/toolsets.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
# Pin the pre-activation source: committing this installer must not silently
# change which deployed baseline it is willing to replace.
BASELINE_REF = '074c76df1dafed3ca3b42086a76ea0cab7554343'
COMPONENT = HERE / 'custom_components/house_manager_general'
NAMES = ('__init__.py','chat.py','discord.py','engine.py','native.py','policy.py',
         'runtime.py','manifest.json')

SETTING_HELPER = r'''
def enable_standing(source):
 import yaml
 node=yaml.compose(source)
 assert isinstance(node,yaml.MappingNode),'settings must be a mapping'
 assert 'standing_permissions' not in [key.value for key,value in node.value],'setting already present'
 if node.flow_style:
  index=node.end_mark.index-1
  assert source[index]=='}','unsupported inline mapping'
  updated=source[:index]+', "standing_permissions": true'+source[index:]
 else:
  index=node.end_mark.index
  updated=source[:index]+'\nstanding_permissions: true\n'+source[index:]
 result=yaml.compose(updated)
 assert [(v.tag,v.value) for k,v in result.value if k.value=='standing_permissions']==[('tag:yaml.org,2002:bool','true')]
 return updated
'''

REMOTE_HA = SETTING_HELPER + r'''
import base64,hashlib,json,os,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
import yaml
p=json.load(sys.stdin)
root=Path('/config/custom_components/house_manager_general')
settings=Path('/config/house_manager_general.private.yaml')
updated_settings=enable_standing(settings.read_text())
for name,digest in p['expected'].items():
 assert name in ('__init__.py','chat.py','discord.py','engine.py','native.py','policy.py','runtime.py','manifest.json')
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,'source drift; stop'
assert not (root/'management.py').exists(),'management source already present; stop'
for name,encoded in p['files'].items():
 data=base64.b64decode(encoded,validate=True)
 if name.endswith('.py'): compile(data,str(root/name),'exec')
print(json.dumps({'baseline_verified':True,'apply':p['apply'],'files':list(p['files'])}))
if not p['apply']:sys.exit(0)
os.umask(0o077)
backup=Path('/config/.house-manager-standing-backups')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup.mkdir(parents=True,mode=0o700)
shutil.copytree(root,backup/'source')
ledger=Path('/config/.storage/house_manager_general.ledger')
if ledger.exists():shutil.copy2(ledger,backup/'ledger-observation.json')
# Ledger snapshot is observation only: NEVER restore it over newer receipts.
for name,encoded in p['files'].items():
 data=base64.b64decode(encoded,validate=True)
 temp=root/(name+'.standing-new')
 with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.chmod(temp,0o600);os.replace(temp,root/name)
st=settings.stat()
temp=settings.with_name(settings.name+'.standing-new')
fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,st.st_mode&0o777)
with os.fdopen(fd,'w') as f:
 f.write(updated_settings);f.flush();os.fsync(f.fileno())
os.chown(temp,st.st_uid,st.st_gid);os.replace(temp,settings)
assert settings.read_text()==updated_settings
for name,encoded in p['files'].items():
 assert (root/name).read_bytes()==base64.b64decode(encoded,validate=True)
assert (backup/'source/engine.py').is_file()
print(json.dumps({'source_readback_verified':True,'setting_enabled_on_disk':True,'backup':str(backup),'restart_performed':False}))
'''

REMOTE_PROFILE = r'''
import base64,hashlib,json,os,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
p=json.load(sys.stdin)
root=Path('/opt/data/profiles/house-manager')
connector=Path('/opt/data/house-manager-tools/general_connector_v3.py')
assert hashlib.sha256(connector.read_bytes()).hexdigest()==p['expected']['connector'],'connector drift; stop'
for name,encoded in p['files'].items():
 data=base64.b64decode(encoded,validate=True)
 if name=='connector':compile(data,str(connector),'exec')
print(json.dumps({'baseline_verified':True,'apply':p['apply'],'files':list(p['files'])}))
if not p['apply']:sys.exit(0)
os.umask(0o077)
backup=root/'.house-manager-standing-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup.mkdir(parents=True,mode=0o700)
shutil.copy2(connector,backup/'general_connector_v3.py')
shutil.copy2(root/'SOUL.md',backup/'SOUL.md')
for name,target in [('connector',connector),('soul',root/'SOUL.md')]:
 data=base64.b64decode(p['files'][name],validate=True)
 temp=target.with_name(target.name+'.standing-new')
 with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.chmod(temp,0o600);os.replace(temp,target)
 assert target.read_bytes()==data
print(json.dumps({'source_readback_verified':True,'backup':str(backup),'fresh_session_required':True}))
'''


def git_baseline(path):
    result = subprocess.run(['git','show',BASELINE_REF+':'+str(path.relative_to(ROOT))],
                            cwd=ROOT,check=True,capture_output=True)
    return hashlib.sha256(result.stdout).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',choices=('ha','profile'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.target=='ha':
        expected={name:git_baseline(COMPONENT/name) for name in NAMES}
        files={name:(COMPONENT/name).read_bytes() for name in NAMES+('management.py',)}
        command=['kubectl','-n','home-assistant','exec','-i','home-assistant-0','-c','home-assistant',
                 '--','python','-c',REMOTE_HA]
    else:
        expected={'connector':git_baseline(HERE/'general_connector_v3.py')}
        files={'connector':(HERE/'general_connector_v3.py').read_bytes(),
               'soul':(HERE.parent/'SOUL-STANDING.md').read_bytes()}
        command=['kubectl','-n','hermes','exec','-i','deployment/hermes','-c','hermes','--',
                 '/command/s6-setuidgid','hermes','/opt/hermes/.venv/bin/python','-c',REMOTE_PROFILE]
    payload={'apply':args.apply,'expected':expected,
             'files':{name:base64.b64encode(data).decode() for name,data in files.items()}}
    subprocess.run(command,input=json.dumps(payload),text=True,check=True)


if __name__=='__main__':
    main()
