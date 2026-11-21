"""No-network approval identity, one-use ledger and shared mutation tests."""
import asyncio
import copy
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch
from custom_components.house_manager_general.chat import ChatApprovals
from custom_components.house_manager_general.engine import Manager, ApprovalError
from custom_components.house_manager_general import policy as p, runtime
from custom_components.house_manager_general.native import validate_settings
from tests_general.test_manager_native import Boundary, BOT
from tests_general import test_edit_general as edit_tests

HUMAN = NS(id='c'*32, is_admin=False, is_active=True)
SPEC = {'title':'Daily lamp off','triggers':[{'type':'time','at':'23:00:00'}],
        'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]}


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def setup_pending(self):
        b = Boundary()
        b.inv = {'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        m = Manager(b, BOT.id, {}, now=lambda:datetime(2026,11,20,tzinfo=timezone.utc))
        m.approval_ready = True
        q = await m.propose(BOT, {'spec':SPEC})
        m.records[q['id']].update(status='awaiting_approval', preview={'message_id':'11'})
        adapter=ChatApprovals(m,HUMAN.id)
        q['interaction_id']=(await adapter.get(HUMAN,q['id']))['interaction_id']
        return b, m, adapter, q

    def body(self, q):
        return {'sha256':q['sha256'], 'surface':'local_chat', 'session_id':'20261120_test',
                'interaction_id':q['interaction_id']}

    async def test_create_stores_separate_evidence_and_is_owned_and_readable(self):
        b, m, adapter, q = await self.setup_pending()
        preview = await adapter.get(HUMAN, q['id'])
        q['interaction_id']=preview['interaction_id']
        self.assertEqual(preview['proposal'], m.records[q['id']]['proposal'])
        self.assertEqual(preview['status'], 'awaiting_approval')
        self.assertNotIn('write', b.events)
        result = await adapter.approve(HUMAN, q['id'], self.body(q))
        self.assertEqual(result['status'], 'verified_enabled')
        evidence = m.records[q['id']]['approval']
        self.assertEqual(evidence['transport'], 'hermes_command')
        self.assertEqual(evidence['author_id'], HUMAN.id)
        self.assertEqual(evidence['sha256'], q['sha256'])
        self.assertEqual((await m.get_managed(BOT, q['id']))['runtime_state'], 'on')
        from general_connector_v3 import validate_status
        self.assertEqual(validate_status(await m.status(BOT, q['id']), q['id'])['status'], 'verified_enabled')
        with self.assertRaises(ApprovalError):
            await adapter.approve(HUMAN, q['id'], self.body(q))
        self.assertEqual(b.events.count('write'), 1)
        self.assertNotIn('device', b.events)

    async def test_bot_other_user_admin_inactive_and_disabled_denied(self):
        b, m, adapter, q = await self.setup_pending()
        for user in (None, NS(id=BOT.id,is_admin=False,is_active=True),
                     NS(id='d'*32,is_admin=False,is_active=True),
                     NS(id=HUMAN.id,is_admin=True,is_active=True),
                     NS(id=HUMAN.id,is_admin=False,is_active=False)):
            with self.subTest(user=user):
                with self.assertRaises(ApprovalError) as caught:
                    await adapter.get(user, q['id'])
                self.assertEqual(caught.exception.status, 403)
                with self.assertRaises(ApprovalError):
                    await adapter.approve(user,q['id'],self.body(q))
        with self.assertRaises(ApprovalError):
            await ChatApprovals(m,None).get(HUMAN,q['id'])
        self.assertNotIn('write',b.events)

    async def test_wrong_hash_status_kind_and_discord_claim_cannot_approve(self):
        for case in ('hash','queued','pending','uncertain','expired','executed','verified_enabled','preview','approval','action','binding'):
            b,m,adapter,q=await self.setup_pending()
            record=m.records[q['id']]
            body=self.body(q)
            if case=='hash':body['sha256']='0'*64
            elif case=='preview':record.pop('preview')
            elif case=='approval':record['approval']={'message_id':'22'}
            elif case=='action':
                doc=p.make_proposal('action',SPEC['actions'][0],b.inv,now=m.now())
                record['proposal']=doc
                body['sha256']=doc['sha256']
            elif case=='binding':b.inv['light.test']['registry_fingerprint']='b'*64
            else:record['status']=case
            with self.subTest(case=case), self.assertRaises(ApprovalError):
                await adapter.approve(HUMAN,q['id'],body)
            self.assertNotIn('write',b.events)
            self.assertNotIn('device',b.events)

    async def test_preview_interaction_is_exact_single_use_and_refetch_invalidates(self):
        b,m,adapter,q=await self.setup_pending()
        old=self.body(q)
        preview=await adapter.get(HUMAN,q['id'])
        self.assertNotEqual(preview['interaction_id'],old['interaction_id'])
        with self.assertRaises(ApprovalError):await adapter.approve(HUMAN,q['id'],old)
        q['interaction_id']=preview['interaction_id']
        for field,value in (('interaction_id','0'*32),('author_id','d'*32),('sha256','0'*64)):
            saved=copy.deepcopy(m.records[q['id']]['chat_preview'])
            m.records[q['id']]['chat_preview'][field]=value
            with self.subTest(field=field),self.assertRaises(ApprovalError):
                await adapter.approve(HUMAN,q['id'],self.body(q))
            m.records[q['id']]['chat_preview']=saved
        self.assertNotIn('write',b.events)
        result=await adapter.approve(HUMAN,q['id'],self.body(q))
        self.assertEqual(result['status'],'verified_enabled')
        with self.assertRaises(ApprovalError):await adapter.approve(HUMAN,q['id'],self.body(q))

    async def test_confirmation_expiry_does_not_expire_or_rehash_proposal(self):
        b,m,adapter,q=await self.setup_pending()
        original=copy.deepcopy(m.records[q['id']]['proposal'])
        old=m.now();m.now=lambda:old+timedelta(seconds=300)
        with self.assertRaises(ApprovalError) as caught:
            await adapter.approve(HUMAN,q['id'],self.body(q))
        self.assertEqual(caught.exception.code,'chat_preview_expired')
        self.assertEqual(m.records[q['id']]['status'],'awaiting_approval')
        self.assertEqual(m.records[q['id']]['proposal'],original)
        self.assertNotIn('write',b.events)
        q['interaction_id']=(await adapter.get(HUMAN,q['id']))['interaction_id']
        self.assertEqual((await adapter.approve(HUMAN,q['id'],self.body(q)))['status'],'verified_enabled')

    async def test_future_confirmation_timestamp_and_malformed_deadline_denied(self):
        for change in ('future','missing','duration','naive'):
            b,m,adapter,q=await self.setup_pending()
            preview=m.records[q['id']]['chat_preview']
            if change=='future':m.now=lambda:datetime(2026,11,19,tzinfo=timezone.utc)
            elif change=='missing':preview.pop('expires_at')
            elif change=='duration':preview['expires_at']=(m.now()+timedelta(seconds=301)).isoformat()
            else:preview['timestamp']='2026-11-20T00:00:00'
            with self.subTest(change=change),self.assertRaises(ApprovalError):
                await adapter.approve(HUMAN,q['id'],self.body(q))
            self.assertNotIn('write',b.events)

    async def test_missing_preview_interaction_cannot_approve(self):
        b,m,adapter,q=await self.setup_pending()
        m.records[q['id']].pop('chat_preview')
        with self.assertRaises(ApprovalError):await adapter.approve(HUMAN,q['id'],self.body(q))
        self.assertNotIn('write',b.events)

    async def test_strict_body_and_no_mcp_approval_route(self):
        b,m,adapter,q=await self.setup_pending()
        invalid=[{}, dict(self.body(q),approved=True),dict(self.body(q),surface='discord'),
                 dict(self.body(q),session_id=''),dict(self.body(q),session_id='a\n'),
                 dict(self.body(q),session_id='a'*257),dict(self.body(q),sha256=q['sha256'].upper())]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ApprovalError):
                await adapter.approve(HUMAN,q['id'],body)
        import general_connector_v3 as connector
        self.assertFalse(any('approv' in t['name'] for t in connector.TOOLS))
        client=connector.HAClient('synthetic')
        with self.assertRaises(ValueError):
            client._request('POST','/chat-approvals/'+q['id'],self.body(q))
        self.assertNotIn('write',b.events)

    async def test_concurrent_chat_approvals_consume_once(self):
        b,m,adapter,q=await self.setup_pending()
        results=await asyncio.gather(*(adapter.approve(HUMAN,q['id'],self.body(q)) for _ in range(2)),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(sum(isinstance(r,ApprovalError) for r in results),1)
        self.assertEqual(b.events.count('write'),1)

    async def test_uncertain_write_is_terminal_across_restart(self):
        b,m,adapter,q=await self.setup_pending()
        b.fail_write=True
        with self.assertRaises(ApprovalError):await adapter.approve(HUMAN,q['id'],self.body(q))
        records=runtime.validate_records(m.records)
        self.assertEqual(records[q['id']]['status'],'uncertain')
        self.assertEqual(records[q['id']]['approval']['transport'],'hermes_command')
        restarted=ChatApprovals(Manager(b,BOT.id,records,now=m.now),HUMAN.id)
        with self.assertRaises(ApprovalError):await restarted.approve(HUMAN,q['id'],self.body(q))
        self.assertEqual(b.events.count('write'),1)

    async def test_interruption_snapshots_never_redispatch_on_restart(self):
        for checkpoint in ('pending','write','reload','receipt'):
            with self.subTest(checkpoint=checkpoint):
                class InterruptedBoundary(Boundary):
                    interrupted=False
                    def interrupt(self):
                        self.interrupted=True
                        raise OSError('synthetic persistent-storage interruption')
                    async def save(self,records):
                        if self.interrupted:raise OSError('synthetic unavailable storage')
                        status=next(iter(records.values()))['status']
                        if checkpoint=='receipt' and status=='verified_enabled':self.interrupt()
                        await super().save(records)
                        if checkpoint=='pending' and status=='pending':self.interrupt()
                    async def write(self,rows):
                        await super().write(rows)
                        if checkpoint=='write':self.interrupt()
                    async def reload(self,identifier):
                        await super().reload(identifier)
                        if checkpoint=='reload':self.interrupt()
                b=InterruptedBoundary()
                b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
                m=Manager(b,BOT.id,{},now=lambda:datetime(2026,11,20,tzinfo=timezone.utc))
                m.approval_ready=True
                q=await m.propose(BOT,{'spec':SPEC})
                m.records[q['id']].update(status='awaiting_approval',preview={'message_id':'11'})
                adapter=ChatApprovals(m,HUMAN.id)
                q['interaction_id']=(await adapter.get(HUMAN,q['id']))['interaction_id']
                with self.assertRaises(ApprovalError):
                    await adapter.approve(HUMAN,q['id'],self.body(q))
                # Storage is frozen at the last successful save, not the
                # in-memory catch handler: simulate reloading that durable state.
                self.assertEqual(b.records[q['id']]['status'],'pending')
                records=runtime.validate_records(b.records)
                self.assertEqual(records[q['id']]['status'],'uncertain')
                observed=list(b.events)
                restarted=ChatApprovals(Manager(b,BOT.id,records,now=m.now),HUMAN.id)
                with self.assertRaises(ApprovalError):
                    await restarted.approve(HUMAN,q['id'],self.body(q))
                self.assertEqual(b.events,observed)
                self.assertEqual(b.events.count('write'),0 if checkpoint=='pending' else 1)
                self.assertNotIn('device',b.events)

    async def test_discord_and_chat_race_have_one_winner(self):
        from custom_components.house_manager_general.discord import ApprovalWorker
        for chat_first in (False,True):
            b,m,adapter,q=await self.setup_pending()
            created=m.now()
            m.now=lambda:created+timedelta(seconds=2)
            m.records[q['id']]['preview']={'message_id':'100','timestamp':(created+timedelta(seconds=1)).isoformat()}
            message={'id':'101','type':19,'channel_id':'33','author':{'id':'22'},
                     'timestamp':m.now().isoformat(),'edited_timestamp':None,
                     'message_reference':{'message_id':'100','channel_id':'33'},
                     'content':f"APPROVE {q['id']} {q['sha256']}"}
            class REST:
                async def messages(self,*args):return [message]
                async def get_message(self,*args):return message
            worker=ApprovalWorker(m,REST(),{'discord_user_id':'22','discord_channel_id':'33'})
            chat=adapter.approve(HUMAN,q['id'],self.body(q))
            discord=worker.poll(q['id'])
            await asyncio.gather(*((chat,discord) if chat_first else (discord,chat)),return_exceptions=True)
            self.assertEqual(m.records[q['id']]['status'],'verified_enabled')
            self.assertEqual(b.events.count('write'),1)
            if chat_first:
                self.assertEqual(m.records[q['id']]['approval']['transport'],'hermes_command')
            else:
                self.assertEqual(m.records[q['id']]['approval']['message_id'],'101')

    async def test_edit_discord_and_chat_race_preserves_state_and_invalidates_losing_prompt(self):
        from custom_components.house_manager_general.discord import ApprovalWorker
        for state in ('off', 'on'):
            for chat_first in (False, True):
                with self.subTest(state=state, chat_first=chat_first):
                    helpers=edit_tests.EditTests()
                    b,m,target=helpers.setup_manager(state)
                    before=copy.deepcopy(b.rows)
                    q=await helpers.queue_edit(m,target)
                    record=m.records[q['id']]
                    record.pop('approval')
                    created=m.now()
                    record['preview']={'message_id':'100','timestamp':(created+timedelta(seconds=1)).isoformat()}
                    m.now=lambda:created+timedelta(seconds=2)
                    adapter=ChatApprovals(m,HUMAN.id)
                    q['interaction_id']=(await adapter.get(HUMAN,q['id']))['interaction_id']
                    message={'id':'101','type':19,'channel_id':'33','author':{'id':'22'},
                             'timestamp':m.now().isoformat(),'edited_timestamp':None,
                             'message_reference':{'message_id':'100','channel_id':'33'},
                             'content':f"APPROVE {q['id']} {q['sha256']}"}
                    class REST:
                        async def messages(self,*args):return [message]
                        async def get_message(self,*args):return message
                    worker=ApprovalWorker(m,REST(),{'discord_user_id':'22','discord_channel_id':'33'})
                    chat=adapter.approve(HUMAN,q['id'],self.body(q))
                    discord=worker.poll(q['id'])
                    await asyncio.gather(*((chat,discord) if chat_first else (discord,chat)),return_exceptions=True)
                    self.assertEqual(record['status'],'verified_edit')
                    self.assertEqual(b.events.count('write'),1)
                    self.assertEqual(b.rows[-1]['id'],target)
                    self.assertEqual(b.rows[-1]['actions'],before[-1]['actions'])
                    self.assertEqual(b.runtime_state,state)
                    self.assertEqual(m.records[target]['status'],'superseded')
                    evidence=copy.deepcopy(record['approval'])
                    if chat_first:
                        self.assertEqual(evidence['transport'],'hermes_command')
                    else:
                        self.assertEqual(evidence['message_id'],'101')
                    with self.assertRaises(ApprovalError):
                        await adapter.approve(HUMAN,q['id'],self.body(q))
                    with self.assertRaises(ApprovalError):
                        await adapter.get(HUMAN,q['id'])
                    await worker.poll(q['id'])
                    self.assertEqual(record['approval'],evidence)
                    self.assertEqual(b.events.count('write'),1)
                    self.assertNotIn('device',b.events)

    async def test_waiting_discord_expiry_cannot_overwrite_consumed_receipt(self):
        from custom_components.house_manager_general.discord import ApprovalWorker
        b,m,adapter,q=await self.setup_pending()
        doc=m.records[q['id']]['proposal']
        doc['expires_at']=(m.now()-timedelta(seconds=1)).isoformat()
        worker=ApprovalWorker(m,NS(),{'discord_user_id':'22','discord_channel_id':'33'})
        await m.operation_lock.acquire()
        task=asyncio.create_task(worker.poll(q['id']))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        m.records[q['id']].update(status='verified_enabled',approval={'transport':'hermes_command'})
        m.operation_lock.release()
        await task
        self.assertEqual(m.records[q['id']]['status'],'verified_enabled')

    async def test_no_expiry_and_legacy_deadline_unchanged(self):
        b,m,adapter,q=await self.setup_pending()
        original=m.now()
        m.now=lambda:original+timedelta(days=30)
        self.assertIsNone((await adapter.get(HUMAN,q['id']))['proposal']['expires_at'])
        b,m,adapter,q=await self.setup_pending()
        doc=m.records[q['id']]['proposal']
        doc['expires_at']=(m.now()+timedelta(seconds=900)).isoformat()
        doc['sha256']=p.hash_json({k:v for k,v in doc.items() if k!='sha256'})
        q['sha256']=doc['sha256']
        old=m.now();m.now=lambda:old+timedelta(seconds=901)
        with self.assertRaises(ApprovalError):await adapter.approve(HUMAN,q['id'],self.body(q))
        self.assertNotIn('write',b.events)

    async def test_edit_preserves_identity_state_and_refuses_drift(self):
        for state in ('off','on'):
            for drift in (None,'config','runtime','binding'):
                helpers=edit_tests.EditTests()
                b,m,target=helpers.setup_manager(state)
                q=await helpers.queue_edit(m,target)
                m.records[q['id']].pop('approval')
                adapter=ChatApprovals(m,HUMAN.id)
                q['interaction_id']=(await adapter.get(HUMAN,q['id']))['interaction_id']
                old=copy.deepcopy(b.rows)
                if drift=='config':b.rows[-1]['alias']='operator change'
                if drift=='runtime':b.runtime_state='on' if state=='off' else 'off'
                if drift=='binding':b.inv['light.test']['registry_fingerprint']='b'*64
                with self.subTest(state=state,drift=drift):
                    if drift:
                        before=copy.deepcopy(b.rows)
                        with self.assertRaises(ApprovalError):await adapter.approve(HUMAN,q['id'],self.body(q))
                        self.assertEqual(b.rows,before)
                        self.assertNotIn('write',b.events)
                    else:
                        result=await adapter.approve(HUMAN,q['id'],self.body(q))
                        self.assertEqual(result['status'],'verified_edit')
                        self.assertEqual(b.rows[-1]['id'],target)
                        self.assertEqual(b.rows[-1]['actions'],old[-1]['actions'])
                        self.assertEqual(b.runtime_state,state)
                        self.assertEqual(m.records[target]['status'],'superseded')
                        from general_connector_v3 import validate_status
                        validate_status(await m.status(BOT,q['id']),q['id'])
                    self.assertNotIn('device',b.events)

    def test_settings_require_distinct_opt_in_and_route_absent_by_default(self):
        settings={'bot_user_id':BOT.id,'discord_token':'FAKE','discord_user_id':'22','discord_channel_id':'33'}
        self.assertEqual(validate_settings(settings),settings)
        self.assertEqual(validate_settings(dict(settings,chat_approver_user_id=HUMAN.id))['chat_approver_user_id'],HUMAN.id)
        for bad in (BOT.id,'','x'*32):
            with self.assertRaises(ApprovalError):validate_settings(dict(settings,chat_approver_user_id=bad))
        for enabled in (False,True):
            views=[]
            class View:pass
            hass=NS(http=NS(register_view=views.append))
            with patch.object(runtime,'import_module',side_effect=lambda name:NS(HomeAssistantView=View) if name=='homeassistant.components.http' else NS()):
                runtime.register_views(hass,NS(bot_user_id=BOT.id),HUMAN.id if enabled else None)
            chat=[v for v in views if 'chat-approvals' in v.url]
            self.assertEqual(len(chat),int(enabled))
            self.assertTrue(all(v.requires_auth for v in views))


if __name__=='__main__':unittest.main()
