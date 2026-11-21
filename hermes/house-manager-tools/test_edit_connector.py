import copy
import unittest
from datetime import datetime, timezone, timedelta
from test_general_connector_v3 import FakeClient, capabilities
import general_connector_v3 as c
from tests_general import test_edit_general as fixtures
from custom_components.house_manager_general import policy as p

class ConnectorEditTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_expiry_cross_validation_legacy_and_invalid_lifetimes(self):
        fixture=fixtures.EditTests(); b,m,target=fixture.setup_manager()
        q=await fixture.queue_edit(m,target)
        m.now=lambda:datetime(2036,11,15,tzinfo=timezone.utc)
        status=await m.status(fixtures.BOT,q['id'])
        self.assertIsNone(status['proposal']['expires_at'])
        self.assertEqual(c.validate_status(status,q['id']),status)
        p.validate_proposal(status['proposal'],b.inv,now=m.now())
        for kind in ('automation','action'):
            doc=p.make_proposal(kind,fixtures.SPEC if kind=='automation' else fixtures.SPEC['actions'][0],b.inv,now=m.now())
            reply=dict(status,id=doc['id'],proposal=doc)
            self.assertEqual(c.validate_status(reply,doc['id']),reply)
            if kind=='action':
                doc['expires_at']=None
                doc['sha256']=p.hash_json({k:v for k,v in doc.items() if k!='sha256'})
                with self.assertRaises(ValueError):c.validate_status(reply,doc['id'])
        for lifetime in ('legacy','invalid','future','missing'):
            reply=copy.deepcopy(status);doc=reply['proposal']
            created=c.timestamp(doc['created_at'])
            if lifetime=='legacy':doc['expires_at']=(created+timedelta(seconds=900)).isoformat()
            if lifetime=='invalid':doc['expires_at']=(created+timedelta(seconds=901)).isoformat()
            if lifetime=='future':doc['created_at']=(m.now()+timedelta(seconds=1)).isoformat()
            if lifetime=='missing':del doc['expires_at']
            doc['sha256']=p.hash_json({k:v for k,v in doc.items() if k!='sha256'})
            if lifetime=='legacy':
                self.assertEqual(c.validate_status(reply,q['id']),reply)  # Readable historical receipt, not approval.
                with self.assertRaises(p.PolicyError):p.validate_proposal(doc,b.inv,now=m.now())
            else:
                with self.assertRaises(ValueError):c.validate_status(reply,q['id'])

    async def test_discovery_edit_and_status_strict_roundtrip(self):
        fixture=fixtures.EditTests();b,m,target=fixture.setup_manager()
        snapshot=await m.get_managed(__import__('tests_general.test_manager_native',fromlist=['BOT']).BOT,target)
        q=await fixture.queue_edit(m,target)
        doc=m.records[q['id']]['proposal']
        class Client(FakeClient):
            def list_managed(self):return {'automations':[snapshot],'unavailable':[]}
            def get_managed(self, identifier):return snapshot
            def propose_edit(self, request):
                self.request=request
                return q
        caps=capabilities();caps['inventory']={'light.test':dict(caps['inventory']['light.room'],entity_id='light.test')}
        client=Client(caps=caps)
        self.assertEqual(c.handle_tool('list_managed_home_automations',{},client)['response']['automations'][0],snapshot)
        self.assertEqual(c.handle_tool('get_managed_home_automation',{'target_id':target},client)['response'],snapshot)
        req={'target_id':target,'base_config_hash':snapshot['config_hash'],'spec':doc['payload']['spec']}
        self.assertEqual(c.handle_tool('propose_home_automation_edit',req,client)['response'],q)
        self.assertEqual(client.request,req)
        status=await m.status(__import__('tests_general.test_manager_native',fromlist=['BOT']).BOT,q['id'])
        self.assertEqual(c.validate_status(status,q['id']),status)
        broken=copy.deepcopy(status);broken['proposal']['payload']['before']['alias']='tampered'
        with self.assertRaises(ValueError):c.validate_status(broken,q['id'])
        for bad in ('',None,'A'*64):
            with self.assertRaises(ValueError):c.handle_tool('propose_home_automation_edit',dict(req,base_config_hash=bad),client)
        await m.approve(q['id'],q['sha256'])
        status=await m.status(fixtures.BOT,q['id'])
        self.assertEqual(c.validate_status(status,q['id']),status)
        broken=copy.deepcopy(status);broken['runtime_state']='on'
        with self.assertRaises(ValueError):c.validate_status(broken,q['id'])
        for name in ('list_managed_home_automations','get_managed_home_automation'):
            tool=next(t for t in c.TOOLS if t['name']==name)
            self.assertTrue(tool['annotations']['readOnlyHint'])

    def test_transport_allows_only_bounded_edit_discovery_routes(self):
        client=c.HAClient('fake')
        calls=[]
        client._request=lambda *args:calls.append(args) or {}
        target='house_manager_general_'+'a'*32
        client.list_managed();client.get_managed(target)
        client.propose_edit({'target_id':target,'base_config_hash':'b'*64,'spec':{'title':'Off','triggers':[{'type':'time','at':'22:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]}})
        self.assertEqual([x[:2] for x in calls],[('GET','/managed'),('GET','/managed/'+target),('POST','/edits')])
        with self.assertRaises(ValueError):client.get_managed('../proposals')
