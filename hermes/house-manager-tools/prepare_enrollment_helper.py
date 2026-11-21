"""Install only the reviewed private enrollment helper, without activating it."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
DESTINATION = '/opt/data/house-manager-tools/enroll_chat_approver.py'
REMOTE = r'''
import base64,hashlib,json,os,sys,shutil
from datetime import datetime,timezone
from pathlib import Path
payload=json.load(sys.stdin)
data=base64.b64decode(payload['source'],validate=True)
assert hashlib.sha256(data).hexdigest()==payload['sha256']
compile(data,'enroll_chat_approver.py','exec')
root=Path('/opt/data/house-manager-tools')
assert root.is_dir() and not root.is_symlink()
p=root/'enroll_chat_approver.py'
assert not p.is_symlink()
backup=None
if p.exists():
    actual=hashlib.sha256(p.read_bytes()).hexdigest()
    if actual!=payload['sha256']:
        assert actual==payload.get('replace_reviewed_sha256'), 'existing helper drift'
        backup=Path('/opt/data/profiles/house-manager/.chat-approval-helper-backups')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        backup.mkdir(parents=True,mode=0o700,exist_ok=False)
        shutil.copy2(p,backup/p.name)
        temporary=root/'enroll_chat_approver.reviewed-new.py'
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chown(temporary,0,10000)
        os.replace(temporary,p)
else:
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.chown(p,0,10000)
assert hashlib.sha256(p.read_bytes()).hexdigest()==payload['sha256']
print(json.dumps({'path':str(p),'sha256':payload['sha256'],'activated':False,'credential_access':False,'source_backup':str(backup) if backup else None}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-reviewed-sha256')
    args=parser.parse_args()
    data=(ROOT/'enroll_chat_approver.py').read_bytes()
    payload={'source':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest(),
             'replace_reviewed_sha256':args.replace_reviewed_sha256}
    result=subprocess.run(['kubectl','-n','hermes','exec','-i','deploy/hermes','--','python','-c',REMOTE],input=json.dumps(payload),capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError('Enrollment helper install failed; no credential data requested')
    print(json.dumps(json.loads(result.stdout),sort_keys=True))


if __name__=='__main__':main()
