"""Generated orchestration/receiver fixtures; NO production IO or existing keys.

Real WriterGuard + capture_stream + age + receiver filesystem publication run.
Sources, all-writer evidence and native semantic parser are synthetic boundaries;
these tests are not native datastore acceptance or production adapter admission.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('tested_first_capture', ROOT/'langfuse/recovery/first_capture.py')
assert SPEC is not None and SPEC.loader is not None
c = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = c
SPEC.loader.exec_module(c)
# Reuse already exercised synthetic evidence/fence, not another production adapter.
FIXTURE_SPEC = importlib.util.spec_from_file_location('first_capture_synthetic_guard', Path(__file__).with_name('test_langfuse_writer_guard.py'))
assert FIXTURE_SPEC is not None and FIXTURE_SPEC.loader is not None
fake = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(fake)
setattr(fake, 'w', c.writer)


def py(script, *args):
    return (sys.executable, '-c', script, *map(str, args))


class PodListResourceVersionTests(unittest.TestCase):
    def test_server_podlist_rv_is_preserved_without_generic_cli_printer(self):
        response={'apiVersion':'v1','kind':'PodList',
                  'metadata':{'resourceVersion':'20630765'},'items':[]}
        with patch.object(c,'run',return_value=json.dumps(response)) as run:
            self.assertEqual(c.get('pods','',123),response)
        run.assert_called_once_with(['kubectl','--request-timeout=20s','get','--raw',
                                     '/api/v1/namespaces/langfuse/pods'],123)

    def test_snapshot_or_incomplete_list_cannot_become_watch_baseline(self):
        for rv in (None,'','0','not-numeric'):
            response={'kind':'PodList','metadata':{'resourceVersion':rv},'items':[]}
            with self.subTest(rv=rv), patch.object(c,'run',return_value=json.dumps(response)):
                with self.assertRaisesRegex(c.Refused,'pod-list-resource-version'):
                    c.get('pods','',123)
        for kind,continuation in (('List',''),('PodList','next-page')):
            response={'kind':kind,'metadata':{'resourceVersion':'20630765',
                                            'continue':continuation},'items':[]}
            with self.subTest(kind=kind,continuation=continuation), patch.object(c,'run',return_value=json.dumps(response)):
                with self.assertRaisesRegex(c.Refused,'pod-list-resource-version'):
                    c.get('pods','',123)


class FirstCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='generated-first-capture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root/'local'; self.local.mkdir(mode=0o700)
        self.nas = self.root/'simulated-nas'; self.nas.mkdir(mode=0o700)
        self.fd = os.open(self.local, os.O_RDONLY|os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.age = shutil.which('age') or str(ROOT/'verification/cache/langfuse-recovery/encryption/age')
        keygen = shutil.which('age-keygen') or str(Path(self.age).with_name('age-keygen'))
        if not Path(self.age).is_file() or not Path(keygen).is_file():
            self.fail('Real age/age-keygen prerequisite missing; do not silently skip coordinator roundtrip')
        # Fresh generated-only identity in anonymous RAM; never open an existing key.
        generated = subprocess.run([keygen], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout
        self.recipient = subprocess.run([keygen, '-y'], input=generated, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, check=True).stdout.decode().strip()
        self.identity = os.memfd_create('generated-coordinator-fixture-identity', os.MFD_CLOEXEC)
        os.write(self.identity, generated); os.lseek(self.identity, 0, os.SEEK_SET)
        self.addCleanup(os.close, self.identity)
        self.clock = fake.SyntheticClock(); self.clock.now = time.monotonic()
        self.api = fake.SyntheticAPI(self.clock)
        self.approval = c.writer.Approval('fixture-first-capture','synthetic-approval',self.recipient,
            'synthetic-generated-only-custody','/storage/k3s/langfuse/recovery/first-fixture',
            'synthetic-client-idle',self.clock()+600)
        self.journal = c.writer.Journal(self.local/'journal.jsonl')
        self.addCleanup(self.journal.close)
        self.guard = c.writer.WriterGuard(self.api,self.journal,self.approval,
            tuple(copy.deepcopy(self.api.objects[n]) for n in c.writer.TARGETS),timeout=120,
            drain_timeout=1,poll_interval=.1,clock=self.clock,sleep=self.clock.sleep)
        self.payloads = {}; self.plan = []
        for component in c.COMPONENTS:
            payload = json.dumps({'generated_fixture':component,'rows':[1,2,3]}).encode()
            self.payloads[component] = payload
            path = self.root/(component+'.generated')
            stage = py('import os,sys; f=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); os.write(f,sys.argv[2].encode()); os.close(f)',path,payload.decode())
            proof = py('import pathlib,hashlib,sys; b=pathlib.Path(sys.argv[1]).read_bytes(); print(len(b)); print(hashlib.sha256(b).hexdigest())',path)
            producer = py('import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())',path)
            self.plan.append((component,{'fixture':component},stage,proof,producer))
        self.checked=[]; self.validated=[]; self.remote=[]
        self.source_patch=patch.object(c,'_source_check',side_effect=lambda source,deadline:self.checked.append(source))
        self.source_patch.start(); self.addCleanup(self.source_patch.stop)
        def isolated_receiver(directory,name,size,digest,mode):
            self.remote.append((name,mode))
            return py(c.NAS_PROGRAM,self.nas,name,size,digest,mode)
        self.nas_patch=patch.object(c,'_nas_argv',side_effect=isolated_receiver)
        self.nas_patch.start(); self.addCleanup(self.nas_patch.stop)

    def verify_native(self,component,directory_fd,name,proof,checkpoint,deadline):
        # A real decrypt + generated schema check, NOT a datastore native parser.
        checkpoint()
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
        try:
            decoded=subprocess.run([self.age,'-d','-i','/proc/self/fd/'+str(self.identity)],
                stdin=fd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                pass_fds=(self.identity,),timeout=max(.01,deadline-time.monotonic()),check=True).stdout
        finally: os.close(fd)
        self.assertEqual(decoded,self.payloads[component])
        self.assertEqual(proof,{'bytes':len(decoded),'sha256':hashlib.sha256(decoded).hexdigest()})
        self.validated.append(component)
        checkpoint()
        return True

    def inputs(self,**changes):
        result=dict(guard=self.guard,plan=tuple(self.plan),directory_fd=self.fd,
                    age_binary=self.age,recipient=self.recipient,identity_fd=self.identity,
                    nas_directory=self.approval.destination_ref,identity_bundle_ref=c.IDENTITY_BUNDLE,
                    verify_native=self.verify_native)
        result.update(changes)
        return result

    def run_capture(self,**changes):
        return c.capture_first(**self.inputs(**changes))

    def test_public_command_real_encryption_publication_and_explicit_resume(self):
        stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code=c.main(['--capture'],capture_inputs=self.inputs())
        self.assertEqual(code,0)
        result=json.loads(stdout.getvalue())
        self.assertEqual(result['status'],'CAPTURED')
        self.assertEqual([v['component'] for v in result['components']],list(c.COMPONENTS))
        self.assertEqual(self.validated,list(c.COMPONENTS))
        self.assertFalse(result['recovery_accepted'])
        self.assertEqual(self.api.writes,[('langfuse-web',0),('langfuse-worker',0)])
        self.assertTrue(self.api.fence_object.finished)
        manifest=json.loads((self.nas/result['manifest']).read_text())
        self.assertEqual(manifest['identity_bundle_ref'],c.IDENTITY_BUNDLE)
        for publication in result['components']:
            data=(self.nas/publication['name']).read_bytes()
            self.assertTrue(data.startswith(b'age-encryption.org/v1'))
            self.assertEqual(hashlib.sha256(data).hexdigest(),publication['sha256'])
            self.assertIn((publication['name'],'read'),self.remote)
            self.assertEqual(stat.S_IMODE((self.nas/publication['name']).stat().st_mode),0o600)
            remote_receipt=publication['complete_receipt']
            record_bytes=(self.nas/remote_receipt['name']).read_bytes()
            self.assertEqual(hashlib.sha256(record_bytes).hexdigest(),remote_receipt['sha256'])
            self.assertEqual(json.loads(record_bytes)['plaintext_sha256'],publication['plaintext_sha256'])
        self.assertEqual(self.guard.resume().state,'RESUMED')
        self.assertEqual(self.api.writes[-2:],[('langfuse-web',2),('langfuse-worker',1)])
        with self.assertRaises(c.Refused): self.run_capture()

    def test_missing_request_standalone_refuses_before_any_commands(self):
        with patch.object(c,'_command') as command,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(c.main(['--capture']),2)
            command.assert_not_called()
        self.assertEqual(self.api.writes,[])

    def test_input_gates_before_pause(self):
        for changes in ({'plan':self.plan[:-1]}, {'verify_native':None},
                        {'identity_bundle_ref':'wrong'}, {'recipient':'wrong'},
                        {'identity_fd':-1}):
            with self.subTest(changes=list(changes)),self.assertRaises(c.Refused):
                self.run_capture(**changes)
        self.assertEqual(self.api.writes,[])

    def test_drain_timeout_does_not_export_or_resume(self):
        self.api.drain=False
        result=self.run_capture()
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertEqual(self.api.writes,[('langfuse-web',0)])
        self.assertEqual(self.validated,[])
        self.assertFalse(any(self.nas.iterdir()))
        self.assertEqual(self.guard.resume().state,'RESUMED')

    def test_encryption_failure_never_calls_validator_or_nas(self):
        result=self.run_capture(age_binary='/bin/false')
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertEqual(self.validated,[])
        self.assertFalse(any(self.nas.iterdir()))
        self.assertTrue(list(self.local.glob('*.incomplete.json')))
        self.assertFalse(list(self.local.glob('*.age')))

    def test_fence_finish_failure_never_publishes_set_marker(self):
        with patch.object(self.api.fence_object,'finish',return_value=False):
            result=self.run_capture()
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertFalse(result['guard']['capture_complete'])
        self.assertEqual(result['guard']['reason'],'writer_exclusion_lost')
        self.assertEqual(len(result['components']),5)
        self.assertFalse(list(self.nas.glob('*capture.json')))

    def test_private_identity_descriptor_is_decrypt_only(self):
        original=c.stream.capture; seen=[]
        def inspected(**kwargs):
            self.assertEqual(kwargs['decrypt_pass_fds'],(self.identity,))
            for role in ('producer','age','sink'):
                self.assertNotIn(self.identity,kwargs.get(role+'_pass_fds',()))
            seen.append(kwargs['producer_argv'])
            return original(**kwargs)
        with patch.object(c.stream,'capture',side_effect=inspected): result=self.run_capture()
        self.assertEqual(result['status'],'CAPTURED')
        self.assertEqual(len(seen),5)

    def test_native_validator_false_leaves_incomplete_no_remote_publication(self):
        result=self.run_capture(verify_native=lambda *args:False)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertFalse(result['guard']['capture_complete'])
        self.assertFalse(any(self.nas.iterdir()))
        self.assertEqual(len(self.api.writes),2)
        self.assertTrue(list(self.local.glob('*.age')))

    def test_transient_writer_loss_during_validator_blocks_publication(self):
        def lost(*args):
            self.api.fence_object.lost=True
            return True
        result=self.run_capture(verify_native=lost)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertEqual(result['guard']['reason'],'writer_exclusion_lost')
        self.assertFalse(any(self.nas.iterdir()))

    def test_remote_no_overwrite_collision_preserves_existing_file(self):
        target=self.nas/(self.approval.operation_id+'-'+c.COMPONENTS[0]+'.age')
        target.write_bytes(b'existing-ciphertext-fixture'); target.chmod(0o600)
        result=self.run_capture()
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertEqual(target.read_bytes(),b'existing-ciphertext-fixture')
        self.assertFalse(list(self.nas.glob('*capture.json')))

    def test_remote_readback_failure_is_not_capture_success(self):
        original=c._command
        def failed_read(argv,deadline,**options):
            if c.NAS_PROGRAM in argv and argv[-1]=='read':
                raise RuntimeError('SENSITIVE PROVIDER ERROR')
            return original(argv,deadline,**options)
        with patch.object(c,'_command',side_effect=failed_read): result=self.run_capture()
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertNotIn('SENSITIVE',json.dumps(result))
        self.assertFalse(list(self.nas.glob('*capture.json')))

    def test_manifest_collision_marks_set_incomplete_even_after_fence_finish(self):
        name=self.approval.operation_id+'-capture.json'
        (self.nas/name).write_bytes(b'existing-fixture')
        result=self.run_capture()
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertTrue(result['guard']['capture_complete'])
        self.assertEqual(result['reason'],'capture-marker-publication-incomplete')
        self.assertEqual((self.nas/name).read_bytes(),b'existing-fixture')
        self.assertEqual(len(result['components']),5)
        self.assertEqual(self.guard.resume().state,'RESUMED')

    def test_source_proof_changed_after_all_exports_blocks_set_marker(self):
        original=c._command; calls={}
        def changed(argv,deadline,**options):
            out=original(argv,deadline,**options)
            if argv==self.plan[0][3]:
                calls['proof']=calls.get('proof',0)+1
                if calls['proof']==2: return b'1\n'+b'0'*64+b'\n'
            return out
        with patch.object(c,'_command',side_effect=changed): result=self.run_capture()
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertFalse(list(self.nas.glob('*capture.json')))
        self.assertEqual(len(result['components']),5)

    def test_receiver_truncation_is_incomplete_and_private(self):
        result=subprocess.run(py(c.NAS_PROGRAM,self.nas,'broken.age',5,'0'*64,'write'),
                              input=b'abc',stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.nas/'broken.age').exists())
        self.assertEqual((self.nas/'broken.age.partial').read_bytes(),b'abc')
        self.assertEqual(stat.S_IMODE((self.nas/'broken.age.partial').stat().st_mode),0o600)

    def test_receiver_symlink_directory_and_occupied_partial_refuse(self):
        alias=self.root/'alias'; alias.symlink_to(self.nas,target_is_directory=True)
        digest=hashlib.sha256(b'abc').hexdigest()
        for directory,name in ((alias,'one.age'),(self.nas,'two.age')):
            if name=='two.age': (self.nas/'two.age.partial').symlink_to(self.root/'unrelated')
            result=subprocess.run(py(c.NAS_PROGRAM,directory,name,3,digest,'write'),input=b'abc',
                                  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((self.nas/name).exists())
        self.assertFalse((self.root/'unrelated').exists())


class NativePlanTests(unittest.TestCase):
    def test_uses_fixed_native_builders_and_retains_every_volume(self):
        spec=importlib.util.spec_from_file_location('coordinator_seaweed_fixture',Path(__file__).with_name('test_langfuse_recovery_seaweed_inventory.py'))
        assert spec is not None and spec.loader is not None
        fixture=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        directory,master,local=fixture.fixture()
        local['DiskStatuses']=[dict(dir='/data',all=1000000,used=100,free=999900,percent_free=99,percent_used=1)]
        admitted=c.objects.admit_seaweed(directory,master,local,'127.0.0.2')
        common=dict(uid='00000000-0000-0000-0000-000000000001',ready='true',phase='Running',deleting='<none>')
        pods={
            'postgresql':dict(common,name=c.postgres.POD,container='postgresql',image=c.postgres.IMAGE),
            'clickhouse':dict(common,name='langfuse-clickhouse-0',container='clickhouse',image=c.objects.CH_IMAGE),
            'seaweedfs':dict(common,name='langfuse-s3-abc-123',container='seaweedfs',image=c.objects.SW_IMAGE)}
        helper=dict(common,name='langfuse-recovery-valkey-fixture',container='capture',image=
                    'docker.io/valkey/valkey:8.0@sha256:'+c.preflight.IMAGE_DIGESTS['langfuse-redis'])
        budgets=dict.fromkeys(('postgresql','clickhouse','seaweedfs','valkey'),1024**2)
        qualified_pg=dict(pods['postgresql'],image='docker.io/'+c.postgres.IMAGE)
        self.assertTrue(all(e.source_image==qualified_pg['image'] for e in c.postgres.build(qualified_pg)))
        pods['postgresql']=qualified_pg
        plan=c.native_plan(pods,helper,'a'*32,budgets,admitted,c.objects.SEAWEED_SCOPE)
        self.assertEqual(tuple(p[0] for p in plan),c.COMPONENTS)
        self.assertIn(c.postgres.DUMP_SHELL,plan[0][2][-1])
        self.assertIn(c.postgres.GLOBALS_SHELL,plan[1][2][-1])
        self.assertIn('BACKUP DATABASE default',plan[2][2][-1])
        self.assertIn('langfuse_1.dat',plan[3][2][-1])
        self.assertIn('source-before.sha256',plan[3][3][-1])
        # Exact unchanged Valkey fragment is shell-quoted, not rewritten.
        import shlex
        self.assertIn(shlex.quote(c.valkey.shell_fragment()),plan[4][2][-1])
        self.assertNotIn('valkey-check-aof --fix',plan[4][2][-1])
        prepared_helper=dict(helper,name='langfuse-first-capture-4e244d488354-4wdfn',container='capture-helper')
        prepared_plan=c.native_plan(pods,prepared_helper,'a'*32,budgets,admitted,c.objects.SEAWEED_SCOPE)
        helper_argv=prepared_plan[4][2]
        self.assertEqual(helper_argv[helper_argv.index('exec')+1],prepared_helper['name'])
        self.assertEqual(helper_argv[helper_argv.index('-c')+1],'capture-helper')
        for bad in (dict(prepared_helper,container='unreviewed'),
                    dict(prepared_helper,name='unreviewed-helper')):
            with self.assertRaisesRegex(c.Refused,'valkey-helper-not-admitted'):
                c.native_plan(pods,bad,'a'*32,budgets,admitted,c.objects.SEAWEED_SCOPE)
        for component,source,stage,validate,producer in plan:
            for command in (stage,validate,producer):
                script=command[-1]
                result=subprocess.run(['/bin/sh','-n'],input=script.encode(),stderr=subprocess.PIPE)
                self.assertEqual(result.returncode,0,(component,result.stderr.decode()))
        with self.assertRaises(c.objects.Refused):
            c.native_plan(pods,helper,'a'*32,budgets,admitted,{})


class NativeStageModeTests(unittest.TestCase):
    """Execute generated filesystem fragments locally; no kubectl/native service IO."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='generated-stage-modes-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root/'setgid-parent'
        self.parent.mkdir(mode=0o700); self.parent.chmod(0o2700)
        self.parent_identity = self.identity(self.parent)
        self.uid = str(os.getuid())

    @staticmethod
    def identity(path):
        s = path.lstat()
        return s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid

    def shell(self, script, *, cwd=None):
        result = subprocess.run(c.objects._shell(script), cwd=cwd, capture_output=True, timeout=5)
        self.assertEqual(self.identity(self.parent), self.parent_identity)
        return result

    def plan(self):
        _, admitted = native_structure_fixtures()
        common = dict(uid='00000000-0000-0000-0000-000000000001',ready='true',phase='Running',deleting='<none>')
        pods = {'postgresql':dict(common,name=c.postgres.POD,container='postgresql',image=c.postgres.IMAGE),
                'clickhouse':dict(common,name='langfuse-clickhouse-0',container='clickhouse',image=c.objects.CH_IMAGE),
                'seaweedfs':dict(common,name='langfuse-s3-abc-123',container='seaweedfs',image=c.objects.SW_IMAGE)}
        helper = dict(common,name='langfuse-recovery-valkey-fixture',container='capture',
                      image='docker.io/valkey/valkey:8.0@sha256:'+c.preflight.IMAGE_DIGESTS['langfuse-redis'])
        budgets = dict.fromkeys(('postgresql','clickhouse','seaweedfs','valkey'),1024**2)
        return pods, helper, budgets, admitted

    def test_host_reproduces_inheritance_and_new_leaf_correction(self):
        raw = self.parent/'raw'
        self.assertEqual(self.shell('mkdir -m 700 '+str(raw)).returncode, 0)
        self.assertEqual(stat.S_IMODE(raw.stat().st_mode), 0o2700)
        self.assertNotEqual(self.shell(c.objects._private_path_checks(str(raw))).returncode, 0)
        # Existing inherited-setgid stage is refused, never repaired.
        before = self.identity(raw)
        self.assertNotEqual(self.shell(c.objects._new_private_directory(str(raw))).returncode, 0)
        self.assertEqual(self.identity(raw), before)

    def test_actual_pg_stages_both_exports_under_setgid(self):
        import shlex
        pods, helper, budgets, admitted = self.plan()
        plan = c.native_plan(pods,helper,'a'*32,budgets,admitted,c.objects.SEAWEED_SCOPE)
        for entry, export in zip(plan[:2], c.postgres.build(pods['postgresql'])):
            component, _, stage, proof, producer = entry
            leaf = self.parent/component
            original = '/tmp/first-'+'a'*32+'-'+component
            # Only native data generation/parser are substituted; execute actual
            # generated mkdir/chmod/checks/redirection and independent proof/cat.
            script = stage[-1].replace(original,str(leaf))
            script = script.replace(shlex.join(export.container_argv), "printf 'GENERATED ONLY'")
            parse = shlex.join(export.complete_archive_validator) if export.complete_archive_validator else None
            if parse: script = script.replace(parse, 'true')
            self.assertEqual(self.shell(script).returncode, 0, component)
            self.assertEqual(stat.S_IMODE(leaf.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((leaf/'native').stat().st_mode), 0o600)
            proof_script = proof[-1].replace(original,str(leaf))
            if parse: proof_script = proof_script.replace(parse,'true')
            self.assertEqual(self.shell(proof_script).returncode, 0)
            self.assertEqual(self.shell(producer[-1].replace(original,str(leaf))).stdout,b'GENERATED ONLY')
            before = self.identity(leaf)
            self.assertNotEqual(self.shell(script).returncode, 0)
            self.assertEqual(self.identity(leaf),before)
            self.assertEqual((leaf/'native').read_bytes(),b'GENERATED ONLY')

    def test_ch_and_sw_actual_creation_fragments_under_setgid(self):
        _, _, _, admitted = self.plan()
        ch_leaf = self.parent/'clickhouse'
        ch = c.objects._ch_scripts(str(ch_leaf),1024**2)[0][-1]
        creation = c.objects._new_private_directory(str(ch_leaf))
        self.assertIn(creation,ch)
        # CH requires an existing exact0700 backups parent. Do not weaken that
        # prerequisite to run a full stage under a setgid source directory.
        scripts = [(ch_leaf,creation)]
        sw = c.objects.seaweed_review_commands('a'*32,1024**2,admitted)
        sw_leaf = self.parent/('first-'+'a'*32)
        scripts.append((sw_leaf,sw['container_commands'][0][-1].replace('/data',str(self.parent))
                        .replace('test "$(id -u)" = 10000','test "$(id -u)" = '+self.uid)))
        for leaf,script in scripts:
            self.assertEqual(self.shell(script+'\nprintf generated > '+str(leaf/'native.tar')).returncode,0)
            self.assertEqual(stat.S_IMODE(leaf.stat().st_mode),0o700)
            if (leaf/'volumes').exists():
                self.assertEqual(stat.S_IMODE((leaf/'volumes').stat().st_mode),0o700)
            self.assertEqual(stat.S_IMODE((leaf/'native.tar').stat().st_mode),0o600)

    def valkey_loop(self):
        fragment = c.valkey.shell_fragment()
        loop = fragment[fragment.index('for d in checkpoint checkpoint/appendonlydir; do'):]
        return loop[:loop.index('\ndone')+len('\ndone')]

    def test_valkey_actual_checkpoint_loop_under_setgid(self):
        loop = self.valkey_loop()
        result = self.shell(loop+'\nprintf generated > checkpoint/appendonlydir/native',cwd=self.parent)
        self.assertEqual(result.returncode,0)
        for path in ('checkpoint','checkpoint/appendonlydir'):
            self.assertEqual(stat.S_IMODE((self.parent/path).stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((self.parent/'checkpoint/appendonlydir/native').stat().st_mode),0o600)
        before = self.identity(self.parent/'checkpoint')
        self.assertNotEqual(self.shell(loop,cwd=self.parent).returncode,0)
        self.assertEqual(self.identity(self.parent/'checkpoint'),before)

    def test_valkey_preexisting_capture_root_is_not_repaired(self):
        # Full fragment refuses the inherited-setgid preexisting root before any
        # native command or confidential file; only its NEW children may change.
        script = c.valkey.shell_fragment().replace('/scratch/capture',str(self.parent))
        result = subprocess.run(('/bin/sh','-ec','export REDISCLI_AUTH=GENERATED_ONLY\n'+script),
                                capture_output=True,timeout=5)
        self.assertEqual(self.identity(self.parent),self.parent_identity)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stderr,b'VALKEY_CHECKPOINT_REFUSED\n')
        self.assertEqual(list(self.parent.iterdir()),[])

    def test_valkey_loop_refuses_existing_occupied_and_symlink_checkpoint(self):
        for kind in ('empty','occupied','symlink','dangling'):
            with self.subTest(kind=kind):
                cwd = self.parent/kind; cwd.mkdir(mode=0o700)
                leaf = cwd/'checkpoint'
                target = self.root/('vk-target-'+kind); target.mkdir(mode=0o750)
                if kind in ('empty','occupied'):
                    leaf.mkdir(mode=0o700); leaf.chmod(0o2750)
                    if kind == 'occupied': (leaf/'keep').write_bytes(b'UNCHANGED')
                else: leaf.symlink_to(target if kind == 'symlink' else self.root/'absent')
                before, target_before = self.identity(leaf), self.identity(target)
                self.assertNotEqual(self.shell(self.valkey_loop(),cwd=cwd).returncode,0)
                self.assertEqual(self.identity(leaf),before)
                self.assertEqual(self.identity(target),target_before)
                if kind == 'occupied': self.assertEqual((leaf/'keep').read_bytes(),b'UNCHANGED')

    def test_occupied_and_symlink_paths_refused_untouched(self):
        for kind in ('empty','occupied','file','symlink','dangling','ancestor'):
            with self.subTest(kind=kind):
                leaf = self.parent/kind
                target = self.root/('target-'+kind); target.mkdir(mode=0o700)
                sentinel = target/'sentinel'; sentinel.write_bytes(b'UNCHANGED')
                if kind in ('empty','occupied'):
                    leaf.mkdir(mode=0o700); leaf.chmod(0o2750)
                    if kind == 'occupied': (leaf/'native').write_bytes(b'EXISTING')
                elif kind == 'file': leaf.write_bytes(b'EXISTING')
                elif kind == 'ancestor': leaf.symlink_to(target); leaf = leaf/'new'
                else: leaf.symlink_to(target if kind == 'symlink' else self.root/'absent')
                observed = leaf.parent if kind == 'ancestor' else leaf
                before, target_before = self.identity(observed), self.identity(target)
                result = self.shell(c.objects._new_private_directory(str(leaf)))
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(self.identity(observed),before)
                self.assertEqual(self.identity(target),target_before)
                self.assertEqual(sentinel.read_bytes(),b'UNCHANGED')
                if kind == 'ancestor': self.assertFalse(leaf.exists())
                if kind == 'occupied': self.assertEqual((leaf/'native').read_bytes(),b'EXISTING')
                if kind == 'file': self.assertEqual(leaf.read_bytes(),b'EXISTING')


class KubernetesIOFixture:
    """Generated IO with explicitly shared revisions, not server ordering proof.

    The admission tests conditionally substitute the unavailable live ordering
    proof. Watch reader, CAS-bound event admission, WriterGuard and Fence are real.
    """
    def __init__(self,root):
        self.root=root; self.rv=100; self.process: Any=None; self.calls=[]; self.writes=[]
        self.original_pods={}; self.journal_name='journal.jsonl'
        self.ready_replies=['READY']; self.queue_values=[0,0,6,0,0,0,6,0,23,0,0,'a'*40]
        self.pg_idle='180007|1|1|0|0|0|0|0'; self.ch_idle='0'; self.exit_code=0
        self.names=['20200101000000_first','20200102000000_second']
        self.queue_names=['fixture-queue-'+str(i) for i in range(46)]
        self.pods={}; self.rows={}; self.deployments={}
        images={'postgresql':c.postgres.IMAGE,'clickhouse':c.objects.CH_IMAGE,'seaweedfs':c.objects.SW_IMAGE,
            'langfuse-redis':'valkey/valkey:8.0@sha256:'+c.preflight.IMAGE_DIGESTS['langfuse-redis'],
            'langfuse-web':'docker.langfuse.com/langfuse/langfuse:4.77.0@sha256:'+c.preflight.IMAGE_DIGESTS['langfuse-web'],
            'langfuse-worker':'docker.langfuse.com/langfuse/langfuse-worker:4.77.0@sha256:'+c.preflight.IMAGE_DIGESTS['langfuse-worker']}
        claims={'postgresql':'postgres-data-langfuse-postgresql-0','clickhouse':'langfuse-clickhouse-data',
                'seaweedfs':'langfuse-s3-data','langfuse-redis':'langfuse-redis'}
        for index,(container,image) in enumerate(images.items(),1):
            name={'postgresql':'langfuse-postgresql-0','clickhouse':'langfuse-clickhouse-0',
                  'seaweedfs':'langfuse-s3-fixture-abc'}.get(container,container+'-fixture-abc')
            uid='00000000-0000-0000-0000-'+str(index).zfill(12)
            spec={'containers':[{'name':container,'image':image}], 'volumes':[]}
            if container in claims: spec['volumes']=[{'name':'data','persistentVolumeClaim':{'claimName':claims[container]}}]
            pod=self.pod(name,uid,spec)
            self.pods[uid]=pod; self.rows[container]=c.pod_row(pod)
            if container in c.writer.TARGETS:
                self.deployments[container]={'kind':'Deployment','metadata':{'namespace':'langfuse','name':container,'uid':'deployment-'+container,'resourceVersion':'1','generation':1},
                    'spec':{'replicas':1,'template':{'spec':copy.deepcopy(spec)}}}
        helper_spec={'automountServiceAccountToken':False,'securityContext':{'runAsUser':1000,'runAsGroup':1000},
            'containers':[{'name':'capture','image':'docker.io/valkey/valkey:8.0@sha256:'+c.preflight.IMAGE_DIGESTS['langfuse-redis'],
                'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                'env':[{'name':'REDISCLI_AUTH','valueFrom':{'secretKeyRef':{'name':'langfuse-redis-auth','key':'default'}}}],
                'volumeMounts':[{'name':'data','mountPath':'/data','readOnly':True},{'name':'scratch','mountPath':'/scratch'}]}],
            'volumes':[{'name':'data','persistentVolumeClaim':{'claimName':'langfuse-redis','readOnly':True}},
                       {'name':'scratch','emptyDir':{}}]}
        helper=self.pod('langfuse-recovery-valkey-fixture','00000000-0000-0000-0000-000000000099',helper_spec)
        helper['metadata']['ownerReferences']=[{'kind':'Job','name':'langfuse-recovery-valkey-fixture','uid':'helper-job-uid'}]
        self.pods[helper['metadata']['uid']]=helper
        self.helper={**c.pod_row(helper),'job_name':'langfuse-recovery-valkey-fixture','job_uid':'helper-job-uid'}
        self.jobs=[{'metadata':{'name':self.helper['job_name'],'uid':self.helper['job_uid']},'status':{'active':1}}]
        for name,value in c.DIAGNOSTICS.items():
            self.jobs.append({'metadata':{'name':name,'uid':value['job_uid']},'status':{'succeeded' if value['exit']==0 else 'failed':1}})
            pod=self.pod(name+'-fixture',value['pod_uid'],{'containers':[{'name':'version','image':images['clickhouse']}]})
            pod['metadata']['ownerReferences']=[{'kind':'Job','name':name,'uid':value['job_uid']}]
            pod['status']['phase']=value['phase']
            pod['status']['containerStatuses'][0].update(ready=False,state={'terminated':{'exitCode':value['exit']}})
            if name!=c.PINNED_JOB:
                # Terminal retained helper Pods keep their immutable PVC refs.
                pod['spec']['volumes']=[{'name':'data','persistentVolumeClaim':
                                        {'claimName':'langfuse-redis','readOnly':True}}]
            self.pods[value['pod_uid']]=pod
        self.application={'spec':{'syncPolicy':{},'sources':[{'targetRevision':'main'}]},
                          'status':{'sync':{'status':'Synced'},'health':{'status':'Healthy'}}}
        self.claims={}; self.pvs={}; self.volumes={}
        for name,(uid,size) in c.preflight.CLAIMS.items():
            self.claims[name]={'metadata':{'uid':uid,'resourceVersion':'10'},'spec':{'volumeName':'pvc-'+uid,
                'storageClassName':'longhorn','resources':{'requests':{'storage':size}}},
                'status':{'phase':'Bound','capacity':{'storage':size}}}
            self.pvs['pvc-'+uid]={'metadata':{'uid':'pv-'+uid,'resourceVersion':'10'},'spec':{
                'claimRef':{'uid':uid,'name':name,'namespace':'langfuse'},'csi':{'driver':'driver.longhorn.io','volumeHandle':'pvc-'+uid},
                'persistentVolumeReclaimPolicy':'Delete'}}
            self.volumes['pvc-'+uid]={'spec':{'numberOfReplicas':2},'status':{'state':'attached','robustness':'healthy'}}
        self.migration={'postgres_image_migrations':2,'postgres_applied_set_sha256':hashlib.sha256('\n'.join(self.names).encode()).hexdigest(),
            'postgres_unfinished':0,'startup_cleanup_rows':0,'clickhouse_image_migrations':56,'clickhouse_latest_version':56,
            'clickhouse_latest_dirty':False,'entrypoint_sha256':'a'*64,'cleanup_sha256':'b'*64,'clickhouse_up_sha256':'c'*64}
        self.prepared={'pods':self.rows,'migration_proof':self.migration,'workloads':[dict(name=name,uid=d['metadata']['uid'],
                        resourceVersion=d['metadata']['resourceVersion'],spec=d['spec'],generation=d['metadata']['generation']) for name,d in self.deployments.items()]}

    def pod(self,name,uid,spec):
        return {'metadata':{'name':name,'uid':uid,'namespace':'langfuse','resourceVersion':'1',
                            'ownerReferences':[{'kind':'ReplicaSet','name':name+'-rs','uid':name+'-rs-uid'}]},
                'spec':spec,'status':{'phase':'Running','containerStatuses':[{'name':spec['containers'][0]['name'],
                    'ready':True,'restartCount':0,'state':{'running':{}}}]}}

    def send(self,event):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write((json.dumps(event)+'\n').encode()); self.process.stdin.flush()
            except (BrokenPipeError,ValueError): pass

    def bookmark(self,initial=False):
        metadata: dict={'resourceVersion':str(self.rv)}
        if initial: metadata['annotations']={'k8s.io/initial-events-end':'true'}
        self.send({'type':'BOOKMARK','object':{'metadata':metadata}})

    def spawn(self,adapter,path,deadline):
        self.calls.append(('watch',path))
        if 'sendInitialEvents' in path or 'resourceVersion=100' not in path: raise AssertionError('exact list/RV resume missing')
        self.process=subprocess.Popen(py('import sys\nfor line in sys.stdin.buffer:\n sys.stdout.buffer.write(line); sys.stdout.buffer.flush()'),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        self.bookmark()
        return self.process

    def get(self,kind,name,deadline,namespace='langfuse') -> dict:
        self.calls.append(('get',kind,name))
        if kind in ('pods','pod'):
            listed={'metadata':{'resourceVersion':str(self.rv)},'items':copy.deepcopy(list(self.pods.values()))}
            self.bookmark()
            return listed if not name else next(p for p in listed['items'] if p['metadata']['name']==name)
        if kind=='replicaset':
            source=next(p for p in self.original_pods.values() if p['metadata']['ownerReferences'][0]['name']==name)
            container=source['spec']['containers'][0]['name']
            return {'metadata':{'uid':source['metadata']['ownerReferences'][0]['uid'],
                'ownerReferences':[{'kind':'Deployment','name':container,'uid':self.deployments[container]['metadata']['uid']}]}}
        if kind=='deployment': return copy.deepcopy(self.deployments[name])
        if kind=='application': return copy.deepcopy(self.application)
        if kind=='cronjobs': return {'items':[]}
        if kind=='jobs': return {'items':copy.deepcopy(self.jobs)}
        if kind=='pvc': return copy.deepcopy(self.claims[name])
        if kind=='pv': return copy.deepcopy(self.pvs[name])
        if kind=='volumes.longhorn.io': return copy.deepcopy(self.volumes[name])
        if kind=='statefulset': return {'spec':{'persistentVolumeClaimRetentionPolicy':{'whenDeleted':'Retain','whenScaled':'Retain'}}}
        raise AssertionError('unexpected metadata IO '+kind)

    def execute(self,pod,container,args,deadline):
        self.calls.append(('exec',container,args))
        if args==['/bin/sh','-c',c.live.READY_SHELL]: return self.ready_replies.pop(0) if len(self.ready_replies)>1 else self.ready_replies[0]
        if args[0]=='valkey-cli':
            if args[7:10]!=['EVAL_RO',c.live.QUEUE_LUA,'0']: raise AssertionError('not readonly source-verified queue API')
            return json.dumps(self.queue_values)
        if args[0]=='node':
            script=args[-1]
            if 'process.stdout.write(JSON.stringify(registry' in script: return json.dumps(self.queue_names)
            return json.dumps({'postgres':self.names,'clickhouse':list(range(1,57)),'cleanup_names':sorted(c.EXPECTED_CLEANUP),
                'entrypoint_sha256':'a'*64,'cleanup_sha256':'b'*64,'clickhouse_up_sha256':'c'*64})
        query=args[-1]
        if query==c.drain.PG_IDLE_SQL: return self.pg_idle
        if query==c.native.PG_MIGRATION_SQL: return '2|0'
        if query==c.native.CH_MIGRATION_SQL: return '56\t0'
        if query.startswith('SELECT migration_name FROM'): return '\n'.join(self.names)
        if query.startswith('SELECT count(*) FROM public._prisma_migrations WHERE migration_name IN'): return '0'
        if 'FROM system.processes' in query: return self.ch_idle
        raise AssertionError('unexpected native IO')

    def patch(self,argv,deadline,limit=1024*1024):
        if 'patch' not in argv: raise AssertionError('unexpected command')
        name=argv[argv.index('deployment')+1]; ops=json.loads(argv[argv.index('--patch')+1]); d=self.deployments[name]
        assert ops[:3]==[{'op':'test','path':'/metadata/uid','value':d['metadata']['uid']},
            {'op':'test','path':'/metadata/resourceVersion','value':d['metadata']['resourceVersion']},
            {'op':'test','path':'/spec','value':d['spec']}]
        last=json.loads((self.root/self.journal_name).read_text().splitlines()[-1])
        assert last['event']=='mutation_intent'
        replicas=ops[3]['value']; assert ops[3]['path']=='/spec/replicas'
        # Model the fixed shared storage revision explicitly; independent per-kind
        # counters cannot prove Pod events follow a Deployment CAS.
        self.rv=max(self.rv,int(d['metadata']['resourceVersion']))+1
        d['spec']['replicas']=replicas; d['metadata']['resourceVersion']=str(self.rv)
        d['metadata']['generation']+=1
        self.writes.append((name,replicas))
        uid=self.rows[name]['uid']
        if replicas==0:
            pod=copy.deepcopy(self.pods[uid]); pod['metadata']['deletionTimestamp']='2026-11-22T00:00:00Z'
            for kind,terminated in (('MODIFIED',False),('MODIFIED',True),('DELETED',True)):
                self.rv+=1; pod['metadata']['resourceVersion']=str(self.rv)
                pod['status']['containerStatuses'][0]['ready']=False
                if terminated:
                    pod['status']['phase']='Succeeded' if self.exit_code==0 else 'Failed'
                    pod['status']['containerStatuses'][0]['state']={'terminated':{'exitCode':self.exit_code,
                        'reason':'Completed' if self.exit_code==0 else 'Error','signal':0}}
                self.send({'type':kind,'object':copy.deepcopy(pod)})
            del self.pods[uid]
        else:
            pod=self.pod(self.rows[name]['name']+'-resumed','resumed-'+uid,copy.deepcopy(d['spec']['template']['spec']))
            pod['metadata']['ownerReferences']=copy.deepcopy(self.original_pods[uid]['metadata']['ownerReferences'])
            self.pods[pod['metadata']['uid']]=pod
        return json.dumps(copy.deepcopy(d))


class LiveAdapterTests(unittest.TestCase):
    def unclean_event(self,mode):
        uid=self.io.rows['langfuse-web']['uid']
        pod=copy.deepcopy(self.io.pods[uid])
        self.io.rv+=1; pod['metadata']['resourceVersion']=str(self.io.rv)
        kind='MODIFIED'
        if mode=='not-ready': pod['status']['containerStatuses'][0]['ready']=False
        elif mode=='deleting': pod['metadata']['deletionTimestamp']='2026-11-22T00:00:00Z'
        elif mode in ('normal-exit','deleted'):
            pod['status']['containerStatuses'][0].update(ready=False,
                state={'terminated':{'exitCode':0,'signal':0,'reason':'Completed'}})
            if mode=='deleted': kind='DELETED'
        return {'type':kind,'object':pod}

    def check_pre_intent_transient(self,mode):
        import threading
        self.start(); pending=[]; migrations=self.adapter.clean_migrations
        def delay_before_intent(deadline):
            result=migrations(deadline)
            pending.append(self.unclean_event(mode))
            # The fresh list sees recovery, but cannot erase transient history.
            self.io.rv+=1
            return result
        def listed_before_delivery(kind,name,deadline,namespace='langfuse'):
            if kind=='pods' and pending:
                listed={'metadata':{'resourceVersion':str(self.io.rv)},
                        'items':copy.deepcopy(list(self.io.pods.values()))}
                batch=list(pending); pending.clear()
                def deliver():
                    for event in batch: self.io.send(event)
                    self.io.bookmark()
                timer=threading.Timer(.03,deliver); timer.start(); self.addCleanup(timer.join)
                return listed
            return self.io.get(kind,name,deadline,namespace)
        with patch.object(self.adapter,'clean_migrations',side_effect=delay_before_intent),\
             patch.object(c,'get',side_effect=listed_before_delivery):
            result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete)
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(self.io.writes,[])
        records=[json.loads(line) for line in (self.directory/'journal.jsonl').read_text().splitlines()]
        self.assertFalse(any(r['event']=='mutation_intent' for r in records))

    def test_pre_intent_barrier_rejects_delayed_not_ready_despite_clean_list(self):
        self.check_pre_intent_transient('not-ready')

    def test_pre_intent_barrier_rejects_delayed_deleting_despite_clean_list(self):
        self.check_pre_intent_transient('deleting')

    def test_pre_intent_barrier_rejects_delayed_normal_exit_despite_clean_list(self):
        self.check_pre_intent_transient('normal-exit')

    def test_pre_intent_barrier_rejects_delayed_deletion_despite_clean_list(self):
        self.check_pre_intent_transient('deleted')

    def test_delayed_pre_cas_events_cannot_gain_decode_time_authorization(self):
        # Run each case with a fresh real guard/reader. Event production occurs
        # after the pre-intent barrier, before CAS; delivery/decoding is delayed
        # until after the response grants authorization to LATER events only.
        self.doCleanups()
        for mode in ('not-ready','deleting','normal-exit','deleted'):
            with self.subTest(mode=mode):
                fixture=self; fixture.setUp()
                try:
                    fixture.start(); callback=[]; sent=[]
                    def delayed(argv,deadline):
                        if not sent:
                            event=fixture.unclean_event(mode); sent.append(event)
                            fixture.io.send(event)
                        return fixture.io.patch(argv,deadline)
                    with patch.object(c,'run',side_effect=delayed):
                        result=fixture.guard.run(lambda *args:callback.append(True))
                    self.assertFalse(result.capture_complete,result)
                    self.assertNotEqual(result.state,'CAPTURED')
                    self.assertEqual(callback,[])
                    self.assertTrue(fixture.adapter.watch.failed)
                    self.assertEqual(fixture.io.writes,[('langfuse-web',0)])
                finally: fixture.doCleanups()

    def test_genuine_shutdown_before_cas_response_is_accepted_by_revision(self):
        self.start(); boundaries={}
        def fast_controller(argv,deadline):
            uid=self.io.rows[argv[argv.index('deployment')+1]]['uid']
            self.assertNotIn(uid,self.adapter.watch.allowed_exit)
            # Actual pipe reader runs concurrently; patch emits deletion/exit
            # before returning its response, while decoder waits on the lock.
            raw=self.io.patch(argv,deadline)
            boundaries[uid]=json.loads(raw)['metadata']['resourceVersion']
            self.assertNotIn(uid,self.adapter.watch.allowed_exit)
            return raw
        with patch.object(c,'run',side_effect=fast_controller):
            result=self.guard.run(self.capture)
        self.assertEqual(result.state,'CAPTURED',result)
        self.assertEqual(self.adapter.watch.exit_after,boundaries)
        for uid,exit in self.adapter.watch.exits.items():
            self.assertGreater(int(exit['rv']),int(boundaries[uid]))

    def test_shutdown_at_exact_cas_revision_is_not_authorized(self):
        self.start(); sent=[]
        def equal_boundary(argv,deadline):
            if not sent:
                event=self.unclean_event('normal-exit')
                # Reserve next shared revision for CAS, not a prior Pod write.
                event['object']['metadata']['resourceVersion']=str(self.io.rv+1)
                sent.append(event); self.io.send(event)
            return self.io.patch(argv,deadline)
        with patch.object(c,'run',side_effect=equal_boundary):
            result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete)
        uid=sent[0]['object']['metadata']['uid']
        self.assertEqual(sent[0]['object']['metadata']['resourceVersion'],
                         self.adapter.watch.exit_after[uid])
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(self.io.writes,[('langfuse-web',0)])

    def test_opaque_cas_revision_never_grants_shutdown_permission(self):
        self.start()
        def unsupported(argv,deadline):
            doc=json.loads(self.io.patch(argv,deadline))
            doc['metadata']['resourceVersion']='opaque'
            return json.dumps(doc)
        with patch.object(c,'run',side_effect=unsupported):
            result=self.guard.run(self.capture)
        self.assertEqual(result.state,'MANUAL_RECOVERY')
        self.assertFalse(result.capture_complete)
        self.assertEqual(self.adapter.watch.exit_after,{})
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(result.uncertain,('langfuse-web',))

    def test_unproven_pause_watch_progress_refuses_before_intent(self):
        self.start(); migrations=self.adapter.clean_migrations; waiting=[False]
        def no_progress(deadline):
            result=migrations(deadline); self.io.rv+=1; waiting[0]=True
            return result
        def listed_only(kind,name,deadline,namespace='langfuse'):
            if kind=='pods' and waiting[0]:
                return {'metadata':{'resourceVersion':str(self.io.rv)},
                        'items':copy.deepcopy(list(self.io.pods.values()))}
            return self.io.get(kind,name,deadline,namespace)
        barrier=self.adapter.watch.barrier
        with patch.object(self.adapter,'clean_migrations',side_effect=no_progress),\
             patch.object(c,'get',side_effect=listed_only),\
             patch.object(self.adapter.watch,'barrier',side_effect=lambda listed,d:barrier(listed,time.monotonic()+.03)):
            result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete)
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(self.io.writes,[])
        records=[json.loads(line) for line in (self.directory/'journal.jsonl').read_text().splitlines()]
        self.assertFalse(any(r['event']=='mutation_intent' for r in records))

    def test_default_live_admission_refuses_without_server_ordering_proof(self):
        self.ordering_fixture.stop()
        self.start()
        with self.assertRaisesRegex(c.Refused,'pause-watch-ordering-unproven'):
            self.adapter._require_pause_ordering()
        result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete)
        self.assertEqual(self.io.writes,[])
        self.assertEqual(self.adapter.watch.exit_after,{})
        records=[json.loads(line) for line in (self.directory/'journal.jsonl').read_text().splitlines()]
        self.assertFalse(any(r['event']=='mutation_intent' for r in records))
        before=self.adapter.read('langfuse-web',self.approval.expires_at)
        with self.assertRaisesRegex(c.Refused,'pause-watch-ordering-unproven'):
            self.adapter.scale(before,0,self.approval.expires_at)
        self.assertEqual(self.io.writes,[])

    def test_exact_terminal_diagnostic_claim_refs_are_not_current_consumers(self):
        deadline=time.monotonic()+10
        self.adapter.start(deadline)
        proof=self.adapter.volume_proofs(deadline)
        self.assertEqual({p['uid'] for p in proof['valkey']['consumers']},
                         {self.io.rows['langfuse-redis']['uid'],self.io.helper['uid']})
        self.assertTrue(all(v['pod_uid'] in self.io.pods for v in c.DIAGNOSTICS.values()))
        self.assertEqual(self.io.writes,[])

    def test_unknown_terminal_claim_reference_still_refuses(self):
        diagnostic=next(v for k,v in c.DIAGNOSTICS.items() if k!=c.PINNED_JOB)
        pod=copy.deepcopy(self.io.pods[diagnostic['pod_uid']])
        uid='90000000-0000-0000-0000-000000000001'
        pod['metadata']['uid']=uid
        self.io.pods[uid]=pod
        with self.assertRaisesRegex(c.Refused,'unreviewed-pod'):
            self.adapter.start(time.monotonic()+10)
        self.assertEqual(self.io.writes,[])

    def test_retained_terminal_helper_cannot_be_reused_for_capture(self):
        diagnostic=next(iter(c.DIAGNOSTICS.values()))
        helper=dict(self.io.helper,uid=diagnostic['pod_uid'])
        with self.assertRaisesRegex(c.Refused,'capture-helper-is-retained-terminal-artifact'):
            c.live.Adapter(c,self.io.prepared,helper,self.approval,self.directory)
        self.assertEqual(self.io.writes,[])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='generated-live-adapter-'); self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name); self.directory.chmod(0o700)
        self.io=KubernetesIOFixture(self.directory); self.io.original_pods=copy.deepcopy(self.io.pods)
        self.approval=c.writer.Approval('fixture-live','operator-authorized-window','synthetic-public-recipient',
            'synthetic-custody','synthetic-destination','synthetic-all-client-admin-idle',time.monotonic()+120)
        self.adapter=c.live.Adapter(c,self.io.prepared,self.io.helper,self.approval,self.directory,timeout=120)
        self.addCleanup(self.adapter.close)
        # This generated backend constructs a shared revision domain. Exercise
        # the algorithm conditionally, NOT as live server-contract admission.
        # The separate default-admission test removes this fixture substitution.
        self.ordering_fixture=patch.object(self.adapter,'_require_pause_ordering',return_value=None)
        self.ordering_fixture.start(); self.addCleanup(self.ordering_fixture.stop)
        for obj,name,effect in ((c,'get',self.io.get),(c,'execute',self.io.execute),(c,'run',self.io.patch)):
            mocked=patch.object(obj,name,side_effect=effect); mocked.start(); self.addCleanup(mocked.stop)
        spawned=patch.object(c.live.Adapter,'spawn_watch',autospec=True,side_effect=self.io.spawn)
        spawned.start(); self.addCleanup(spawned.stop)
        self.journal=c.writer.Journal(self.directory/'journal.jsonl'); self.addCleanup(self.journal.close)
        self.guard=c.writer.WriterGuard(self.adapter,self.journal,self.approval,
            tuple(self.adapter.expected[n] for n in c.writer.TARGETS),timeout=120,drain_timeout=2,poll_interval=.01)

    def start(self): self.adapter.start(self.approval.expires_at)

    def capture(self,checkpoint,deadline):
        self.assertEqual(self.io.writes,[('langfuse-web',0),('langfuse-worker',0)])
        self.assertEqual(self.adapter.watch.gone,self.adapter.writer_uids)
        checkpoint()

    def test_real_adapter_order_watch_native_idle_preserved_schedules_and_resume(self):
        self.start()
        self.assertEqual(self.io.writes,[])
        result=self.guard.run(self.capture)
        self.assertEqual(result.state,'CAPTURED',result)
        self.assertEqual(self.adapter.scheduled['counts']['delayed'],6)
        self.assertEqual(self.adapter.scheduled['counts']['repeat'],6)
        self.assertEqual(self.adapter.scheduled['counts']['failed'],23)
        self.assertEqual(len(self.adapter.watch.exits),2)
        self.assertTrue(self.adapter.watch.closed)
        self.assertEqual(self.guard.resume().state,'RESUMED')
        self.assertEqual(self.io.writes[-2:],[('langfuse-web',1),('langfuse-worker',1)])
        queue_calls=[call for call in self.io.calls if call[0]=='exec' and call[2][0]=='valkey-cli']
        self.assertTrue(queue_calls)
        self.assertTrue(all(call[2][7]=='EVAL_RO' for call in queue_calls))

    def test_patch_ack_then_status_only_get_uses_new_snapshot_for_resume_cas(self):
        self.start()
        def status_after_ack(argv, deadline, limit=1024*1024):
            ack = self.io.patch(argv, deadline, limit)
            name = argv[argv.index('deployment')+1]
            metadata = self.io.deployments[name]['metadata']
            metadata['resourceVersion'] = str(int(metadata['resourceVersion'])+1)
            return ack
        with patch.object(c, 'run', side_effect=status_after_ack):
            result = self.guard.run(self.capture)
            self.assertEqual(result.state, 'CAPTURED', result)
            for name in c.writer.TARGETS:
                self.assertEqual(self.guard.current[name].version,
                                 self.io.deployments[name]['metadata']['resourceVersion'])
                self.assertEqual(self.guard.current[name].generation, 2)
                self.assertEqual(self.guard.current[name], self.guard.paused[name])
            result = self.guard.resume()
            self.assertEqual(result.state, 'RESUMED', result)
        self.assertEqual(self.io.writes, [('langfuse-web',0),('langfuse-worker',0),
                                          ('langfuse-web',1),('langfuse-worker',1)])

    def test_later_repeated_status_churn_through_termination_evidence_capture_resume(self):
        self.start()
        updates=[]
        def status(name, boundary):
            metadata=self.io.deployments[name]['metadata']
            metadata['resourceVersion']=str(int(metadata['resourceVersion'])+7)
            updates.append((name,boundary,metadata['resourceVersion']))
        stopped=self.adapter.stopped
        def terminating(name,deadline):
            # Immediate acknowledgement GET already completed before termination.
            status(name,'termination')
            return stopped(name,deadline)
        migrations=self.adapter.clean_migrations
        def during_evidence(deadline):
            for name in c.writer.TARGETS: status(name,'evidence')
            return migrations(deadline)
        scale=self.adapter.scale
        def before_cas(before,replicas,deadline):
            status(before.name,'cas-precheck')
            return scale(before,replicas,deadline)
        def capture(checkpoint,deadline):
            self.capture(checkpoint,deadline)
            for _ in range(3):
                for name in c.writer.TARGETS: status(name,'capture')
                checkpoint()
        with patch.object(self.adapter,'stopped',side_effect=terminating),\
             patch.object(self.adapter,'clean_migrations',side_effect=during_evidence),\
             patch.object(self.adapter,'scale',side_effect=before_cas):
            result=self.guard.run(capture)
            self.assertEqual(result.state,'CAPTURED',result)
            self.assertEqual(len(self.adapter.watch.exits),2)
            for name in c.writer.TARGETS:
                self.assertEqual(self.guard.current[name],self.guard.paused[name])
                self.assertEqual(self.guard.current[name].version,self.io.deployments[name]['metadata']['resourceVersion'])
                status(name,'before-resume')
            result=self.guard.resume()
            self.assertEqual(result.state,'RESUMED',result)
        self.assertEqual(self.io.writes,[('langfuse-web',0),('langfuse-worker',0),
                                         ('langfuse-web',1),('langfuse-worker',1)])
        self.assertEqual({u[1] for u in updates},
                         {'termination','evidence','cas-precheck','capture','before-resume'})
        for name in c.writer.TARGETS:
            self.assertEqual(self.guard.current[name].generation,3)
        with self.assertRaises(c.writer.Refused): self.guard.run(capture)
        with self.assertRaises(c.writer.Refused): self.guard.resume()

    def test_cas_precheck_rejects_later_drift_without_patch(self):
        self.start()
        before=self.adapter.read('langfuse-web',self.approval.expires_at)
        original=copy.deepcopy(self.io.deployments[before.name])
        for field,value in (('resourceVersion','0'),('resourceVersion','opaque'),
                            ('generation',3),('uid','replacement'),
                            ('name','langfuse-worker'),('namespace','other'),('kind','StatefulSet'),('spec',None)):
            with self.subTest(field=field,value=value):
                doc=copy.deepcopy(original); doc['metadata']['resourceVersion']='20'
                if field=='kind': doc[field]=value
                elif field=='spec': doc['spec']['strategy']={'type':'Recreate'}
                else: doc['metadata'][field]=value
                self.io.deployments[before.name]=doc
                with self.assertRaisesRegex(c.Refused,'deployment-cas-precheck'):
                    self.adapter.scale(before,0,self.approval.expires_at)
                self.assertEqual(self.io.writes,[])

    def test_status_race_after_cas_precheck_is_not_retried(self):
        self.start()
        attempts=[]
        def conflict(argv,deadline):
            attempts.append(argv)
            name=argv[argv.index('deployment')+1]
            self.io.deployments[name]['metadata']['resourceVersion']='99'
            raise c.Refused('fixture-atomic-conflict')
        with patch.object(c,'run',side_effect=conflict):
            result=self.guard.run(self.capture)
        self.assertEqual(len(attempts),1)
        self.assertEqual(self.io.writes,[])
        self.assertEqual(result.state,'MANUAL_RECOVERY')
        self.assertEqual(result.uncertain,('langfuse-web',))
        with self.assertRaises(c.writer.Refused): self.guard.resume()

    def test_patch_ack_then_spec_aba_get_is_not_status_only_churn(self):
        self.start()
        def aba_after_ack(argv, deadline, limit=1024*1024):
            ack = self.io.patch(argv, deadline, limit)
            name = argv[argv.index('deployment')+1]
            metadata = self.io.deployments[name]['metadata']
            # Two intervening spec writes return to the acknowledged full spec.
            metadata['resourceVersion'] = str(int(metadata['resourceVersion'])+2)
            metadata['generation'] += 2
            return ack
        with patch.object(c, 'run', side_effect=aba_after_ack):
            result = self.guard.run(self.capture)
        self.assertEqual(result.state, 'MANUAL_RECOVERY')
        self.assertEqual(result.reason, 'mutation_readback_failed')
        self.assertEqual(result.uncertain, ('langfuse-web',))
        self.assertEqual(self.io.writes, [('langfuse-web',0)])
        with self.assertRaises(c.writer.Refused): self.guard.resume()

    def test_patch_ack_without_generation_never_accepts_matching_get(self):
        self.start()
        def missing_generation(argv, deadline, limit=1024*1024):
            ack = json.loads(self.io.patch(argv, deadline, limit))
            ack['metadata'].pop('generation')
            return json.dumps(ack)
        with patch.object(c, 'run', side_effect=missing_generation):
            result = self.guard.run(self.capture)
        self.assertEqual(result.state, 'MANUAL_RECOVERY')
        self.assertEqual(result.reason, 'operation_failed')
        self.assertEqual(self.adapter.watch.exit_after,{})
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(self.io.writes, [('langfuse-web',0)])

    def test_api_list_can_precede_delivery_of_normal_delete_watch_events(self):
        import threading
        self.start(); pending=[]; original_send=self.io.send
        def defer(event):
            if event['type'] in ('MODIFIED','DELETED') and event['object']['metadata']['uid'] in self.adapter.writer_uids:
                pending.append(copy.deepcopy(event))
            else: original_send(event)
        self.io.send=defer
        def delayed_get(kind,name,deadline,namespace='langfuse'):
            if kind=='pods' and pending:
                listed={'metadata':{'resourceVersion':str(self.io.rv)},'items':copy.deepcopy(list(self.io.pods.values()))}
                batch=list(pending); pending.clear()
                def deliver():
                    for event in batch: original_send(event)
                    self.io.bookmark()
                timer=threading.Timer(.04,deliver); timer.daemon=True; timer.start()
                self.addCleanup(timer.join)
                return listed
            return self.io.get(kind,name,deadline,namespace)
        with patch.object(c,'get',side_effect=delayed_get):
            result=self.guard.run(self.capture)
        self.assertEqual(result.state,'CAPTURED',result)
        self.assertEqual(len(self.adapter.watch.exits),2)

    def test_explicit_resume_accepts_new_pending_web_without_old_node_assignment(self):
        self.io.pods[self.io.rows['langfuse-web']['uid']]['spec']['nodeName']='fixture-original-node'
        self.start()
        self.assertEqual(self.guard.run(self.capture).state,'CAPTURED')
        self.assertEqual(self.guard.resume().state,'RESUMED')
        self.assertEqual(self.io.writes[-2:],[('langfuse-web',1),('langfuse-worker',1)])

    def test_readiness_retries_connection_refused_only_before_pause(self):
        self.io.ready_replies=['CONNECTION_REFUSED','READY']
        with patch.object(c.live.time,'sleep') as sleep: self.start()
        sleep.assert_called_once_with(3)
        self.assertEqual(self.io.writes,[])
        self.assertEqual(self.adapter.phase,'READY')

    def test_auth_refusal_never_retried_or_paused(self):
        self.io.ready_replies=['AUTH_REFUSED','READY']
        with patch.object(c.live.time,'sleep') as sleep,self.assertRaises(c.Refused): self.start()
        self.assertFalse(any(call.args==(3,) for call in sleep.call_args_list))
        self.assertEqual(self.io.writes,[])
        self.assertEqual(self.io.ready_replies,['READY'])

    def test_terminal_diagnostic_uid_owner_outcome_are_exact(self):
        for name,value in c.DIAGNOSTICS.items():
            pod=copy.deepcopy(self.io.pods[value['pod_uid']]); self.assertTrue(c.diagnostic_pod(pod))
            pod['metadata']['ownerReferences'][0]['uid']='wrong'
            with self.assertRaises(c.Refused): c.diagnostic_pod(pod)
        unknown=copy.deepcopy(next(iter(self.io.pods.values())))
        unknown['metadata']['uid']='extra'; self.io.pods['extra']=unknown
        with self.assertRaises(c.Refused): self.start()
        self.assertEqual(self.io.writes,[])

    def test_transient_writer_between_list_and_first_watch_bookmark_is_not_lost(self):
        original=self.io.bookmark; sent=[False]
        def replay_then_bookmark(initial=False):
            if self.io.process is not None and not sent[0]:
                sent[0]=True
                pod=copy.deepcopy(next(iter(self.io.pods.values())))
                pod['metadata']['uid']='transient-before-handshake'
                for kind in ('ADDED','DELETED'):
                    self.io.rv+=1; pod['metadata']['resourceVersion']=str(self.io.rv)
                    self.io.send({'type':kind,'object':copy.deepcopy(pod)})
            original(initial)
        self.io.bookmark=replay_then_bookmark
        with self.assertRaises(c.Refused): self.start()
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(self.io.writes,[])

    def test_unknown_transient_writer_cannot_disappear_from_history(self):
        self.start()
        pod=copy.deepcopy(next(iter(self.io.pods.values()))); pod['metadata']['uid']='transient'
        self.io.rv+=1; pod['metadata']['resourceVersion']=str(self.io.rv)
        self.io.send({'type':'ADDED','object':pod}); self.io.send({'type':'DELETED','object':pod})
        self.io.bookmark()
        # Native reads give the real background reader a bounded processing barrier.
        for _ in range(100):
            if self.adapter.watch.failed: break
            time.sleep(.005)
        result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete)
        self.assertEqual(self.io.writes,[])

    def test_abnormal_or_unobserved_original_exit_prevents_capture(self):
        self.start(); self.io.exit_code=137
        result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete)
        self.assertEqual(self.io.writes,[('langfuse-web',0)])

    def test_lost_watch_disconnect_and_overflow_are_fail_closed(self):
        self.start(); self.io.process.stdin.close(); self.io.process.wait(timeout=2)
        for _ in range(100):
            if self.adapter.watch.failed: break
            time.sleep(.005)
        self.assertFalse(self.guard.run(self.capture).capture_complete)
        self.assertEqual(self.io.writes,[])

    def test_explicit_overflow_watch_error_and_rv_regression(self):
        self.start(); watch=self.adapter.watch
        for event in ({'type':'ERROR','object':{'code':410}},
                      {'type':'BOOKMARK','object':{'metadata':{'resourceVersion':'1'}}}):
            watch.failed=False; watch.accept(event); self.assertTrue(watch.failed)
        watch.failed=False; watch.events=65536
        watch.accept({'type':'BOOKMARK','object':{'metadata':{'resourceVersion':'100'}}})
        self.assertTrue(watch.failed)

    def test_original_volume_policy_or_argo_mutation_blocks_first_write(self):
        self.start()
        self.io.application['spec']['syncPolicy']['automated']={}
        result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete); self.assertEqual(self.io.writes,[])

    def test_bound_storage_uid_drift_blocks_capture_without_overwrite(self):
        self.start()
        self.io.claims['langfuse-redis']['metadata']['uid']='not-original'
        result=self.guard.run(self.capture)
        self.assertFalse(result.capture_complete); self.assertEqual(self.io.writes,[])

    def test_scheduled_or_db_changes_after_stop_invalidate_capture(self):
        self.start()
        def changing(checkpoint,deadline):
            self.io.queue_values[11]='b'*40
            self.adapter.last_frozen_check=0
            checkpoint()
        result=self.guard.run(changing)
        self.assertFalse(result.capture_complete)
        self.assertEqual(result.reason,'writer_exclusion_lost')
        self.assertEqual(self.io.writes,[('langfuse-web',0),('langfuse-worker',0)])

    def test_active_work_is_not_confused_with_preserved_scheduled_work(self):
        self.start(); self.io.queue_values[1]=1
        self.assertFalse(self.adapter.drained(self.approval.expires_at))
        self.io.queue_values[1]=0
        self.assertTrue(self.adapter.drained(self.approval.expires_at))
        self.io.pg_idle='180007|1|1|1|1|0|0|0'
        self.assertFalse(self.adapter.drained(self.approval.expires_at))

    def test_helper_uid_auth_mount_and_ownership_admission(self):
        helper=copy.deepcopy(self.io.pods[self.io.helper['uid']])
        self.adapter.admit_helper(helper)
        helper['spec']['volumes'][0]['persistentVolumeClaim']['readOnly']=False
        with self.assertRaises(c.Refused): self.adapter.admit_helper(helper)
        helper=copy.deepcopy(self.io.pods[self.io.helper['uid']])
        helper['spec']['containers'][0]['env'][0]={'name':'REDISCLI_AUTH','value':'FAKE-LITERAL-NOT-PERMITTED'}
        with self.assertRaises(c.Refused): self.adapter.admit_helper(helper)


    def test_readiness_shell_classifies_auth_errors_without_echo(self):
        import shlex
        examples=[('PONG',0,'READY'),('Connection refused',1,'CONNECTION_REFUSED'),
                  ('WRONGPASS generated invalid credentials',1,'AUTH_REFUSED'),
                  ('NOAUTH Authentication required.',0,'AUTH_REFUSED'),
                  ('NOPERM generated denied',1,'AUTH_REFUSED'),('unclassified generated failure',1,'REFUSED')]
        for text,code,expected in examples:
            script='timeout() { printf %s '+shlex.quote(text)+'; return '+str(code)+'; };\n'+c.live.READY_SHELL
            result=subprocess.run(('/bin/sh','-c',script),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3)
            self.assertEqual(result.stdout.decode(),expected)
            self.assertEqual(result.stderr,b'')

    def test_missing_final_watch_progress_is_bounded_and_refuses(self):
        self.start()
        listed=self.io.get('pods','',self.approval.expires_at)
        listed['metadata']['resourceVersion']=str(self.io.rv+1)
        with self.assertRaises(c.Refused):
            self.adapter.watch.barrier(listed,time.monotonic()+.02)
        self.assertTrue(self.adapter.watch.failed)
        self.assertEqual(self.io.writes,[])

    def test_home_only_empty_environment_kubectl_wrapper(self):
        with patch('shutil.which',return_value='/usr/bin/kubectl'):
            command=c.producer_command(('kubectl','-n','langfuse','get','pods'))
        self.assertEqual(command,('/usr/bin/env','HOME='+str(Path.home()),'PATH=/usr/bin:/bin',
                                  '/usr/bin/kubectl','-n','langfuse','get','pods'))



def native_structure_fixtures():
    """Generated framing/schema only; native source executables are low-level IO.

    This exercises the CURRENT full CH/SW/VK validators, not a boolean callback.
    Actual native dump/check-aof/restore acceptance has its separate fixture suite.
    """
    import tarfile,gzip,struct
    def tar(files,uid=10000):
        output=io.BytesIO()
        with tarfile.open(fileobj=output,mode='w:') as archive:
            for name,body in files.items():
                entry=tarfile.TarInfo(name); entry.size=len(body); entry.mode=0o600; entry.uid=uid
                archive.addfile(entry,io.BytesIO(body))
        return output.getvalue()
    sw_spec=importlib.util.spec_from_file_location('native_validator_sw_fixture',Path(__file__).with_name('test_langfuse_recovery_seaweed_inventory.py'))
    assert sw_spec and sw_spec.loader
    fixture=importlib.util.module_from_spec(sw_spec); sw_spec.loader.exec_module(fixture)
    d,m,l=fixture.fixture(); l['DiskStatuses']=[dict(dir='/data',all=1000000,used=100,free=999900,percent_free=99,percent_used=1)]
    admitted=c.objects.admit_seaweed(d,m,l,'127.0.0.2')
    def field(number,body): return bytes([number*8+2,len(body)])+body
    entry=field(1,b'x')+field(4,b'\x08\x01')
    full=field(1,b'/')+field(2,entry)
    meta=gzip.compress(struct.pack('>I',len(full))+full,mtime=0)
    volumes={'langfuse_1.dat':b'\x03'+b'\0'*7,'langfuse_1.idx':b'',
        'langfuse_1.vif':json.dumps({'files':[],'version':3,'replication':'','bytesOffset':4,'datFileSize':'0',
            'expireAtSec':'0','readOnly':False,'ecShardConfig':None}).encode()}
    sums=''.join(hashlib.sha256(body).hexdigest()+'  /data/'+name+'\n' for name,body in volumes.items()).encode()
    sw_files={'filer-before.meta.gz':meta,'filer-after.meta.gz':meta,'source-before.sha256':sums,'source-after.sha256':sums,
              **{'volumes/'+name:body for name,body in volumes.items()}}
    for label in ('before','after'):
        for kind,sample in admitted.items(): sw_files[label+'-'+kind+'.json']=json.dumps(sample).encode()
    restore_spec=importlib.util.spec_from_file_location('native_validator_vk_fixture',Path(__file__).with_name('test_langfuse_first_restore.py'))
    assert restore_spec and restore_spec.loader
    restore_fixture=importlib.util.module_from_spec(restore_spec); restore_spec.loader.exec_module(restore_fixture)
    payloads={'postgres-database':b'PGDMPgenerated-source-proof-fixture',
              'postgres-globals':b'-- PostgreSQL database cluster dump\n-- GENERATED ONLY\n-- PostgreSQL database cluster dump complete\n',
              'clickhouse':tar({'.backup':b'GENERATED-NATIVE-FORMAT-METADATA','data/part.bin':b'GENERATED CONTENT'},101),
              'seaweedfs':tar(sw_files),'valkey':restore_fixture.archive(restore_fixture.valkey_files())}
    return payloads,admitted


class NativeValidationWiringTests(unittest.TestCase):
    def setUp(self):
        self.fixture=FirstCaptureTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.payloads,self.admitted=native_structure_fixtures()

    def test_actual_current_three_full_parsers_and_bounded_age_decryption(self):
        fixture=self.fixture
        original=c._command
        current={}
        def source_proof(argv,deadline,**kwargs):
            if argv==('fixture-native-full-source-proof',):
                proof=current['proof']; return (str(proof['bytes'])+'\n'+proof['sha256']+'\n').encode()
            return original(argv,deadline,**kwargs)
        with patch.object(c,'_command',side_effect=source_proof),patch.object(c,'seaweed_sample',return_value=self.admitted):
            for component,payload in self.payloads.items():
                name='generated-native-'+component+'.age'
                ciphertext=subprocess.run((fixture.age,'-r',fixture.recipient),input=payload,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True).stdout
                fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=fixture.fd)
                os.write(fd,ciphertext); os.close(fd)
                proof={'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}; current['proof']=proof
                plan=((component,{'fixture':component},(),('fixture-native-full-source-proof',),()),)
                validator=c.NativeValidator(plan,fixture.age,fixture.identity,1024**2)
                validator.before(component,lambda:None,time.monotonic()+10)
                self.assertTrue(validator(component,fixture.fd,name,proof,lambda:None,time.monotonic()+10))
                self.assertTrue(validator.receipts[component]['complete_native_source_and_archive_validation'])
                with self.assertRaises(c.Refused):
                    c.decrypt_native(fixture.fd,name,fixture.age,fixture.identity,proof,lambda:None,time.monotonic()+10,1)

    def test_valid_cipher_hash_does_not_accept_corrupt_native_tar(self):
        fixture=self.fixture; payload=b'not a native tar but full correctly encrypted bytes'
        cipher=subprocess.run((fixture.age,'-r',fixture.recipient),input=payload,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,check=True).stdout
        fd=os.open('bad.age',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=fixture.fd)
        os.write(fd,cipher); os.close(fd)
        proof={'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
        validator=c.NativeValidator((('clickhouse',{},(),('proof',),()),),fixture.age,fixture.identity,1024**2)
        with patch.object(c,'_command',return_value=(str(len(payload))+'\n'+proof['sha256']+'\n').encode()):
            with self.assertRaises(c.objects.Refused):
                validator('clickhouse',fixture.fd,'bad.age',proof,lambda:None,time.monotonic()+10)
        self.assertEqual(validator.receipts,{})

    def test_standalone_driver_real_adapter_real_validator_real_crypto_local_receiver(self):
        fixture=self.fixture
        fixture.source_patch.stop()  # Exercise the real UID/image metadata projection too.
        backend=KubernetesIOFixture(fixture.local); backend.original_pods=copy.deepcopy(backend.pods)
        request_root=fixture.root/'request-cache'; request_root.mkdir(mode=0o700)
        verified_dir=request_root/c.IDENTITY_BUNDLE; verified_dir.mkdir(mode=0o700)
        request={'operation_id':'fixture-driver','prepared_receipt':str(request_root/'prepared.json'),
            'helper':backend.helper,'authorization_ref':'generated-approved-once','client_idle_ref':'generated-all-clients-admins-idle',
            'custody_ref':'generated-only-inherited-memfd','operator_client_idle_confirmed':True,
            'expires_at':c.datetime.fromtimestamp(time.time()+100,c.timezone.utc).isoformat(),
            'budgets':dict.fromkeys(('postgresql','clickhouse','seaweedfs','valkey'),1024**2),'max_validation_bytes':1024**2}
        for path,data in ((request_root/'request.json',request),(request_root/'prepared.json',backend.prepared),
            (verified_dir/'verified.json',{'status':'IDENTITY_SNAPSHOT_VERIFIED','native_decrypt_and_private_schema_validation':True,
                'secret_count':6,'public_recipient':fixture.recipient,
                'remote_directory':'/storage/k3s/langfuse/recovery/first-20261120/'+c.IDENTITY_BUNDLE})):
            c.save(path,data)
        original_execute=backend.execute; original_command=c._command
        def native_io(pod,container,args,deadline):
            if args[0]=='wget':
                kind={'/dir/status':'directory','/vol/status':'master','/status':'local'}['/'+args[-1].split('/',3)[-1]]
                return json.dumps(self.admitted[kind])
            return original_execute(pod,container,args,deadline)
        def component(argv):
            script=argv[-1]
            if 'postgres-database' in script: return 'postgres-database'
            if 'postgres-globals' in script: return 'postgres-globals'
            container=argv[argv.index('-c')+1]
            return {'clickhouse':'clickhouse','seaweedfs':'seaweedfs','capture':'valkey'}[container]
        def native_commands(argv,deadline,**kwargs):
            if argv[0]=='kubectl':
                if 'get' in argv:
                    name=argv[argv.index('pod')+1]; pod=next(p for p in backend.pods.values() if p['metadata']['name']==name)
                    row=c.pod_row(pod)
                    return '|'.join((row['uid'],row['image'],'Running','true','')).encode()
                name=component(argv); body=self.payloads[name]
                if kwargs.get('output'): return (str(len(body))+'\n'+hashlib.sha256(body).hexdigest()+'\n').encode()
                return b''  # Native generator/parser exits are the low-level source IO seam.
            return original_command(argv,deadline,**kwargs)
        producer_original=c.producer_command
        producers=[]
        def generated_source(argv):
            producers.append(producer_original(argv))
            body=self.payloads[component(argv)]
            return py('import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))',body.hex())
        # Driver's operation journal lives in the new exclusive operation directory.
        backend.root=request_root/'first-live-fixture-driver'; backend.journal_name='operation.jsonl'
        with patch.object(c,'CACHE',request_root),patch.object(c,'get',side_effect=backend.get),\
             patch.object(c,'execute',side_effect=native_io),patch.object(c,'run',side_effect=backend.patch),\
             patch.object(c.live.Adapter,'spawn_watch',autospec=True,side_effect=backend.spawn),\
             patch.object(c.live.Adapter,'_require_pause_ordering',return_value=None),\
             patch.object(c,'_command',side_effect=native_commands),patch.object(c,'producer_command',side_effect=generated_source):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code=c.main(['--capture',str(request_root/'request.json'),'--identity-fd',str(fixture.identity)])
            outcome=json.loads(output.getvalue())
        self.assertEqual(exit_code,0,outcome)
        self.assertEqual(outcome['status'],'CAPTURED')
        self.assertEqual(backend.writes,[('langfuse-web',0),('langfuse-worker',0)])
        self.assertTrue(all(p[:3]==('/usr/bin/env','HOME='+str(Path.home()),'PATH=/usr/bin:/bin') for p in producers))
        self.assertEqual(len(producers),5)
        self.assertTrue((backend.root/'reviewed-plan.json').is_file())



if __name__=='__main__': unittest.main()
