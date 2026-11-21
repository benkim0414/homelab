"""Exercise command -> exact confirmation -> real adapter/manager, without HTTP."""
import asyncio
import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock
import chat_approval_plugin as plugin
from custom_components.house_manager_general.chat import ChatApprovals
from custom_components.house_manager_general.engine import Manager, ApprovalError
from tests_general.test_manager_native import Boundary, BOT


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_creates_and_enables_only_after_full_preview_confirmation(self):
        await self.command_flow('cli', 'cli')

    async def test_tui_command_approves_shared_proposal(self):
        await self.command_flow('tui', 'tui')

    async def test_desktop_bot_chat_command_approves_shared_proposal(self):
        await self.command_flow('desktop', 'gui')

    async def command_flow(self, surface, launch_source):
        b=Boundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        m=Manager(b,BOT.id,{},now=lambda:datetime.now(timezone.utc))
        m.approval_ready=True
        spec={'title':'Synthetic flow','triggers':[{'type':'time','at':'23:00:00'}],
              'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]}
        q=await m.propose(BOT,{'spec':spec})
        m.records[q['id']].update(status='awaiting_approval',preview={'message_id':'1'})
        human=NS(id='c'*32,is_admin=False,is_active=True)
        adapter=ChatApprovals(m,human.id)
        loop=asyncio.get_running_loop()
        calls=[]
        def http(method,identifier,token,payload=None):
            self.assertEqual(token,'synthetic-separate-token')
            calls.append(method)
            coro=adapter.get(human,identifier) if method=='GET' else adapter.approve(human,identifier,payload)
            return asyncio.run_coroutine_threadsafe(coro,loop).result(10)
        def choose(question,choices):
            self.assertNotIn('write',b.events)
            shown=question.split('BEGIN EXACT PROPOSAL JSON\n')[1].split('\nEND EXACT PROPOSAL JSON')[0]
            self.assertEqual(shown,plugin.canonical(m.records[q['id']]['proposal']).decode())
            return 'approve_exact'
        ctx=NS(profile_name='house-manager',current_cron_execution=lambda:None,
               session_surface=lambda:surface,session_launch_source=lambda:launch_source,ask_choice=choose,
               command_is_live=lambda:True,claim_command_dispatch=lambda:True)
        handler=plugin.make_handler(ctx,environ={'HOUSE_MANAGER_APPROVAL_TOKEN':'synthetic-separate-token'},http=http)
        kwargs=dict(source=None,session_id='synthetic_flow',session_key='synthetic_flow',platform=surface)
        result=await asyncio.to_thread(handler,q['id']+' '+q['sha256'],**kwargs)
        self.assertIn('applied',result)
        self.assertEqual(calls,['GET','POST'])
        self.assertEqual(m.records[q['id']]['status'],'verified_enabled')
        self.assertEqual(b.events.count('write'),1)
        self.assertEqual(m.records[q['id']]['approval']['interaction_id'],m.records[q['id']]['chat_preview']['interaction_id'])
        self.assertEqual(m.records[q['id']]['approval']['session_id'],'synthetic_flow')
        self.assertNotIn('device',b.events)
        # The same explicit command cannot silently replay a finished record.
        result=await asyncio.to_thread(handler,q['id']+' '+q['sha256'],**kwargs)
        self.assertIn('not confirmed',result)
        self.assertEqual(b.events.count('write'),1)


if __name__=='__main__':unittest.main()
