#!/usr/bin/env python3
"""Fixed first-recovery preparation and one-shot guarded native capture.

Standalone preparation remains read-only. --capture takes one private nonsecret
request plus an inherited identity FD; no key path/value or provider is accepted.
No generic providers, schedules, pruning or storage variants.
"""
from datetime import datetime, timezone
import hashlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
CACHE=ROOT/'verification/cache/langfuse-recovery'
HERE=Path(__file__).resolve().parent
PINNED_JOB='langfuse-recovery-cpu-check-20261121'
PINNED_JOB_UID='c06f4b51-c5c0-4004-a2a7-73dd6ce5aa29'
DIAGNOSTICS = {
 PINNED_JOB: dict(job_uid=PINNED_JOB_UID,pod_uid='65fbcd53-3262-4d99-a385-9e3d8a89eed2',phase='Succeeded',exit=0),
 'langfuse-first-valkey-access-20261121': dict(job_uid='4119e51f-e5eb-44db-b885-6c2a62ca0a45',pod_uid='43b9f5b2-85a1-45d7-8b89-7a7a3a15b540',phase='Failed',exit=1),
 'langfuse-valkey-access-diagnostic-20261121': dict(job_uid='2a21f125-b298-4d4c-9522-da63fba0417b',pod_uid='4f8d3dee-ab25-4754-aad8-00f6f6a0f2ff',phase='Failed',exit=1),
 'langfuse-valkey-ping-reason-20261121': dict(job_uid='8b4c1e1e-bb30-4ef3-ba45-d417173a38fd',pod_uid='47c018df-cc34-40b9-8e40-a4282a0b5d45',phase='Failed',exit=1),
 'langfuse-valkey-network-ready-20261121': dict(job_uid='38847381-59fa-4f35-9578-4145007174d8',pod_uid='a3fc7f72-0868-46e2-b9d0-923938e2d25b',phase='Succeeded',exit=0),
 'langfuse-first-capture-4e244d488354': dict(job_uid='4a7a54bd-b89d-42cb-bcd0-4d6a5a2b4747',pod_uid='affb9358-21f1-4797-98d5-fe2fb6a77e9e',phase='Succeeded',exit=0),
 'langfuse-recovery-valkey-47d6711e2ff9': dict(job_uid='77d128e2-4fae-4931-9555-1f9c411657c8',pod_uid='efc31ff5-3788-49ce-bb48-9a03dc39503e',phase='Succeeded',exit=0),
 'langfuse-recovery-valkey-d079828f7d5f': dict(job_uid='76ae349e-9130-48ba-b896-1eda46d0f3d1',pod_uid='bdc080bb-63ea-4573-8aa1-ec9c34407da7',phase='Succeeded',exit=0),
 'langfuse-recovery-valkey-914466344c5e': dict(job_uid='f636cb83-5723-43ef-84e3-ceb0703d07bd',pod_uid='bf059559-3206-448d-b31d-2d7a87712d20',phase='Succeeded',exit=0),
 'langfuse-recovery-valkey-72c99b7e2a51': dict(job_uid='10cd5881-9751-456c-bb8d-e0190d4c2b33',pod_uid='0157bc7c-e483-48dc-9bf2-2f29c0e25bc5',phase='Succeeded',exit=0),
 'langfuse-recovery-valkey-83e5bc5fa2a1': dict(job_uid='155bad3b-7a9e-46ed-8b25-1a3067f61ba2',pod_uid='e9679fc7-265f-4e7f-9c91-dd3adf801c14',phase='Succeeded',exit=0),
}

EXPECTED_CLEANUP={
 '20240606090858_pricings_add_latest_gemini_models',
 '20240530212419_model_price_anthropic_via_google_vertex',
 '20240604133340_backfill_manual_scores',
 '20260203220622_pending_deletions_object_id_idx'}


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError('module-unavailable')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


native=load('first_native',HERE/'inspect-native.py')
preflight=native.preflight


class Refused(RuntimeError):
    pass


def check(ok,reason):
    if not ok: raise Refused(reason)


def run(argv,deadline,limit=1024*1024):
    remaining=deadline-time.monotonic()
    check(remaining>0,'preparation-deadline')
    result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL,cwd=ROOT,timeout=min(25,remaining))
    check(result.returncode==0 and len(result.stdout)<=limit,'metadata-command-failed')
    return result.stdout.decode()


def get(kind,name,deadline,namespace: str | None='langfuse'):
    if kind=='pods' and not name:
        # kubectl's generic List printer drops the server list resourceVersion.
        # Preserve the exact PodList RV: an empty RV silently starts a snapshot
        # watch and cannot establish the list/watch continuity required here.
        check(namespace=='langfuse','pod-list-namespace-scope')
        result=json.loads(run(['kubectl','--request-timeout=20s','get','--raw',
                               '/api/v1/namespaces/langfuse/pods'],deadline))
        rv=result.get('metadata',{}).get('resourceVersion')
        check(result.get('kind')=='PodList' and isinstance(result.get('items'),list)
              and isinstance(rv,str) and re.fullmatch(r'[1-9][0-9]*',rv) is not None
              and not result['metadata'].get('continue'),'pod-list-resource-version')
        return result
    command=['kubectl','--request-timeout=20s']
    if namespace:command+=['-n',namespace]
    return json.loads(run(command+['get',kind]+([name] if name else [])+['-o','json'],deadline))


def execute(pod,container,args,deadline):
    return run(['kubectl','--request-timeout=20s','-n','langfuse','exec',pod,'-c',container,'--',*args],deadline,256*1024)


def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())


def migration_proof(pods,deadline):
    script=r'''
const fs=require('fs'),crypto=require('crypto');
if(process.env.CLICKHOUSE_CLUSTER_ENABLED!=='false')process.exit(1);
const base='/app/packages/shared';
const pg=fs.readdirSync(base+'/prisma/migrations',{withFileTypes:true}).filter(d=>d.isDirectory()).map(d=>d.name).sort();
// Preserve literal delivered Prisma directory names, including spaces, mixed
// case, hyphens and .sql suffixes; they are compared, never executed as SQL.
if(!pg.length||pg.some(n=>!n.length||n.length>200||/[\0\r\n]/.test(n)))process.exit(1);
const ch=fs.readdirSync(base+'/clickhouse/migrations/unclustered').filter(n=>n.endsWith('.up.sql'));
if(!ch.length||ch.some(n=>!/^\d+_[a-z0-9_]+\.up\.sql$/.test(n)))process.exit(1);
const cleanup=fs.readFileSync(base+'/scripts/cleanup.sql','utf8');
const names=[...cleanup.matchAll(/'(\d{14}_[a-z0-9_]+)'/g)].map(m=>m[1]).sort();
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
process.stdout.write(JSON.stringify({postgres:pg,clickhouse:ch.map(n=>Number(n.split('_')[0])).sort((a,b)=>a-b),cleanup_names:names,entrypoint_sha256:hash('/app/web/entrypoint.sh'),cleanup_sha256:hash(base+'/scripts/cleanup.sql'),clickhouse_up_sha256:hash(base+'/clickhouse/scripts/up.sh')}));
'''
    source=json.loads(execute(pods['langfuse-web']['name'],'langfuse-web',['node','-e',script],deadline))
    check(set(source)=={'postgres','clickhouse','cleanup_names','entrypoint_sha256','cleanup_sha256','clickhouse_up_sha256'},'image-migration-schema')
    check(len(source['cleanup_names'])==4 and set(source['cleanup_names'])==EXPECTED_CLEANUP,'startup-cleanup-changed')
    for name in source['postgres']:
        check(isinstance(name,str) and 0<len(name)<=200 and not any(c in name for c in '\0\r\n/'),
              'image-migration-name')
    query="SELECT migration_name FROM public._prisma_migrations WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL ORDER BY migration_name"
    database=execute(pods['postgresql']['name'],'postgresql',
                     ['/bin/sh','-ec',native.PG_SHELL,'first-capture-metadata',query],deadline).strip().splitlines()
    check(database==source['postgres'] and len(database)==len(set(database)),'postgres-image-migration-set-differs')
    names=','.join("'"+name+"'" for name in sorted(EXPECTED_CLEANUP))
    cleanup_count=execute(pods['postgresql']['name'],'postgresql',
              ['/bin/sh','-ec',native.PG_SHELL,'first-capture-metadata',
               'SELECT count(*) FROM public._prisma_migrations WHERE migration_name IN ('+names+')'],deadline).strip()
    check(cleanup_count=='0','startup-cleanup-would-mutate')
    p=native.parse_pg_migrations(execute(pods['postgresql']['name'],'postgresql',
              ['/bin/sh','-ec',native.PG_SHELL,'first-capture-metadata',native.PG_MIGRATION_SQL],deadline).strip())
    check(p['migrations_clean'],'unfinished-postgres-migration')
    ch=native.parse_ch_migration(execute(pods['clickhouse']['name'],'clickhouse',
                                native.CH_OPTIONS+[native.CH_MIGRATION_SQL],deadline).strip())
    check(ch['migrations_clean'] and source['clickhouse']==list(range(1,ch['latest_migration_version']+1)),
          'clickhouse-image-migrations-differ')
    return {'postgres_image_migrations':len(database),'postgres_applied_set_sha256':hashlib.sha256('\n'.join(database).encode()).hexdigest(),
            'postgres_unfinished':p['unfinished_migrations'],'startup_cleanup_rows':0,
            'clickhouse_image_migrations':len(source['clickhouse']),
            'clickhouse_latest_version':ch['latest_migration_version'],'clickhouse_latest_dirty':False,
            'entrypoint_sha256':source['entrypoint_sha256'],'cleanup_sha256':source['cleanup_sha256'],
            'clickhouse_up_sha256':source['clickhouse_up_sha256']}


def pause_dry_runs(workloads,deadline):
    reviewed=[]
    for source in workloads:
        name=source['name']
        before=get('deployment',name,deadline)
        check(before['metadata']['uid']==source['uid'] and before['metadata']['resourceVersion']==source['resourceVersion']
              and before['spec']==source['spec'],'deployment-changed-before-dry-run')
        patch=[{'op':'test','path':'/metadata/uid','value':source['uid']},
               {'op':'test','path':'/metadata/resourceVersion','value':source['resourceVersion']},
               {'op':'test','path':'/spec/replicas','value':1},
               {'op':'replace','path':'/spec/replicas','value':0}]
        simulated=json.loads(run(['kubectl','--request-timeout=20s','-n','langfuse','patch','deployment',name,
                                  '--type=json','--patch',json.dumps(patch),'--dry-run=server','-o','json'],deadline))
        expected=copy.deepcopy(source['spec']);expected['replicas']=0
        check(simulated['metadata']['uid']==source['uid'] and simulated['spec']==expected,'dry-run-modified-more-than-replicas')
        after=get('deployment',name,deadline)
        check(after['metadata']['uid']==source['uid'] and after['metadata']['resourceVersion']==source['resourceVersion']
              and after['spec']==source['spec'],'real-deployment-changed-during-dry-run')
        reviewed.append({'name':name,'uid':source['uid'],'resourceVersion':source['resourceVersion'],
                         'json_patch':patch,'server_dry_run_passed':True,'real_source_unchanged':True})
    return reviewed


def pod_row(pod):
    containers=pod['spec'].get('containers',[]); states=pod.get('status',{}).get('containerStatuses',[])
    check(len(containers)==len(states)==1,'single-container-source-required')
    return {'name':pod['metadata']['name'],'uid':pod['metadata']['uid'],'container':containers[0]['name'],
        'image':containers[0]['image'],'phase':pod.get('status',{}).get('phase',''),
        'ready':str(states[0].get('ready',False)).lower(),'restarts':str(states[0].get('restartCount',-1)),
        'deleting':pod['metadata'].get('deletionTimestamp') or '<none>'}


def diagnostic_pod(pod):
    matches=[(name,value) for name,value in DIAGNOSTICS.items() if value['pod_uid']==pod['metadata']['uid']]
    if not matches: return False
    name,expected=matches[0]; m=pod['metadata']; status=pod.get('status',{})
    owners=m.get('ownerReferences',[]); states=status.get('containerStatuses',[])
    check(m['name'].startswith(name+'-') and m.get('namespace')=='langfuse'
        and not m.get('deletionTimestamp') and len(owners)==1 and owners[0].get('kind')=='Job'
        and owners[0].get('name')==name and owners[0].get('uid')==expected['job_uid']
        and status.get('phase')==expected['phase'] and len(states)==1
        and states[0].get('restartCount')==0
        and states[0].get('state',{}).get('terminated',{}).get('exitCode')==expected['exit'],
        'retained-diagnostic-pod-changed')
    return True


def validate_diagnostic_jobs(jobs):
    check(len(jobs)==len(DIAGNOSTICS),'unreviewed-namespace-job')
    seen=set()
    for job in jobs:
        m=job['metadata']; name=m['name']; expected=DIAGNOSTICS.get(name)
        check(expected is not None and name not in seen and m['uid']==expected['job_uid']
            and not m.get('deletionTimestamp') and not job['status'].get('active')
            and job['status'].get('succeeded' if expected['exit']==0 else 'failed')==1,
            'retained-diagnostic-job-changed')
        seen.add(name)


def prepare(helper=None):
    deadline=time.monotonic()+120
    pod_objects=get('pods','',deadline)['items']
    pods={}; diagnostic_uids=set(); helper_seen=False
    for pod in pod_objects:
        if diagnostic_pod(pod):
            diagnostic_uids.add(pod['metadata']['uid']); continue
        if helper is not None and pod['metadata']['uid']==helper['uid']:
            check(pod['metadata']['name']==helper['name'],'helper-identity-changed')
            helper_seen=True; continue  # Full fixed helper admission is Adapter's gate.
        row=pod_row(pod)
        check(row['container'] in preflight.IMAGE_DIGESTS and row['container'] not in pods,'unreviewed-namespace-pod')
        check(row['phase']=='Running' and row['ready']=='true' and row['restarts']=='0' and row['deleting']=='<none>','source-pod-not-clean')
        check(row['image'].endswith('@sha256:'+preflight.IMAGE_DIGESTS[row['container']]),'source-image-differs')
        pods[row['container']]=row
    check(set(pods)==set(preflight.IMAGE_DIGESTS) and diagnostic_uids=={v['pod_uid'] for v in DIAGNOSTICS.values()}
          and (helper is None or helper_seen),'source-inventory-incomplete')
    jobs=get('jobs','',deadline)['items']
    if helper is not None:
        selected=[j for j in jobs if j['metadata']['uid']==helper['job_uid']]
        check(len(selected)==1 and selected[0]['metadata']['name']==helper['job_name'],'helper-job-identity-changed')
        jobs=[j for j in jobs if j['metadata']['uid']!=helper['job_uid']]
    validate_diagnostic_jobs(jobs)
    check(not get('cronjobs','',deadline)['items'],'unreviewed-namespace-cronjob')
    application=get('application','langfuse',deadline,'argocd')
    check('automated' not in application['spec'].get('syncPolicy',{}) and not application.get('operation'),'application-operation-or-automation')
    check(application['status']['sync']['status']=='Synced' and application['status']['health']['status']=='Healthy','application-not-healthy-synced')
    storage=[]
    for name,(uid,size) in preflight.CLAIMS.items():
        pvc=get('pvc',name,deadline)
        check(pvc['metadata']['uid']==uid and not pvc['metadata'].get('deletionTimestamp') and not pvc['metadata'].get('ownerReferences'),'claim-identity-owner-differs')
        check(pvc['spec']['volumeName']=='pvc-'+uid and pvc['spec']['storageClassName']=='longhorn'
              and pvc['spec']['resources']['requests']['storage']==size and pvc['status']['capacity']['storage']==size
              and pvc['status']['phase']=='Bound','claim-binding-size-differs')
        pv=get('pv','pvc-'+uid,deadline,namespace=None)
        check(pv['spec']['claimRef']['uid']==uid and pv['spec']['claimRef']['name']==name
              and pv['spec']['claimRef']['namespace']=='langfuse' and pv['spec']['csi']['volumeHandle']=='pvc-'+uid
              and pv['spec']['csi']['driver']=='driver.longhorn.io'
              and pv['spec']['persistentVolumeReclaimPolicy']=='Delete' and not pv['metadata'].get('deletionTimestamp'),'volume-identity-reclaim-differs')
        volume=get('volumes.longhorn.io','pvc-'+uid,deadline,'longhorn-system')
        check(volume['spec']['numberOfReplicas']==2 and volume['status']['state']=='attached'
              and volume['status']['robustness']=='healthy','source-volume-not-healthy-replicated')
        storage.append({'claim':name,'uid':uid,'volume':'pvc-'+uid,'capacity':size,'reclaim':'Delete'})
    for name in ('langfuse-postgresql','langfuse-clickhouse'):
        controller=get('statefulset',name,deadline)
        check(controller['spec']['persistentVolumeClaimRetentionPolicy']=={'whenDeleted':'Retain','whenScaled':'Retain'},
              'statefulset-retention-differs')
    workloads=[]
    for name in ('langfuse-web','langfuse-worker'):
        doc=get('deployment',name,deadline)
        check(doc['spec']['replicas']==1 and not doc['metadata'].get('deletionTimestamp'),'source-replicas-not-one')
        workloads.append({'name':name,'uid':doc['metadata']['uid'],'resourceVersion':doc['metadata']['resourceVersion'],
                          'spec':doc['spec'],'generation':doc['metadata'].get('generation')})
    proof=migration_proof(pods,deadline)
    pause_review=pause_dry_runs(workloads,deadline)
    check(time.monotonic()<deadline,'preparation-deadline')
    return {'scope':'fixed first-recovery read-only preparation','observed_at':datetime.now(timezone.utc).isoformat(),
            'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source_revision':run(['git','rev-parse','HEAD'],deadline).strip(),
            'workloads':workloads,'pods':pods,'storage':storage,'migration_proof':proof,
            'pause_patch_server_dry_runs':pause_review,
            'retained_completed_probe_job':{'name':PINNED_JOB,'uid':PINNED_JOB_UID},
            'operator_client_idle_confirmed':False,'capture_ready':False,
            'remaining':['one-shot live helper/watch admission and native capture execution','preserved scheduled-work checkpoint proof',
                         'explicit bounded client-idle maintenance window before any pause'],
            'no_production_mutation':True}


# The fixed live adapter starts a gap-free watch before any pause. Samples do
# not substitute for that watch or the operator's bounded client/admin-idle window.
writer = load('first_capture_writer', HERE/'writer_guard.py')
stream = load('first_capture_stream', HERE/'capture_stream.py')
postgres = load('first_capture_postgres', HERE/'postgres_exports.py')
objects = load('first_capture_objects', HERE/'first_object_capture.py')
valkey = load('first_capture_valkey', HERE/'first_valkey_capture.py')
drain = load('first_capture_drain', HERE/'inspect-drain.py')
restore = load('first_capture_restore', HERE/'first_restore.py')
live = load('first_capture_live', HERE/'first_live_adapter.py')
COMPONENTS = ('postgres-database', 'postgres-globals', 'clickhouse', 'seaweedfs', 'valkey')
IDENTITY_BUNDLE = 'identity-20261121-bb5b26c1e5c64dd9be271473f8be74be'


def native_plan(pods, helper, token, budgets, seaweed, scope):
    """Fixed five-stream plan; builds only, never exports or admits a helper.

    PG native exports are staged once in new private source-container scratch,
    not re-dumped to guess a stream hash. Valkey's unchanged helper is staged on
    its fresh emptyDir. Parent admission must prove those scratch budgets/tools,
    the helper's read-only original PVC/SecretKeyRef, UID1000 and no fsGroup.
    """
    import shlex
    check(set(budgets) == {'postgresql','clickhouse','seaweedfs','valkey'}, 'budget-inventory')
    for budget in budgets.values(): objects._token(token, budget)
    plan = []
    for export in postgres.build(pods['postgresql']):
        directory = '/tmp/first-' + token + '-' + export.component
        path = directory + '/native'
        prefix = export.kubectl_argv[:-len(export.container_argv)]
        script = (objects._new_private_directory(directory)
                  + shlex.join(export.container_argv) + f' > {path}\n')
        if export.complete_archive_validator:
            script += shlex.join(export.complete_archive_validator) + f' {path}\n'
        else:
            script += f'test -s {path}\n'
        checks = (objects._private_path_checks(directory) +
                  f'test -f {path}; test ! -L {path}; test "$(stat -c %h {path})" = 1\n'
                  f'test "$(stat -c %u {path})" = "$(id -u)"; test "$(stat -c %a {path})" = 600\n'
                  f'test "$(wc -c < {path})" -le {budgets["postgresql"]}\n')
        native_parse=(shlex.join(export.complete_archive_validator)+f' {path}\n') if export.complete_archive_validator else ''
        proof = checks + native_parse + f'wc -c < {path}; sha256sum {path} | cut -d " " -f 1\n'
        plan.append((export.component, pods['postgresql'], prefix+objects._shell(script),
                     prefix+objects._shell(proof), prefix+objects._shell(checks+'exec cat '+path)))
    for name, source, fragment in (
        ('clickhouse', pods['clickhouse'], objects.build_clickhouse(pods['clickhouse'],token,budgets['clickhouse'])),
        ('seaweedfs', pods['seaweedfs'], objects.build_seaweed(pods['seaweedfs'],token,budgets['seaweedfs'],
                                                          admitted=seaweed,scope=scope))):
        check(not fragment.blockers, 'native-fragment-blocked')
        plan.append((name,source,fragment.stage_argv,fragment.validate_argv,fragment.producer_argv))
    # Admit the original fixed helper form and the separately reviewed one-shot
    # manifest form. Preserve actual container/name values; never relabel a Pod
    # snapshot to satisfy the builder. Adapter still proves UID/Job/auth/mounts.
    helper_form = (helper.get('container') == 'capture'
                   and re.fullmatch(r'langfuse-recovery-valkey-[a-z0-9-]+', helper.get('name','')))
    helper_form = helper_form or (helper.get('container') == 'capture-helper'
                   and re.fullmatch(r'langfuse-first-capture-[0-9a-f]{12}-[a-z0-9]+', helper.get('name','')))
    check(helper_form and helper.get('image') ==
          'docker.io/valkey/valkey:8.0@sha256:'+preflight.IMAGE_DIGESTS['langfuse-redis']
          and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', helper.get('uid',''))
          and helper.get('phase') == 'Running' and helper.get('ready') == 'true'
          and helper.get('deleting') == '<none>', 'valkey-helper-not-admitted')
    prefix = ('kubectl','--request-timeout=30s','-n','langfuse','exec',helper['name'],'-c',helper['container'],'--')
    path = '/scratch/native.tar'
    stage = objects._shell('test ! -e '+path+'; test ! -L '+path+'; set -C\n'
                           + shlex.join(('/bin/sh','-ec',valkey.shell_fragment()))+' > '+path+'\n')
    checks = (objects._private_path_checks('/scratch/capture') +
              f'test -f {path}; test ! -L {path}; test "$(stat -c %a {path})" = 600\n'
              f'test "$(stat -c %u {path})" = 1000; test "$(stat -c %h {path})" = 1\n'
              f'test "$(wc -c < {path})" -le {budgets["valkey"]}\n')
    proof = checks+'timeout 10 valkey-check-aof /scratch/capture/checkpoint/appendonlydir/appendonly.aof.manifest >/dev/null\n'+f'tar -tf {path} >/dev/null; wc -c < {path}; sha256sum {path} | cut -d " " -f 1\n'
    plan.append(('valkey',helper,prefix+stage,prefix+objects._shell(proof),prefix+objects._shell(checks+'exec cat '+path)))
    check(tuple(p[0] for p in plan) == COMPONENTS, 'component-inventory')
    return tuple(plan)


def _command(argv, deadline, *, stdin=None, output=False):
    """Bounded fixed command; confidential stdout is never sent through this API."""
    remaining = deadline-time.monotonic()
    check(remaining > 0, 'capture-deadline')
    result = subprocess.run(argv, stdin=stdin if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE if output else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=remaining, close_fds=True)
    check(result.returncode == 0, 'capture-command-failed')
    if output:
        check(len(result.stdout) <= 256*1024, 'capture-receipt-too-large')
        return result.stdout
    return b''


def _source_check(source, deadline):
    # Projection only: no Pod environment or Secret contents are retrieved.
    projection = ('{.metadata.uid}|{.spec.containers[*].image}|{.status.phase}|'
                  '{.status.containerStatuses[*].ready}|{.metadata.deletionTimestamp}')
    raw = _command(('kubectl','--request-timeout=20s','-n','langfuse','get','pod',source['name'],
                    '-o','jsonpath='+projection),deadline,output=True).decode()
    check(raw == '|'.join((source['uid'],source['image'],'Running','true','')), 'source-identity-changed')


# Executed only on the configured NAS (or explicitly isolated receiver fixtures).
# Both modes pin and recheck the directory; no chmod/chown or cleanup is performed.
NAS_PROGRAM = r"""
import hashlib,json,os,stat,sys
root,name,size,digest,mode=sys.argv[1:]
size=int(size)
assert mode in ('write','read') and size>0
assert '/' not in name and name not in ('.','..')
for parent in [root]+[str(p) for p in __import__('pathlib').Path(root).parents]:
    assert stat.S_ISDIR(os.lstat(parent).st_mode)
d=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
def private():
    s=os.fstat(d); t=os.stat(root,follow_symlinks=False)
    assert s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o700
    assert (s.st_dev,s.st_ino)==(t.st_dev,t.st_ino)
private()
if mode=='write':
    # Occupied partial/final paths refuse, including symlinks. Never overwrite.
    try: os.stat(name,dir_fd=d,follow_symlinks=False)
    except FileNotFoundError: pass
    else: raise RuntimeError('occupied')
    partial=name+'.partial'
    f=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=d)
    os.fchmod(f,0o600)
    n=0; h=hashlib.sha256()
    while True:
        b=sys.stdin.buffer.read(65536)
        if not b: break
        n+=len(b); assert n<=size; h.update(b)
        v=memoryview(b)
        while v:
            k=os.write(f,v); assert k>0; v=v[k:]
    assert n==size and h.hexdigest()==digest
    os.fsync(f); private()
    s=os.fstat(f); t=os.stat(partial,dir_fd=d,follow_symlinks=False)
    assert s.st_nlink==1 and (s.st_dev,s.st_ino)==(t.st_dev,t.st_ino)
    os.link(partial,name,src_dir_fd=d,dst_dir_fd=d,follow_symlinks=False)
    os.fsync(d); os.close(f)
f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=d)
s=os.fstat(f)
assert stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o600
assert s.st_nlink==2 and s.st_size==size
n=0; h=hashlib.sha256()
while True:
    b=os.read(f,65536)
    if not b: break
    n+=len(b); h.update(b)
assert n==size and h.hexdigest()==digest
private(); os.fsync(f); os.fsync(d)
print(json.dumps({'bytes':n,'sha256':h.hexdigest(),'exclusive':True,'durable':True}))
"""


def _nas_argv(directory, name, size, digest, mode):
    import shlex
    check(re.fullmatch(r'/storage/k3s/langfuse/recovery/first-[a-z0-9-]+',directory) is not None,
          'nas-destination-not-fixed-scope')
    return ('ssh','-oBatchMode=yes','-oStrictHostKeyChecking=yes','-oConnectTimeout=10',
            'nas',shlex.join(('python3','-c',NAS_PROGRAM,directory,name,str(size),digest,mode)))


def _nas_publish(directory_fd, name, receipt, nas_directory, deadline):
    size,digest = receipt['ciphertext_bytes'],receipt['ciphertext_sha256']
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
    try:
        import stat
        info=os.fstat(fd)
        check(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
              and stat.S_IMODE(info.st_mode)==0o600 and info.st_size==size, 'local-ciphertext-identity')
        _command(_nas_argv(nas_directory,name,size,digest,'write'),deadline,stdin=fd)
    finally:
        os.close(fd)
    # Separate authenticated readback, not receiver exit/echo acceptance.
    actual=json.loads(_command(_nas_argv(nas_directory,name,size,digest,'read'),deadline,output=True))
    check(actual == {'bytes':size,'sha256':digest,'exclusive':True,'durable':True}, 'nas-readback-failed')
    return actual


def producer_command(producer):
    """Only HOME/PATH are restored to kubectl's otherwise empty environment.

    The normal configured auth path was independently exercised by the parent.
    No credential/config reads, private env copying or authentication change.
    """
    import shutil
    executable=shutil.which(producer[0]); check(executable is not None,'producer-executable-missing')
    if Path(executable).name=='kubectl':
        return ('/usr/bin/env','HOME='+str(Path.home()),'PATH=/usr/bin:/bin',executable,*producer[1:])
    return (executable,*producer[1:])  # Generated-only producer fixtures.


def seaweed_sample(source,deadline):
    _source_check(source,deadline)
    samples={}
    for port,path,name in ((9333,'/dir/status','directory'),(9333,'/vol/status','master'),(8080,'/status','local')):
        raw=execute(source['name'],source['container'],['wget','-q','-T','5','-O','-',
                    'http://127.0.0.1:'+str(port)+path],deadline)
        samples[name]=json.loads(raw)
    _source_check(source,deadline)
    node=samples['directory']['Topology']['DataCenters'][0]['Racks'][0]['DataNodes'][0]
    return objects.admit_seaweed(samples['directory'],samples['master'],samples['local'],node['Url'].removesuffix(':8080'))


def stream_checkpoint(guard,checkpoint):
    """Watch/cancellation are checked every pipe poll; fresh API proof at 2Hz.

    Full checkpoints also bracket every native command and parser/publication.
    Do not issue two Deployment GETs for every 64KiB cipher chunk: the independent
    background watch retains every event and the final RV barrier catches backlog.
    """
    if not isinstance(guard.api,live.Adapter): return checkpoint
    last=[float('-inf')]
    def poll():
        guard._check()  # Same pinned guard's deadline, approval and cancellation.
        guard.api.watch.healthy()
        if time.monotonic()-last[0]>=.5:
            checkpoint(); last[0]=time.monotonic()
    return poll


def decrypt_native(directory_fd,name,age_binary,identity_fd,proof,checkpoint,deadline,max_bytes):
    """Private bounded RAM only. Identity FD is inherited by age alone."""
    import selectors
    import signal
    check(type(max_bytes) is int and 0<proof['bytes']<=max_bytes,'native-validation-byte-bound')
    source=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
    process=None; data=bytearray(); digest=hashlib.sha256()
    try:
        checkpoint()
        process=subprocess.Popen((age_binary,'-d','-i','/proc/self/fd/'+str(identity_fd)),
            stdin=source,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={},cwd='/',
            pass_fds=(identity_fd,),close_fds=True,start_new_session=True)
        assert process.stdout is not None
        os.set_blocking(process.stdout.fileno(),False)
        with selectors.DefaultSelector() as select:
            select.register(process.stdout,selectors.EVENT_READ)
            eof=False
            while not eof or process.poll() is None:
                check(time.monotonic()<deadline,'native-validation-deadline'); checkpoint()
                for key,_ in select.select(.05):
                    body=os.read(key.fd,65536)
                    if not body:
                        eof=True; select.unregister(key.fileobj)
                    else:
                        check(len(data)+len(body)<=proof['bytes'],'native-decrypted-overflow')
                        digest.update(body); data.extend(body)
        check(process.returncode==0 and len(data)==proof['bytes'] and digest.hexdigest()==proof['sha256'],
              'native-decrypted-identity')
        checkpoint()
        return data
    finally:
        os.close(source)
        if process is not None:
            try: os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=3)
            if process.stdout: process.stdout.close()


class NativeValidator:
    """Fixed real validation, not a provider callback/restore substitute.

    PostgreSQL is FULLY parsed by source pg_restore; the generated globals stream
    is bound to pg_dumpall rc0, framing and the exact staged full-stream hash.
    Valkey source check-aof checks every dependency; its current outer validator
    checks complete inventory/checksums. CH/SW use their current full parsers.
    Isolated native RESTORE and application reconciliation remain step4.
    """
    def __init__(self,plan,age_binary,identity_fd,max_bytes,*,guard=None):
        self.guard=guard
        self.plan={entry[0]:entry for entry in plan}
        self.age=age_binary; self.identity_fd=identity_fd; self.max_bytes=max_bytes
        self.seaweed_before=None; self.receipts={}

    def before(self,component,checkpoint,deadline):
        checkpoint()
        if component=='seaweedfs': self.seaweed_before=seaweed_sample(self.plan[component][1],deadline)
        checkpoint()

    def __call__(self,component,directory_fd,name,proof,checkpoint,deadline):
        check(component in COMPONENTS and component in self.plan,'native-component')
        poll=stream_checkpoint(self.guard,checkpoint) if self.guard is not None else checkpoint
        blob=decrypt_native(directory_fd,name,self.age,self.identity_fd,proof,poll,deadline,self.max_bytes)
        try:
            checkpoint(); source=self.plan[component][1]
            _source_check(source,deadline)
            # Recheck the exact native full-parser/staged source receipt too.
            current=objects.parse_archive_receipt(_command(self.plan[component][3],deadline,output=True))
            check(current==proof,'native-source-proof-changed')
            if component=='clickhouse': evidence=objects.validate_clickhouse_archive(blob)
            elif component=='seaweedfs':
                check(self.seaweed_before is not None,'seaweed-before-missing')
                after=seaweed_sample(source,deadline)
                evidence=objects.validate_seaweed_archive(blob,before=self.seaweed_before,after=after)
            elif component=='valkey': evidence=restore.validate_valkey_archive(blob)
            elif component=='postgres-database':
                check(blob[:5]==b'PGDMP','postgres-custom-header')
                # validate_argv includes pg_restore --file=/dev/null, with full
                # producer/staged/decrypted identity equality, not a TOC-only read.
                evidence=proof
            else:
                check(not b'\0' in blob and b'-- PostgreSQL database cluster dump' in blob[:4096]
                      and b'-- PostgreSQL database cluster dump complete' in blob[-4096:], 'postgres-globals-framing')
                blob.decode('utf-8'); evidence=proof
            check(evidence['bytes']==proof['bytes'] and evidence['sha256']==proof['sha256'],'native-parser-identity')
            self.receipts[component]={'bytes':proof['bytes'],'sha256':proof['sha256'],
                                      'complete_native_source_and_archive_validation':True}
            _source_check(source,deadline); checkpoint()
            check(time.monotonic()<deadline,'native-validation-deadline')
            return True
        finally:
            del blob  # No plaintext filesystem publication, logs or raw errors.


def capture_first(*, guard, plan, directory_fd, age_binary, recipient, identity_fd,
                  nas_directory, identity_bundle_ref, verify_native):
    """One fixed capture attempt, with explicit guard.resume() left to caller.

    The standalone driver supplies the fixed live Adapter and NativeValidator.
    In-process fixture callers may supply synthetic IO for orchestration tests.
    Requires a NEW WriterGuard backed by a reviewed production adapter. Before
    invoking this function parent verifies approval refs (recipient, custody, NAS,
    idle window and the already encrypted identity bundle) through that adapter.
    verify_native(component, directory_fd, name, proof, checkpoint, deadline) must
    independently validate the complete DECRYPTED native archive, using only the
    approved child descriptors. It may not accept a cipher hash as a native parse.
    This callback is mandatory because capture_stream validates byte equality,
    not PostgreSQL/Valkey/Seaweed native semantics. It must honor the deadline.

    No implicit resume, retries, fallback capture, Secret reads or step4 restore.
    Returns guard state plus separate capture publication state. Component files
    alone never mark a coordinated set complete. Production adapter/native-parser
    integration is deliberately a prerequisite, not a fabricated implementation.
    """
    import dataclasses
    import math
    check(guard.state == 'NEW', 'new-guard-required')
    check(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,48}',guard.approval.operation_id) is not None,
          'operation-id-invalid')
    check(guard.approval.recipient_ref == recipient
          and guard.approval.destination_ref == nas_directory, 'approval-destination-binding')
    check(tuple(p[0] for p in plan) == COMPONENTS, 'component-inventory')
    check(identity_bundle_ref == IDENTITY_BUNDLE, 'identity-bundle-reference')
    check(callable(verify_native), 'native-validation-required')
    check(os.path.isabs(age_binary) and re.fullmatch(r'age1[0-9a-z]{58}',recipient) is not None,
          'encryption-inputs')
    check(type(identity_fd) is int and identity_fd>=3, 'identity-descriptor-required')
    os.fstat(identity_fd)  # Metadata only; never read private identity in this process.
    stream._private(directory_fd)
    # Validate syntax before a writer pause or confidential native export.
    _nas_argv(nas_directory,'probe.age',1,'0'*64,'read')
    check(math.isfinite(guard.timeout) and guard.timeout<=1800, 'capture-bound')
    publications=[]; proofs={}

    def checked_command(source, argv, checkpoint, deadline, output=False):
        checkpoint(); _source_check(source,deadline)
        result=_command(argv,deadline,output=output)
        _source_check(source,deadline); checkpoint()
        return result

    def capture(checkpoint, deadline):
        for component, source, stage, validate, producer in plan:
            if isinstance(verify_native,NativeValidator): verify_native.before(component,checkpoint,deadline)
            checked_command(source,stage,checkpoint,deadline)
            proof=objects.parse_archive_receipt(checked_command(source,validate,checkpoint,deadline,True))
            proofs[component]=proof
            name=guard.approval.operation_id+'-'+component+'.age'
            checkpoint(); _source_check(source,deadline)
            producer=producer_command(producer)
            poll=stream_checkpoint(guard,checkpoint)
            def cancelled():
                poll()
                return False
            result=stream.capture(directory_fd=directory_fd,name=name,producer_argv=producer,
                age_argv=(age_binary,'-r',recipient),
                decrypt_argv=(age_binary,'-d','-i','/proc/self/fd/'+str(identity_fd)),
                decrypt_pass_fds=(identity_fd,),expected_bytes=proof['bytes'],expected_sha256=proof['sha256'],
                max_ciphertext_bytes=proof['bytes']*2+65536,
                timeout_seconds=deadline-time.monotonic(),cancelled=cancelled)
            _source_check(source,deadline); checkpoint()
            check(result.complete,'encrypted-stream-incomplete')
            # Mandatory, exercised trusted boundary. Never silently skip a parser.
            check(verify_native(component,directory_fd,name,copy.deepcopy(proof),checkpoint,deadline) is True,
                  'native-validation-failed')
            checkpoint()
            fd=os.open(result.receipt,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
            with os.fdopen(fd) as file: receipt=json.load(file)
            check(receipt.get('status')=='COMPLETE' and receipt.get('plaintext_bytes')==proof['bytes']
                  and receipt.get('plaintext_sha256')==proof['sha256']
                  and receipt.get('exits')=={'producer':0,'age':0,'decrypt':0}, 'component-receipt-binding')
            remote=_nas_publish(directory_fd,name,receipt,nas_directory,deadline)
            checkpoint()
            # Keep the set self-contained on NAS: step4 needs the primitive's
            # exact complete receipts, not a workstation cache surviving loss.
            fd=os.open(result.receipt,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
            with os.fdopen(fd,'rb') as file: receipt_bytes=file.read()
            metadata=_nas_publish(directory_fd,result.receipt,{'ciphertext_bytes':len(receipt_bytes),
                'ciphertext_sha256':hashlib.sha256(receipt_bytes).hexdigest()},nas_directory,deadline)
            checkpoint()
            publications.append({'component':component,'name':name,'source_uid':source.get('uid'),
                'plaintext_bytes':proof['bytes'],'plaintext_sha256':proof['sha256'],
                'complete_receipt':{'name':result.receipt,**metadata},**remote})
        # Revalidate ALL staged sources, including Seaweed background/log writes.
        for component,source,_,validate,_ in plan:
            after=objects.parse_archive_receipt(checked_command(source,validate,checkpoint,deadline,True))
            check(after==proofs[component],'native-source-changed')

    result=guard.run(capture)
    outcome={'status':'INCOMPLETE','guard':dataclasses.asdict(result),
             'components':publications,'identity_bundle_ref':identity_bundle_ref,
             'recovery_accepted':False,'replicas_automatically_resumed':False}
    if isinstance(verify_native,NativeValidator): outcome['native_validation']=copy.deepcopy(verify_native.receipts)
    if isinstance(guard.api,live.Adapter):
        outcome['preserved_queue_state']=copy.deepcopy(guard.api.scheduled)
        outcome['watch_completion_rv']=guard.api.watch.last_rv
        outcome['normal_writer_exits']=copy.deepcopy(guard.api.watch.exits)
    if result.capture_complete and result.state=='CAPTURED':
        # A separate marker is written only AFTER continuous fence.finish passed.
        # It is local only until NAS publication AND separate readback succeed.
        name=guard.approval.operation_id+'-capture.json'
        value=json.dumps({'scope':'coordinated-native-encrypted-capture-not-restore',
                          'operation_id':guard.approval.operation_id,'components':publications,
                          'identity_bundle_ref':identity_bundle_ref,'recovery_accepted':False,
                          'native_validation':outcome.get('native_validation',{}),
                          'preserved_queue_state':outcome.get('preserved_queue_state'),
                          'watch_completion_rv':outcome.get('watch_completion_rv'),
                          'normal_writer_exits':outcome.get('normal_writer_exits',{})},
                         sort_keys=True).encode()
        try:
            stream._record(directory_fd,name,json.loads(value))
            # _record serializes differently; hash exact persisted marker bytes.
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
            with os.fdopen(fd,'rb') as file: data=file.read()
            remote=_nas_publish(directory_fd,name,{'ciphertext_bytes':len(data),
                'ciphertext_sha256':hashlib.sha256(data).hexdigest()},nas_directory,guard.deadline)
            outcome.update(status='CAPTURED',manifest=name,manifest_readback=remote)
        except BaseException:
            outcome['reason']='capture-marker-publication-incomplete'
    # Always retain a private exclusive local attempt outcome. No log/raw errors.
    stream._record(directory_fd,guard.approval.operation_id+'-outcome.json',outcome)
    return outcome


def private_json(path,limit=2*1024*1024):
    import stat
    path=Path(path).absolute()
    check(path.is_relative_to(CACHE),'request-outside-private-cache')
    for parent in path.parents: check(not parent.is_symlink(),'request-symlink-parent')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        check(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
              and stat.S_IMODE(info.st_mode)==0o600 and info.st_size<=limit,'request-not-private')
        with os.fdopen(fd,'rb',closefd=False) as file: return json.load(file)
    finally: os.close(fd)


def recipient_proof(age_binary,recipient,identity_fd,deadline):
    # Known PUBLIC generated text only, no existing Secret or identity value read.
    plain=b'fixed-first-langfuse-capture-recipient-custody-check\n'
    encrypted=subprocess.run((age_binary,'-r',recipient),input=plain,stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,env={},cwd='/',timeout=min(15,deadline-time.monotonic()),check=True).stdout
    restored=subprocess.run((age_binary,'-d','-i','/proc/self/fd/'+str(identity_fd)),input=encrypted,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={},cwd='/',pass_fds=(identity_fd,),
        timeout=min(15,deadline-time.monotonic()),check=True).stdout
    check(restored==plain,'recipient-custody-mismatch')


def run_live_request(request_path,identity_fd,*,review_resume=None):
    """Public standalone driver, one fixed request + inherited private identity FD.

    Request is nonsecret owner-only JSON under verification/cache/langfuse-recovery:
    operation_id, prepared_receipt, helper (exact Pod row plus job_name/job_uid),
    authorization_ref, client_idle_ref (includes all client/admin writers quiet),
    custody_ref, expires_at (UTC ISO8601), budgets (four source byte ceilings),
    max_validation_bytes (bounded private RAM), and operator_client_idle_confirmed.
    Recipient/NAS are taken from the already verified fixed step1 public receipt.
    No caller-supplied executable/provider/Secret/config/identity path is accepted.
    review_resume is an explicit operator decision AFTER outcome, never a retry.
    """
    os.umask(0o077)
    request=private_json(request_path)
    check(request.get('operator_client_idle_confirmed') is True,'explicit-client-admin-idle-window-required')
    operation=request['operation_id']
    check(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,48}',operation) is not None,'operation-id-invalid')
    expires=datetime.fromisoformat(request['expires_at'])
    check(expires.tzinfo is not None,'window-timezone-required')
    seconds=(expires-datetime.now(timezone.utc)).total_seconds()
    check(0<seconds<=1800,'bounded-live-window-required')
    deadline=time.monotonic()+seconds
    prepared=private_json(request['prepared_receipt'])
    identity=private_json(CACHE/IDENTITY_BUNDLE/'verified.json')
    check(identity['status']=='IDENTITY_SNAPSHOT_VERIFIED' and identity['native_decrypt_and_private_schema_validation'] is True
          and identity['secret_count']==6,'step1-identity-not-verified')
    recipient=identity['public_recipient']; destination='/storage/k3s/langfuse/recovery/first-20261120'
    check(identity['remote_directory']==destination+'/'+IDENTITY_BUNDLE,'step1-destination-binding')
    approval=writer.Approval(operation,request['authorization_ref'],recipient,request['custody_ref'],destination,
                            request['client_idle_ref'],deadline)
    approval.validate(time.monotonic())
    check(type(identity_fd) is int and identity_fd>=3,'identity-descriptor-required'); os.fstat(identity_fd)
    encryption=load('first_capture_encryption',HERE/'fixture-encryption.py')
    check((encryption.CACHE/'age-v1.3.2-linux-amd64.tar.gz').is_file(),'verified-age-cache-required')
    age=str(encryption.tools()['age'])
    recipient_proof(age,recipient,identity_fd,deadline)
    state=CACHE/('first-live-'+operation)
    state.mkdir(mode=0o700)  # Exclusive operation-id reservation, never reuse/replay.
    directory_fd=os.open(state,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    adapter=None
    try:
        with writer.Journal(state/'operation.jsonl') as journal:
            adapter=live.Adapter(sys.modules[__name__],prepared,request['helper'],approval,state,timeout=seconds)
            expected=tuple(adapter.expected[name] for name in writer.TARGETS)
            guard=writer.WriterGuard(adapter,journal,approval,expected,timeout=seconds,drain_timeout=min(120,seconds))
            # Readiness, original objects, migration image proof, and the watch's
            # initial bookmark all precede the first possible replica CAS.
            adapter.start(deadline)
            source=prepared['pods']['seaweedfs']
            topology=seaweed_sample(source,deadline)
            token=uuid.uuid4().hex
            plan=native_plan(prepared['pods'],request['helper'],token,request['budgets'],topology,objects.SEAWEED_SCOPE)
            validation_bound=request['max_validation_bytes']
            check(type(validation_bound) is int and 1048576<=validation_bound<=4*1024**3,'native-memory-bound')
            validator=NativeValidator(plan,age,identity_fd,validation_bound,guard=guard)
            save(state/'reviewed-plan.json',{'operation_id':operation,'plan':plan,
                 'source_helper_hashes':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in
                    ('first_capture.py','first_live_adapter.py','writer_guard.py','capture_stream.py',
                     'postgres_exports.py','first_valkey_capture.py','first_object_capture.py','first_restore.py')},
                 'approval':approval.__dict__,'prepared_receipt':request['prepared_receipt']})
            outcome=capture_first(guard=guard,plan=plan,directory_fd=directory_fd,age_binary=age,recipient=recipient,
                identity_fd=identity_fd,nas_directory=destination,identity_bundle_ref=IDENTITY_BUNDLE,verify_native=validator)
            if review_resume is not None and guard.state in ('CAPTURED','INCOMPLETE') and not guard.uncertain:
                if review_resume(copy.deepcopy(outcome),operation) is True:
                    import dataclasses
                    outcome['explicit_resume']=dataclasses.asdict(guard.resume())
                    stream._record(directory_fd,operation+'-explicit-resume.json',outcome['explicit_resume'])
            return outcome
    finally:
        if adapter is not None: adapter.close()
        os.close(directory_fd)


def capture_cli(argv):
    # argv excludes --capture. Never echo rejected inputs/private key literals.
    if len(argv) not in (3,4) or argv[1]!='--identity-fd' or (len(argv)==4 and argv[3]!='--review-resume'):
        print('Use --capture REQUEST_JSON --identity-fd FD [--review-resume]. Private identity values/paths are not accepted.',file=sys.stderr)
        return 2
    def review(outcome,operation):
        print(json.dumps(outcome,sort_keys=True),flush=True)
        if not sys.stdin.isatty(): return False
        return input('After reviewing the private journal, type RESUME '+operation+' to restore unchanged replicas: ')==('RESUME '+operation)
    try:
        fd=int(argv[2])
        outcome=run_live_request(argv[0],fd,review_resume=review if len(argv)==4 else None)
        print(json.dumps(outcome,sort_keys=True))
        return 0 if outcome['status']=='CAPTURED' and outcome.get('explicit_resume',{}).get('state','RESUMED')=='RESUMED' else 1
    except BaseException:
        print('Capture incomplete; inspect the private operation journal. No automatic resume/retry; raw diagnostics withheld.',file=sys.stderr)
        return 1


def main(argv=None, *, capture_inputs=None):
    argv=sys.argv[1:] if argv is None else argv
    if argv and argv[0]=='--capture':
        if capture_inputs is None:
            return capture_cli(argv[1:])
        try:
            outcome=capture_first(**capture_inputs)
            print(json.dumps(outcome,sort_keys=True))
            return 0 if outcome['status']=='CAPTURED' else 1
        except BaseException:
            print('Capture incomplete; raw diagnostics withheld. Inspect the private journal; no automatic resume.',file=sys.stderr)
            return 1
    if argv!=['--prepare']:
        print('Use --prepare or --capture REQUEST_JSON --identity-fd FD [--review-resume]; no automatic resume/replay.',file=sys.stderr);return 2
    os.umask(0o077)
    state=CACHE/('first-prepare-'+uuid.uuid4().hex);state.mkdir(mode=0o700)
    try:
        result=prepare();save(state/'prepared.json',result)
        print(json.dumps({'status':'PREPARATION_CHECKED','migration_proof':result['migration_proof'],
                          'pause_dry_runs_verified':len(result['pause_patch_server_dry_runs']),
                          'receipt':str(state/'prepared.json'),'capture_ready':False,'production_mutated':False},indent=2))
        return 0
    except Exception as error:
        reason=str(error) if isinstance(error,Refused) else 'preparation failed; raw diagnostics withheld'
        save(state/'incomplete.json',{'status':'INCOMPLETE','reason':reason})
        print('Preparation refused: '+reason+'. No production mutation.',file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
