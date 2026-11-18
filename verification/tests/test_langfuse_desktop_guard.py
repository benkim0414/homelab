"""Credential-free guard contract tests; no runtime profiles or network access."""
import atexit
import hashlib
import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch
import tempfile
import os

PLUGIN = Path(__file__).resolve().parents[2] / 'langfuse/plugins/homelab-langfuse-desktop'
# Public source only; override for CI with a checkout, never a profile directory.
CORE = Path(os.environ.get('HERMES_TEST_CORE', '/home/benkim0414/.hermes/hermes-agent'))
SOURCE = CORE / 'plugins/observability/langfuse/__init__.py'
PIN = '75f0959a4152145a7c33591d6ddd3c4c8bfd53b29e0807f18abdc19bb8a485d1'


class Context:
    def __init__(self):
        self.hooks = {}
        self.unloads = []
    def register_hook(self, name, fn):
        self.hooks[name] = fn
    def on_unload(self, fn):
        self.unloads.append(fn)
    def unload(self):
        for fn in self.unloads:
            fn()


@unittest.skipUnless(SOURCE.exists(), 'reviewed public Hermes source required (HERMES_TEST_CORE)')
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.profile = 'default'
        self.multiplex = False
        self.calls = []
        self.clients = []
        self.secrets = {'HERMES_LANGFUSE_PUBLIC_KEY': 'pk-lf-fake-test-only',
                        'HERMES_LANGFUSE_SECRET_KEY': 'sk-lf-fake-test-only'}
        self.original = SOURCE.read_bytes()
        self.constants = types.ModuleType('hermes_constants')
        self.constants.__file__ = str(CORE / 'hermes_constants.py')
        self.constants.get_hermes_home = lambda: self.home
        profiles = types.ModuleType('hermes_cli.profiles')
        profiles.get_active_profile_name = lambda: self.profile
        scope = types.ModuleType('agent.secret_scope')
        scope.is_multiplex_active = lambda: self.multiplex
        scope.get_secret = lambda name: self.secrets.get(name, '')
        class Manager:
            _instances = {}
            _lock = threading.RLock()
        self.manager = Manager
        owner = self
        class Client:
            def __init__(self, **kwargs):
                owner.calls.append(kwargs)
                self._base_url = kwargs['base_url']
                self._environment = kwargs['environment']
                self._resources = types.SimpleNamespace(base_url=kwargs['base_url'])
                Manager._instances[kwargs['public_key']] = self._resources
                self.flushes = self.shutdowns = 0
                owner.clients.append(self)
            def flush(self):
                self.flushes += 1
            def shutdown(self):
                self.shutdowns += 1
        sdk = types.ModuleType('langfuse')
        sdk.Langfuse = Client
        sdk.propagate_attributes = lambda **kw: None
        rm = types.ModuleType('langfuse._client.resource_manager')
        rm.LangfuseResourceManager = Manager
        self.env = {'HERMES_LANGFUSE_BASE_URL': 'https://langfuse.tailbd291c.ts.net',
                    'HERMES_LANGFUSE_CAPTURE': 'metadata', 'HERMES_LANGFUSE_ENV': 'homelab-desktop',
                    'HERMES_LANGFUSE_SAMPLE_RATE': '1', 'OTEL_SERVICE_NAME': 'hermes-desktop-default'}
        self.envpatch = patch.dict(os.environ, self.env, clear=True)
        self.envpatch.start()
        self.addCleanup(self.envpatch.stop)
        self.modulespatch = patch.dict(sys.modules, {'hermes_constants': self.constants,
            'hermes_cli': types.ModuleType('hermes_cli'), 'hermes_cli.profiles': profiles,
            'agent': types.ModuleType('agent'), 'agent.secret_scope': scope,
            'langfuse': sdk, 'langfuse._client.resource_manager': rm})
        self.modulespatch.start()
        self.addCleanup(self.modulespatch.stop)
        name = 'desktop_guard_test'
        spec = importlib.util.spec_from_file_location(name, PLUGIN / '__init__.py',
                                                     submodule_search_locations=[str(PLUGIN)])
        self.guard = importlib.util.module_from_spec(spec)
        sys.modules[name] = self.guard
        self.addCleanup(lambda: sys.modules.pop(name, None))
        spec.loader.exec_module(self.guard)
        self.providers = []
        def provider(service):
            item = types.SimpleNamespace(service=service, shutdowns=0)
            def shutdown():
                item.shutdowns += 1
            item.shutdown = shutdown
            self.providers.append(item)
            return item
        self.guard._private_provider = provider
        self.contexts = []
        self.addCleanup(lambda: [ctx.unload() for ctx in self.contexts])

    def register(self):
        ctx = Context()
        self.contexts.append(ctx)
        self.guard.register(ctx)
        return ctx

    def delegate(self, ctx):
        return ctx.hooks['pre_api_request'].__guard_delegate__

    def test_valid_registration_and_original_untouched(self):
        ctx = self.register()
        self.assertEqual(len(ctx.hooks), 11)
        self.assertFalse(self.calls)
        native = self.delegate(ctx)
        self.assertEqual(native._capture_mode(), 'metadata')
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), PIN)
        self.assertEqual(SOURCE.read_bytes(), self.original)
        self.assertNotIn('plugins.observability.langfuse', sys.modules)
        self.assertTrue(native.__name__.startswith(self.guard.__name__ + '.'))

    def test_distinct_roots_keep_session_and_reuse_active_turn(self):
        native = self.delegate(self.register())
        opened = []
        class TraceClient:
            def create_trace_id(self, *, seed=None):
                if seed is not None:
                    return hashlib.sha256(seed.encode()).hexdigest()[:32]
                import uuid
                return uuid.uuid4().hex
            def start_observation(self, **kwargs):
                opened.append(kwargs)
                return types.SimpleNamespace(set_trace_io=lambda **kw: None)
            def start_as_current_observation(self, **kwargs):
                from contextlib import nullcontext
                return nullcontext(self.start_observation(**kwargs))
        kwargs = dict(task_id='same-task', session_id='same-session', platform='cli',
                      provider='fixture', model='none', api_mode='fixture',
                      messages=[{'role': 'user', 'content': 'PRIVATE_FIXTURE_CANARY'}],
                      client=TraceClient(), turn_id='same-legacy-turn-id')
        first = native._get_or_start_state_locked('same-key', **kwargs)
        retry = native._get_or_start_state_locked('same-key', **kwargs)
        self.assertIs(first, retry)
        self.assertEqual(len(opened), 1)
        native._TRACE_STATE.pop('same-key')
        second = native._get_or_start_state_locked('same-key', **kwargs)
        self.assertNotEqual(first.trace_id, second.trace_id)
        self.assertEqual(len(opened), 2)
        for call in opened:
            self.assertEqual(call['trace_context']['session_id'], 'same-session')
            self.assertTrue(call['input']['content']['omitted'])
            self.assertNotIn('PRIVATE_FIXTURE_CANARY', str(call))
        native._TRACE_STATE.clear()
        self.assertFalse(self.calls)

    def test_launch_rejections_no_sdk(self):
        for key, value in [('HERMES_LANGFUSE_BASE_URL', None), ('HERMES_LANGFUSE_BASE_URL', 'https://cloud.langfuse.com'),
                           ('HERMES_LANGFUSE_CAPTURE', None), ('HERMES_LANGFUSE_CAPTURE', 'sanitized'),
                           ('HERMES_LANGFUSE_CAPTURE', 'full'), ('HERMES_LANGFUSE_ENV', 'production'),
                           ('HERMES_LANGFUSE_SAMPLE_RATE', '.5'), ('OTEL_SERVICE_NAME', None)]:
            with self.subTest(key=key, value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
                self.assertFalse(self.register().hooks)
        self.assertFalse(self.calls)

    def test_home_multiplex_and_environment_checked_each_call(self):
        ctx = self.register()
        native = self.delegate(ctx)
        seen = []
        # Wrapped callbacks retain their original function, so replace its dependency.
        native._get_langfuse = lambda: seen.append(True)
        hook = ctx.hooks['subagent_start']
        hook(child_session_id='x')
        self.assertEqual(len(seen), 1)
        os.environ['HERMES_LANGFUSE_CAPTURE'] = 'full'
        hook(child_session_id='x', child_goal='MUST NOT LOG')
        os.environ.update(self.env)
        self.home = self.home / 'other'
        hook(child_session_id='x')
        self.home = Path(self.tmp.name)
        self.multiplex = True
        hook(child_session_id='x')
        self.assertEqual(len(seen), 1)

    def test_multiplex_refused_at_registration(self):
        self.multiplex = True
        self.assertFalse(self.register().hooks)
        self.assertFalse(self.calls)

    def test_source_drift(self):
        drift = Path(self.tmp.name) / 'drift.py'
        drift.write_text('raise AssertionError("must not execute")')
        with patch.object(self.guard, '_source_path', return_value=drift):
            self.assertFalse(self.register().hooks)
        self.assertFalse(self.calls)

    def test_isolated_generations(self):
        a, b = self.register(), self.register()
        na, nb = self.delegate(a), self.delegate(b)
        self.assertIsNot(na, nb)
        self.assertIsNot(na._TRACE_STATE, nb._TRACE_STATE)
        na._TRACE_STATE['sentinel'] = None
        self.assertFalse(nb._TRACE_STATE)
        na._TRACE_STATE.clear()

    def test_fixed_env_and_primary_auth_only(self):
        native = self.delegate(self.register())
        os.environ['LANGFUSE_BASE_URL'] = 'https://cloud.langfuse.com'
        os.environ['LANGFUSE_SECRET_KEY'] = 'sk-lf-alternate-fake'
        self.assertEqual(native._env('LANGFUSE_SECRET_KEY'), '')
        self.assertEqual(native._env('HERMES_LANGFUSE_DEBUG'), '')
        self.assertIsNotNone(native._get_langfuse())
        self.assertEqual(self.calls[0]['base_url'], self.env['HERMES_LANGFUSE_BASE_URL'])
        self.assertEqual(self.calls[0]['sample_rate'], 1.0)
        self.secrets.clear()
        other = self.delegate(self.register())
        self.assertIsNone(other._get_langfuse())
        self.assertEqual(len(self.calls), 1)

    def test_actual_constructor_args_rejected_before_sdk(self):
        native = self.delegate(self.register())
        good = dict(public_key=self.secrets['HERMES_LANGFUSE_PUBLIC_KEY'],
                    secret_key=self.secrets['HERMES_LANGFUSE_SECRET_KEY'],
                    base_url=self.env['HERMES_LANGFUSE_BASE_URL'], environment='homelab-desktop', sample_rate=1.0)
        for key, value in [('base_url', 'https://cloud.langfuse.com'), ('environment', 'production'),
                           ('sample_rate', .1), ('public_key', 'pk-lf-other-fake'),
                           ('secret_key', 'sk-lf-other-fake'), ('host', 'https://cloud.langfuse.com')]:
            with self.subTest(key=key):
                self.assertIsNone(native.Langfuse(**{**good, key: value}))
        self.assertFalse(self.calls)

    def test_resource_cache_collision_is_not_shutdown(self):
        foreign = types.SimpleNamespace(base_url='https://cloud.langfuse.com', shutdown=lambda: self.fail('foreign shutdown'))
        self.manager._instances[self.secrets['HERMES_LANGFUSE_PUBLIC_KEY']] = foreign
        native = self.delegate(self.register())
        self.assertIsNone(native._get_langfuse())
        self.assertFalse(self.calls)
        self.contexts[-1].unload()
        self.assertIs(self.manager._instances[self.secrets['HERMES_LANGFUSE_PUBLIC_KEY']], foreign)

    def test_actual_destination_checked_and_silent_failure(self):
        native = self.delegate(self.register())
        real = native._guard_sdk_constructor
        def wrong(**kw):
            client = real(**kw)
            client._resources.base_url = 'https://cloud.langfuse.com'
            return client
        native._guard_sdk_constructor = wrong
        with self.assertNoLogs(level='WARNING'):
            self.assertIsNone(native._get_langfuse())

    def test_nested_metadata_stubs_and_freeze(self):
        native = self.delegate(self.register())
        os.environ['HERMES_LANGFUSE_CAPTURE'] = 'full'
        self.assertEqual(native._capture_mode(), 'metadata')
        result = native._capture_content({'nested': {'body': 'PRIVATE CANARY'}})
        self.assertTrue(result['omitted'])
        self.assertNotIn('PRIVATE CANARY', str(result))
        self.assertEqual(native._capture_content('PRIVATE CANARY')['type'], 'text')
        tc = types.SimpleNamespace(id='call-id', type='function', function=types.SimpleNamespace(
            name='read_file', arguments='{"path":"PRIVATE CANARY"}'))
        output = native._serialize_assistant_message(types.SimpleNamespace(
            content='PRIVATE CANARY', reasoning='PRIVATE CANARY', tool_calls=[tc]))
        self.assertTrue(output['content']['omitted'])
        self.assertTrue(output['reasoning']['omitted'])
        self.assertTrue(output['tool_calls'][0]['arguments']['omitted'])
        self.assertTrue(output['tool_calls'][0]['function']['arguments']['omitted'])
        self.assertNotIn('PRIVATE CANARY', str(output))
        messages = native._messages_for_langfuse_input(request_messages=[
            {'role': 'user', 'content': [{'text': 'PRIVATE CANARY'}]},
            {'role': 'tool', 'content': 'PRIVATE CANARY', 'tool_call_id': 'call-id'}],
            system_prompt='PRIVATE CANARY')
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'tool'])
        self.assertTrue(all(m['content']['omitted'] for m in messages))
        self.assertNotIn('PRIVATE CANARY', str(messages))

    def test_canonical_import_and_single_native_register(self):
        canonical = types.ModuleType('plugins.observability.langfuse')
        canonical.marker = object()
        with patch.dict(sys.modules, {'plugins.observability.langfuse': canonical}):
            ctx = self.register()
            self.assertIs(sys.modules['plugins.observability.langfuse'], canonical)
            self.assertEqual(len(ctx.hooks), 11)
        self.assertEqual(len(ctx.unloads), 1)

    def test_policy_changes_never_reach_actual_constructor(self):
        ctx = self.register()
        native = self.delegate(ctx)
        os.environ.pop('HERMES_LANGFUSE_BASE_URL')
        self.assertIsNone(native._get_langfuse())
        self.assertFalse(self.calls)
        self.assertFalse(self.providers)

    def test_atexit_is_private_and_idempotent(self):
        callbacks = []
        with patch.object(atexit, 'register', side_effect=lambda fn: callbacks.append(fn)), \
                patch.object(atexit, 'unregister') as unregister:
            ctx = self.register()
            native = self.delegate(ctx)
            native._get_langfuse()
            self.assertEqual(len(callbacks), 1)
            ended = []
            span = types.SimpleNamespace(end=lambda: ended.append(True))
            native._TRACE_STATE['root'] = native.TraceState('id', None, span)
            ctx.unload()
            callbacks[0]()
            self.assertEqual(ended, [True])
            self.assertEqual(self.clients[0].shutdowns, 1)
            self.assertEqual(self.providers[0].shutdowns, 1)
            unregister.assert_called_once_with(callbacks[0])

    def test_cache_replacement_denies_use_and_preserves_foreign(self):
        ctx = self.register()
        native = self.delegate(ctx)
        client = native._get_langfuse()
        foreign = object()
        self.manager._instances[self.secrets['HERMES_LANGFUSE_PUBLIC_KEY']] = foreign
        seen = []
        native._get_langfuse = lambda: seen.append(True)
        ctx.hooks['subagent_start'](child_session_id='x')
        self.assertFalse(seen)
        ctx.unload()
        self.assertEqual(client.shutdowns, 0)
        self.assertIs(self.manager._instances[self.secrets['HERMES_LANGFUSE_PUBLIC_KEY']], foreign)

    def test_partial_native_load_failure_is_silent_and_removed(self):
        before = {n for n in sys.modules if n.startswith(self.guard.__name__ + '.')}
        with patch.object(self.guard._PinnedLoader, 'exec_module', side_effect=RuntimeError('PRIVATE ERROR')):
            with self.assertNoLogs():
                self.assertFalse(self.register().hooks)
        self.assertEqual({n for n in sys.modules if n.startswith(self.guard.__name__ + '.')}, before)
        self.assertFalse(self.calls)

    def test_named_profile_and_unapproved_profile(self):
        self.profile = 'homelab-scientist'
        os.environ['OTEL_SERVICE_NAME'] = 'hermes-desktop-homelab-scientist'
        self.assertEqual(len(self.register().hooks), 11)
        self.profile = 'other'
        os.environ['OTEL_SERVICE_NAME'] = 'hermes-desktop-other'
        self.assertFalse(self.register().hooks)

    def test_constructor_failure_cleans_only_new_manager(self):
        ctx = self.register()
        native = self.delegate(ctx)
        stopped = []
        def broken(**kwargs):
            self.manager._instances[kwargs['public_key']] = types.SimpleNamespace(
                base_url=self.env['HERMES_LANGFUSE_BASE_URL'], shutdown=lambda: stopped.append(True))
            raise RuntimeError('PRIVATE ERROR MUST NOT LOG')
        native._guard_sdk_constructor = broken
        with self.assertNoLogs():
            self.assertIsNone(native._get_langfuse())
        self.assertEqual(stopped, [True])
        self.assertFalse(self.manager._instances)
        self.assertEqual(self.providers[0].shutdowns, 1)

    def test_unload_reload_no_duplicate_export_or_atexit(self):
        ctx = self.register()
        native = self.delegate(ctx)
        client = native._get_langfuse()
        self.assertIsNotNone(client)
        calls = []
        native._finalize_all_traces = lambda: calls.append('finalized')
        # Original finalizer registered by _get_langfuse must also be removed.
        ctx.unload()
        ctx.unload()
        self.assertEqual(calls, ['finalized'])
        self.assertNotIn(native.__name__, sys.modules)
        self.assertFalse(native._TRACE_STATE)
        self.assertEqual(client.shutdowns, 1)
        old_count = len(self.calls)
        ctx.hooks['subagent_start'](child_session_id='old')
        self.assertEqual(len(self.calls), old_count)
        second = self.delegate(self.register())
        self.assertIsNotNone(second._get_langfuse())
        self.assertEqual(len(self.calls), old_count + 1)


if __name__ == '__main__':
    unittest.main()
