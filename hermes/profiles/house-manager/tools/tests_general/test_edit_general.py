"""Conditional edits use real policy and a no-device native boundary."""
import copy
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from custom_components.house_manager_general import policy as p
from custom_components.house_manager_general.engine import Manager, ApprovalError
from tests_general.test_manager_native import Boundary, BOT

SPEC = {'title':'Daily lamp off','triggers':[{'type':'time','at':'23:00:00'}], 'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]}

class EditBoundary(Boundary):
    async def loaded(self, identifier):
        row = next((r for r in self.rows if r['id'] == identifier), None)
        return None if row is None else {'entity_id':'automation.managed', 'state':self.runtime_state, 'raw_config':copy.deepcopy(row)}
    async def reload(self, identifier):
        assert self.lock.locked()
        self.events.append('reload:'+identifier)
        # HA 2026.11.1 restores the same entity's last state if initial_state=None.
    async def reload_edit(self, identifier):
        assert self.lock.locked()
        self.events.append('reload:'+identifier)
    async def disable(self, entity):
        assert self.lock.locked()
        self.events.append('disable:'+entity)
        self.runtime_state='off'

class EditTests(unittest.IsolatedAsyncioTestCase):
    def setup_manager(self, state='off'):
        b=EditBoundary(); b.runtime_state=state
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        now=datetime(2026,11,15,tzinfo=timezone.utc)
        doc=p.make_proposal('automation',SPEC,b.inv,now=now-timedelta(hours=1))
        config=dict(p.validate_spec(SPEC,b.inv),id=doc['id'])
        b.rows.append(config)
        record={'status':'verified_enabled','proposal':doc,'config_hash':p.hash_json(config), 'verified_at':now.isoformat(), 'preview':{'message_id':'1'},'approval':{'message_id':'2'}}
        m=Manager(b,BOT.id,{doc['id']:record},now=lambda:now);m.approval_ready=True
        return b,m,doc['id']

    async def queue_edit(self, m, target):
        snapshot=await m.get_managed(BOT,target)
        spec=copy.deepcopy(SPEC);spec['triggers'][0]['at']='22:30:00'
        queued=await m.propose_edit(BOT,{'target_id':target,'base_config_hash':snapshot['config_hash'],'spec':spec})
        m.records[queued['id']].update(status='awaiting_approval',preview={'message_id':'3'},approval={'message_id':'4'})
        return queued

    async def test_approved_edit_preserves_off_id_other_rows_and_supersedes_receipt(self):
        b,m,target=self.setup_manager()
        old=copy.deepcopy(b.rows)
        q=await self.queue_edit(m,target)
        self.assertEqual(b.rows,old)
        doc=m.records[q['id']]['proposal']
        self.assertEqual(doc['payload']['before'],old[-1])
        self.assertEqual(doc['payload']['base_config_hash'],p.hash_json(old[-1]))
        result=await m.approve(q['id'],q['sha256'])
        self.assertEqual(result['status'],'verified_edit')
        self.assertEqual(b.rows[0],old[0]);self.assertEqual(b.rows[-1]['id'],target)
        self.assertEqual(b.rows[-1]['triggers'][0]['at'],'22:30:00')
        self.assertEqual(b.rows[-1]['actions'],old[-1]['actions'])
        self.assertEqual(b.runtime_state,'off')
        self.assertEqual(b.events.count('disable:automation.managed'),2)
        self.assertNotIn('device',b.events)
        self.assertFalse(any(e.startswith('enable:') for e in b.events))
        self.assertEqual((await m.status(BOT,target))['status'],'superseded')
        self.assertEqual((await m.status(BOT,q['id']))['status'],'verified_edit')
        self.assertEqual((await m.get_managed(BOT,target))['owner_record_id'],q['id'])
        self.assertEqual(len((await m.list_managed(BOT))['automations']),1)
        with self.assertRaises(ApprovalError):await m.approve(q['id'],q['sha256'])

    async def test_edit_refuses_drift_unowned_duplicates_and_unsafe_initial_state(self):
        for drift in ('config','runtime','missing','duplicate','owner','initial_true','initial_false','binding','expired','hash'):
            with self.subTest(drift=drift):
                b,m,target=self.setup_manager()
                if drift.startswith('initial_'):
                    b.rows[-1]['initial_state']=drift=='initial_true'
                    m.records[target]['config_hash']=p.hash_json(b.rows[-1])
                    with self.assertRaises(ApprovalError):await self.queue_edit(m,target)
                    continue
                q=await self.queue_edit(m,target)
                if drift=='config':b.rows[-1]['alias']='operator edit'
                if drift=='runtime':b.runtime_state='on'
                if drift=='missing':b.rows.pop()
                if drift=='duplicate':b.rows.append(copy.deepcopy(b.rows[-1]))
                if drift=='owner':m.records[target]['status']='uncertain'
                if drift=='binding':b.inv['light.test']['registry_fingerprint']='b'*64
                if drift=='expired':
                    # Legacy finite edit retains its original immutable deadline.
                    doc=m.records[q['id']]['proposal']
                    doc['expires_at']=(m.now()+timedelta(seconds=900)).isoformat()
                    doc['sha256']=p.hash_json({k:v for k,v in doc.items() if k!='sha256'})
                    q['sha256']=doc['sha256']
                    m.now=lambda:datetime(2026,11,16,tzinfo=timezone.utc)
                before=copy.deepcopy(b.rows)
                with self.assertRaises(ApprovalError):await m.approve(q['id'],'0'*64 if drift=='hash' else q['sha256'])
                self.assertEqual(b.rows,before)
                self.assertFalse(any(e.startswith(('reload','disable','enable')) or e=='write' for e in b.events))

    async def test_second_edit_preserves_on_and_restart_ledger_accepts_new_statuses(self):
        from custom_components.house_manager_general.runtime import validate_records
        b,m,target=self.setup_manager('on')
        q=await self.queue_edit(m,target)
        await m.approve(q['id'],q['sha256'])
        records=validate_records(m.records)
        n=Manager(b,BOT.id,records,now=lambda:m.now()+timedelta(minutes=2));n.approval_ready=True
        r=await self.queue_edit(n,target)
        await n.approve(r['id'],r['sha256'])
        self.assertEqual(n.records[q['id']]['status'],'superseded')
        self.assertEqual((await n.get_managed(BOT,target))['runtime_state'],'on')
        self.assertFalse(any(e.startswith(('enable','disable')) for e in b.events))

    async def test_native_disable_is_locked_targeted_and_never_stops_actions(self):
        from custom_components.house_manager_general.native import NativeBoundary
        calls=[]
        async def call(*args,**kwargs):calls.append((args,kwargs))
        boundary=NativeBoundary(SimpleNamespace(services=SimpleNamespace(async_call=call)),{},SimpleNamespace(mutation_lock=__import__('asyncio').Lock()),None)
        with self.assertRaises(ApprovalError):await boundary.disable('automation.managed')
        async with boundary.lock:await boundary.disable('automation.managed')
        self.assertEqual(calls,[(('automation','turn_off',{'entity_id':'automation.managed','stop_actions':False}),{'blocking':True})])

    async def test_runtime_toggle_during_prewrite_check_is_refused(self):
        b,m,target=self.setup_manager('on')
        q=await self.queue_edit(m,target)
        original=b.capabilities
        async def drift():
            if b.lock.locked():b.runtime_state='off'
            return await original()
        b.capabilities=drift
        before=copy.deepcopy(b.rows)
        with self.assertRaises(ApprovalError):await m.approve(q['id'],q['sha256'])
        self.assertEqual(b.rows,before)
        self.assertNotIn('write',b.events)

    async def test_independent_edit_approvals_serialize_and_stale_base_never_overwrites(self):
        import asyncio
        b,m,target=self.setup_manager('on')
        first=await self.queue_edit(m,target)
        m.now=lambda:datetime(2026,11,15,tzinfo=timezone.utc)+timedelta(minutes=2)
        second=await self.queue_edit(m,target)
        results=await asyncio.gather(m.approve(first['id'],first['sha256']),m.approve(second['id'],second['sha256']),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(sum(isinstance(r,ApprovalError) for r in results),1)
        self.assertEqual(b.events.count('write'),1)
        self.assertEqual(b.events.count('reload:'+target),1)

    async def test_unowned_prefix_missing_approval_and_legacy_ledger_cannot_be_adopted(self):
        for missing in ('approval','preview','verified_at','version','status'):
            b,m,target=self.setup_manager()
            if missing=='version':m.records[target]['proposal']['version']=2
            else:m.records[target].pop(missing)
            with self.assertRaises(ApprovalError):await m.get_managed(BOT,target)
            self.assertEqual((await m.list_managed(BOT))['automations'],[])
            with self.assertRaises(ApprovalError):await self.queue_edit(m,target)
            self.assertNotIn('write',b.events)
        b,m,target=self.setup_manager();m.records.clear()
        with self.assertRaises(ApprovalError):await m.get_managed(BOT,target)

    async def test_off_reload_mismatch_is_corrected_without_enable_and_reported_uncertain(self):
        b,m,target=self.setup_manager()
        async def bad_reload(identifier):
            b.events.append('reload:'+identifier)
            b.runtime_state='on'
        b.reload_edit=bad_reload
        q=await self.queue_edit(m,target)
        with self.assertRaises(ApprovalError):await m.approve(q['id'],q['sha256'])
        self.assertEqual(b.runtime_state,'off')
        self.assertEqual(m.records[q['id']]['status'],'uncertain')
        self.assertEqual(m.records[target]['status'],'verified_enabled')
        with self.assertRaises(ApprovalError):await m.get_managed(BOT,target)

    async def test_discord_preview_labels_edit_and_exact_before_after_hashes(self):
        from custom_components.house_manager_general.discord import preview_text
        b,m,target=self.setup_manager()
        q=await self.queue_edit(m,target)
        doc=m.records[q['id']]['proposal'];text=preview_text(doc)
        self.assertIn('EDIT',text);self.assertIn(target,text)
        self.assertIn(doc['payload']['base_config_hash'],text)
        self.assertIn(p.hash_json(doc['payload']['after']),text)
        self.assertIn('off',text)
