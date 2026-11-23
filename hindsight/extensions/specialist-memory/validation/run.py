"""One-shot LOCAL packaged acceptance. No production credentials or services.

Run with the dedicated native dependency interpreter. --sudo applies only to
fixed Docker commands, never to this Python process. Image build logs contain
only public build inputs. Service containers use the none log driver.
"""
import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from docker_resources import DockerResources, LABEL
from fixture_env import DATABASE_IMAGE, DATABASE_PASSWORD, environment
from model_artifacts import FILES, verify_file

ROOT = HERE.parents[3]
PACKAGE = HERE.parent
MODELS = ROOT / 'verification/cache/specialist-models/bge-small-en-v1.5-5c38ec7'
IMAGE_PYTHON = '/app/api/.venv/bin/python'
MODULES = ('__init__.py','ingress.py','server.py')
SCHEMAS = ('public','user_learning_coach','user_career_advisor')
TABLES = ('banks','documents','chunks','memory_units','entities','unit_entities')
CHECKS = ('model_integrity','image_owned_code','api_nonroot','native_no_llm_config',
          'isolated_network','tenant_schemas','positive_client','database_fixture_rows','negative_client',
          'persisted_content_unchanged','zero_observations','cleanup')


class Failure(RuntimeError):
    def __init__(self, stage, code=None):
        super().__init__(stage)
        self.stage, self.code = stage, code


def _terminal_success(report):
    return isinstance(report,dict) and report.get('stage')=='complete' and 'error' not in report


def acceptance_is_valid(report):
    if not (_terminal_success(report) and report.get('passed') is True
            and isinstance(report.get('checks'),dict) and set(report['checks'])==set(CHECKS)
            and all(v is True for v in report['checks'].values())):
        return False
    from client import report_is_valid
    return report_is_valid(report.get('positive'),'positive') and report_is_valid(report.get('denials'),'denials')


def choose_subnet(routes, used):
    occupied = [ipaddress.ip_network(x,strict=False) for x in (*routes,*used) if x not in ('default','0.0.0.0/0')]
    for pool in ('172.30.200.0/21','10.254.240.0/20'):
        for candidate in ipaddress.ip_network(pool,strict=False).subnets(new_prefix=28):
            if not any(candidate.overlaps(other) for other in occupied if other.version==4):
                return str(candidate)
    raise ValueError('no nonoverlapping private fixture subnet')


class Docker:
    def __init__(self, sudo, command):
        self.prefix = (['sudo','-n'] if sudo else []) + ['/usr/bin/docker']
        self.command = command

    def __call__(self, args, timeout=60, log=None):
        if log is None:
            return self.command(self.prefix+list(args),capture_output=True,text=True,timeout=timeout,check=False)
        with log.open('w') as output:
            return self.command(self.prefix+list(args),stdout=output,stderr=subprocess.STDOUT,
                                text=True,timeout=timeout,check=False)

    def checked(self, stage, args, timeout=60, log=None):
        result = self(args,timeout=timeout,log=log)
        if result.returncode != 0:
            raise Failure(stage,result.returncode)
        return result.stdout or ''

    def json(self,stage,args):
        return json.loads(self.checked(stage,args))

    def image_id(self,reference):
        value = self.json('image-identity',['image','inspect','--format','{{json .Id}}',reference])
        if not isinstance(value,str) or not re.fullmatch('sha256:[0-9a-f]{64}',value):
            raise Failure('image-identity')
        return value


def fixture_rows_match(snapshot):
    """Require real database rows, not a vacuous equality of empty snapshots."""
    from client import RECORDS
    if not isinstance(snapshot,dict) or set(snapshot)!=set(SCHEMAS):return False
    for record in RECORDS:
        state=snapshot.get(record['schema'])
        if not isinstance(state,dict):return False
        documents,units=state.get('documents'),state.get('memory_units')
        if not isinstance(documents,list) or len(documents)!=1 or not isinstance(units,list):return False
        document=documents[0]
        if (not isinstance(document,dict) or document.get('id')!=record['document']
                or document.get('bank_id')!=record['bank'] or document.get('original_text')!=record['text']
                or not document.get('content_hash')):return False
        if not any(isinstance(unit,dict) and unit.get('id') and unit.get('fact_type')=='world'
                   and unit.get('document_id')==record['document'] and unit.get('bank_id')==record['bank']
                   and unit.get('text')==record['text'] for unit in units):return False
    return True


def _models():
    for name,(size,kind,digest) in FILES.items():
        if not verify_file(MODELS/name,size,kind,digest):
            raise Failure('model-integrity')


def _freeze(destination):
    names = ['Dockerfile','.dockerignore','pyproject.toml'] + ['src/homelab_hindsight_specialists/'+n for n in MODULES]
    for name in names:
        source = PACKAGE/name
        if source.is_symlink() or not source.is_file():
            raise Failure('build-context')
        target = destination/name
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        shutil.copy2(source,target)
    return {n:hashlib.sha256((destination/'src/homelab_hindsight_specialists'/n).read_bytes()).hexdigest() for n in MODULES}


def _owned(life,handle):
    if handle.id is None or handle.failed or life._inspect(handle) not in ('running','created','exited','stopped'):
        raise Failure('resource-identity')


def _exec(docker,life,handle,argv,user=None):
    _owned(life,handle)
    args=['container','exec']+(['--user',user] if user else [])+[handle.id,*argv]
    return docker.checked('fixture-exec',args)


def _wait(docker,life,handle,probe,seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        _owned(life,handle)
        if life._inspect(handle) != 'running':
            raise Failure('service-startup')
        if probe():return
        time.sleep(1)
    raise Failure('service-readiness')


def _psql(docker,life,db,sql):
    return _exec(docker,life,db,['psql','-X','-q','-t','-A','-v','ON_ERROR_STOP=1','-U','fixture','-d','fixture','-c',sql],'999:999').strip()


def _snapshot(docker,life,db):
    result={}
    for schema in SCHEMAS:
        result[schema]={}
        for table in TABLES:
            sql=f'SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),\'[]\'::jsonb) FROM "{schema}"."{table}" t'
            result[schema][table]=json.loads(_psql(docker,life,db,sql))
    return result


def _verified_url(docker,life,api,network,subnet,*,expected=None):
    """Resolve only this run's exact owned, running API on its internal /28."""
    try:
        for handle,kind in ((api,'container'),(network,'network')):
            if (not any(h is handle for h in life.handles) or handle.kind != kind
                    or handle.owner != life.owner or handle.removed):
                raise ValueError()
            _owned(life,handle)
        container,=docker.json('api-target',['container','inspect',api.id])
        net,=docker.json('api-target',['network','inspect',network.id])
        if not (container['Id']==api.id and container['Name']=='/'+api.name
                and container['Image']==api.image and container['Config']['Image']==api.image
                and container['Config']['Labels'][LABEL]==life.owner
                and container['State']['Status']=='running'
                and net['Id']==network.id and net['Name']==network.name
                and net['Labels'][LABEL]==life.owner and net['Internal'] is True):
            raise ValueError()
        selected=ipaddress.IPv4Network(subnet,strict=True)
        if not selected.is_private or selected.prefixlen != 28:
            raise ValueError()
        configs=net['IPAM']['Config']
        if not isinstance(configs,list) or len(configs)!=1 or configs[0]['Subnet']!=subnet:
            raise ValueError()
        attachments=container['NetworkSettings']['Networks']
        if set(attachments)!={network.name}:
            raise ValueError()
        attachment=attachments[network.name]
        if not isinstance(attachment['IPAddress'],str):
            raise ValueError()
        address=ipaddress.IPv4Address(attachment['IPAddress'])
        peer=net['Containers'][api.id]
        if not (attachment['NetworkID']==network.id and type(attachment['IPPrefixLen']) is int
                and attachment['IPPrefixLen']==28 and address in selected
                and address not in (selected.network_address,selected.broadcast_address)
                and not address.is_loopback and not address.is_link_local
                and peer['Name']==api.name and peer['IPv4Address']==str(address)+'/28'):
            raise ValueError()
        url=f'http://{address}:8888'
        if expected is not None and url != expected:
            raise ValueError()
        return url
    except (ValueError,KeyError,TypeError,AttributeError):
        raise Failure('api-target') from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise Failure('health-redirect')


def _client_phase(phase,url,run_dir,*,subnet):
    from client import report_is_valid
    env={'PATH':'/usr/bin:/bin','HOME':str(run_dir/'home'),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    # Python-only parent opt-in; standalone client.py has no non-loopback flag.
    bootstrap=('import sys; sys.path.insert(0,sys.argv[1]); from client import main; '
               'raise SystemExit(main(sys.argv[2:4], verified_target=(sys.argv[3],sys.argv[4])))')
    result=subprocess.run([sys.executable,'-B','-c',bootstrap,str(HERE),phase,url,subnet],env=env,
                          capture_output=True,text=True,timeout=200,check=False)
    try: report=json.loads(result.stdout)
    except (ValueError,TypeError):raise Failure('client-'+phase) from None
    if result.returncode != 0 or not report_is_valid(report,phase):
        if isinstance(report,dict) and report.get('ok') is False:
            diagnostic={key:report.get(key) for key in ('ok','stage','exception','status')}
            detail=report.get('detail')
            if (isinstance(detail,dict) and set(detail)=={'role','leaf_types'}
                    and detail['role'] in ('learning','career','legacy',None)
                    and isinstance(detail['leaf_types'],list) and len(detail['leaf_types'])<=8
                    and all(isinstance(x,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',x) for x in detail['leaf_types'])):
                diagnostic['detail']=detail
            (run_dir/('client-'+phase+'-failure.json')).write_text(json.dumps(diagnostic)+'\n')
        raise Failure('client-'+phase,result.returncode)
    return report


def run_validation(*,sudo=False,output_root=None,command=subprocess.run):
    root = Path(output_root) if output_root is not None else ROOT/'verification/cache/packaged-runs'
    run_dir=root/uuid.uuid4().hex
    run_dir.mkdir(mode=0o700,parents=True)
    (run_dir/'home').mkdir(mode=0o700)
    docker=Docker(sudo,command)
    life=DockerResources(docker)
    report={'passed':False,'stage':'docker-access','checks':dict.fromkeys(CHECKS,False),
            'positive':None,'denials':None,'images':{},'report_path':str(run_dir/'result.json')}
    try:
        docker.checked('docker-access',['version','--format','{{.Server.Version}}'])
        report['stage']='model-integrity';_models();report['checks']['model_integrity']=True
        hashes=_freeze(run_dir/'build-context')
        report['source_hashes']=hashes
        report['stage']='image-pull'
        docker.checked('image-pull',['pull',DATABASE_IMAGE],timeout=900,log=run_dir/'database-image-build.log')
        db_image=docker.image_id(DATABASE_IMAGE)
        tag='homelab-hindsight-specialist:validation-'+life.owner
        if docker.checked('image-tag',['image','ls','--quiet','--filter','reference='+tag]).strip():
            raise Failure('image-tag')
        report['stage']='image-build'
        docker.checked('image-build',['build','--pull=false','--label',LABEL+'='+life.owner,'--tag',tag,
                       str(run_dir/'build-context')],timeout=1800,log=run_dir/'api-image-build.log')
        api_image=docker.image_id(tag)
        labels=docker.json('image-label',['image','inspect','--format','{{json .Config.Labels}}',api_image])
        if not isinstance(labels,dict) or labels.get(LABEL)!=life.owner:raise Failure('image-label')
        arch=docker.json('image-platform',['image','inspect','--format','{{json .Architecture}}',api_image])
        report['images']={'api':api_image,'database':db_image,'architecture':arch}
        volumes=docker.json('image-volumes',['image','inspect','--format','{{json .Config.Volumes}}',api_image])
        if volumes not in (None,{}):raise Failure('unexpected-api-image-volumes')
        db_volumes=docker.json('image-volumes',['image','inspect','--format','{{json .Config.Volumes}}',db_image])
        if not isinstance(db_volumes,dict) or set(db_volumes)!={'/var/lib/postgresql/data'}:
            raise Failure('unexpected-database-image-volumes')
        report['stage']='network'
        routes=json.loads(subprocess.check_output(['/usr/bin/ip','-json','route','show'],text=True))
        route_ranges=[r['dst'] for r in routes if 'dst' in r]
        network_ids=docker.checked('network-inventory',['network','ls','--quiet','--no-trunc']).splitlines()
        used=[]
        for network_id in network_ids:
            if not re.fullmatch('[0-9a-f]{64}',network_id):raise Failure('network-inventory')
            entries=docker.json('network-inventory',['network','inspect','--format','{{json .IPAM.Config}}',network_id])
            for entry in entries or []:
                if isinstance(entry,dict) and entry.get('Subnet'):used.append(entry['Subnet'])
        subnet=choose_subnet(route_ranges,used)
        network=life.create('network',subnet=subnet)
        _owned(life,network)
        report['checks']['isolated_network']=True
        report['subnet']=subnet
        volume=life.create('volume');_owned(life,volume)
        report['stage']='database-start'
        db=life.create('container',image=db_image,network=network,volume=volume,
                       environment={'POSTGRES_USER':'fixture','POSTGRES_DB':'fixture','POSTGRES_PASSWORD':DATABASE_PASSWORD})
        if not life.start(db):raise Failure('database-start')
        def database_ready():
            return docker(['container','exec',db.id,'pg_isready','-U','fixture','-d','fixture']).returncode==0
        _wait(docker,life,db,database_ready,90)
        from client import FIXTURE_CONFIG
        api_env=environment(db.name,FIXTURE_CONFIG)
        report['stage']='api-start'
        api=life.create('container',image=api_image,network=network,models=str(MODELS),
                        environment=api_env)
        if not life.start(api):raise Failure('api-start')
        mounts=docker.json('api-mounts',['container','inspect','--format','{{json .Mounts}}',api.id])
        if not isinstance(mounts,list):raise Failure('api-mounts')
        data_mounts=[m for m in mounts if m.get('Type')=='bind' and m.get('Destination')=='/models'
                     and m.get('Source')==str(MODELS.resolve()) and m.get('RW') is False]
        if len(data_mounts)!=1 or any(m not in data_mounts and not
                (m.get('Type')=='tmpfs' and m.get('Destination')=='/tmp') for m in mounts):raise Failure('api-mounts')
        security=docker.json('api-security',['container','inspect','--format','{{json .HostConfig}}',api.id])
        if (security.get('ReadonlyRootfs') is not True or security.get('CapDrop')!=['ALL']
                or security.get('Privileged') is not False):raise Failure('api-security')
        url=_verified_url(docker,life,api,network,subnet)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        def api_ready():
            _verified_url(docker,life,api,network,subnet,expected=url)
            try:
                with opener.open(url+'/health',timeout=3) as response:return response.status==200
            except (OSError,urllib.error.URLError):return False
        _wait(docker,life,api,api_ready,180)
        report['stage']='image-runtime'
        code="""import asyncio,hashlib,json,os,pathlib
from importlib.metadata import version
import homelab_hindsight_specialists as p
from hindsight_api.config import get_config
from hindsight_api.extensions import load_extension,TenantExtension
async def check():
 cfg=get_config();tenant=load_extension('TENANT',TenantExtension)
 print(json.dumps({'uid':os.getuid(),'hindsight':version('hindsight-api-slim'),'mcp':version('mcp'),
 'provider':cfg.llm_provider,'embedding':cfg.embeddings_provider,'reranker':cfg.reranker_provider,
 'worker_enabled':cfg.worker_enabled,'schemas':[x.schema for x in await tenant.list_tenants()],
 'source':{n:hashlib.sha256((pathlib.Path(p.__file__).parent/n).read_bytes()).hexdigest() for n in ('__init__.py','ingress.py','server.py')}}))
asyncio.run(check())"""
        proof=json.loads(_exec(docker,life,api,[IMAGE_PYTHON,'-I','-B','-c',code],'1000:1000').splitlines()[-1])
        report['checks']['image_owned_code']=(proof['source']==hashes and proof['hindsight']=='1.2.1' and proof['mcp']=='2.3.0')
        report['checks']['api_nonroot']=type(proof['uid']) is int and proof['uid']==1000
        report['checks']['native_no_llm_config']=(proof['provider']=='none' and proof['embedding']=='onnx' and proof['reranker']=='rrf' and proof['worker_enabled'] is True)
        present=json.loads(_psql(docker,life,db,"SELECT json_agg(schema_name ORDER BY schema_name) FROM information_schema.schemata WHERE schema_name IN ('public','user_learning_coach','user_career_advisor')"))
        report['checks']['tenant_schemas']=set(present)==set(SCHEMAS)==set(proof['schemas'])
        if not all(report['checks'][k] is True for k in ('image_owned_code','api_nonroot','native_no_llm_config','tenant_schemas')):raise Failure('image-runtime')
        report['stage']='positive-client'
        _verified_url(docker,life,api,network,subnet,expected=url)
        report['positive']=_client_phase('positive',url,run_dir,subnet=subnet)
        report['checks']['positive_client']=True
        report['stage']='snapshot-before';before=_snapshot(docker,life,db)
        if not fixture_rows_match(before):raise Failure('database-positive-control')
        report['checks']['database_fixture_rows']=True
        report['stage']='negative-client'
        _verified_url(docker,life,api,network,subnet,expected=url)
        report['denials']=_client_phase('denials',url,run_dir,subnet=subnet)
        report['checks']['negative_client']=True
        report['stage']='snapshot-after';after=_snapshot(docker,life,db)
        report['checks']['persisted_content_unchanged']=before==after
        observations=[int(_psql(docker,life,db,f'SELECT count(*) FROM "{s}".memory_units WHERE fact_type=\'observation\'')) for s in SCHEMAS]
        report['checks']['zero_observations']=observations==[0,0,0]
        report['snapshots']={'unchanged':before==after,'documents':[len(after[s]['documents']) for s in SCHEMAS]}
        report['stage']='complete'
    except BaseException as error:
        report['stage']=error.stage if isinstance(error,Failure) else report['stage']
        report['error']={'type':type(error).__name__ if type(error).__name__ in ('Failure','ValueError','TimeoutExpired','OSError','PermissionError','KeyboardInterrupt','KeyError') else 'RuntimeError',
                         'exit_code':error.code if isinstance(error,Failure) else None}
    finally:
        report['checks']['cleanup']=life.cleanup()
        report['resources']=[{'kind':h.kind,'id':h.id,'name':h.name,'image':h.image,'removed':h.removed,'failed':h.failed} for h in life.handles]
        report['events']=[{'stage':e.stage,'exit_code':e.exit_code} for e in life.events[-40:]]
        report['passed']=_terminal_success(report) and all(value is True for value in report['checks'].values())
        report['passed']=acceptance_is_valid(report)
        (run_dir/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description='Build and validate the packaged specialist server against a disposable database')
    parser.add_argument('--sudo',action='store_true',help='use only sudo -n /usr/bin/docker for Docker operations')
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    report=run_validation(sudo=args.sudo)
    print(json.dumps(report,sort_keys=True))
    return 0 if acceptance_is_valid(report) else 1


if __name__=='__main__':raise SystemExit(main())
