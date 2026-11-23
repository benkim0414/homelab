"""Offline tests for the one-shot packaged runner. No Docker execution."""
import ast
import copy
import json
import importlib.util
import ipaddress
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'hindsight/extensions/specialist-memory/validation/run.py'


class PackagedRunnerTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_client_failure_preserves_only_redacted_diagnostic_fields(self):
        module=self.load()
        diagnostic={'ok':False,'stage':'bank','exception':'ValueError','status':None}
        result=subprocess.CompletedProcess([],1,json.dumps({**diagnostic,'body':'UNIT-SENSITIVE'}),'UNIT-SENSITIVE')
        with tempfile.TemporaryDirectory() as tmp,patch.object(module.subprocess,'run',return_value=result):
            with self.assertRaises(module.Failure):
                module._client_phase('positive','http://127.0.0.1:8123',Path(tmp),subnet='10.254.240.0/28')
            saved=json.loads((Path(tmp)/'client-positive-failure.json').read_text())
        self.assertEqual(saved,diagnostic)

    def load(self):
        self.assertTrue(SOURCE.is_file(), 'packaged database runner is missing')
        sys.path.insert(0,str(SOURCE.parent))
        spec=importlib.util.spec_from_file_location('specialist_packaged_run',SOURCE)
        assert spec and spec.loader
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_subnet_avoids_host_and_docker_ranges(self):
        module=self.load()
        subnet=module.choose_subnet(['192.168.0.0/24','10.42.0.0/16','172.30.200.0/28'],['172.30.201.0/24'])
        self.assertEqual(subnet,'172.30.200.16/28')
        with self.assertRaises(ValueError):module.choose_subnet(['172.30.0.0/16','10.254.0.0/16'],[])

    def test_subnet_falls_back_when_preferred_pool_is_covered_by_existing_route(self):
        module=self.load()
        routes=['172.30.0.0/16','10.42.0.0/16','10.254.240.0/28']
        used=['10.254.240.0/24']
        selected=ipaddress.IPv4Network(module.choose_subnet(routes,used))
        self.assertTrue(selected.subnet_of(ipaddress.IPv4Network('10.254.240.0/20')))
        self.assertEqual(selected.prefixlen,28)
        self.assertFalse(any(selected.overlaps(ipaddress.ip_network(x)) for x in routes+used))

    def target_fixture(self, module):
        from docker_resources import Handle, LABEL
        api=Handle('container','unit-api','unit-owner','sha256:'+'a'*64,'b'*64)
        network=Handle('network','unit-network','unit-owner',id='c'*64)
        container={'Id':api.id,'Name':'/'+api.name,'Image':api.image,
                   'Config':{'Image':api.image,'Labels':{LABEL:api.owner}},
                   'State':{'Status':'running'},
                   'NetworkSettings':{'Networks':{network.name:{'NetworkID':network.id,
                       'IPAddress':'10.254.240.3','IPPrefixLen':28}}}}
        net={'Id':network.id,'Name':network.name,'Labels':{LABEL:network.owner},'Internal':True,
             'IPAM':{'Config':[{'Subnet':'10.254.240.0/28'}]},
             'Containers':{api.id:{'Name':api.name,'IPv4Address':'10.254.240.3/28'}}}
        life=SimpleNamespace(owner=api.owner,handles=[api,network],
                             _inspect=lambda h:'running' if h is api else 'stopped')
        calls=[]
        def inspect(stage,args):
            calls.append(args)
            return [container if args[0]=='container' else net]
        return api,network,container,net,life,SimpleNamespace(json=inspect),calls

    def test_direct_target_requires_exact_owned_internal_attachment(self):
        module=self.load()
        api,network,container,net,life,docker,calls=self.target_fixture(module)
        url=module._verified_url(docker,life,api,network,'10.254.240.0/28')
        self.assertEqual(url,'http://10.254.240.3:8888')
        self.assertEqual(calls,[['container','inspect',api.id],['network','inspect',network.id]])
        self.assertEqual(module._verified_url(docker,life,api,network,'10.254.240.0/28',expected=url),url)
        for target,path,value in (
            ('container',('Id',),'d'*64), ('container',('Name',),'/foreign'),
            ('container',('Image',),'sha256:'+'d'*64),
            ('container',('Config','Image'),'foreign'),
            ('container',('Config','Labels'),'wrong'),
            ('container',('State','Status'),'exited'),
            ('container',('NetworkSettings','Networks',network.name,'NetworkID'),'d'*64),
            ('container',('NetworkSettings','Networks',network.name,'IPAddress'),'10.254.241.3'),
            ('container',('NetworkSettings','Networks',network.name,'IPAddress'),'10.254.240.0'),
            ('container',('NetworkSettings','Networks',network.name,'IPAddress'),'::1'),
            ('container',('NetworkSettings','Networks',network.name,'IPAddress'),int(ipaddress.IPv4Address('10.254.240.3'))),
            ('container',('NetworkSettings','Networks',network.name,'IPPrefixLen'),24),
            ('net',('Id',),'d'*64), ('net',('Name',),'foreign'),
            ('net',('Labels',),{}), ('net',('Internal',),False),
            ('net',('IPAM','Config'),[{'Subnet':'10.254.241.0/28'}]),
            ('net',('Containers',),{}),
            ('net',('Containers',api.id,'IPv4Address'),'10.254.240.4/28')):
            with self.subTest(path=path,value=value):
                a,n,c,b,l,d,_=self.target_fixture(module)
                obj=c if target=='container' else b
                for key in path[:-1]:obj=obj[key]
                obj[path[-1]]=value
                with self.assertRaises(module.Failure):
                    module._verified_url(d,l,a,n,'10.254.240.0/28',expected=url)
        container['NetworkSettings']['Networks'][network.name]['IPAddress']='10.254.240.4'
        net['Containers'][api.id]['IPv4Address']='10.254.240.4/28'
        with self.assertRaises(module.Failure):
            module._verified_url(docker,life,api,network,'10.254.240.0/28',expected=url)

    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_parent_phase_passes_exact_context_without_widening_standalone_cli(self):
        from unittest.mock import patch
        module=self.load()
        import client
        url='http://10.254.240.3:8888';subnet='10.254.240.0/28'
        valid=self.complete_report(module)['positive']
        calls=[]
        def child(args,**kwargs):
            calls.append((args,kwargs))
            # Execute the actual bootstrap with an inert UNIT phase boundary.
            with patch.object(sys,'argv',['-c',*args[4:]]), patch.object(client,'main',return_value=0) as main:
                with self.assertRaises(SystemExit) as stopped:exec(args[3],{})
                self.assertEqual(stopped.exception.code,0)
                main.assert_called_once_with(['positive',url],verified_target=(url,subnet))
            return subprocess.CompletedProcess(args,0,json.dumps(valid),'')
        with patch.object(module.subprocess,'run',side_effect=child):
            self.assertEqual(module._client_phase('positive',url,Path('/unit-only'),subnet=subnet),valid)
        self.assertEqual(calls[0][1]['timeout'],200)
        self.assertEqual(set(calls[0][1]['env']),{'PATH','HOME','LANG','PYTHONDONTWRITEBYTECODE'})

    def test_health_and_each_phase_recheck_target_and_api_create_has_no_publish(self):
        tree=ast.parse(SOURCE.read_text())
        runner=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_validation')
        guarded=next(n for n in runner.body if isinstance(n,ast.Try))
        ready=next(n for n in guarded.body if isinstance(n,ast.FunctionDef) and n.name=='api_ready')
        first=ready.body[0].value
        self.assertEqual(first.func.id,'_verified_url')
        for index,node in enumerate(guarded.body):
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='_client_phase':
                check=guarded.body[index-1].value
                self.assertEqual(check.func.id,'_verified_url')
                self.assertEqual(check.keywords[0].arg,'expected')
                self.assertEqual(check.keywords[0].value.id,'url')
        api=next(n for n in guarded.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='api' for t in n.targets))
        self.assertNotIn('ports',{k.arg for k in api.value.keywords})
        module=self.load()
        with self.assertRaises(module.Failure):module._NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_owned_stopped_network_and_volume_are_valid_handles(self):
        module=self.load()
        life=SimpleNamespace(_inspect=lambda h:'stopped')
        for kind in ('network','volume'):
            module._owned(life,SimpleNamespace(id='owned',failed=False,kind=kind))

    def test_privilege_failure_never_creates_or_pulls_resources(self):
        module=self.load()
        calls=[]
        def unavailable(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,1,'','private error text must not escape')
        with tempfile.TemporaryDirectory() as tmp:
            report=module.run_validation(sudo=False,output_root=Path(tmp),command=unavailable)
            self.assertFalse(report['passed'])
            self.assertEqual(report['stage'],'docker-access')
            self.assertTrue(report['checks']['cleanup'])
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1],'version')
            self.assertNotIn('private error',str(report))

    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_database_positive_control_rejects_empty_or_changed_fixture_rows(self):
        module=self.load()
        records=importlib.import_module('client').RECORDS
        # Explicit synthetic UNIT rows, never used by the actual SQL client.
        rows={schema: {'documents': [],'memory_units': []} for schema in module.SCHEMAS}
        self.assertFalse(module.fixture_rows_match(rows))
        for record in records:
            rows[record['schema']]['documents'].append({
                'id': record['document'],'bank_id': record['bank'],
                'original_text': record['text'],'content_hash': 'unit-only-hash'})
            rows[record['schema']]['memory_units'].append({
                'id': 'unit-only-id','document_id': record['document'],
                'bank_id': record['bank'],'text': record['text'],'fact_type': 'world'})
        self.assertTrue(module.fixture_rows_match(rows))
        rows['public']['documents'][0]['original_text']='unit-only-wrong-text'
        self.assertFalse(module.fixture_rows_match(rows))

    def complete_report(self, module):
        from client import POSITIVE_CHECKS,DENIAL_CHECKS
        positive={'ok':True,'checks':dict.fromkeys(POSITIVE_CHECKS,True),
                  'counts':{'documents':3,'rest_recalls':3,'mcp_recalls':3,'readonly_inventories':2}}
        negative={'ok':True,'checks':dict.fromkeys(DENIAL_CHECKS,True),'counts':{'denials':42,'own_recalls':2}}
        return {'passed':True,'stage':'complete','checks':dict.fromkeys(module.CHECKS,True),
                'positive':positive,'denials':negative}

    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_acceptance_requires_complete_boolean_checks_and_phase_counts(self):
        module=self.load()
        report=self.complete_report(module)
        self.assertTrue(module.acceptance_is_valid(report))
        for field, value in (('checks',{}),('checks',[]),('passed',1)):
            bad=copy.deepcopy(report);bad[field]=value
            self.assertFalse(module.acceptance_is_valid(bad))
        for name in module.CHECKS:
            bad=copy.deepcopy(report);bad['checks'][name]=1
            self.assertFalse(module.acceptance_is_valid(bad))
        bad=copy.deepcopy(report);bad['positive']['counts']['documents']=True
        self.assertFalse(module.acceptance_is_valid(bad))
        bad=copy.deepcopy(report);bad['denials']['counts']['denials']=0
        self.assertFalse(module.acceptance_is_valid(bad))

    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_acceptance_rejects_incomplete_or_missing_stage(self):
        module=self.load()
        for stage in ('snapshot-after','positive-client','',None):
            with self.subTest(stage=stage):
                report=self.complete_report(module);report['stage']=stage
                self.assertFalse(module.acceptance_is_valid(report))
        report=self.complete_report(module);del report['stage']
        self.assertFalse(module.acceptance_is_valid(report))

    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_acceptance_rejects_any_error_key_even_when_complete(self):
        module=self.load()
        for error in ({'type':'KeyboardInterrupt','exit_code':None},None,{},False,''):
            with self.subTest(error=error):
                report=self.complete_report(module);report['error']=error
                self.assertFalse(module.acceptance_is_valid(report))

    @unittest.skipUnless(importlib.util.find_spec('httpx2'),'requires the dedicated client dependency environment')
    def test_interrupted_after_last_check_cannot_pass_finalization(self):
        module=self.load()
        # Exercise the runner's actual catch/finally without its Docker/DB body.
        tree=ast.parse(SOURCE.read_text())
        runner=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='run_validation')
        guarded=copy.deepcopy(next(node for node in runner.body if isinstance(node,ast.Try)))
        guarded.body=ast.parse('raise KeyboardInterrupt()').body
        harness=ast.fix_missing_locations(ast.Module(body=[guarded],type_ignores=[]))
        report=self.complete_report(module)
        report.update(passed=False,stage='snapshot-after')
        report['checks']['cleanup']=False
        life=SimpleNamespace(cleanup=lambda:True,handles=[],events=[])
        with tempfile.TemporaryDirectory() as tmp:
            scope=dict(vars(module),report=report,life=life,run_dir=Path(tmp))
            exec(compile(harness,str(SOURCE),'exec'),scope)
            saved=json.loads((Path(tmp)/'result.json').read_text())
        self.assertTrue(all(value is True for value in report['checks'].values()))
        self.assertEqual(report['error']['type'],'KeyboardInterrupt')
        self.assertEqual(report['stage'],'snapshot-after')
        self.assertFalse(report['passed'])
        self.assertFalse(saved['passed'])
        self.assertFalse(module.acceptance_is_valid(saved))


if __name__=='__main__':unittest.main()
