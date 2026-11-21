"""Offline tests: synthetic runtime context, credentials and HTTP only."""
import copy
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import io
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

import chat_approval_plugin as plugin

IDENTIFIER = 'house_manager_general_' + 'a' * 32
TOKEN = 'synthetic-approval-only'
INTERACTION = 'c' * 32
CONTEXT = dict(source=None, session_id='session-1', session_key='session-1', platform='cli')


def document(kind='automation', lifetime=None):
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    spec = {'title': 'Routine ü', 'triggers': [{'type': 'time', 'at': '12:00:00'}],
            'conditions': [], 'actions': [{'action': 'light.turn_off',
                                         'target': {'entity_id': 'light.test'}, 'data': {}}]}
    payload = spec
    if kind == 'edit':
        before = {'id': IDENTIFIER, 'title': 'Before'}
        payload = dict(target_id=IDENTIFIER, base_config_hash=hashlib.sha256(plugin.canonical(before)).hexdigest(),
                       before=before, after=dict(before, title='After'), spec=spec, runtime_state='off')
    result = dict(id=IDENTIFIER, version=3, kind=kind, created_at=now.isoformat(),
                  expires_at=None if lifetime is None else (now + lifetime).isoformat(),
                  bindings={'light.test': 'b' * 64}, payload=payload)
    result['sha256'] = hashlib.sha256(plugin.canonical(result)).hexdigest()
    return result


def context():
    return types.SimpleNamespace(profile_name='house-manager', current_cron_execution=lambda: None,
                                 session_surface=lambda: 'cli', session_launch_source=lambda:'cli', ask_choice=Mock(return_value='approve_exact'),
                                 register_command=Mock(),command_is_live=lambda:True,
                                 claim_command_dispatch=Mock(return_value=True))


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context()
        self.doc = document()
        self.calls = []
        self.response = None

    def http(self, method, identifier, token, payload=None):
        self.calls.append((method, identifier, token, copy.deepcopy(payload)))
        if method == 'GET':
            return copy.deepcopy(self.response or {'proposal': self.doc, 'status': 'awaiting_approval', 'interaction_id':INTERACTION})
        return {'id': IDENTIFIER, 'status': 'verified_edit' if self.doc['kind'] == 'edit' else 'verified_enabled'}

    def run_command(self, args=None, runtime=None, env=None, http=None):
        handler = plugin.make_handler(self.ctx, environ=env if env is not None else {'HOUSE_MANAGER_APPROVAL_TOKEN': TOKEN},
                                      http=http or self.http)
        return handler(args if args is not None else IDENTIFIER + ' ' + self.doc['sha256'],
                       **(CONTEXT if runtime is None else runtime))

    def test_create_complete_prompt_and_exact_post(self):
        self.assertIn('applied', self.run_command())
        question, choices = self.ctx.ask_choice.call_args.args
        self.assertIn('enables a persistent routine', question)
        shown = question.split('BEGIN EXACT PROPOSAL JSON\n')[1].split('\nEND EXACT PROPOSAL JSON')[0]
        self.assertEqual(json.loads(shown), self.doc)
        self.assertEqual(self.calls, [('GET', IDENTIFIER, TOKEN, None), ('POST', IDENTIFIER, TOKEN,
                          {'sha256': self.doc['sha256'], 'surface': 'local_chat', 'session_id': 'session-1', 'interaction_id':INTERACTION})])
        self.assertEqual(choices[0]['value'], 'cancel')

    def test_edit_complete_before_after_and_preserved_off(self):
        self.doc = document('edit')
        self.assertIn('applied', self.run_command())
        question = self.ctx.ask_choice.call_args.args[0]
        self.assertIn('preserves its current on/off state', question)
        self.assertIn(plugin.canonical(self.doc).decode(), question)
        self.assertEqual(self.doc['payload']['runtime_state'], 'off')

    def test_never_truncate_large_document(self):
        self.doc['payload']['title'] = 'x' * 100000
        self.rehash()
        self.run_command()
        self.assertIn(plugin.canonical(self.doc).decode(), self.ctx.ask_choice.call_args.args[0])

    def rehash(self):
        self.doc['sha256'] = hashlib.sha256(plugin.canonical({k: v for k, v in self.doc.items() if k != 'sha256'})).hexdigest()

    def test_literal_arguments(self):
        good = IDENTIFIER + ' ' + self.doc['sha256']
        for bad in ['', ' ' + good, good + ' ', good + '\n', good.replace(' ', '  '),
                    good.replace(' ', '\t'), good.upper(), good + ' extra', '../x ' + 'a' * 64]:
            with self.subTest(bad=bad):
                self.calls.clear()
                self.run_command(args=bad)
                self.assertEqual(self.calls, [])

    def test_missing_context_fails_closed(self):
        for key in CONTEXT:
            runtime = dict(CONTEXT)
            runtime.pop(key)
            with self.subTest(key=key):
                self.calls.clear()
                self.run_command(runtime=runtime)
                self.assertEqual(self.calls, [])

    def test_wrong_profile_cron_and_nonlocal_surfaces(self):
        for profile, cron, surface in [('default', None, 'cli'), ('house-manager', object(), 'cli')]+[
            ('house-manager', None, s) for s in ('', 'acp', 'discord', 'telegram', 'local', 'cron', 'bot')]:
            self.ctx.profile_name = profile
            self.ctx.current_cron_execution = lambda: cron
            self.ctx.session_surface = lambda: surface
            self.run_command()
            self.assertEqual(self.calls, [])

    def test_noninteractive_or_missing_launch_is_denied_even_if_surface_cli(self):
        for label in ('acp','tool','oneshot','bot_room','a2a','local','desktop',None):
            self.calls.clear()
            self.ctx.session_launch_source=lambda:label
            self.run_command()
            self.assertEqual(self.calls,[])
        del self.ctx.session_launch_source
        self.run_command()
        self.assertEqual(self.calls,[])

    def test_none_source_cli_tui_desktop(self):
        for surface in plugin.LOCAL_SURFACES:
            self.calls.clear()
            self.ctx.session_surface = lambda: surface
            self.ctx.session_launch_source = lambda: {'cli':'cli','tui':'tui','desktop':'gui'}[surface]
            self.assertIn('applied', self.run_command(runtime=dict(CONTEXT, platform=surface)))

    def test_source_must_be_installed_session_source_local_enum(self):
        class Platform(Enum):
            LOCAL = 'local'
            DISCORD = 'discord'
        class SessionSource:
            platform = Platform.LOCAL
            is_bot = False
            profile = 'house-manager'
            profile_route_rejected = False
            delivered_via_upstream_relay = False
            detached_route = None
        modules = {'gateway': types.ModuleType('gateway'),
                   'gateway.config': types.SimpleNamespace(Platform=Platform),
                   'gateway.session': types.SimpleNamespace(SessionSource=SessionSource)}
        with patch.dict(sys.modules, modules):
            self.assertIn('applied', self.run_command(runtime=dict(CONTEXT, source=SessionSource(), platform='local')))
            for field, value in [('platform', Platform.DISCORD), ('platform', 'local'), ('is_bot', True),
                                 ('profile', 'other'), ('profile_route_rejected', True),
                                 ('delivered_via_upstream_relay', True), ('detached_route', 'old')]:
                self.calls.clear()
                source = SessionSource()
                setattr(source, field, value)
                self.run_command(runtime=dict(CONTEXT, source=source, platform='local'))
                self.assertEqual(self.calls, [])
            self.calls.clear()
            self.run_command(runtime=dict(CONTEXT, source=types.SimpleNamespace(platform=Platform.LOCAL), platform='local'))
            self.assertEqual(self.calls, [])

    def test_invalid_session_ids(self):
        for value in ('', 'x y', 'x\n', 'x/y', 'x' * 257, None):
            self.run_command(runtime=dict(CONTEXT, session_id=value))
            self.assertEqual(self.calls, [])

    def test_production_scoped_credential_and_no_ambient_fallback(self):
        modules={'agent':types.ModuleType('agent'),
                 'agent.secret_scope':types.SimpleNamespace(get_secret=Mock(return_value=TOKEN),current_secret_scope=lambda:{'HOUSE_MANAGER_APPROVAL_TOKEN':TOKEN})}
        with patch.dict(sys.modules,modules):
            handler=plugin.make_handler(self.ctx,http=self.http)
            self.assertIn('applied',handler(IDENTIFIER+' '+self.doc['sha256'],**CONTEXT))
            modules['agent.secret_scope'].get_secret.assert_not_called()
            self.calls.clear()
            modules['agent.secret_scope'].current_secret_scope=lambda:{}
            with patch.dict(plugin.os.environ,{'HOUSE_MANAGER_APPROVAL_TOKEN':TOKEN}):
                self.assertIn('not confirmed',handler(IDENTIFIER+' '+self.doc['sha256'],**CONTEXT))
            self.assertEqual(self.calls,[])
            modules['agent.secret_scope'].get_secret.assert_not_called()

    def test_missing_scoped_secret_context_is_denied(self):
        module=types.SimpleNamespace(get_secret=Mock(return_value=TOKEN),current_secret_scope=lambda:None)
        with patch.dict(sys.modules,{'agent':types.ModuleType('agent'),'agent.secret_scope':module}):
            handler=plugin.make_handler(self.ctx,http=self.http)
            self.assertIn('not confirmed',handler(IDENTIFIER+' '+self.doc['sha256'],**CONTEXT))
        module.get_secret.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_preview_interaction_required_before_prompt(self):
        for value in (None,'','C'*32,'0'*31,'0'*33):
            self.calls.clear()
            self.response={'proposal':self.doc,'status':'awaiting_approval','interaction_id':value}
            self.run_command()
            self.ctx.ask_choice.assert_not_called()
            self.assertEqual(len(self.calls),1)

    def test_missing_separate_credential_never_falls_back(self):
        for env in ({}, {'HA_MCP_TOKEN': TOKEN}, {'HOUSE_MANAGER_APPROVAL_TOKEN': 'bad\nheader'}):
            self.run_command(env=env)
            self.assertEqual(self.calls, [])

    def test_dispatch_cancellation_or_failed_claim_never_posts(self):
        self.ctx.command_is_live=lambda:False
        self.run_command()
        self.assertEqual(self.calls,[])
        self.ctx.command_is_live=lambda:True
        self.ctx.claim_command_dispatch.return_value=False
        self.run_command()
        self.assertEqual([c[0] for c in self.calls],['GET'])

    def test_cancellation_timeout_or_unexpected_answer_never_posts(self):
        for answer in (None, 'cancel', 'yes', True, 'Approve exact proposal'):
            self.calls.clear()
            self.ctx.ask_choice.return_value = answer
            self.assertIn('Cancelled', self.run_command())
            self.assertEqual(len(self.calls), 1)

    def test_nonpending_and_actions_rejected_before_prompt(self):
        for status in ('queued', 'pending', 'verified_enabled', 'superseded', 'uncertain'):
            self.response = {'proposal': self.doc, 'status': status}
            self.run_command()
        self.response = None
        self.doc = document('action')
        self.run_command()
        self.ctx.ask_choice.assert_not_called()
        self.assertTrue(all(call[0] == 'GET' for call in self.calls))

    def test_hash_identity_and_shape_mismatches(self):
        original = copy.deepcopy(self.doc)
        for mutation in (lambda d: d['payload'].update(title='changed'),
                         lambda d: d.update(id='house_manager_general_' + 'f'*32),
                         lambda d: d.update(version=True), lambda d: d.update(extra=1),
                         lambda d: d.pop('bindings'), lambda d: d.update(sha256='0'*64)):
            self.doc = copy.deepcopy(original)
            mutation(self.doc)
            self.run_command(args=IDENTIFIER + ' ' + original['sha256'])
        self.ctx.ask_choice.assert_not_called()
        self.assertTrue(all(call[0] == 'GET' for call in self.calls))

    def test_lifetimes_unchanged_and_expired_rejected(self):
        self.doc = document(lifetime=timedelta(minutes=15))
        before = copy.deepcopy(self.doc)
        self.assertIn('applied', self.run_command())
        self.assertEqual(self.doc, before)
        for created, expires in [(datetime.now(timezone.utc)-timedelta(hours=1), None),
                                 (datetime.now(timezone.utc)+timedelta(hours=1), None)]:
            self.calls.clear()
            self.doc = document()
            self.doc['created_at'] = created.isoformat()
            self.doc['expires_at'] = (created+timedelta(minutes=15)).isoformat() if created < datetime.now(timezone.utc) else expires
            self.rehash()
            self.run_command()
            self.assertEqual(len(self.calls), 1)

    def test_rechecks_runtime_after_choice(self):
        def choose(*args):
            self.ctx.profile_name = 'other'
            return 'approve_exact'
        self.ctx.ask_choice.side_effect = choose
        self.run_command()
        self.assertEqual(len(self.calls), 1)

    def test_errors_never_leak_or_retry(self):
        for method in ('GET', 'POST'):
            self.calls.clear()
            def failing(verb, *args):
                if verb == method:
                    self.calls.append((verb,))
                    raise RuntimeError(TOKEN + ' sensitive-body')
                return self.http(verb, *args)
            result = self.run_command(http=failing)
            self.assertNotIn(TOKEN, result)
            self.assertNotIn('sensitive-body', result)
            self.assertEqual([x[0] for x in self.calls], ['GET'] if method == 'GET' else ['GET', 'POST'])

    def test_loader_package_import_has_no_registration_or_environment_reads(self):
        import importlib.util
        from pathlib import Path
        root = Path(plugin.__file__).parent
        self.assertTrue((root / 'plugin.yaml').is_file())
        spec = importlib.util.spec_from_file_location('synthetic_loader_plugin', root / '__init__.py',
                                                      submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        poison_env = Mock()
        poison_env.get.side_effect = AssertionError('environment read during import or registration')
        with patch.object(plugin.os, 'environ', poison_env):
            spec.loader.exec_module(module)
            module.register(self.ctx)
        poison_env.get.assert_not_called()
        self.ctx.register_command.assert_called_once()

    def test_hash_encoding_matches_existing_policy(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('synthetic_approval_policy',
                  Path(__file__).parent / 'custom_components/house_manager_general/policy.py')
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        self.assertEqual(self.doc['sha256'], policy.hash_json(
                         {k: v for k, v in self.doc.items() if k != 'sha256'}))

    def test_registration_command_only_and_no_import_env_access(self):
        with patch.object(plugin.os, 'environ', {}):
            plugin.register(self.ctx)
        name, handler = self.ctx.register_command.call_args.args
        self.assertEqual(name, 'house-approve')
        import inspect
        self.assertFalse(inspect.iscoroutinefunction(handler))
        self.assertEqual(self.ctx.register_command.call_args.kwargs['argument_mode'], 'text')
        self.ctx.register_command.reset_mock()
        self.ctx.profile_name = 'other'
        plugin.register(self.ctx)
        self.ctx.register_command.assert_not_called()


class HTTPTests(unittest.TestCase):
    def call(self, raw=b'{}', status=200, method='GET'):
        response = Mock(status=status)
        response.read.return_value = raw
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(plugin.urllib.request, 'build_opener', return_value=opener) as build:
            result = plugin.request(method, IDENTIFIER, TOKEN,
                                    {'sha256': 'a'*64, 'surface': 'local_chat', 'session_id': 'session-1'} if method == 'POST' else None)
        return result, response, opener, build

    def test_fixed_origin_token_no_proxy_redirect_and_bounded_read(self):
        result, response, opener, build = self.call(method='POST')
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, plugin.BASE_URL + IDENTIFIER)
        self.assertEqual(req.get_header('Authorization'), 'Bearer ' + TOKEN)
        self.assertEqual(json.loads(req.data)['surface'], 'local_chat')
        self.assertEqual(opener.open.call_args.kwargs, {'timeout': 10})
        self.assertEqual(response.read.call_args.args, (plugin.MAX_RESPONSE+1,))
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], plugin.NoRedirect)
        opener.open.assert_called_once()

    def test_redirects_rejected(self):
        for code in (301, 302, 303, 307, 308):
            with self.assertRaises(plugin.Refused):
                plugin.NoRedirect().redirect_request(None, None, code, '', {}, 'http://elsewhere/')

    def test_invalid_and_oversized_responses_rejected(self):
        for raw, status in [(b'{}', 302), (b'{}', 401), (b'[]', 200), (b'not json', 200),
                            (b'{"a":1,"a":2}', 200), (b'{"a":NaN}', 200),
                            (b'x'*(plugin.MAX_RESPONSE+1), 200), (b'\xff', 200)]:
            with self.subTest(status=status, size=len(raw)), self.assertRaises(Exception):
                self.call(raw, status)

    def test_route_injection_rejected_without_network(self):
        with patch.object(plugin.urllib.request, 'build_opener') as build:
            for method, identifier in [('DELETE', IDENTIFIER), ('GET', '../config'), ('GET', IDENTIFIER+'?x=y')]:
                with self.assertRaises(plugin.Refused):
                    plugin.request(method, identifier, TOKEN)
            build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
