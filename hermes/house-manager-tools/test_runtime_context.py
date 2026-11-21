"""Stdlib regression harness using captured ORIGINAL installed public source.

No upstream repository or private runtime state required. Dependencies outside the
reviewed functions are isolated stubs; actual policy, workspace, plugin surface,
dispatch and executor context-copy bodies are compiled from installed source.
"""
from __future__ import annotations

import ast
import asyncio
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, replace
from enum import Enum
from functools import cached_property
import functools
import hashlib
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parent / 'runtime_context'
FIXTURES = Path(os.environ.get('HERMES_PUBLIC_SOURCE_FIXTURES', str(ROOT / '.test-state/installed')))


class Platform(str, Enum):
    LOCAL = 'local'


def load_local(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = load_local('render')
provenance = load_local('provenance')


def extract(text, names, namespace):
    tree = ast.parse(text)
    nodes: list[Any] = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise AssertionError(f'missing installed definitions: {names}')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<installed-public-source>', 'exec'), namespace)


def module(name, **attributes):
    obj = ModuleType(name)
    obj.__dict__.update(attributes)
    return obj


class RuntimeHarness:
    def __init__(self, patched=True):
        self.originals = {p: (FIXTURES / p).read_bytes() for p in renderer.BASE_SHA256}
        self.rendered = renderer.render(self.originals) if patched else self.originals
        self.cwd = ContextVar('fixture_cwd', default='outer-cwd')
        self.terminal: ContextVar[Any] = ContextVar('fixture_terminal', default='outer-terminal')
        self.env = ContextVar('fixture_env', default={})
        self.owner = SimpleNamespace(profile_id='/synthetic/profile')
        self.policy = module('gateway.session_policy', contextmanager=contextmanager,
                             ContextVar=ContextVar, dataclass=dataclass, cached_property=cached_property,
                             json=json, _ACTIVE_POLICY=ContextVar('local_session_policy', default=None),
                             _COMMAND_LIFETIME=ContextVar('plugin_command_lifetime',default=None))
        with patch.dict(sys.modules, {'gateway.session_policy': self.policy}):
            extract(self.rendered['gateway/session_policy.py'].decode(),
                    {'LocalSessionPolicy', 'active_policy', 'policy_for_source'} |
                    ({'active_policy_scope','_CommandDispatchLease','command_dispatch_scope',
                      'command_dispatch_live','command_dispatch_cancelled','claim_command_dispatch'} if patched else set()), self.policy.__dict__)
        class LocalSessionAdapter:
            def __init__(self):
                self.policies = {}
            def authorize_source(self, source):
                return source.authorized
        self.adapter = LocalSessionAdapter()
        self.runner = SimpleNamespace(_adapter_for_source=lambda source: self.adapter)
        self.mods = {
            'gateway': module('gateway'), 'agent': module('agent'), 'tools': module('tools'),
            'hermes_cli': module('hermes_cli'),
            'gateway.session_policy': self.policy,
            'gateway.session_local': module('gateway.session_local', LocalSessionAdapter=LocalSessionAdapter),
            'gateway.config': module('gateway.config', Platform=Platform),
            'agent.runtime_cwd': module('agent.runtime_cwd',
                set_session_cwd=self.cwd.set, reset_session_cwd=self.cwd.reset),
            'agent.runtime_scope': module('agent.runtime_scope',
                bind_terminal_policy=lambda value, profile_home=None: self.terminal.set((value, profile_home))),
            'tools.terminal_scope': module('tools.terminal_scope', reset_terminal_scope=self.terminal.reset),
            'gateway.session_authorities': module('gateway.session_authorities', active_authority=lambda runner: self.owner),
            'gateway.session_context': module('gateway.session_context',
                get_session_env=lambda key, default='': self.env.get().get(key, default)),
        }
        ns: dict[str, Any] = {'contextmanager': contextmanager}
        extract(self.rendered['gateway/session_commands.py'].decode(), {'_session_workspace'}, ns)
        self.workspace = ns['_session_workspace']
        ps = module('hermes_cli.plugin_session')
        exec(compile(self.rendered['hermes_cli/plugin_session.py'], 'plugin_session.py', 'exec'), ps.__dict__)
        self.mods['hermes_cli.plugin_session'] = ps
        self.surface = lambda: ps.context_surface(SimpleNamespace(_cli_ref=None))
        if patched:
            accessor_ns = {'Optional': __import__('typing').Optional}
            extract(self.rendered['hermes_cli/plugins_context.py'].decode(),
                    {'session_launch_source','command_is_live','claim_command_dispatch'}, accessor_ns)
            ctx = SimpleNamespace(_manager=SimpleNamespace(_cli_ref=None))
            self.launch_source = lambda: accessor_ns['session_launch_source'](ctx)
            self.command_is_live = lambda: accessor_ns['command_is_live'](ctx)
            self.claim_dispatch = lambda: accessor_ns['claim_command_dispatch'](ctx)
        dispatch = module('hermes_cli.plugin_command_dispatch')
        exec(compile((FIXTURES / 'hermes_cli/plugin_command_dispatch.py').read_bytes(), 'plugin_command_dispatch.py', 'exec'), dispatch.__dict__)
        self.mods['hermes_cli.plugin_command_dispatch'] = dispatch
        self.mods['gateway.plugin_messages'] = module('gateway.plugin_messages', bind_live_source=lambda source: nullcontext())
        self.mods['gateway.plugin_command_choice'] = module('gateway.plugin_command_choice', chat_choices=lambda *a: nullcontext())
        self.dispatch_ns = dict(asyncio=asyncio, functools=functools, inspect=inspect,
            MessageEvent=object, SessionSource=object, Optional=__import__('typing').Optional,
            build_session_context=lambda source, config, entry: SimpleNamespace(session_id='fixture-id', session_key='fixture-key'))
        extract((FIXTURES / 'gateway/run_inbound_hooks.py').read_text(), {'_hm_run_plugin_handler'}, self.dispatch_ns)
        self.dispatch = self.dispatch_ns['_hm_run_plugin_handler']
        self.runner.config = {}
        self.runner._session_key_for_source = lambda source: 'fixture-key'
        self.runner._session_env_scope = self.session_env
        # The actual installed executor body is captured separately, without importing gateway/run.
        executor_text = (FIXTURES / 'gateway/executor_context.py').read_text()
        executor_ns: dict[str, Any] = dict(asyncio=asyncio, copy_context=copy_context)
        extract(executor_text, {'_run_in_executor_with_context'}, executor_ns)
        self.runner._get_executor = lambda: None
        self.runner._run_in_executor_with_context = functools.partial(executor_ns['_run_in_executor_with_context'], self.runner)

    @contextmanager
    def session_env(self, context):
        token = self.env.set({'HERMES_SESSION_PLATFORM': 'local'})
        try:
            yield
        finally:
            self.env.reset(token)

    def launch(self, source, platform=None):
        platform = platform or {'gui': 'desktop', 'tool': 'cli', 'oneshot': 'cli'}.get(source, source)
        policy = self.policy.LocalSessionPolicy(source, platform, '/synthetic/workspace', None, (), '{}',
                                               json.dumps({'source': source}), '{}')
        src = SimpleNamespace(platform=Platform.LOCAL, chat_id=source, authorized=True)
        self.adapter.policies[source] = policy
        return src, policy

    async def invoke(self, source, handler, args='exact args'):
        event = SimpleNamespace(get_command_args=lambda: args)
        with self.workspace(self.runner, source):
            return await self.dispatch(self.runner, handler, event, source, object())


class RendererTests(unittest.TestCase):
    def test_public_fixture_hashes(self):
        with patch.dict(sys.modules, {'render': renderer}):
            collector = load_local('capture_public_sources')
        for name, digest in collector.FIXTURE_SHA256.items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest, name)

    def test_hash_preconditions_and_determinism(self):
        originals = {p: (FIXTURES / p).read_bytes() for p in renderer.BASE_SHA256}
        result = renderer.render(originals)
        self.assertEqual(result, renderer.render(originals))
        for name in originals:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    renderer.render({**originals, name: originals[name] + b'\n'})
        with self.assertRaises(ValueError):
            renderer.render(result)  # double application refuses

    def test_authorization_and_dispatch_are_byte_unchanged(self):
        originals = {p: (FIXTURES / p).read_bytes() for p in renderer.BASE_SHA256}
        patched = renderer.render(originals)
        name = 'gateway/session_commands.py'
        before, after = originals[name].decode(), patched[name].decode()
        marker = '\n\nasync def execute_command('
        self.assertEqual(before[before.index(marker):], after[after.index(marker):])
        prefix = '@contextmanager\ndef _session_workspace('
        self.assertEqual(before[:before.index(prefix)], after[:after.index(prefix)])
        # Bind only provenance: no policy_scope/profile/model/credential resolution added.
        self.assertNotIn('policy.config(', renderer.POLICY_HELPER)
        self.assertNotIn('read_profile', renderer.POLICY_HELPER)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_picker_worker_cannot_submit_even_if_it_returns_approve(self):
        import chat_approval_plugin as approval
        import test_chat_approval_plugin as fixtures
        h=RuntimeHarness()
        class SessionSource(SimpleNamespace):pass
        h.mods['gateway.session']=module('gateway.session',SessionSource=SessionSource)
        with patch.dict(sys.modules,h.mods):
            source,_=h.launch('gui')
            source=SessionSource(**source.__dict__,is_bot=False,profile='house-manager',
                                 profile_route_rejected=False,delivered_via_upstream_relay=False,detached_route=None)
            started,release,finished=threading.Event(),threading.Event(),threading.Event()
            calls=[];results=[];doc=fixtures.document()
            def http(method,*args):
                calls.append(method)
                return {'status':'awaiting_approval','proposal':doc,'interaction_id':'c'*32}
            def choose(*args):
                started.set()
                if not release.wait(3):raise AssertionError('picker test timeout')
                return 'approve_exact'
            ctx=SimpleNamespace(profile_name='house-manager',current_cron_execution=lambda:None,
                                session_surface=h.surface,session_launch_source=h.launch_source,ask_choice=choose,
                                command_is_live=h.command_is_live,claim_command_dispatch=h.claim_dispatch)
            callback=approval.make_handler(ctx,environ={'HOUSE_MANAGER_APPROVAL_TOKEN':'synthetic-only'},http=http)
            def handler(args,**kwargs):
                try:
                    result=callback(args,**kwargs);results.append(result);return result
                finally:finished.set()
            task=asyncio.create_task(h.invoke(source,handler,fixtures.IDENTIFIER+' '+doc['sha256']))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait,3))
                task.cancel()
                # Release immediately, BEFORE awaiting cancellation cleanup.
                # Admission must also see the owner's pending cancel request.
                release.set()
                with self.assertRaises(asyncio.CancelledError):await task
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait,3))
            self.assertEqual(calls,['GET'])
            self.assertIn('not confirmed',results[0])
            self.assertFalse(h.command_is_live())

    async def test_dispatch_claim_is_once_and_is_closed_on_normal_completion(self):
        h=RuntimeHarness()
        with patch.dict(sys.modules,h.mods):
            source,_=h.launch('cli')
            def handler(args):
                self.assertTrue(h.command_is_live())
                self.assertTrue(h.claim_dispatch())
                self.assertFalse(h.claim_dispatch())
                return 'one admission'
            self.assertEqual(await h.invoke(source,handler),'one admission')
            self.assertFalse(h.command_is_live())
            self.assertFalse(h.claim_dispatch())

    async def test_native_picker_gets_live_cancellation_predicate(self):
        h=RuntimeHarness();started,finished=threading.Event(),threading.Event()
        observed=[]
        def ask(*args,**kwargs):
            cancelled=kwargs['cancelled'];observed.append(cancelled())
            started.set()
            deadline=__import__('time').monotonic()+3
            while not cancelled():
                if __import__('time').monotonic()>deadline:raise AssertionError('cancellation was not propagated')
                threading.Event().wait(0.01)
            observed.append(cancelled())
            return None
        h.mods['gateway.session_server_requests']=module('gateway.session_server_requests',ask_viewer_result=ask)
        h.mods['tools.clarify_gateway']=module('tools.clarify_gateway',get_clarify_timeout=lambda:90)
        ns={'Optional':__import__('typing').Optional}
        extract(h.rendered['gateway/plugin_command_choice.py'].decode(),{'_ask_viewers'},ns)
        with patch.dict(sys.modules,h.mods):
            source,_=h.launch('tui')
            def handler(args):
                try:return ns['_ask_viewers'](SimpleNamespace(event_stream=object()),'fixture-id','question',['Cancel'])
                finally:finished.set()
            task=asyncio.create_task(h.invoke(source,handler))
            self.assertTrue(await asyncio.to_thread(started.wait,3))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(await asyncio.to_thread(finished.wait,3))
            self.assertEqual(observed,[False,True])

    async def test_real_plugin_consumes_patched_accessor_and_cancels_without_post(self):
        import chat_approval_plugin as approval
        import test_chat_approval_plugin as fixtures
        h=RuntimeHarness()
        class SessionSource(SimpleNamespace):pass
        h.mods['gateway.session']=module('gateway.session',SessionSource=SessionSource)
        doc=fixtures.document()
        for label in ('cli','tui','gui','tool','oneshot','acp','bot_room','a2a'):
            with self.subTest(label=label),patch.dict(sys.modules,h.mods):
                source,_=h.launch(label)
                source=SessionSource(**source.__dict__,is_bot=False,profile='house-manager',
                                     profile_route_rejected=False,delivered_via_upstream_relay=False,detached_route=None)
                calls=[];questions=[]
                def http(method,identifier,token,payload=None):
                    calls.append(method)
                    self.assertEqual(method,'GET')
                    return {'status':'awaiting_approval','proposal':doc,'interaction_id':'c'*32}
                def choose(question,choices):
                    questions.append(question)
                    self.assertIn(approval.canonical(doc).decode(),question)
                    return 'cancel'
                ctx=SimpleNamespace(profile_name='house-manager',current_cron_execution=lambda:None,
                                    session_surface=h.surface,session_launch_source=h.launch_source,ask_choice=choose,
                                    command_is_live=h.command_is_live,claim_command_dispatch=h.claim_dispatch)
                handler=approval.make_handler(ctx,environ={'HOUSE_MANAGER_APPROVAL_TOKEN':'synthetic-only'},http=http)
                result=await h.invoke(source,handler,fixtures.IDENTIFIER+' '+doc['sha256'])
                if label in ('cli','tui','gui'):
                    self.assertIn('Cancelled',result)
                    self.assertEqual(calls,['GET'])
                    self.assertEqual(len(questions),1)
                else:
                    self.assertEqual(calls,[])
                    self.assertEqual(questions,[])
                    self.assertIn('not confirmed',result)
                self.assertIsNone(h.policy.active_policy())

    async def test_actual_execute_actor_and_profile_gates(self):
        class Refusal(Exception):
            pass
        def denied(*args):
            raise Refusal('actor denied')
        ns: dict[str, Any] = dict(Path=Path, RuntimeStoreError=Refusal)
        extract((FIXTURES / 'gateway/session_commands.py').read_text(), {'execute_command', '_parse'}, ns)
        connection = SimpleNamespace(authority=SimpleNamespace(authorize=denied), actor='synthetic-actor')
        with self.assertRaisesRegex(Refusal, 'actor denied'):
            await ns['execute_command'](connection, object(), {'command': '/house-approve'})
        seen = []
        connection.authority.authorize = lambda *args: seen.append(args)
        connection.authority.profile_id = '/synthetic/owning-profile'
        mods = {
            'hermes_cli.commands': module('hermes_cli.commands', resolve_command=lambda name: None),
            'hermes_cli.profiles': module('hermes_cli.profiles', profile_matches_home=lambda name, home: False),
        }
        with patch.dict(sys.modules, mods):
            with self.assertRaisesRegex(Refusal, 'profile_mismatch'):
                await ns['execute_command'](connection, object(), {'command': '/house-approve', 'profile': 'foreign'})
        self.assertEqual(seen[0][-1], 'session:read')

    async def test_original_bug_reproduced(self):
        h = RuntimeHarness(patched=False)
        with patch.dict(sys.modules, h.mods):
            source, _ = h.launch('gui')
            self.assertEqual(await h.invoke(source, lambda args: h.surface()), 'local')

    async def test_three_surfaces_sync_and_async_real_dispatch(self):
        h = RuntimeHarness()
        with patch.dict(sys.modules, h.mods):
            for source_name, surface in [('cli', 'cli'), ('tui', 'tui'), ('gui', 'desktop')]:
                source, policy = h.launch(source_name)
                def sync(args, source=None, session_id=None, session_key=None, platform=None):
                    self.assertEqual(args, 'exact args')
                    self.assertEqual((session_id, session_key, platform), ('fixture-id', 'fixture-key', 'local'))
                    self.assertIs(h.policy.active_policy(), policy)
                    self.assertEqual(h.cwd.get(), '/synthetic/workspace')
                    self.assertEqual(h.terminal.get()[1], '/synthetic/profile')
                    self.assertEqual(provenance.trusted_launch_source(h.policy.active_policy()), source_name)
                    self.assertEqual(h.launch_source(), source_name)
                    return h.surface()
                async def async_handler(args):
                    await asyncio.sleep(0)
                    return h.surface()
                self.assertEqual(await h.invoke(source, sync), surface)
                self.assertEqual(await h.invoke(source, async_handler), surface)
                self.assertIsNone(h.policy.active_policy())
                self.assertEqual(h.cwd.get(), 'outer-cwd')
                self.assertEqual(h.terminal.get(), 'outer-terminal')

    async def test_denied_labels_and_incoherent_evidence(self):
        h = RuntimeHarness()
        with patch.dict(sys.modules, h.mods):
            for label in ['acp', 'tool', 'oneshot', 'bot_room', 'a2a', 'local', 'unknown', '', 'desktop', 'CLI']:
                source, policy = h.launch(label)
                def handler(args):
                    self.assertIs(h.policy.active_policy(), policy)
                    self.assertIsNone(provenance.trusted_launch_source(h.policy.active_policy()))
                    self.assertIsNone(h.launch_source())
                    return 'denied'
                self.assertEqual(await h.invoke(source, handler), 'denied')
            _, good = h.launch('cli')
            for bad in [None, replace(good, request_json='{}'), replace(good, request_json='null'),
                        replace(good, request_json='oops'), replace(good, platform='desktop'),
                        replace(good, request_json='{"source":"tool"}'), SimpleNamespace(source=[]),
                        replace(good, request_json='{"source":"gui"}')]:
                self.assertIsNone(provenance.trusted_launch_source(bad))

    async def test_exception_cancel_nested_and_none_restore(self):
        h = RuntimeHarness()
        with patch.dict(sys.modules, h.mods):
            source, policy = h.launch('gui')
            _, outer = h.launch('tui')
            with h.policy.active_policy_scope(outer):
                with self.assertRaisesRegex(RuntimeError, 'sentinel'):
                    def fail(args):
                        self.assertIs(h.policy.active_policy(), policy)
                        raise RuntimeError('sentinel')
                    await h.invoke(source, fail)
                self.assertIs(h.policy.active_policy(), outer)
                with h.workspace(h.runner, None):
                    self.assertIsNone(h.policy.active_policy())
                self.assertIs(h.policy.active_policy(), outer)
                with self.assertRaises(asyncio.CancelledError):
                    with h.workspace(h.runner, source):
                        raise asyncio.CancelledError()
                self.assertIs(h.policy.active_policy(), outer)
            self.assertIsNone(h.policy.active_policy())
            entered = asyncio.Event()
            async def waiting(args):
                entered.set()
                await asyncio.Event().wait()
            task = asyncio.create_task(h.invoke(source, waiting))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertIsNone(h.policy.active_policy())
            self.assertEqual(h.cwd.get(), 'outer-cwd')
            self.assertEqual(h.terminal.get(), 'outer-terminal')

    async def test_concurrent_tasks_and_executor_context_copy(self):
        h = RuntimeHarness()
        with patch.dict(sys.modules, h.mods):
            gate = asyncio.Event()
            ready = []
            async def run(label):
                source, policy = h.launch(label)
                async def handler(args):
                    ready.append(label)
                    if len(ready) == 3:
                        gate.set()
                    await gate.wait()
                    await asyncio.sleep(0)
                    self.assertIs(h.policy.active_policy(), policy)
                    self.assertIs(await asyncio.to_thread(h.policy.active_policy), policy)
                    loop = asyncio.get_running_loop()
                    self.assertIs(await loop.run_in_executor(None, copy_context().run, h.policy.active_policy), policy)
                    # Plain run_in_executor intentionally does NOT inherit contextvars.
                    self.assertIsNone(await loop.run_in_executor(None, h.policy.active_policy))
                    return h.surface()
                result = await h.invoke(source, handler)
                self.assertIsNone(h.policy.active_policy())
                return result
            self.assertEqual(await asyncio.gather(*(run(s) for s in ['cli', 'tui', 'gui'])), ['cli', 'tui', 'desktop'])
            self.assertIsNone(h.policy.active_policy())

    async def test_policy_source_authorization_is_not_bypassed(self):
        h = RuntimeHarness()
        with patch.dict(sys.modules, h.mods):
            source, policy = h.launch('gui')
            source.authorized = False
            with h.workspace(h.runner, source):
                self.assertIsNone(h.policy.active_policy())
            self.assertIsNone(h.policy.active_policy())


    async def test_cancelled_sync_worker_copy_does_not_leak(self):
        h = RuntimeHarness()
        with patch.dict(sys.modules, h.mods):
            source, policy = h.launch('gui')
            started, release, finished = threading.Event(), threading.Event(), threading.Event()
            observed, unwound = [], []
            def handler(args):
                try:
                    observed.append(h.policy.active_policy())
                    started.set()
                    if not release.wait(3):
                        raise AssertionError('test worker timed out')
                    # Cancellation cannot revoke a context already copied to a running thread.
                    observed.append(h.policy.active_policy())
                    return h.surface()
                finally:
                    finished.set()
            async def invoke():
                try:
                    return await h.invoke(source, handler)
                finally:
                    unwound.append((h.policy.active_policy(), h.cwd.get(), h.terminal.get()))
            task = asyncio.create_task(invoke())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(unwound, [(None, 'outer-cwd', 'outer-terminal')])
            finally:
                release.set()
                self.assertTrue(await asyncio.to_thread(finished.wait, 3))
            self.assertEqual(observed, [policy, policy])
            self.assertIsNone(await h.runner._run_in_executor_with_context(h.policy.active_policy))
            self.assertIsNone(h.policy.active_policy())


if __name__ == '__main__':
    unittest.main(verbosity=2)
