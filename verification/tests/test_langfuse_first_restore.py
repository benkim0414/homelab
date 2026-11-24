"""Credential-free fixed target restore preparation tests; never call kubectl."""
import base64

import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import uuid
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('langfuse_first_restore',ROOT/'langfuse/recovery/first_restore.py')
assert SPEC is not None and SPEC.loader is not None
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


def synthetic_identity():
    return {'kind':'List','apiVersion':'v1','items':[
      {'apiVersion':'v1','kind':'Secret','type':'Opaque','metadata':{'name':name,'namespace':'langfuse',
       'uid':'generated-only','resourceVersion':'1','ownerReferences':[{'name':'must-not-copy'}]},
       'data':{key:base64.b64encode(b'generated-only-not-real').decode() for key in keys}}
       for name,keys in r.SECRET_KEYS.items()]}


def storage():
    pvcs=[]; pvs=[]; volumes=[]
    for index,(component,size) in enumerate(r.CLAIMS.items(),1):
        uid='00000000-0000-0000-0000-'+str(index).zfill(12); handle='pvc-'+uid
        pvcs.append({'metadata':{'name':'recovery-'+component,'namespace':r.NAMESPACE,'uid':uid},
         'spec':{'storageClassName':'longhorn','resources':{'requests':{'storage':size}},'volumeName':handle},
         'status':{'phase':'Bound','capacity':{'storage':size}}})
        pvs.append({'metadata':{'name':handle},'spec':{'csi':{'driver':'driver.longhorn.io','volumeHandle':handle},
         'claimRef':{'name':'recovery-'+component,'namespace':r.NAMESPACE,'uid':uid}}})
        volumes.append({'metadata':{'name':handle},'spec':{'numberOfReplicas':2},'status':{'robustness':'healthy'}})
    return pvcs,pvs,volumes


def valkey_files():
    files={'appendonlydir/appendonly.aof.1.base.rdb':b'GENERATED-ONLY-RDB-NOT-NATIVE',
     'appendonlydir/appendonly.aof.1.incr.aof':b'',
     'appendonlydir/appendonly.aof.manifest':b'file appendonly.aof.1.base.rdb seq 1 type b\nfile appendonly.aof.1.incr.aof seq 1 type i\n',
     'receipt.txt':b'native-live-checkpoint\nversion=8.0.12\nfreeze=CLIENT PAUSE 60000 WRITE\ncopy_deadline_seconds=45\n',
     'server.identity':b'fixture-only\n','source-file-identities.private':b'fixture-only\n',
     'rewrite-counter':b'1\n','monotonic-window':b'1 2\n'}
    files['SHA256SUMS']=''.join(hashlib.sha256(body).hexdigest()+'  '+name+'\n'
      for name,body in files.items() if name.startswith('appendonlydir/')).encode()
    return files


def archive(files, extra=None):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w:') as tf:
        for name,body in files.items():
            member=tarfile.TarInfo('./'+name); member.size=len(body); member.mode=0o600
            tf.addfile(member,io.BytesIO(body))
        if extra:
            tf.addfile(extra)
    return output.getvalue()


class FixedPlanTests(unittest.TestCase):
    def test_revised_restore_only_placement_keeps_original_resource_budgets(self):
        self.assertEqual({name:value[0] for name,value in r.PLACEMENT.items()},
                         {'postgresql':'k3s-01','clickhouse':'k3s-04','valkey':'k3s-01',
                          'seaweedfs':'k3s-01','web':'k3s-05','worker':'k3s-05'})
        self.assertEqual({name:value[3:] for name,value in r.PLACEMENT.items()},
                         {'postgresql':('250m','512Mi','1','1Gi'),
                          'clickhouse':('500m','2Gi','2','4Gi'),
                          'valkey':('100m','256Mi','1','768Mi'),
                          'seaweedfs':('250m','512Mi','2','2Gi'),
                          'web':('250m','1Gi','2','2Gi'),
                          'worker':('250m','1Gi','2','2Gi')})

    def setUp(self):
        self.resources=r.resources()
        self.pods=[p for p in self.resources if p['kind']=='Pod']

    def test_exact_namespace_and_four_unbound_new_claims(self):
        claims=[p for p in self.resources if p['kind']=='PersistentVolumeClaim']
        self.assertEqual({p['metadata']['name']:p['spec']['resources']['requests']['storage'] for p in claims},
                         {'recovery-'+k:v for k,v in r.CLAIMS.items()})
        for p in self.resources:
            if p['kind']!='Namespace':self.assertEqual(p['metadata']['namespace'],r.NAMESPACE)
        for p in claims:
            self.assertNotIn('volumeName',p['spec']);self.assertNotIn('dataSource',p['spec'])

    def test_no_argo_schedules_secrets_or_public_exposure(self):
        self.assertTrue({p['kind'] for p in self.resources}<={'Namespace','NetworkPolicy','PersistentVolumeClaim','Pod','Service','ConfigMap'})
        for service in [p for p in self.resources if p['kind']=='Service']:
            self.assertEqual(service['spec']['type'],'ClusterIP')
            self.assertEqual(service['spec']['selector']['recovery'],'first-20261120')
        self.assertNotIn('argocd.argoproj.io',json.dumps(self.resources))

    def test_deny_all_and_same_namespace_intersection(self):
        policies={p['metadata']['name']:p['spec'] for p in self.resources if p['kind']=='NetworkPolicy'}
        self.assertEqual(policies['deny-all'],{'podSelector':{},'policyTypes':['Ingress','Egress']})
        peer=policies['target-only']['egress'][0]['to'][0]
        self.assertEqual(peer['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name'],r.NAMESPACE)
        self.assertIn('podSelector',peer)
        dns=policies['target-only']['egress'][1]
        self.assertEqual({p['port'] for p in dns['ports']},{53})
        self.assertNotIn('ipBlock',json.dumps(policies))

    def test_pinned_images_placement_and_security(self):
        self.assertEqual(len(self.pods),6)
        for pod in self.pods:
            s=pod['spec'];c=s['containers'][0];component=c['name']
            self.assertEqual(c['image'],r.IMAGES[component]); self.assertIn('@sha256:',c['image'])
            self.assertEqual(s['restartPolicy'],'Never');self.assertFalse(s['automountServiceAccountToken'])
            self.assertFalse(s['enableServiceLinks']);self.assertTrue(s['securityContext']['runAsNonRoot'])
            self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
            self.assertEqual(s['nodeSelector']['kubernetes.io/hostname'],r.PLACEMENT[component][0])
            self.assertEqual(c['command'],['/bin/sh','-ec',r.HOLD])
            self.assertFalse(s.get('hostNetwork',False))
            for volume in s['volumes']:
                self.assertNotIn('hostPath',volume)
                if 'persistentVolumeClaim' in volume:
                    self.assertEqual(volume['persistentVolumeClaim']['claimName'],'recovery-'+component)

    def test_no_bootstrap_or_startup_migrations(self):
        for component in ('web','worker'):
            env=r.app_env(component)
            self.assertFalse(any(e['name'].startswith('LANGFUSE_INIT_') for e in env))
            self.assertFalse(any(e.get('valueFrom',{}).get('secretKeyRef',{}).get('name')=='langfuse-bootstrap' for e in env))
            self.assertNotIn('entrypoint.sh',r.SCRIPTS[component])
            literals={e['name']:e.get('value') for e in env}
            self.assertEqual(literals['LANGFUSE_AUTO_POSTGRES_MIGRATION_DISABLED'],'true')
            self.assertEqual(literals['LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED'],'true')
            self.assertEqual(literals['NEXTAUTH_URL'],'http://127.0.0.1:3300')
            for e in env:
                self.assertNotIn('.langfuse.svc',e.get('value',''))

    def test_all_shell_scripts_parse(self):
        for name,script in {**r.SCRIPTS,'hold':r.HOLD}.items():
            with self.subTest(name=name):
                result=subprocess.run(['/bin/sh','-n'],input=script.encode(),capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_commands_are_fixed_target_only(self):
        def walk(value):
            if isinstance(value,dict):
                for item in value.values():yield from walk(item)
            elif isinstance(value,list) and value and value[0]=='kubectl':yield value
        commands=list(walk(r.commands())); self.assertGreater(len(commands),20)
        for command in commands:
            self.assertEqual(command[command.index('-n')+1],r.NAMESPACE)
            self.assertNotIn('delete',command);self.assertNotIn('apply',command)
        self.assertIn('--address=127.0.0.1',r.commands()['private_owner_access'])

    def test_commands_shell_arguments_parse(self):
        def walk(value):
            if isinstance(value,dict):
                for item in value.values():yield from walk(item)
            elif isinstance(value,list):yield value
        for command in walk(r.commands()):
            if '/bin/sh' in command:
                script=command[command.index('/bin/sh')+2]
                self.assertEqual(subprocess.run(['/bin/sh','-n'],input=script.encode(),capture_output=True).returncode,0)

    def test_no_acceptance_or_deployment_claim(self):
        bundle=r.bundle()
        self.assertFalse(bundle['recovery_accepted']);self.assertFalse(bundle['deployed'])
        self.assertGreater(len(bundle['required_gates']),10)
        self.assertNotIn('no capture has yet occurred',json.dumps(bundle))
        self.assertIn('first_live_adapter.py',bundle['dependencies_sha256'])

    def test_native_methods_are_real_and_nonrepairing(self):
        self.assertIn('pg_restore -h /restore -U restore_admin -d postgres --create --exit-on-error',r.PG)
        self.assertIn('pg_amcheck',r.PG);self.assertIn('RESTORE DATABASE default FROM File',r.CH)
        executable='\n'.join(line for line in r.VK.splitlines() if not line.lstrip().startswith('#'))
        self.assertIn('valkey-check-aof',executable);self.assertNotIn('--fix',executable)
        self.assertIn('fs.meta.load -v=false',r.SW);self.assertIn('kill -TERM "$server"; wait "$server"',r.SW)
        self.assertLess(r.SW.index('test "$reconciled" = 1'),r.SW.index('exec 3>&-'))
        self.assertIn('password_hash=',r.VK)


    def test_app_url_uses_original_password_encoded_without_echo(self):
        js=shlex.split(r.APP[r.APP.index('exec node -e '):])[3]
        stub=r'''const EventEmitter=require('events');
const generated='fixture @:/%#?& only';
process.env.RECOVERY_DB_PASSWORD=generated;process.env.REDIS_AUTH=generated;process.env.RECOVERY_COMPONENT='web';
require('child_process').spawn=(binary,args,options)=>{
 const u=new URL(options.env.DATABASE_URL),redis=new URL(options.env.REDIS_CONNECTION_STRING);
 if(binary!=='node'||args[0]!=='./web/server.js'||u.hostname!=='recovery-postgresql'||
 u.username!=='langfuse'||decodeURIComponent(u.password)!==generated||u.pathname!=='/langfuse'||
 options.env.DIRECT_URL!==options.env.DATABASE_URL||redis.hostname!=='recovery-valkey'||redis.username!=='default'||decodeURIComponent(redis.password)!==generated)process.exit(2);
 console.log('APP_URL_ENCODING_OK');return new EventEmitter();
};
'''
        result=subprocess.run(['node','-e',stub+js],capture_output=True,timeout=10)
        self.assertEqual((result.returncode,result.stdout),(0,b'APP_URL_ENCODING_OK\n'))
        self.assertNotIn(b'fixture',result.stdout)


@unittest.skipUnless(os.environ.get('LANGFUSE_RESTORE_NATIVE')=='1','explicit generated native fixture invocation only')
class NativeStartupTests(unittest.TestCase):
    """Reuse fixture.worker, original OCI roots, bwrap and cgroup checks.

    Execute in the existing fixture's bounded systemd user scope. Fixed paths are
    mapped beneath its /tmp/fixture mount, never production or confidential data.
    """
    def setUp(self):
        self.previous_umask=os.umask(0o077)

    def tearDown(self):
        os.umask(self.previous_umask)

    def native(self,engine,script):
        spec=importlib.util.spec_from_file_location('restore_native_shared',ROOT/'langfuse/recovery/fixture-pg-valkey.py')
        assert spec and spec.loader
        shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
        receipt={'postgres':'postgres-export/run-503d1e2f504f47c2b74c956a30ae678c',
                 'valkey':'pg-valkey/valkey/run-d39595a90b74441a95a3b4df9da3a4c4'}[engine]
        image=json.loads((r.CACHE/receipt/'image.json').read_text())
        self.assertEqual(image['index_digest'],r.IMAGES['postgresql' if engine=='postgres' else engine].split('@')[1])
        root=Path(image['rootfs']);before=shared.tree_hash(root)
        run=r.CACHE/('first-restore-native-'+engine+'-'+uuid.uuid4().hex);run.mkdir(mode=0o700)
        shared.save(run/'attempt.json',b'{"status":"INCOMPLETE","synthetic_only":true}\n')
        if engine=='postgres':shared.PG_SCRIPT=script
        else:shared.VALKEY_SCRIPT=script
        try:
            shared.worker(engine,root,run)
            self.assertEqual(shared.tree_hash(root),before)
            shared.save(run/'verified.json',json.dumps({'status':'PASS','synthetic_only':True,
             'restore_code_sha256':shared.sha(ROOT/'langfuse/recovery/first_restore.py'),
             'image_tree_before_after_sha256':before}).encode())
            print('FIRST_RESTORE_NATIVE_PASS '+str(run),flush=True)
        except BaseException:
            shared.save(run/'failure.json',b'{"status":"FAILED","synthetic_only":true}\n')
            print('FIRST_RESTORE_NATIVE_FAILED '+str(run),flush=True)
            raise

    def test_postgres_actual_restore_startup_scram(self):
        actual=re.sub(r'(?<![A-Za-z0-9_/])/restore\b','/tmp/fixture/restore',r.PG)
        actual=re.sub(r'(?<![A-Za-z0-9_/])/data\b','/tmp/fixture/data',actual)
        script=r'''set -eu
export PATH=/usr/lib/postgresql/18/bin:$PATH
umask 077
mkdir data restore
initdb -D /tmp/fixture/source --username=postgres --auth=trust --no-locale > source-init.private
pg_ctl -D /tmp/fixture/source -l source.private -o "-k /tmp/fixture -c listen_addresses=''" -w start
psql -X -h /tmp/fixture -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE langfuse LOGIN;
CREATE DATABASE langfuse OWNER langfuse;
SQL
psql -X -h /tmp/fixture -U postgres -d langfuse -v ON_ERROR_STOP=1 <<'SQL'
SET ROLE langfuse;
CREATE TABLE fixture_rows(id integer PRIMARY KEY);
INSERT INTO fixture_rows SELECT generate_series(1,1000);
SQL
pg_dumpall -h /tmp/fixture -U postgres --globals-only --no-role-passwords > restore/globals.sql
pg_dump -h /tmp/fixture -U postgres -d langfuse -Fc --create > restore/database.dump
pg_ctl -D /tmp/fixture/source -m fast -w stop
cat > target.sh <<'ACTUAL'
''' + actual + r'''
ACTUAL
export POSTGRES_PASSWORD='generated-admin-only' USERDB_PASSWORD='generated @:/%#?& only'
/bin/sh target.sh > target.private 2>&1 & target=$!
trap 'kill -TERM "$target" 2>/dev/null || true; wait "$target" 2>/dev/null || true' EXIT
export PGPASSWORD="$USERDB_PASSWORD"
ready=0
for i in $(seq 1 150); do
 kill -0 "$target"
 if test -f restore/native-restored && psql -XAt -h 127.0.0.1 -U langfuse -d langfuse -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM fixture_rows' > count.private 2>/dev/null; then ready=1; break; fi
 sleep .1
done
test "$ready" = 1; test "$(cat count.private)" = 1000
if PGPASSWORD=wrong psql -XAt -h 127.0.0.1 -U langfuse -d langfuse -c 'SELECT 1' >/dev/null 2>&1; then exit 1; fi
psql -XAt -h /tmp/fixture/restore -U restore_admin -d langfuse -c "SELECT count(*) FROM pg_hba_file_rules WHERE type='host' AND database=ARRAY['langfuse'] AND user_name=ARRAY['langfuse'] AND address='10.42.4.0' AND auth_method='scram-sha-256' AND error IS NULL" > hba-count.private
test "$(cat hba-count.private)" = 1
kill -TERM "$target"; wait "$target"; trap - EXIT
printf 'POSTGRES_NATIVE_RESTORE_PASS\n'
'''
        self.native('postgres',script)

    def test_clickhouse_actual_default_database_restore_entrypoint(self):
        fixture=r._module('fixture-clickhouse');fixture.bounds()
        image=json.loads((r.CACHE/'clickhouse/run-32bc69bb38ea49f59a0386de6582be21/image.json').read_text())
        self.assertEqual(image['index_digest'],r.IMAGES['clickhouse'].split('@')[1])
        root=Path(image['rootfs']);before=fixture.shared.tree_hash(root)
        run=r.CACHE/('first-restore-native-clickhouse-'+uuid.uuid4().hex);run.mkdir(mode=0o700)
        fixture.save(run/'attempt.json',b'{"status":"INCOMPLETE","synthetic_only":true}')
        try:
            fixture.PROLOGUE=fixture.PROLOGUE.replace('recovery_fixture','default')
            fixture.SOURCE=fixture.SOURCE.replace('CREATE DATABASE recovery_fixture ENGINE=Atomic','SELECT 1').replace('recovery_fixture','default')
            fixture.phase(root,run/'source','source')
            archive=run/'source/data/backups/fixture.tar'
            actual=re.sub(r'(?<![A-Za-z0-9_/])/restore\b','/tmp/fixture',r.CH)
            actual=actual.replace('/var/lib/clickhouse','/tmp/fixture/data').replace('cp /tmp/fixture/native.tar','cp /tmp/fixture/data/backups/fixture.tar')
            inventory=fixture.PROLOGUE[fixture.PROLOGUE.index('inventory() {'):]
            fixture.CONFIG=fixture.CONFIG.replace('</clickhouse>','<user_directories><users_xml><path>/tmp/fixture/users.xml</path></users_xml></user_directories></clickhouse>')
            fixture.PROLOGUE='';fixture.END=''
            fixture.RESTORE=r'''set -eu
umask 077
export CLICKHOUSE_CONFIG=/tmp/fixture/config.xml CLICKHOUSE_SKIP_USER_SETUP=1
cat > /tmp/fixture/target.sh <<'ACTUAL'
'''+actual+r'''
ACTUAL
/bin/sh /tmp/fixture/target.sh > /tmp/fixture/target.private 2>&1 & target=$!
trap 'kill -TERM "$target" 2>/dev/null || true; wait "$target" 2>/dev/null || true' EXIT
ready=0
for i in $(seq 1 200); do
 kill -0 "$target"
 if test -f /tmp/fixture/native-restored; then ready=1; break; fi
 sleep .1
done
test "$ready" = 1
cli() { clickhouse client --host=127.0.0.1 --port=9000 --query "$1"; }
'''+inventory+r'''
inventory
kill -TERM "$target"; wait "$target"; trap - EXIT
printf 'NATIVE_PHASE_PASS\n'
'''
            fixture.phase(root,run/'restore','restore',archive)
            for name in ('ddl.txt','database.txt','rows.txt','view.txt','migrations.txt','latest-migration.txt'):
                self.assertEqual((run/'source'/name).read_bytes(),(run/'restore'/name).read_bytes())
            self.assertEqual(fixture.shared.tree_hash(root),before)
            fixture.save(run/'verified.json',json.dumps({'status':'PASS','synthetic_only':True,
              'restore_code_sha256':fixture.sha(ROOT/'langfuse/recovery/first_restore.py'),
              'image_tree_before_after_sha256':before,'scope':'actual native default DB restore and original entrypoint; loopback fixture user config'}).encode())
            print('FIRST_RESTORE_NATIVE_PASS '+str(run),flush=True)
        except BaseException:
            fixture.save(run/'failure.json',b'{"status":"FAILED","synthetic_only":true}')
            print('FIRST_RESTORE_NATIVE_FAILED '+str(run),flush=True)
            raise

    def test_seaweed_actual_loader_held_and_cold_native_startup(self):
        fixture=r._module('fixture-seaweed')
        root=fixture.ENGINE/'image/root';before=fixture.tree(root)
        source=fixture.CACHE/'first-object-equivalence-309b8e499f6644a1bc1d7ce5c0c8a6d6/first-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        run=r.CACHE/('first-restore-native-seaweedfs-'+uuid.uuid4().hex);run.mkdir(mode=0o700)
        fixture.save(run/'attempt.json','{"status":"INCOMPLETE","synthetic_only":true}')
        restore=run/'restore';restore.mkdir(mode=0o700)
        body=io.BytesIO()
        with tarfile.open(fileobj=body,mode='w:') as archive:
            archive.add(source/'filer.meta.gz',arcname='filer-before.meta.gz')
            for path in sorted((source/'volumes').iterdir()):archive.add(path,arcname='volumes/'+path.name)
        blob=body.getvalue();fixture.save(restore/'native.tar',blob)
        metadata=fixture.records((source/'filer.meta.gz').read_bytes(),application_state=True)
        expected=r.seaweed_expected(blob,{'application_metadata':metadata})
        fixture.save(run/'generated-s3.json',json.dumps({'identities':[{'name':'generated-only','credentials':[
          {'accessKey':'generated-access','secretKey':'generated-secret'}],'actions':['Read','List']}]}))
        target=fixture.Sandbox(run,'target',root,application_s3=True)
        actual=re.sub(r'(?<![A-Za-z0-9_/])/restore\b','/data/restore',r.SW)
        actual=re.sub(r'(?<![A-Za-z0-9_/])/data\b','/data/target',actual)
        # Protect the fixture mount's /data/restore root from the data-dir mapping.
        actual=actual.replace('/data/target/restore','/data/restore')
        actual=actual.replace('/etc/sw/s3/seaweedfs_s3_config','/data/generated-s3.json')
        original_save=fixture.save
        def generated_start(path,data):
            if path.name=='target-start.sh':data='#!/bin/sh\nexport POD_IP=127.0.0.1\n'+actual
            return original_save(path,data)
        try:
            with patch.object(fixture,'save',side_effect=generated_start):target.start()
            def compare(label):
                actual_meta=target.export_meta(label)
                self.assertEqual(actual_meta,expected['application_metadata'])
                for item in expected['objects']:
                    data=target.http('http://127.0.0.1:8888/buckets/langfuse/'+item['key'])
                    self.assertEqual((len(data),hashlib.sha256(data).hexdigest()),(item['bytes'],item['sha256']))
                    # Independent real S3 SigV4 with generated-only identity.
                    import hmac
                    from datetime import datetime,timezone
                    from urllib.parse import quote
                    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');day=stamp[:8]
                    uri='/langfuse/'+quote(item['key'],safe='/-_.~');empty=hashlib.sha256(b'').hexdigest()
                    signed='host;x-amz-content-sha256;x-amz-date'
                    headers='host:127.0.0.1:8333\nx-amz-content-sha256:'+empty+'\nx-amz-date:'+stamp+'\n'
                    canonical='GET\n'+uri+'\n\n'+headers+'\n'+signed+'\n'+empty
                    scope=day+'/auto/s3/aws4_request'
                    to_sign='AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
                    key=b'AWS4generated-secret'
                    for part in (day,'auto','s3','aws4_request'):key=hmac.new(key,part.encode(),hashlib.sha256).digest()
                    auth='AWS4-HMAC-SHA256 Credential=generated-access/'+scope+', SignedHeaders='+signed+', Signature='+hmac.new(key,to_sign.encode(),hashlib.sha256).hexdigest()
                    url='http://127.0.0.1:8333'+uri
                    self.assertNotEqual(target.command(['/usr/bin/wget','-q','-T','3','-O','-',url]).returncode,0)
                    response=target.command(['/usr/bin/wget','-q','-T','3','-O','-',
                      '--header=Authorization: '+auth,'--header=X-Amz-Date: '+stamp,'--header=X-Amz-Content-Sha256: '+empty,url])
                    self.assertEqual(response.returncode,0)
                    self.assertEqual((len(response.stdout),hashlib.sha256(response.stdout).hexdigest()),(item['bytes'],item['sha256']))
            import time
            deadline=time.monotonic()+30;attempt=0
            while True:
                try:compare('live-'+str(attempt));break
                except AssertionError:
                    self.assertLess(time.monotonic(),deadline);attempt+=1;time.sleep(.1)
            self.assertEqual(target.command(['/bin/sh','-ec','kill -0 "$(cat /data/restore/loader.pid)"']).returncode,0)
            self.assertEqual(target.command(['touch','/data/restore/metadata-reconciled']).returncode,0)
            def cold_ready():
                fixture.need(target.command(['test','-f','/data/restore/native-restored']).returncode==0,'waiting-for-cold-marker')
                target.http('http://127.0.0.1:8888/')
                return True
            target.wait(cold_ready,120)
            deadline=time.monotonic()+120;attempt=0
            while True:
                try:compare('cold-'+str(attempt));break
                except (AssertionError,fixture.Refusal):
                    self.assertLess(time.monotonic(),deadline);attempt+=1;time.sleep(.2)
            fixture.jsave(run/'verified.json',{'status':'PASS','synthetic_only':True,
             'objects_verified':len(expected['objects']),'metadata_held_until_reconciled':True,'cold_restart':True,
             'restore_code_sha256':hashlib.sha256((ROOT/'langfuse/recovery/first_restore.py').read_bytes()).hexdigest()})
            print('FIRST_RESTORE_NATIVE_PASS '+str(run),flush=True)
        except BaseException:
            fixture.jsave(run/'failure.json',{'status':'FAILED','synthetic_only':True})
            print('FIRST_RESTORE_NATIVE_FAILED '+str(run),flush=True)
            raise
        finally:
            target.stop();self.assertEqual(fixture.tree(root),before)

    def test_transport_real_age_authentication_and_hash_binding(self):
        fixture=r._module('fixture-encryption');binaries=fixture.tools()
        run=r.CACHE/('first-restore-native-transport-'+uuid.uuid4().hex);run.mkdir(mode=0o700)
        fixture.new_file(run/'attempt.json',b'{"status":"INCOMPLETE","synthetic_only":true}')
        try:
            for name in ('generated.identity','wrong.identity'):
                fixture.require_success(fixture.native(binaries,run,'age-keygen',['-o','/fixture/'+name]))
            recipient=fixture.native(binaries,run,'age-keygen',['-y','/fixture/generated.identity'])
            fixture.require_success(recipient)
            plaintext=b'generated-only-native-archive-transport\x00'*1024
            fixture.new_file(run/'generated.bin',plaintext)
            fixture.require_success(fixture.native(binaries,run,'age',['-r',recipient.stdout.decode().strip(),'/fixture/generated.bin'],output=run/'archive.age'))
            cipher=(run/'archive.age').read_bytes()
            record={'status':'COMPLETE','ciphertext_bytes':len(cipher),'ciphertext_sha256':hashlib.sha256(cipher).hexdigest(),
                    'plaintext_bytes':len(plaintext),'plaintext_sha256':hashlib.sha256(plaintext).hexdigest()}
            fd=os.open(run/'archive.age',os.O_RDONLY|os.O_NOFOLLOW)
            identity=os.open(run/'generated.identity',os.O_RDONLY|os.O_NOFOLLOW)
            wrong=os.open(run/'wrong.identity',os.O_RDONLY|os.O_NOFOLLOW)
            try:
                self.assertEqual(r.decrypt_archive(fd,record,identity),plaintext)
                with self.assertRaises(r.Refused):r.decrypt_archive(fd,record,wrong)
                bad=dict(record,plaintext_sha256='0'*64)
                with self.assertRaises(r.Refused):r.decrypt_archive(fd,bad,identity)
                truncated=cipher[:-20];fixture.new_file(run/'truncated.age',truncated)
                short=os.open(run/'truncated.age',os.O_RDONLY|os.O_NOFOLLOW)
                try:
                    with self.assertRaises(r.Refused):r.decrypt_archive(short,dict(record,ciphertext_bytes=len(truncated),ciphertext_sha256=hashlib.sha256(truncated).hexdigest()),identity)
                finally:os.close(short)
            finally:
                for handle in (fd,identity,wrong):os.close(handle)
            fixture.new_file(run/'verified.json',json.dumps({'status':'PASS','synthetic_only':True,
              'real_age_authentication':True,'wrong_identity_rejected':True,'truncation_rejected':True,
              'plaintext_hash_mismatch_rejected':True,'restore_code_sha256':hashlib.sha256((ROOT/'langfuse/recovery/first_restore.py').read_bytes()).hexdigest()}).encode())
            print('FIRST_RESTORE_NATIVE_PASS '+str(run),flush=True)
        except BaseException:
            fixture.new_file(run/'failure.json',b'{"status":"FAILED","synthetic_only":true}')
            print('FIRST_RESTORE_NATIVE_FAILED '+str(run),flush=True)
            raise

    def test_valkey_actual_restore_startup_original_auth(self):
        spec=importlib.util.spec_from_file_location('restore_native_source',ROOT/'langfuse/recovery/fixture-pg-valkey.py')
        assert spec and spec.loader
        shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)
        seed=shared.VALKEY_SCRIPT.split('# Corrupt a separate synthetic copy')[0]
        seed=seed.replace(' cli DEBUG DIGEST',' # target typed readback does not need DEBUG')
        actual=r.VK.replace('/restore','/tmp/fixture/restore').replace('/data','/tmp/fixture/data')
        script=seed+r'''
umask 077
mkdir data restore
(cd checkpoint; sha256sum appendonlydir/*) > checkpoint/SHA256SUMS
tar -C checkpoint -cf restore/checkpoint.tar .
cat > target.sh <<'ACTUAL'
'''+actual+r'''
ACTUAL
export REDISCLI_AUTH='generated @:/%#?& only'
/bin/sh target.sh > target.private 2>&1 & target=$!
trap 'kill -TERM "$target" 2>/dev/null || true; wait "$target" 2>/dev/null || true' EXIT
cli() { valkey-cli -e --raw -h 127.0.0.1 "$@"; }
ready=0
for i in $(seq 1 100); do
 kill -0 "$target"
 if test "$(cli PING 2>/dev/null)" = PONG; then ready=1; break; fi
 sleep .1
done
test "$ready" = 1
if REDISCLI_AUTH=wrong valkey-cli -e --raw -h 127.0.0.1 PING >/dev/null 2>&1; then exit 1; fi
inventory > actual.txt
cmp expected.txt actual.txt
test "$(cli LLEN fixture:queue)" = 4
test "$(cli CONFIG GET maxmemory-policy | tail -n 1)" = noeviction
cli SHUTDOWN NOSAVE; wait "$target"; trap - EXIT
printf 'VALKEY_AOF_RESTORE_PASS\n'
'''
        self.native('valkey',script)


class RuntimeIntegrationTests(unittest.TestCase):
    def test_capacity_rejection_precedes_every_target_operation(self):
        with patch.object(r,'run_target') as execute:
            with self.assertRaisesRegex(r.Refused,'capacity-not-accepted'):
                r.restore_stores({}, {}, {}, {}, {}, {'runtime_and_replica_headroom_verified':False})
            execute.assert_not_called()

    def test_incomplete_capture_rejected_before_metadata_or_decryption(self):
        with patch.object(r,'read_metadata') as read,patch.object(r,'decrypt_archive') as decrypt:
            with self.assertRaisesRegex(r.Refused,'capture-marker-required'):
                r.stage_archives({}, {}, {}, {}, 3,seaweed_before={},seaweed_after={})
            read.assert_not_called();decrypt.assert_not_called()

    def test_target_identity_rejects_source_claim_host_network_and_uid_drift(self):
        from types import SimpleNamespace
        uid='00000000-0000-0000-0000-000000000001'
        for mutation in ('valid','source-claim','host-network','uid','restart'):
            volumes=[{'name':'data','persistentVolumeClaim':{'claimName':'recovery-postgresql'}}]
            identity=uid;network='';restarts='0'
            if mutation=='source-claim':volumes[0]['persistentVolumeClaim']['claimName']='postgres-data-langfuse-postgresql-0'
            if mutation=='host-network':network='true'
            if mutation=='uid':identity=next(iter(r.SOURCE_UIDS))
            if mutation=='restart':restarts='1'
            raw='|'.join((identity,'Running',r.IMAGES['postgresql'],restarts,'',json.dumps(volumes),network,'k3s-01')).encode()
            with self.subTest(mutation=mutation),patch.object(r.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=raw)):
                if mutation=='valid':r._target_identity('postgresql',uid)
                else:
                    with self.assertRaises(r.Refused):r._target_identity('postgresql',uid)

    def test_fixed_queue_adapter_is_real_readonly_registry_probe(self):
        code=r.queue_probe_code()
        self.assertIn('["recovery-valkey"]',code)
        self.assertNotIn('["langfuse-redis",',code)
        self.assertIn('EVAL_RO',code);self.assertIn('sourceRoots()',code)
        self.assertIn('source_tree_sha256',code)
        self.assertEqual(subprocess.run(['node','--check'],input=code.encode(),capture_output=True).returncode,0)

    def test_native_reconciliation_checks_exact_migrations_and_scheduled_counts(self):
        names=['20260101000000_Literal Name.sql']
        proof={'postgres_image_migrations':1,'postgres_applied_set_sha256':hashlib.sha256('\n'.join(names).encode()).hexdigest(),
               'clickhouse_latest_version':56,'clickhouse_latest_dirty':False}
        queue={'registry_sha256':'e52079e4004a907a42a870f16e46842956ff95e6f83c8d56be84dc00f9ad92f9',
               'scheduled_sha1':'ddef3c573a4990bc65863669cfeadc3e8c393c34','fingerprint_scope':r.QUEUE_SCOPE,
               'counts':dict.fromkeys(r._module('first_live_adapter').QUEUE_STATES,0)}
        queue['counts'].update(repeat=6,delayed=6,failed=23)
        observed=dict(queue,target_source_tree_sha256=r.QUEUE_TREES)
        integrity_response=[b'{"result":1}\n']
        def io(component,uid,args,**kwargs):
            if component=='postgresql':
                if args[0]=='pg_amcheck':return b''
                if args[-1].startswith('SELECT migration_name'):return ('\n'.join(names)+'\n').encode()
                return b'0\n'
            if component=='clickhouse':
                sql=args[-1]
                if sql=='SELECT version()':return b'26.8.36.3\n'
                if sql.startswith('SELECT version,dirty'):return b'56\t0\n'
                if sql.startswith('SELECT name,engine'):return b'{"name":"events","engine":"MergeTree"}\n'
                if sql.startswith('CHECK TABLE'):
                    self.assertIn('SETTINGS check_query_single_value_result=1 FORMAT JSONEachRow',sql)
                    return integrity_response[0]
            if component=='worker':
                r.validate_queue_state(json.loads(kwargs['data']))
                return json.dumps(observed).encode()
            self.fail('unexpected target-only command')
        uids={k:'generated-target-uid' for k in r.SCRIPTS}
        with patch.object(r,'run_target',side_effect=io):
            result=r.reconcile_databases(uids,{'migration_proof':proof},queue)
            self.assertTrue(result['queue_and_scheduler_counts_verified'])
            self.assertTrue(result['queue_canonical_fingerprint_verified'])
            self.assertEqual(result['target_queue_source_tree_sha256'],r.QUEUE_TREES)
            for state in queue['counts']:
                changed=json.loads(json.dumps(queue));changed['counts'][state]+=1
                with self.subTest(state=state),self.assertRaisesRegex(r.Refused,'scheduler-or-ttl-drift'):
                    r.reconcile_databases(uids,{'migration_proof':proof},changed)
            for field,value in [('scheduled_sha1','0'*40),('registry_sha256','0'*64)]:
                changed=dict(observed);changed[field]=value
                with patch.dict(observed,changed),self.assertRaisesRegex(r.Refused,'scheduler-or-ttl-drift'):
                    r.reconcile_databases(uids,{'migration_proof':proof},queue)
            for field,value in [('fingerprint_scope','wrong'),('target_source_tree_sha256',['0'*64]),
                                ('scheduled_sha1',True),('counts',dict(queue['counts'],wait=True))]:
                with patch.dict(observed,{field:value}),self.assertRaises(r.Refused):
                    r.reconcile_databases(uids,{'migration_proof':proof},queue)
            changed_proof=dict(proof,postgres_applied_set_sha256='0'*64)
            with self.assertRaisesRegex(r.Refused,'migration-set-differs'):
                r.reconcile_databases(uids,{'migration_proof':changed_proof},queue)
            # Empty/default per-part output, failure, bools, duplicate summaries
            # and unexpected fields cannot satisfy the pinned summary contract.
            for response in (b'',b'{"is_passed":1}\n',b'{"result":0}\n',
                             b'{"result":true}\n',b'{"result":1}\n{"result":1}\n',
                             b'{"result":1,"message":"unexpected"}\n'):
                integrity_response[0]=response
                with self.subTest(integrity_response=response),self.assertRaisesRegex(r.Refused,'table-integrity'):
                    r.reconcile_databases(uids,{'migration_proof':proof},queue)

    def test_generated_javascript_executes_only_canonical_eval_ro_and_fixed_db0(self):
        # Generated transport/source stubs only: this does not prove image or live IO.
        code=r.queue_probe_code()
        self.assertEqual(code.count('restoreQueueProbe();'),1)
        code=code.replace('restoreQueueProbe();','')
        stub=r'''
const a=require('assert');
let calls=0,constructed=0;
const names=['generated-a','generated-b'];
const expected={registry_sha256:digest(JSON.stringify(names))};
fs.readFileSync=(p)=>p===0?JSON.stringify(expected):'generated static source';
sourceRoots=()=>'/generated';
registry=(source,env)=>{a.strictEqual(source,'generated static source');
 return env.LANGFUSE_INGESTION_QUEUE_SHARD_COUNT==='2'?[...names,'generated-a-1']:names;};
a.strictEqual(digest(CAPTURE_LUA),'dda956242ceb79e9e1d8e1c2ca7729d1b09b37de82a09f1a40d30be9896e315e');
require=(name)=>{
 if(name!=='ioredis')throw Error('unexpected import');
 return class {
  constructor(o){constructed++;a.strictEqual(o.host,'recovery-valkey');a.strictEqual(o.port,6379);
   a.strictEqual(o.db,0);a.strictEqual(o.username,'default');a.strictEqual(o.password,'generated @:/ only');
   a.strictEqual(o.enableOfflineQueue,false);}
  on(){} async connect(){} async ping(){return 'PONG';} disconnect(){}
  async call(command,lua,n,...args){calls++;a.strictEqual(command,'EVAL_RO');
   a.strictEqual(lua,CAPTURE_LUA);a.strictEqual(n,0);a.deepStrictEqual(args,names);
   const values=[0,0,6,0,0,0,6,0,23,0,0,'b'.repeat(40)];
   if(MODE==='bool')values[0]=true;
   if(MODE==='float')values[0]=0.5;
   if(MODE==='negative')values[0]=-1;
   if(MODE==='overflow')values[0]=9007199254740992;
   if(MODE==='sha-type')values[11]=1;
   if(MODE==='short')values.pop();
   return values;
  }
 };
};
require.resolve=(n)=>{a.strictEqual(n,'ioredis');return n;};
process.env.REDIS_AUTH='generated @:/ only';
if(MODE==='shard')process.env.LANGFUSE_INGESTION_QUEUE_SHARD_COUNT='2';
if(MODE==='registry')expected.registry_sha256='0'.repeat(64);
restoreQueueProbe().then(()=>{
 a.strictEqual(calls,MODE==='shard'||MODE==='registry'?0:1);
 a.strictEqual(constructed,MODE==='shard'||MODE==='registry'?0:1);
}).catch(()=>process.exitCode=3);
'''
        for mode in ('valid','shard','registry','bool','float','negative','overflow','sha-type','short'):
            script=code+'\nconst MODE='+json.dumps(mode)+';\n'+stub
            env={k:v for k,v in os.environ.items() if not k.startswith(('REDIS_','LANGFUSE_'))}
            result=subprocess.run(['node','-e',script],env=env,capture_output=True,timeout=10)
            with self.subTest(mode=mode):
                self.assertEqual(result.returncode,0 if mode=='valid' else 1,'generated JS failed (diagnostics withheld)')
                self.assertEqual(result.stderr,b'')
                if mode=='valid':
                    value=json.loads(result.stdout)
                    self.assertEqual(value['scheduled_sha1'],'b'*40)
                    self.assertEqual(value['fingerprint_scope'],r.QUEUE_SCOPE)
                    self.assertEqual(value['target_source_tree_sha256'],r.QUEUE_TREES)
                    self.assertEqual(set(value['counts']),set(r._module('first_live_adapter').QUEUE_STATES))
                else:self.assertEqual(result.stdout,b'')

    def test_canonical_baseline_rejects_legacy_extra_missing_types_and_scope_before_io(self):
        original={'counts':dict.fromkeys(r._module('first_live_adapter').QUEUE_STATES,0),
                  'registry_sha256':'a'*64,'scheduled_sha1':'b'*40,'fingerprint_scope':r.QUEUE_SCOPE}
        mutations=[lambda q:q.update(schema=1),lambda q:q.update(queue_count=46),
                   lambda q:q.update(source_tree_sha256=r.QUEUE_TREES),lambda q:q.pop('scheduled_sha1'),
                   lambda q:q.update(fingerprint_scope='counts-only'),lambda q:q.update(registry_sha256=4),
                   lambda q:q.update(scheduled_sha1='B'*40),lambda q:q['counts'].pop('repeat'),
                   lambda q:q['counts'].update(wait=True),lambda q:q['counts'].update(wait=1.0),
                   lambda q:q['counts'].update(wait=-1),lambda q:q['counts'].update(wait=2**53),
                   lambda q:q['counts'].update(extra=0)]
        for mutate in mutations:
            value=json.loads(json.dumps(original));mutate(value)
            with patch.object(r,'run_target') as execute,self.assertRaises(r.Refused):
                r.reconcile_databases({}, {}, value)
            execute.assert_not_called()


class ArchivedSeaweedMetadataTests(unittest.TestCase):
    def files(self):
        directory={'Topology':{'DataCenters':[{'Racks':[{'DataNodes':[{'Url':'192.0.2.1:8080'}]}]}]}}
        return {label+'-'+kind+'.json':json.dumps(directory if kind=='directory' else {'generated':kind}).encode()
                for label in ('before','after') for kind in ('directory','master','local')}

    def blob(self,files,extra=None):
        # Production members have no ./ prefix; use only generated metadata here.
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:') as tf:
            for name,body in files.items():
                member=tarfile.TarInfo(name);member.size=len(body);tf.addfile(member,io.BytesIO(body))
            if extra is not None:tf.addfile(extra)
        return out.getvalue()

    def test_archive_admissions_precede_full_existing_validator(self):
        from types import SimpleNamespace
        calls=[]
        def admit(directory,master,local,ip):
            self.assertEqual(ip,'192.0.2.1');calls.append('admit')
            return {'directory':directory,'master':master,'local':local}
        def validate(blob,*,before,after):
            self.assertEqual(calls,['admit','admit']);self.assertEqual(before,after)
            calls.append('validate');return {'application_metadata':{'generated':b'only'}}
        objects=SimpleNamespace(admit_seaweed=admit,validate_seaweed_archive=validate)
        with patch.object(r,'_module',return_value=objects),patch.object(r,'run_target') as live:
            before,after,validation=r.archived_seaweed_metadata(self.blob(self.files()))
        live.assert_not_called();self.assertEqual(before,after)
        self.assertEqual(validation,{'application_metadata':{'generated':b'only'}})
        self.assertEqual(calls,['admit','admit','validate'])

    def test_malformed_archive_metadata_rejected_before_admission(self):
        for mutation in ('missing','duplicate','directory','link','oversize','json-list','json-duplicate','invalid-json','path','truncated'):
            files=self.files();extra=None;name='before-local.json'
            if mutation=='missing':del files[name]
            if mutation in ('duplicate','directory','link'):
                extra=tarfile.TarInfo(name)
                if mutation!='duplicate':
                    del files[name];extra.type=tarfile.DIRTYPE if mutation=='directory' else tarfile.SYMTYPE
            if mutation=='oversize':files[name]=b' '* (1024**2+1)
            if mutation=='json-list':files[name]=b'[]'
            if mutation=='json-duplicate':files[name]=b'{"x":1,"x":2}'
            if mutation=='invalid-json':files[name]=b'not json'
            if mutation=='path':files['../unexpected']=b'{}'
            blob=self.blob(files,extra)
            if mutation=='truncated':blob=blob[:1000]
            with self.subTest(mutation=mutation),patch.object(r,'_module') as module,self.assertRaises(r.Refused):
                r.archived_seaweed_metadata(blob)
            module.assert_not_called()

    def test_full_validator_failure_is_not_accepted(self):
        from types import SimpleNamespace
        objects=SimpleNamespace(admit_seaweed=lambda *args:{},
                                validate_seaweed_archive=lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('private')))
        with patch.object(r,'_module',return_value=objects),self.assertRaisesRegex(r.Refused,'archived-seaweed-metadata-invalid'):
            r.archived_seaweed_metadata(self.blob(self.files()))

    def test_partial_explicit_admission_rejected_before_any_io(self):
        with patch.object(r,'read_metadata') as read,self.assertRaisesRegex(r.Refused,'admission-pair-required'):
            r.stage_archives({}, {}, {}, {}, 3,seaweed_before={})
        read.assert_not_called()

    def test_staging_uses_archive_metadata_only_after_authenticated_decrypt(self):
        from types import SimpleNamespace
        components=('postgres-database','postgres-globals','clickhouse','seaweedfs','valkey')
        operation='first-generated-only'
        manifest={'scope':'coordinated-native-encrypted-capture-not-restore','identity_bundle_ref':r.IDENTITY,
                  'operation_id':operation,'components':[{'component':c,'exclusive':True,'durable':True,
                  'bytes':1,'sha256':'a'*64,'name':operation+'-'+c+'.age'} for c in components]}
        records={c:{'ciphertext_bytes':1,'ciphertext_sha256':'a'*64} for c in components}
        fds={c:i for i,c in enumerate(components,10)}
        streams={'postgres-database':b'PGDMP-generated','postgres-globals':b'CREATE ROLE generated;',
                 'clickhouse':b'generated-ch','seaweedfs':b'generated-sw','valkey':b'generated-vk'}
        events=[];received={}
        def decrypt(fd,record,identity):
            component=next(c for c in components if fds[c]==fd)
            events.append('decrypt-'+component);return streams[component]
        def metadata(blob):
            self.assertEqual(events[-1],'decrypt-seaweedfs');self.assertEqual(blob,b'generated-sw')
            events.append('archive-admission');return {},{}, {'application_metadata':{}}
        def target(component,uid,args,**kwargs):
            if 'data' in kwargs:received[component]=kwargs['data'];return b''
            if args[0]=='pg_restore':return b''
            blob=received[component]
            return (str(len(blob))+'\n'+hashlib.sha256(blob).hexdigest()+'  /restore/generated\n').encode()
        objects=SimpleNamespace(validate_clickhouse_archive=lambda blob:None)
        with patch.object(r,'_module',return_value=objects),patch.object(r,'read_metadata',return_value=[]),\
             patch.object(r,'admit_target_storage'),patch.object(r,'decrypt_archive',side_effect=decrypt),\
             patch.object(r,'archived_seaweed_metadata',side_effect=metadata) as archived,\
             patch.object(r,'seaweed_expected',return_value={'generated':True}),patch.object(r,'validate_valkey_archive'),\
             patch.object(r,'run_target',side_effect=target),patch.object(r,'_cipher_identity'):
            receipt,private=r.stage_archives(manifest,records,fds,dict.fromkeys(r.SCRIPTS,'generated-uid'),3)
        archived.assert_called_once_with(b'generated-sw')
        self.assertFalse(receipt['stores_started']);self.assertEqual(private,{'generated':True})
        self.assertEqual(set(receipt['staged']),set(components))


class IdentityTests(unittest.TestCase):
    def test_only_type_data_name_namespace_copied(self):
        outputs=r.identity_resources(synthetic_identity())
        self.assertEqual(len(outputs),6)
        for value in outputs:
            self.assertEqual(set(value),{'apiVersion','kind','metadata','type','data'})
            self.assertEqual(set(value['metadata']),{'name','namespace'})
            self.assertEqual(value['metadata']['namespace'],r.NAMESPACE)

    def test_malformed_identity_rejected_without_echo(self):
        for mutation in ('namespace','duplicate','missing-key','invalid-base64','wrong-type'):
            source=synthetic_identity()
            if mutation=='namespace':source['items'][0]['metadata']['namespace']='unrelated'
            elif mutation=='duplicate':source['items'][-1]=source['items'][0]
            elif mutation=='missing-key':source['items'][0]['data']={}
            elif mutation=='invalid-base64':source['items'][0]['data'][next(iter(source['items'][0]['data']))]='PRIVATE INVALID DATA'
            elif mutation=='wrong-type':source['items'][0]['type']='kubernetes.io/tls'
            with self.subTest(mutation=mutation),self.assertRaises(r.Refused) as caught:r.identity_resources(source)
            self.assertNotIn('PRIVATE',str(caught.exception))


class VolumeTests(unittest.TestCase):
    def test_four_new_dynamic_two_replica_volumes(self):
        self.assertEqual(r.admit_target_storage(*storage()),{'new_claims':4,'distinct_new_handles':4,'two_replicas':True})

    def test_every_source_uid_rejected(self):
        for uid in r.SOURCE_UIDS:
            inputs=storage();inputs[0][0]['metadata']['uid']=uid
            with self.subTest(uid=uid),self.assertRaises(r.Refused):r.admit_target_storage(*inputs)

    def test_every_source_handle_rejected(self):
        for uid in r.SOURCE_UIDS:
            inputs=storage();inputs[1][0]['spec']['csi']['volumeHandle']='pvc-'+uid
            with self.subTest(uid=uid),self.assertRaises(r.Refused):r.admit_target_storage(*inputs)

    def test_bad_storage_bindings_rejected(self):
        for mutation in ('wrong-namespace','claim-ref','replicas','degraded','prepopulated','wrong-size','owner','shared-handle'):
            pvcs,pvs,vols=storage()
            if mutation=='wrong-namespace':pvcs[0]['metadata']['namespace']='langfuse'
            elif mutation=='claim-ref':pvs[0]['spec']['claimRef']['namespace']='langfuse'
            elif mutation=='replicas':vols[0]['spec']['numberOfReplicas']=1
            elif mutation=='degraded':vols[0]['status']['robustness']='degraded'
            elif mutation=='prepopulated':pvcs[0]['spec']['dataSource']={'kind':'VolumeSnapshot','name':'production'}
            elif mutation=='wrong-size':pvcs[0]['spec']['resources']['requests']['storage']='1Gi'
            elif mutation=='owner':pvcs[0]['metadata']['ownerReferences']=[{'uid':'production'}]
            elif mutation=='shared-handle':pvs[1]['spec']['csi']['volumeHandle']=pvs[0]['spec']['csi']['volumeHandle']
            with self.subTest(mutation=mutation),self.assertRaises(r.Refused):r.admit_target_storage(pvcs,pvs,vols)

    @patch.object(r,'read_metadata')
    def test_existing_namespace_never_adopted(self,read):
        read.return_value=[{'metadata':{'name':r.NAMESPACE}}]
        with self.assertRaisesRegex(r.Refused,'already-exists'):r.admission()
        read.assert_called_once_with('namespaces')


class ValkeySchemaTests(unittest.TestCase):
    def test_complete_actual_outer_schema(self):
        # Structural validation only: fake generated base is NOT native integrity.
        self.assertEqual(r.validate_valkey_archive(archive(valkey_files()))['dependencies'],2)

    def test_corruption_and_missing_dependencies(self):
        for mutation in ('hash','missing','extra','manifest','truncated','trailing','duplicate'):
            files=valkey_files()
            if mutation=='hash':files['appendonlydir/appendonly.aof.1.base.rdb']+=b'x'
            elif mutation=='missing':del files['appendonlydir/appendonly.aof.1.incr.aof']
            elif mutation=='extra':files['unexpected']=b'x'
            elif mutation=='manifest':files['appendonlydir/appendonly.aof.manifest']=b'file ../../escape seq 1 type b\n'
            blob=archive(files,tarfile.TarInfo('./SHA256SUMS') if mutation=='duplicate' else None)
            if mutation=='truncated':blob=blob[:1000]
            elif mutation=='trailing':blob+=archive({'hidden':b'x'})
            with self.subTest(mutation=mutation),self.assertRaises(r.Refused):r.validate_valkey_archive(blob)

    def test_links_and_traversal_rejected(self):
        for name,kind in (('../escape',tarfile.REGTYPE),('evil-link',tarfile.SYMTYPE),('hard-link',tarfile.LNKTYPE)):
            member=tarfile.TarInfo(name);member.type=kind;member.linkname='/etc/passwd'
            with self.subTest(name=name),self.assertRaises(r.Refused):r.validate_valkey_archive(archive(valkey_files(),member))


if __name__=='__main__':unittest.main()
