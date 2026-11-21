"""Deterministic bundle/init checks; never access production or credentials."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import yaml
from runtime_context import build_bundle, init_overlay, render, probe_installed_image

ROOT=Path(__file__).resolve().parent
FIXTURES=ROOT/'runtime_context/.test-state/installed'


class BundleTests(unittest.TestCase):
    def test_bundle_is_reproducible_immutable_and_matches_declared_mounts(self):
        config,receipt=build_bundle.bundle(FIXTURES)
        self.assertEqual((config,receipt),build_bundle.bundle(FIXTURES))
        saved=yaml.safe_load((ROOT.parent/'runtime-context.yaml').read_text())
        self.assertEqual(saved,config)
        self.assertIs(config['immutable'],True)
        self.assertEqual(set(config['data']),{'render.py','init_overlay.py','expected.json'})
        deployment=next(d for d in yaml.safe_load_all((ROOT.parent/'deployment.yaml').read_text()) if d['kind']=='Deployment')
        pod=deployment['spec']['template']
        self.assertEqual(pod['metadata']['annotations']['checksum/runtime-context'],receipt['checksum'])
        spec=pod['spec'];main=spec['containers'][0]
        init=next(c for c in spec['initContainers'] if c['name']=='verify-runtime-context')
        self.assertEqual(init['image'],main['image'])
        self.assertNotIn('env',init)
        self.assertNotIn('envFrom',init)
        self.assertEqual({v['name'] for v in init['volumeMounts']},{'runtime-context-source','runtime-context-overlay'})
        self.assertFalse(spec['automountServiceAccountToken'])
        mounts=[v for v in main['volumeMounts'] if v['name']=='runtime-context-overlay']
        self.assertEqual({v['subPath'] for v in mounts},set(render.BASE_SHA256))
        self.assertTrue(all(v['readOnly'] and v['mountPath']=='/opt/hermes/'+v['subPath'] for v in mounts))
        volumes={v['name']:v for v in spec['volumes']}
        self.assertEqual(volumes['runtime-context-source']['configMap']['name'],receipt['name'])
        self.assertEqual(volumes['data']['persistentVolumeClaim']['claimName'],'hermes-data')
        self.assertEqual(deployment['spec']['strategy']['type'],'Recreate')

    def test_init_checks_originals_outputs_and_idempotent_private_scratch(self):
        config,receipt=build_bundle.bundle(FIXTURES)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bundle=root/'bundle';output=root/'output'
            bundle.mkdir();output.mkdir()
            for name,data in config['data'].items():(bundle/name).write_text(data)
            result=init_overlay.prepare(FIXTURES,bundle,output)
            self.assertEqual(result,receipt['output_sha256'])
            self.assertEqual(init_overlay.prepare(FIXTURES,bundle,output),result)
            for name,digest in result.items():
                self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(),digest)
                self.assertEqual((output/name).stat().st_mode & 0o777,0o444)

    def test_image_probe_uses_clean_environment_and_exact_reviewed_recipe(self):
        config,receipt=build_bundle.bundle(FIXTURES)
        response={'runtime_image_probe':'PASS','output_sha256':receipt['output_sha256']}
        with patch.object(probe_installed_image.subprocess,'run',return_value=NS(returncode=0,stdout=json.dumps(response))) as run:
            result=probe_installed_image.probe(FIXTURES)
        args,kwargs=run.call_args
        command=args[0]
        self.assertEqual(command[:8],['kubectl','-n','hermes','exec','-i','deployment/hermes','-c','hermes'])
        self.assertIn('/command/s6-setuidgid',command)
        self.assertIn('-i',command[command.index('env')+1:])
        self.assertEqual(command[-2:],['-c',probe_installed_image.REMOTE])
        self.assertEqual(json.loads(kwargs['input']),config['data'])
        self.assertEqual(kwargs['timeout'],60)
        self.assertEqual(result['checksum'],receipt['checksum'])

    def test_image_probe_failure_does_not_expose_remote_output(self):
        response=NS(returncode=1,stdout='synthetic-private-output',stderr='synthetic-private-error')
        with patch.object(probe_installed_image.subprocess,'run',return_value=response),self.assertRaises(RuntimeError) as caught:
            probe_installed_image.probe(FIXTURES)
        self.assertNotIn('synthetic-private',str(caught.exception))

    def test_image_probe_rejects_status_and_digest_mismatch(self):
        for response in ({'runtime_image_probe':'FAIL','output_sha256':{}},
                         {'runtime_image_probe':'PASS','output_sha256':{}}):
            with self.subTest(response=response),patch.object(probe_installed_image.subprocess,'run',return_value=NS(returncode=0,stdout=json.dumps(response))),self.assertRaises(RuntimeError):
                probe_installed_image.probe(FIXTURES)

    def test_wrong_expected_digest_and_symlink_or_drift_refuse(self):
        config,receipt=build_bundle.bundle(FIXTURES)
        for kind in ('expected','symlink','source'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);bundle=root/'bundle';output=root/'output';source=root/'source'
                bundle.mkdir();output.mkdir()
                for name,data in config['data'].items():(bundle/name).write_text(data)
                for name in render.BASE_SHA256:
                    target=source/name;target.parent.mkdir(exist_ok=True,parents=True)
                    target.write_bytes((FIXTURES/name).read_bytes())
                if kind=='expected':
                    expected=json.loads((bundle/'expected.json').read_text());expected['gateway/session_policy.py']='0'*64
                    (bundle/'expected.json').write_text(json.dumps(expected))
                elif kind=='symlink':(output/'gateway').symlink_to(root/'outside')
                else:(source/'gateway/session_policy.py').write_bytes(b'drift')
                with self.assertRaises(ValueError):init_overlay.prepare(source,bundle,output)
                self.assertFalse((output/'hermes_cli').exists())


if __name__=='__main__':unittest.main()
