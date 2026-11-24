"""Check a review-only strategic merge patch. Never contact a cluster or registry."""
import argparse
import copy
import fnmatch
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
IMAGE_PLACEHOLDER='__PUBLISHED_IMAGE_DIGEST_REQUIRED__'
IMAGE_REPOSITORY='ghcr.io/benkim0414/hindsight-specialist-memory'
NEW_KEY_FIELDS=('LEARNING_COACH_API_KEY','CAREER_ADVISOR_API_KEY',
                'OPERATOR_LEARNING_COACH_API_KEY','OPERATOR_CAREER_ADVISOR_API_KEY')
RELEASE_GATES=('published_image_digest','sealed_credentials','legacy_live_metadata',
               'backup_restore_evidence','reviewed_startup_migrations',
               'production_provider_compatibility','reviewed_manual_sync_and_rollback')
BASELINE='c2dbb6eed77fe85d414597880161a05283957fb1'
ACTIVE_PATHS=('hindsight/api.yaml','hindsight/postgresql.yaml','hindsight/storage.yaml',
              'hindsight/values.yaml','argocd/apps/hindsight.yaml',
              'hindsight/initialize-bank-job.yaml','hindsight/pg-backup-cronjob.yaml')


def baseline_matches():
    return subprocess.run(['git','diff','--quiet',BASELINE,'--',*ACTIVE_PATHS],cwd=ROOT,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          timeout=10,check=False).returncode==0


def _require(value):
    if not value:raise ValueError('proposal differs from the bounded reviewed scope')


def read_patch():
    return json.loads((HERE/'deployment-patch.json.template').read_text())


def _expected_env():
    def ref(name,key):
        return {'valueFrom':{'secretKeyRef':{'name':name,'key':key,'optional':False}}}
    result={
        'HINDSIGHT_API_TENANT_EXTENSION':{'value':'homelab_hindsight_specialists:SpecialistTenantExtension'},
        'HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION':{'value':'homelab_hindsight_specialists:SpecialistOperationValidator'},
        'HINDSIGHT_API_DATABASE_SCHEMA':{'value':'public'},
        'HINDSIGHT_API_OPERATION_VALIDATOR_API_KEY':ref('hindsight-api-credentials','HINDSIGHT_API_TENANT_API_KEY')}
    for prefix in ('HINDSIGHT_API_TENANT_','HINDSIGHT_API_OPERATION_VALIDATOR_'):
        for suffix in NEW_KEY_FIELDS:
            result[prefix+suffix]=ref('hindsight-specialist-memory-credentials',suffix)
    return result


def check_patch(patch):
    _require(isinstance(patch,dict) and set(patch)=={'apiVersion','kind','metadata','spec'})
    _require(patch['apiVersion']=='apps/v1' and patch['kind']=='Deployment')
    _require(patch['metadata']=={'name':'hindsight-api','namespace':'hindsight'})
    _require(set(patch['spec'])=={'template'} and set(patch['spec']['template'])=={'spec'})
    pod=patch['spec']['template']['spec'];_require(set(pod)=={'containers'})
    _require(isinstance(pod['containers'],list) and len(pod['containers'])==1)
    container=pod['containers'][0]
    _require(set(container)=={'name','image','command','env'} and container['name']=='api')
    _require(container['command']==['/app/api/.venv/bin/hindsight-specialist-api'])
    _require(container['image']==IMAGE_PLACEHOLDER)
    env=container['env'];_require(isinstance(env,list))
    _require(all(isinstance(e,dict) and isinstance(e.get('name'),str) for e in env))
    _require(len({e['name'] for e in env})==len(env))
    actual={e['name']:{k:v for k,v in e.items() if k!='name'} for e in env}
    _require(actual==_expected_env())
    return True


def check():
    import yaml
    _require(baseline_matches())
    patch=read_patch();check_patch(patch)
    objects=list(yaml.safe_load_all((ROOT/'hindsight/api.yaml').read_text()))
    deployment=next(x for x in objects if x['kind']=='Deployment')
    _require(deployment['metadata']==patch['metadata'])
    _require(deployment['spec']['replicas']==1 and deployment['spec']['strategy']=={'type':'Recreate'})
    api=next(x for x in deployment['spec']['template']['spec']['containers'] if x['name']=='api')
    env={x['name']:x for x in api['env']}
    _require(env['HINDSIGHT_API_TENANT_EXTENSION'].get('value')=='hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension')
    _require(env['HINDSIGHT_API_TENANT_API_KEY']['valueFrom']['secretKeyRef']==
             {'name':'hindsight-api-credentials','key':'HINDSIGHT_API_TENANT_API_KEY'})
    _require(env.get('HINDSIGHT_API_DATABASE_SCHEMA',{'value':'public'}).get('value')=='public')
    app=yaml.safe_load((ROOT/'argocd/apps/hindsight.yaml').read_text())
    _require('automated' not in app['spec']['syncPolicy'])
    source=next(s for s in app['spec']['sources'] if s.get('path')=='hindsight')
    include=source['directory']['include']
    _require(include.startswith('{') and include.endswith('}'))
    patterns=include[1:-1].split(',')
    relative='proposals/specialist-memory/deployment-patch.json.template'
    _require(not any(fnmatch.fnmatch(relative,p) for p in patterns))
    _require(any(fnmatch.fnmatch('api.yaml',p) for p in patterns))
    values=yaml.safe_load((ROOT/'hindsight/values.yaml').read_text())
    _require(values['api']['enabled'] is False and values['worker']['enabled'] is False)
    return {'status':'DRAFT_BLOCKED','deployable':False,'active_manifest_unchanged':True,
            'excluded_from_argocd':True,'proposed_schema':'public','release_gates':list(RELEASE_GATES),
            'changes':[{'field':'image','proposed':IMAGE_PLACEHOLDER},
                       {'field':'command','proposed':['/app/api/.venv/bin/hindsight-specialist-api']},
                       *[{'field':'env/'+k,'proposed':v} for k,v in _expected_env().items()]]}


def materialize(image):
    check()
    _require(isinstance(image,str) and re.fullmatch(re.escape(IMAGE_REPOSITORY)+r'@sha256:[0-9a-f]{64}',image))
    # Shape validation is not proof of publication, platform coverage or approval.
    result=copy.deepcopy(read_patch())
    result['spec']['template']['spec']['containers'][0]['image']=image
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='report structural checks and unresolved release gates')
    args=parser.parse_args()
    print(json.dumps(check(),indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
