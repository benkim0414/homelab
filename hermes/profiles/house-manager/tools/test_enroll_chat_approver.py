"""Private enrollment uses synthetic credentials and temporary homes only."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import enroll_chat_approver as enroll

TOKEN='synthetic.payload.signature'
BOT='b'*32
HUMAN='c'*32


class EnrollmentTests(unittest.TestCase):
    def test_only_distinct_non_admin_identity(self):
        good={'id':HUMAN,'is_admin':False,'is_owner':False}
        self.assertEqual(enroll.validate_identity(good,BOT),HUMAN)
        for user in (None,{},dict(good,id=BOT),dict(good,is_admin=True),dict(good,is_owner=True),dict(good,id='c'*31),{'id':HUMAN}):
            with self.subTest(user=user),self.assertRaises(ValueError):enroll.validate_identity(user,BOT)

    def test_preserves_other_bytes_and_private_modes_without_token_in_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            original=b'# opaque unrelated values remain byte-identical\nUNRELATED=synthetic-only'
            (home/'.env').write_bytes(original)
            record=enroll.persist(home,TOKEN,HUMAN,BOT,effective_names=frozenset())
            self.assertEqual((home/'.env').read_bytes(),original+b'\nHOUSE_MANAGER_APPROVAL_TOKEN='+TOKEN.encode()+b'\n')
            self.assertEqual((home/'.env').stat().st_mode & 0o777,0o600)
            receipt=home/'.chat-approval-enrollment.json'
            self.assertEqual(receipt.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(receipt.read_text()),record)
            self.assertNotIn(TOKEN,receipt.read_text())
            self.assertEqual(record['approver_user_id'],HUMAN)
            with self.assertRaises(ValueError):enroll.persist(home,TOKEN,HUMAN,BOT,effective_names=frozenset())

    def test_refuses_existing_key_symlinks_and_bad_formats_before_write(self):
        cases=['key','export','env_link','receipt_link','token','bot','id']
        for case in cases:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                home=Path(directory);env=home/'.env';env.write_bytes(b'UNCHANGED=synthetic\n')
                if case=='key':env.write_bytes(b'HOUSE_MANAGER_APPROVAL_TOKEN=old.synthetic.only\n')
                if case=='export':env.write_bytes(b'export HOUSE_MANAGER_APPROVAL_TOKEN=old.synthetic.only\n')
                if case=='env_link':
                    env.unlink();env.symlink_to(home/'target')
                if case=='receipt_link':(home/'.chat-approval-enrollment.json').symlink_to(home/'target')
                before=env.read_bytes() if env.exists() else None
                token=TOKEN if case!='token' else 'synthetic\nINJECT=value'
                with self.assertRaises(ValueError):enroll.persist(home,token,HUMAN if case!='id' else 'bad',BOT if case!='bot' else HUMAN,effective_names=frozenset())
                self.assertEqual(env.read_bytes() if env.exists() else None,before)

    def test_private_tty_required_before_any_secret_prompt(self):
        with patch('sys.argv',['enroll','--bot-user-id',BOT]),patch.object(enroll.sys.stdin,'isatty',return_value=False),patch.object(enroll.getpass,'getpass') as prompt:
            with self.assertRaises(ValueError):enroll.main()
            prompt.assert_not_called()

    def test_effective_key_collision_is_denied_without_writing_or_exposing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'.env').write_bytes(b'UNRELATED=synthetic\n')
            with self.assertRaises(ValueError):
                enroll.persist(home,TOKEN,HUMAN,BOT,effective_names=frozenset({enroll.KEY}))
            self.assertEqual((home/'.env').read_bytes(),b'UNRELATED=synthetic\n')
            self.assertFalse((home/'.chat-approval-enrollment.json').exists())

    def test_normal_provider_key_projection_and_failed_provider_denial(self):
        config={'secrets':{'command':{'enabled':True}}};observed=[]
        def apply(sources,home,environ):
            self.assertEqual(sources,config['secrets'])
            self.assertIsNot(environ,os.environ)
            environ[enroll.KEY]='synthetic-hidden-value'
            observed.append(dict(sources))
            return NS(sources=[NS(result=NS(ok=True,secrets={enroll.KEY:'synthetic-hidden-value'}))],provenance={enroll.KEY:object()})
        mods={'hermes_cli':NS(),'agent':NS(),'agent.secret_sources':NS(),
              'hermes_cli.config_backend':NS(read_config_doc_readonly=lambda path:config),
              'agent.secret_scope':NS(_is_global_env=lambda key:key=='PATH',load_env_file=lambda path:{'UNRELATED':'synthetic-only'}),
              'agent.secret_sources.registry':NS(apply_all=apply),
              'hermes_cli.managed_scope':NS(load_managed_env=lambda:{'MANAGED_ONLY':'synthetic-only'})}
        with patch.dict('sys.modules',mods),patch.dict(enroll.os.environ,{'PATH':'synthetic'},clear=True):
            names=enroll.effective_secret_names(Path('/synthetic/profile'))
            self.assertIn(enroll.KEY,names)
            self.assertIn('MANAGED_ONLY',names)
            self.assertNotIn('synthetic-hidden-value',names)
            self.assertNotIn(enroll.KEY,enroll.os.environ)
            mods['agent.secret_sources.registry'].apply_all=lambda *a,**k:NS(sources=[NS(result=NS(ok=False))],provenance={})
            with self.assertRaises(ValueError):enroll.effective_secret_names(Path('/synthetic/profile'))
        self.assertEqual(config,{'secrets':{'command':{'enabled':True}}})

    def test_external_collision_is_checked_before_private_token_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            with patch.object(enroll,'PROFILE_HOME',home),patch.dict(enroll.os.environ,{'HERMES_HOME':str(home)}),patch('sys.argv',['enroll','--bot-user-id',BOT]),patch.object(enroll.sys.stdin,'isatty',return_value=True),patch.object(enroll.sys.stderr,'isatty',return_value=True),patch.object(enroll.os,'getuid',return_value=10000),patch.object(enroll,'effective_secret_names',return_value=frozenset({enroll.KEY})),patch.object(enroll.getpass,'getpass') as prompt:
                with self.assertRaises(ValueError):enroll.main()
                prompt.assert_not_called()


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_supported_websocket_auth_only_and_no_redirects(self):
        sent=[];captured={}
        replies=iter([{'type':'auth_required'},{'type':'auth_ok'},{'id':1,'type':'result','success':True,'result':{'id':HUMAN,'is_admin':False,'is_owner':False}}])
        class WS:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def receive_json(self):return next(replies)
            async def send_json(self,payload):sent.append(payload)
        class Session:
            def __init__(self,**kwargs):captured.update(kwargs)
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def ws_connect(self,url,**kwargs):captured['url']=url;return WS()
        class Trace:
            def __init__(self):self.on_request_redirect=[]
        module=NS(ClientSession=Session,TraceConfig=Trace,ClientTimeout=lambda **kwargs:kwargs)
        with patch.dict('sys.modules',{'aiohttp':module}):result=await enroll.authenticate(TOKEN)
        self.assertEqual(result['id'],HUMAN)
        self.assertEqual(sent,[{'type':'auth','access_token':TOKEN},{'id':1,'type':'auth/current_user'}])
        self.assertEqual(captured['url'],enroll.WS_URL)
        self.assertIs(captured['trust_env'],False)
        with self.assertRaises(ValueError):await captured['trace_configs'][0].on_request_redirect[0](None)

    async def test_denied_auth_never_writes_or_requests_an_approval(self):
        sent=[]
        replies=iter([{'type':'auth_required'},{'type':'auth_invalid'}])
        class WS:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def receive_json(self):return next(replies)
            async def send_json(self,value):sent.append(value)
        class Session:
            def __init__(self,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def ws_connect(self,*args,**kwargs):return WS()
        class Trace:
            def __init__(self):self.on_request_redirect=[]
        with patch.dict('sys.modules',{'aiohttp':NS(ClientSession=Session,TraceConfig=Trace,ClientTimeout=lambda **k:k)}):
            with self.assertRaises(ValueError):await enroll.authenticate(TOKEN)
        self.assertEqual(sent,[{'type':'auth','access_token':TOKEN}])


if __name__=='__main__':unittest.main()
