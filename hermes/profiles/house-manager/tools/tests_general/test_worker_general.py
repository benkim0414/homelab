"""Tests exercise a REST-only worker with in-memory Discord, no network."""
import copy
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from custom_components.house_manager_general.discord import ApprovalWorker, approval_matches, canonical_json

DOC = {'id':'house_manager_general_'+'a'*32,'sha256':'b'*64,'kind':'automation','created_at':'2026-11-13T00:00:00+00:00','expires_at':'2026-11-13T00:15:00+00:00','payload':{'alias':'Daily','triggers':[{'trigger':'time','at':'21:00:00'}], 'actions':[]}}
SETTINGS = {'discord_user_id':'22','discord_channel_id':'33','discord_token':'FAKE'}
PREVIEW = {'message_id':'100','timestamp':'2026-11-13T00:01:00+00:00'}

def message():
    return {'id':'101','type':19,'channel_id':'33','author':{'id':'22'},'timestamp':'2026-11-13T00:02:00+00:00','edited_timestamp':None,'message_reference':{'message_id':'100','channel_id':'33'},'content':f"APPROVE {DOC['id']} {DOC['sha256']}"}

class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_skips_every_already_approved_record_without_discord_preview(self):
        for approval in ({'source':'standing_policy'}, {'message_id':'101'}, {'source':'chat'}):
            record = {'status':'awaiting_approval', 'proposal':copy.deepcopy(DOC),
                      'preview':{'source':'standing_policy'}, 'approval':approval}
            before = copy.deepcopy(record)
            manager = NS(records={DOC['id']:record})
            # No clock, lock, or REST methods: poll must exit before any I/O.
            worker = ApprovalWorker(manager, NS(), SETTINGS)
            worker._poll_scans[DOC['id']] = ('100', None, '100')
            await worker.poll(DOC['id'])
            self.assertEqual(record, before)
            self.assertNotIn(DOC['id'], worker._poll_scans)

    def test_binding_rejects_every_untrusted_message_dimension(self):
        self.assertTrue(approval_matches(message(), DOC, PREVIEW, SETTINGS))
        for key, value in [('author',{'id':'99'}),('author',{'id':'22','bot':True}),('channel_id','99'),('webhook_id','777'),('edited_timestamp','2026-11-13T00:03:00Z'),('timestamp','2026-11-13T00:00:00Z'),('message_reference',{'message_id':'99','channel_id':'33'}),('content',f"APPROVE {DOC['id']} {'c'*64}"),('content','yes'),('id','90')]:
            bad = message(); bad[key] = value
            with self.subTest(key=key,value=value): self.assertFalse(approval_matches(bad,DOC,PREVIEW,SETTINGS))

    async def test_preview_persists_send_claim_attaches_exact_json_and_reads_back(self):
        records = {DOC['id']:{'status':'queued','proposal':copy.deepcopy(DOC)}}
        events=[]
        async def save(value): events.append('save:'+value[DOC['id']]['status'])
        class REST:
            async def send_preview(self, channel, content, filename, attachment):
                events.append('send')
                self.content=content; self.filename=filename; self.attachment=attachment
                return {'id':'100'}
            async def get_message(self, channel, identifier):
                events.append('read')
                if identifier == '102':
                    return {'id':'102','channel_id':'33','author':{'id':'44','bot':True},
                            'timestamp':'2026-11-13T00:01:01+00:00','content':self.approval,
                            'attachments':[], 'message_reference':{'message_id':'100','channel_id':'33'}}
                return {'id':'100','channel_id':'33','author':{'id':'44','bot':True},'timestamp':PREVIEW['timestamp'],'content':self.content,'attachments':[{'filename':self.filename,'size':len(self.attachment)}]}
            async def send_approval(self, channel, content, preview_id):
                events.append('send_command')
                self.approval=content
                self.parent=preview_id
                return {'id':'102'}
        manager=NS(records=records,operation_lock=__import__('asyncio').Lock(),boundary=NS(save=save),now=lambda:datetime(2026,11,13,0,2,tzinfo=timezone.utc))
        rest=REST(); worker=ApprovalWorker(manager,rest,SETTINGS); worker.bot_id='44'
        await worker.publish(DOC['id'])
        self.assertEqual(rest.attachment,canonical_json(DOC))
        self.assertEqual(json.loads(rest.attachment),DOC)
        self.assertIn('persistent',rest.content)
        self.assertIn('Daily',rest.content)
        self.assertIn('21:00:00',rest.content)
        self.assertLess(len(rest.content),1900)
        self.assertEqual(events,['save:preview_pending','send','read','send_command','read','save:awaiting_approval'])
        self.assertNotIn(f"APPROVE {DOC['id']}",rest.content)
        self.assertEqual(rest.approval,f"APPROVE {DOC['id']} {DOC['sha256']}")
        self.assertEqual(rest.parent,'100')
        self.assertEqual(records[DOC['id']]['preview']['message_id'],'100')
        self.assertEqual(records[DOC['id']]['preview']['copy_message_id'],'102')
        copied = message(); copied['id']='103'
        self.assertTrue(approval_matches(copied,DOC,records[DOC['id']]['preview'],SETTINGS))
        copied['message_reference']['message_id']='99'
        self.assertFalse(approval_matches(copied,DOC,records[DOC['id']]['preview'],SETTINGS))

    async def test_copy_message_failure_is_uncertain_and_never_resends(self):
        from custom_components.house_manager_general.engine import ApprovalError
        import asyncio
        events = []
        records = {DOC['id']: {'status':'queued', 'proposal':copy.deepcopy(DOC)}}
        async def save(value): events.append('save:'+value[DOC['id']]['status'])
        class REST:
            async def send_preview(self, channel, content, filename, attachment):
                events.append('preview'); self.content=content; self.filename=filename
                self.attachment=attachment; return {'id':'100'}
            async def get_message(self, channel, identifier):
                return {'id':'100','channel_id':'33','author':{'id':'44','bot':True},
                        'timestamp':PREVIEW['timestamp'],'content':self.content,
                        'attachments':[{'filename':self.filename,'size':len(self.attachment)}]}
            async def send_approval(self, *args):
                events.append('copy'); raise ApprovalError('discord_unavailable',503)
        manager = NS(records=records, operation_lock=asyncio.Lock(), boundary=NS(save=save),
                     now=lambda:datetime(2026,11,13,0,2,tzinfo=timezone.utc))
        worker=ApprovalWorker(manager,REST(),SETTINGS); worker.bot_id='44'
        with self.assertRaises(ApprovalError): await worker.publish(DOC['id'])
        self.assertEqual(records[DOC['id']]['status'],'uncertain')
        await worker.publish(DOC['id'])
        self.assertEqual(events.count('preview'),1)
        self.assertEqual(events.count('copy'),1)
        self.assertNotIn('preview',records[DOC['id']])

    async def test_copy_rest_payload_is_only_command_and_linked_without_mentions(self):
        from custom_components.house_manager_general.discord import DiscordREST
        calls=[]
        async def request(method,path,**kwargs):
            calls.append((method,path,kwargs)); return {'id':'102'}
        rest=DiscordREST('FAKE'); rest._request=request
        command=f"APPROVE {DOC['id']} {DOC['sha256']}"
        await rest.send_approval('33',command,'100')
        method,path,kwargs=calls[0]
        self.assertEqual((method,path),('POST','/channels/33/messages'))
        payload=kwargs['json']
        self.assertEqual(payload['content'],command)
        self.assertNotIn('\n',payload['content'])
        self.assertEqual(payload['allowed_mentions'],{'parse':[],'replied_user':False})
        self.assertEqual(payload['message_reference'],{'message_id':'100','channel_id':'33','fail_if_not_exists':True})
        self.assertNotIn('attachments',payload)
        # Existing approval parser must ignore the copy aid authored by the bot.
        copied=message(); copied['author']={'id':'44','bot':True}
        self.assertFalse(approval_matches(copied,DOC,PREVIEW,SETTINGS))

    async def test_worker_authenticates_private_dm_and_claims_exact_human_reply(self):
        events=[]
        records={DOC['id']:{'status':'awaiting_approval','proposal':copy.deepcopy(DOC),'preview':PREVIEW}}
        async def save(value): events.append('save')
        async def approve(identifier, expected_hash):
            events.append(('approved',identifier,expected_hash))
            records[identifier]['status']='executed'
        class REST:
            async def me(self): return {'id':'44','bot':True}
            async def channel(self, channel): return {'id':'33','type':1,'recipients':[{'id':'22','bot':False}]}
            async def messages(self, channel, after): return [message()]
            async def get_message(self, channel, identifier): return message()
            async def close(self): events.append('close')
        manager=NS(records=records,operation_lock=__import__('asyncio').Lock(),boundary=NS(save=save),now=lambda:datetime(2026,11,13,0,2,tzinfo=timezone.utc),approve=approve,approval_ready=False)
        worker=ApprovalWorker(manager,REST(),SETTINGS)
        await worker.initialize()
        self.assertTrue(manager.approval_ready)
        await worker.poll(DOC['id'])
        self.assertEqual(records[DOC['id']]['approval']['message_id'],'101')
        self.assertEqual(events,['save',('approved',DOC['id'],DOC['sha256'])])
        await worker.stop()
        self.assertFalse(manager.approval_ready)
        self.assertEqual(events[-1],'close')

    async def test_paginated_reply_discovery_survives_busy_dm_and_worker_restart(self):
        import asyncio
        from urllib.parse import urlsplit,parse_qs
        from custom_components.house_manager_general.discord import DiscordREST
        for restart in (False,True):
            with self.subTest(restart=restart):
                records={DOC['id']:{'status':'awaiting_approval','proposal':copy.deepcopy(DOC),'preview':copy.deepcopy(PREVIEW)}}
                approved=[];paths=[]
                # Valid reply is older than 250 irrelevant messages: third page.
                rows=[{'id':str(value),'content':'irrelevant'} for value in range(102,352)]+[message()]
                async def request(method,path,**kwargs):
                    self.assertEqual(method,'GET')
                    paths.append(path)
                    if path.endswith('/101'):return message()
                    query=parse_qs(urlsplit(path).query)
                    self.assertEqual(query['limit'],['100'])
                    self.assertNotIn('after',query)
                    before=int(query.get('before',['999999'])[0])
                    return sorted((row for row in rows if int(row['id'])<before),key=lambda row:int(row['id']),reverse=True)[:100]
                async def save(value):pass
                async def approve(identifier,digest):
                    approved.append((identifier,digest))
                    records[identifier]['status']='executed'
                manager=NS(records=records,operation_lock=asyncio.Lock(),boundary=NS(save=save),now=lambda:datetime(2026,11,13,0,2,tzinfo=timezone.utc),approve=approve)
                rest=DiscordREST('FAKE');rest._request=request
                worker=ApprovalWorker(manager,rest,SETTINGS)
                await worker.poll(DOC['id'])
                self.assertEqual(approved,[])
                if restart:
                    worker=ApprovalWorker(manager,rest,SETTINGS)
                    await worker.poll(DOC['id'])
                # Newer traffic must not reset the older-page cursor.
                rows.extend({'id':str(value),'content':'new traffic'} for value in range(1000,1200))
                await worker.poll(DOC['id'])
                self.assertEqual(approved,[])
                await worker.poll(DOC['id'])
                self.assertEqual(approved,[(DOC['id'],DOC['sha256'])])
                self.assertIn('/channels/33/messages?before=252&limit=100',paths)
                self.assertIn('/channels/33/messages?before=152&limit=100',paths)
                observed=len(paths)
                await worker.poll(DOC['id'])
                self.assertEqual(len(paths),observed)
                self.assertEqual(len(approved),1)

    async def test_invalid_page_and_read_failure_do_not_advance_scan(self):
        import asyncio
        from custom_components.house_manager_general.engine import ApprovalError
        records={DOC['id']:{'status':'awaiting_approval','proposal':copy.deepcopy(DOC),'preview':copy.deepcopy(PREVIEW)}}
        class REST:
            reply: object=[]
            async def messages(self,*args,**kwargs):
                if isinstance(self.reply,Exception):raise self.reply
                return self.reply
        rest=REST()
        manager=NS(records=records,operation_lock=asyncio.Lock(),now=lambda:datetime(2026,11,13,0,2,tzinfo=timezone.utc))
        worker=ApprovalWorker(manager,rest,SETTINGS)
        for reply in ([{'id':'102'},{'id':'102'}],[{'id':'bad'}], [{'id':'102'}]*101, ApprovalError('discord_unavailable',503)):
            rest.reply=reply
            with self.subTest(reply=type(reply).__name__),self.assertRaises(ApprovalError):
                await worker.poll(DOC['id'])
            self.assertEqual(worker._poll_scans,{})
            self.assertNotIn('approval',records[DOC['id']])

    async def test_rest_fixed_origin_no_redirect_proxy_and_safe_read_retry(self):
        from custom_components.house_manager_general.discord import DiscordREST
        calls=[]; sleeps=[]
        class Response:
            def __init__(self,status,data): self.status=status; self.data=data; self.headers={'Retry-After':'0.1'}
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def read(self): return json.dumps(self.data).encode()
            @property
            def content(self): return self
            async def iter_chunked(self,n): yield await self.read()
        class Session:
            def request(self,method,url,**kwargs):
                calls.append((method,url,kwargs))
                return Response(429 if len(calls)==1 else 200, {'id':'44','bot':True})
            async def close(self): pass
        async def sleep(delay): sleeps.append(delay)
        rest=DiscordREST('FAKE',session=Session(),sleep=sleep)
        self.assertEqual((await rest.me())['id'],'44')
        self.assertEqual(len(calls),2)
        for method,url,kwargs in calls:
            self.assertEqual(url,'https://discord.com/api/v10/users/@me')
            self.assertFalse(kwargs['allow_redirects'])
            self.assertIsNone(kwargs['proxy'])
        self.assertEqual(sleeps,[0.1])
        with self.assertRaises(Exception): await rest.get_message('33','../../evil')

    async def test_stale_consumed_approval_is_terminal_not_still_waiting(self):
        from custom_components.house_manager_general.engine import ApprovalError
        import asyncio
        records={DOC['id']:{'status':'awaiting_approval','proposal':copy.deepcopy(DOC),'preview':PREVIEW}}
        async def save(value): pass
        async def approve(*args): raise ApprovalError('invalid_proposal',409)
        class REST:
            async def messages(self,*args): return [message()]
            async def get_message(self,*args): return message()
        manager=NS(records=records,operation_lock=asyncio.Lock(),boundary=NS(save=save),now=lambda:datetime(2026,11,13,0,2,tzinfo=timezone.utc),approve=approve)
        worker=ApprovalWorker(manager,REST(),SETTINGS)
        with self.assertRaises(ApprovalError): await worker.poll(DOC['id'])
        self.assertEqual(records[DOC['id']]['status'],'uncertain')

if __name__ == '__main__': unittest.main()
