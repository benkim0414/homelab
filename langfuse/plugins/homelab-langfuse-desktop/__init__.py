"""Fail-closed, single-profile desktop adapter for one reviewed native plugin.

This is not a sandbox against hostile in-process Python. No canonical plugin,
SDK module, process environment, or Hermes core object is patched. Updating the
source pin or the SDK's private resource API requires a fresh source review.
"""
from __future__ import annotations

import atexit
import contextlib
import hashlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys
import threading
import types
import uuid

SOURCE_SHA256 = '75f0959a4152145a7c33591d6ddd3c4c8bfd53b29e0807f18abdc19bb8a485d1'
BASE_URL = 'https://langfuse.tailbd291c.ts.net'
POLICY = {
    'HERMES_LANGFUSE_BASE_URL': BASE_URL,
    'HERMES_LANGFUSE_CAPTURE': 'metadata',
    'HERMES_LANGFUSE_ENV': 'homelab-desktop',
    'HERMES_LANGFUSE_SAMPLE_RATE': '1',
}
AUTH = ('HERMES_LANGFUSE_PUBLIC_KEY', 'HERMES_LANGFUSE_SECRET_KEY')


class _TurnClient:
    """Root-local SDK view; never mutate the real client or its resource cache."""
    def __init__(self, client):
        self.client = client

    def create_trace_id(self, *, seed):
        # The pinned delegate's session/task seed repeats across CLI turns.
        # A fresh SDK ID per new root leaves session grouping untouched. Native
        # state lookup still reuses the active root for requests/retries/tools.
        return self.client.create_trace_id()

    def __getattr__(self, name):
        return getattr(self.client, name)


def _per_turn_roots(original):
    def start(task_key, *, client, **kwargs):
        return original(task_key, client=_TurnClient(client), **kwargs)
    return start


def _source_path():
    import hermes_constants
    return Path(hermes_constants.__file__).resolve().parent / 'plugins/observability/langfuse/__init__.py'


class _PinnedLoader(importlib.abc.Loader):
    """Execute the bytes already hashed, never a second read or stale .pyc."""
    def __init__(self, source, filename):
        self.source, self.filename = source, filename

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.source, self.filename, 'exec'), module.__dict__)


class _Silent:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@contextlib.contextmanager
def _silent_failsafe(*args, **kwargs):
    try:
        yield
    except Exception:
        pass


def _private_provider(service):
    # Avoid the SDK's default process-global tracer provider, which accumulates
    # exporters over unload/reload and may belong to a different integration.
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    return TracerProvider(resource=Resource.create({'service.name': service}),
                          sampler=ALWAYS_ON, shutdown_on_exit=False)


class _Generation:
    def __init__(self, home, profile):
        self.home, self.profile = home, profile
        self.lock = threading.RLock()
        self.active = True
        self.module = None
        self.client = self.manager = self.provider = None
        self.public_key = self.secret_key = None
        self.finalizers = []
        self.exit_callback = self.close

    def admitted(self):
        from hermes_constants import get_hermes_home
        from hermes_cli.profiles import get_active_profile_name
        from agent.secret_scope import is_multiplex_active
        return (self.active and not is_multiplex_active()
                and Path(get_hermes_home()).resolve() == self.home
                and get_active_profile_name() == self.profile
                and all(os.environ.get(k) == v for k, v in POLICY.items())
                and os.environ.get('OTEL_SERVICE_NAME') == 'hermes-desktop-' + self.profile
                and os.environ.get('LANGFUSE_DEBUG', '').lower() not in {'1', 'true', 'yes', 'on'})

    def env(self, name, default=''):
        # No alternate LANGFUSE_* fallback, debug, release, or other ambient
        # delegate settings. Only normal primary profile-scoped authentication.
        if name in AUTH:
            from agent.secret_scope import get_secret
            value = get_secret(name)
            return value.strip() if isinstance(value, str) else ''
        return POLICY.get(name, '')

    def destination_ok(self):
        if self.client is None:
            return True
        from langfuse._client.resource_manager import LangfuseResourceManager as RM
        with RM._lock:
            return (self.client._base_url == BASE_URL
                    and self.client._environment == 'homelab-desktop'
                    and self.client._resources is self.manager
                    and RM._instances.get(self.public_key) is self.manager
                    and self.manager.base_url == BASE_URL
                    and self.env(AUTH[0]) == self.public_key
                    and self.env(AUTH[1]) == self.secret_key)

    def construct(self, *args, **kwargs):
        # Validate actual kwargs immediately BEFORE SDK construction, not merely
        # the launch settings or the upstream builder's intended destination.
        try:
            from langfuse._client.resource_manager import LangfuseResourceManager as RM
            with self.lock, RM._lock:
                if not self.admitted() or args or self.client is not None:
                    return None
                expected = dict(public_key=self.env(AUTH[0]), secret_key=self.env(AUTH[1]),
                                base_url=BASE_URL, environment='homelab-desktop', sample_rate=1.0)
                if (kwargs != expected or type(kwargs.get('sample_rate')) not in (int, float)
                        or not expected['public_key'].startswith('pk-lf-')
                        or not expected['secret_key'].startswith('sk-lf-')
                        or expected['public_key'] in RM._instances):
                    return None
                self.public_key, self.secret_key = expected['public_key'], expected['secret_key']
                self.provider = _private_provider('hermes-desktop-' + self.profile)
                try:
                    client = self.module._guard_sdk_constructor(**kwargs, tracer_provider=self.provider)
                except Exception:
                    # Under the same SDK RLock, an entry absent at admission is
                    # ours even if the constructor failed after caching it.
                    self.manager = RM._instances.get(self.public_key)
                    raise
                manager = RM._instances.get(self.public_key)
                # A changed SDK layout is a refusal, not a reason to infer routing.
                self.client, self.manager = client, manager
                if manager is None or not self.destination_ok():
                    self._dispose_client()
                    return None
                return client
        except Exception:
            self._dispose_client()
            return None

    def _dispose_client(self):
        # Only a newly created cache entry owned by this generation may be
        # removed/shut down. Never touch a pre-existing or replaced manager.
        try:
            from langfuse._client.resource_manager import LangfuseResourceManager as RM
            with RM._lock:
                if self.manager is not None and RM._instances.get(self.public_key) is self.manager:
                    with contextlib.suppress(Exception):
                        if self.client is not None:
                            self.client.shutdown()
                        else:
                            self.manager.shutdown()
                    RM._instances.pop(self.public_key, None)
        except Exception:
            pass
        if self.provider is not None:
            with contextlib.suppress(Exception):
                self.provider.shutdown()
        self.client = self.manager = self.provider = None
        self.public_key = self.secret_key = None

    def register_atexit(self, callback, *args, **kwargs):
        # The pinned delegate registers just its finalizer. Keep it generation-
        # local; our single close callback controls admission and idempotence.
        if args or kwargs:
            raise RuntimeError('unsupported finalizer')
        self.finalizers.append(callback)
        return callback

    def hook(self, fn):
        def guarded(*args, **kwargs):
            try:
                with self.lock:
                    if not self.admitted() or not self.destination_ok():
                        return None
                    # Native shutdown is reserved for close(), after deactivation.
                    # Session-end callbacks still finalize/flush private traces.
                    if fn.__name__ == 'on_session_finalize' and kwargs.get('reason') == 'shutdown':
                        kwargs = {**kwargs, 'reason': 'guard-session-end'}
                    return fn(*args, **kwargs)
            except Exception:
                return None
        guarded.__guard_delegate__ = self.module
        return guarded

    def close(self):
        with self.lock:
            if not self.active:
                return
            try:
                permitted = self.admitted() and self.destination_ok()
            except Exception:
                permitted = False
            self.active = False
            atexit.unregister(self.exit_callback)
            if self.module is not None:
                if permitted:
                    with contextlib.suppress(Exception):
                        self.module._finalize_all_traces()
                getattr(self.module, '_TRACE_STATE', {}).clear()
                self.module._LANGFUSE_CLIENT = getattr(self.module, '_INIT_FAILED', None)
                self.finalizers.clear()
                sys.modules.pop(self.module.__name__, None)
            self._dispose_client()


def register(ctx):
    """Register once per isolated generation; invalid launch policy is inert."""
    generation = None
    try:
        from hermes_constants import get_hermes_home
        from hermes_cli.profiles import get_active_profile_name
        profile = get_active_profile_name()
        if profile not in {'default', 'homelab-scientist'}:
            return
        generation = _Generation(Path(get_hermes_home()).resolve(), profile)
        if not generation.admitted():
            return
        path = _source_path()
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
            return
        name = __name__ + '._native_' + uuid.uuid4().hex
        spec = importlib.util.spec_from_loader(name, _PinnedLoader(source, str(path)), origin=str(path))
        module = importlib.util.module_from_spec(spec)
        generation.module = module
        sys.modules[name] = module
        spec.loader.exec_module(module)
        module.logger = _Silent()
        module._debug = lambda *args, **kwargs: None
        module._failsafe = _silent_failsafe
        module._capture_mode = lambda: 'metadata'
        module._env = generation.env
        module._start_root_trace = _per_turn_roots(module._start_root_trace)
        module._guard_sdk_constructor = module.Langfuse
        module.Langfuse = generation.construct
        module.atexit = types.SimpleNamespace(register=generation.register_atexit)
        # Native register runs exactly once and only sees the hook-admission proxy.
        proxy = types.SimpleNamespace(register_hook=lambda name, fn: ctx.register_hook(name, generation.hook(fn)))
        ctx.on_unload(generation.close)
        atexit.register(generation.exit_callback)
        module.register(proxy)
    except Exception:
        if generation is not None:
            generation.close()
