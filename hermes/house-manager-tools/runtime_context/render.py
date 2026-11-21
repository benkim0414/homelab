"""Fail-closed, stdlib-only renderer for the reviewed installed v0.23.2 sources.

No imports from or execution of the input tree. No in-place runtime editing.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

BASE_SHA256 = {
    'gateway/session_policy.py': '22b42f98d6ae57c23a0963530f5aa50852f55fc623dc0c7a77940d7647ab6e09',
    'gateway/session_commands.py': '04d0887612721c979ba254d9492a24632ae934b5afb369182e162543091db628',
    'hermes_cli/plugin_session.py': '4311b653262e9bed2b73cebd23824b83d943c5df99e1aa0ee88d711f8d7efe74',
    'hermes_cli/plugins_context.py': '2984a4def458cb1ac4b6f6406861f4dd905a00e4bb11000f3383ffca9136c25f',
    'gateway/plugin_command_choice.py': 'f3a04b3fac8da831201b7b668652a5dca58befd87b97d3c4f16f9a6262555b77',
}

POLICY_ANCHOR = '\ndef active_policy():\n'
POLICY_HELPER = '''
_COMMAND_LIFETIME = ContextVar('plugin_command_lifetime', default=None)


class _CommandDispatchLease:
    def __init__(self):
        import asyncio
        import threading
        self._lock = threading.Lock()
        self._open, self._claimed = True, False
        try:
            self._loop, self._task = asyncio.get_running_loop(), asyncio.current_task()
        except RuntimeError:
            self._loop, self._task = None, None

    def live(self):
        with self._lock:
            return self._open and self._task is not None

    def claim(self):
        # Admit on the OWNER loop, not a stale copied worker context. A cancel()
        # request is observed even before that task's finally block has run.
        import asyncio
        from concurrent.futures import Future
        if self._loop is None or self._task is None:
            return False
        result = Future()
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        try:
            if running is self._loop:
                self._claim_on_owner(result)
            else:
                self._loop.call_soon_threadsafe(self._claim_on_owner, result)
            return result.result(timeout=5)
        except (RuntimeError, TimeoutError):
            result.cancel()
            return False

    def _claim_on_owner(self, result):
        if not result.set_running_or_notify_cancel():
            return
        # Linearization point before external I/O: cancellation that won first
        # denies. Already-admitted I/O cannot be unsent or automatically retried.
        with self._lock:
            allowed = (self._open and not self._claimed and self._task is not None
                       and not self._task.done() and not self._task.cancelling())
            if allowed:
                self._claimed = True
        result.set_result(bool(allowed))

    def close(self):
        with self._lock:
            self._open = False


@contextmanager
def command_dispatch_scope():
    lease = _CommandDispatchLease()
    token = _COMMAND_LIFETIME.set(lease)
    try:
        yield
    finally:
        # Copied synchronous-worker contexts retain this SAME closed lease.
        lease.close()
        _COMMAND_LIFETIME.reset(token)


def command_dispatch_live():
    lease = _COMMAND_LIFETIME.get()
    return lease is not None and lease.live()


def command_dispatch_cancelled():
    lease = _COMMAND_LIFETIME.get()
    # Preserve existing non-command picker callers lacking a command scope.
    return lease is not None and not lease.live()


def claim_command_dispatch():
    lease = _COMMAND_LIFETIME.get()
    return lease is not None and lease.claim()


@contextmanager
def active_policy_scope(policy):
    """Bind only frozen policy provenance, without resolving model/config/credentials.

    Context-local, inherited by copied executor contexts; restore even on cancellation.
    None explicitly clears an enclosing policy for a command without a local policy.
    """
    token = _ACTIVE_POLICY.set(policy)
    try:
        yield
    finally:
        _ACTIVE_POLICY.reset(token)

'''


LAUNCH_ACCESSOR = '''

def session_launch_source():
    """Downstream public API: coherent frozen interactive launch label, or None.

    Returns provenance only, not the policy, model, config or credentials.
    Presentation surface alone cannot distinguish tool/oneshot from cli.
    """
    import json
    policy = _active_policy()
    if policy is None:
        return None
    allowed = {'cli': 'cli', 'tui': 'tui', 'gui': 'desktop'}
    source = getattr(policy, 'source', None)
    if not isinstance(source, str) or source not in allowed:
        return None
    if getattr(policy, 'platform', None) != allowed[source]:
        return None
    try:
        request = json.loads(policy.request_json)
    except (AttributeError, TypeError, ValueError):
        return None
    return source if isinstance(request, dict) and request.get('source') == source else None


def context_launch_source(manager):
    """Classic interactive CLI is owner-local; gateway uses frozen provenance."""
    return 'cli' if manager._cli_ref is not None else session_launch_source()


def command_is_live():
    """Whether the owning async command is still admitted and running."""
    from gateway.session_policy import command_dispatch_live
    return command_dispatch_live()


def claim_command_dispatch():
    """Admit external I/O once, only before command cancellation/teardown."""
    from gateway.session_policy import claim_command_dispatch as claim
    return claim()
'''

CONTEXT_ACCESSOR = '''    def session_launch_source(self) -> Optional[str]:
        """Downstream API: cli/tui/gui frozen launch label, or None if untrusted.

        This is provenance, not separate human authentication or approval.
        """
        from hermes_cli.plugin_session import context_launch_source
        return context_launch_source(self._manager)

    def command_is_live(self) -> bool:
        """Downstream API: live owning command lease, not just copied provenance."""
        from hermes_cli.plugin_session import command_is_live
        return command_is_live()

    def claim_command_dispatch(self) -> bool:
        """Downstream API: atomically admit one external submission if live."""
        from hermes_cli.plugin_session import claim_command_dispatch
        return claim_command_dispatch()

'''


def _replace_once(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError('reviewed patch anchor is absent or ambiguous')
    return text.replace(before, after, 1)


def render(originals: dict[str, bytes]) -> dict[str, bytes]:
    """Return five patched modules; verify ALL inputs before transforming any."""
    for name, expected in BASE_SHA256.items():
        if name not in originals or hashlib.sha256(originals[name]).hexdigest() != expected:
            raise ValueError(f'upstream SHA256 precondition failed: {name}')
    policy = originals['gateway/session_policy.py'].decode('utf-8')
    commands = originals['gateway/session_commands.py'].decode('utf-8')
    session = originals['hermes_cli/plugin_session.py'].decode('utf-8')
    context = originals['hermes_cli/plugins_context.py'].decode('utf-8')
    choice = originals['gateway/plugin_command_choice.py'].decode('utf-8')
    policy = _replace_once(policy, POLICY_ANCHOR, POLICY_HELPER + POLICY_ANCHOR)
    # Limit replacement to this function; authorization and dispatch remain byte-identical.
    start = commands.index('@contextmanager\ndef _session_workspace(')
    end = commands.index('\n\nasync def execute_command(', start)
    before = commands[start:end]
    after = _replace_once(before,
        'from gateway.session_policy import policy_for_source',
        'from gateway.session_policy import active_policy_scope, command_dispatch_scope, policy_for_source')
    after = _replace_once(after, '    if policy is None:\n        yield\n',
        '    if policy is None:\n        with active_policy_scope(None), command_dispatch_scope():\n            yield\n')
    after = _replace_once(after, '    try:\n        yield\n    finally:',
        '    try:\n        with active_policy_scope(policy), command_dispatch_scope():\n            yield\n    finally:')
    commands = _replace_once(commands, before, after)
    if 'def session_launch_source(' in session or 'def session_launch_source(' in context:
        raise ValueError('public launch accessor already exists')
    session += LAUNCH_ACCESSOR
    context = _replace_once(context, '    def post_message(self, text: str) -> Any:',
                            CONTEXT_ACCESSOR + '    def post_message(self, text: str) -> Any:')
    choice = _replace_once(choice, '    from gateway.session_server_requests import ask_viewer_result',
                          '    from gateway.session_server_requests import ask_viewer_result\n'
                          '    from gateway.session_policy import command_dispatch_cancelled')
    choice = _replace_once(choice, 'timeout=timeout if timeout > 0 else None, qids=["q0"])',
                          'timeout=timeout if timeout > 0 else None, qids=["q0"],\n'
                          '                               cancelled=command_dispatch_cancelled)')
    result = {'gateway/session_policy.py': policy.encode(),
              'gateway/session_commands.py': commands.encode(),
              'hermes_cli/plugin_session.py': session.encode(),
              'hermes_cli/plugins_context.py': context.encode(),
              'gateway/plugin_command_choice.py': choice.encode()}
    for name, data in result.items():
        compile(data, name, 'exec')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output_root.resolve()
    if source == output or source in output.parents or output in source.parents:
        parser.error('input and output trees must be disjoint (no in-place patching)')
    rendered = render({name: (source / name).read_bytes() for name in BASE_SHA256})
    for name, data in rendered.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f'{hashlib.sha256(data).hexdigest()}  {name}')


if __name__ == '__main__':
    main()
