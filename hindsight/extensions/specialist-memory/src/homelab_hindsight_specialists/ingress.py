"""Fail-closed ASGI boundary for the fixed specialist REST/MCP read paths."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import json
from time import monotonic
from typing import Any
from hindsight_api.extensions.tenant import AuthenticationError

_ADMITTED: ContextVar[Any] = ContextVar('homelab_specialist_ingress', default=None)
MAX_BODY = 65536
MAX_SESSIONS = 64
SESSION_IDLE_TIMEOUT_SECONDS = 3600


@dataclass
class _Session:
    principal: Any
    last_used: float


class Refused(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused()
        result[key] = value
    return result


def _json(data):
    try:
        value = json.loads(data, object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refused()))
    except (ValueError, RecursionError, UnicodeError):
        raise Refused() from None
    if not isinstance(value, dict):
        raise Refused()
    return value


def _query(arguments):
    if not isinstance(arguments, dict) or 'bank_id' in arguments:
        return False
    query = arguments.get('query')
    return isinstance(query, str) and 0 < len(query) <= 4096


class SpecialistBoundary:
    """Wrap the complete upstream app, outside its HTTP AND MCP middleware.

    Session identifiers are bound to authenticated fixed identities before reuse.
    The finite map is cleared on server restart; unknown sessions fail closed.
    Trusted legacy calls preserve upstream behavior and cannot seed this map.
    """
    def __init__(self, app, tenant):
        self.app, self.tenant = app, tenant
        self.sessions = {}
        self.initializing = 0

    def prune_sessions(self):
        now = monotonic()
        for sid, session in list(self.sessions.items()):
            if now - session.last_used >= SESSION_IDLE_TIMEOUT_SECONDS:
                del self.sessions[sid]
        return now

    async def reject(self, send, status=403):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body': b'{"detail":"Operation not permitted"}'})

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        headers = {}
        for key, value in scope.get('headers', []):
            key = key.lower()
            if key in headers and key in (b'authorization', b'mcp-session-id', b'x-bank-id'):
                if scope['type'] == 'websocket':
                    return await send({'type': 'websocket.close', 'code': 1008})
                return await self.reject(send, 401)
            headers[key] = value
        auth = headers.get(b'authorization')
        # Missing credentials retain upstream health/unauthenticated behavior.
        if auth is None:
            # A GET event stream does not run JSON-RPC message middleware.
            # Never treat an owned session identifier as authentication.
            if headers.get(b'mcp-session-id') in self.sessions:
                if scope['type'] == 'websocket':
                    return await send({'type': 'websocket.close', 'code': 1008})
                return await self.reject(send, 401)
            return await self.app(scope, receive, send)
        try:
            text = auth.decode('ascii')
            key = text[7:].strip() if text.lower().startswith('bearer ') else text.strip()
            principal = self.tenant.identify(key)
        except (AuthenticationError, ValueError, UnicodeError):
            # No credential, exception text, arguments or arbitrary path is emitted.

            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 1008})
            return await self.reject(send, 401)
        if principal is None:
            # Existing clients retain their own sessions, but cannot reuse a
            # session issued here to a new specialist or operator identity.
            if headers.get(b'mcp-session-id') in self.sessions:
                if scope['type'] == 'websocket':
                    return await send({'type': 'websocket.close', 'code': 1008})
                return await self.reject(send)
            return await self.app(scope, receive, send)
        if scope['type'] != 'http':
            return await send({'type': 'websocket.close', 'code': 1008})
        path, method = scope.get('path', ''), scope.get('method')
        try:
            canonical = path.encode('ascii')
        except UnicodeError:
            return await self.reject(send)
        if (scope.get('raw_path', canonical) != canonical or '//' in path
                or scope.get('query_string', b'') or b'x-bank-id' in headers):
            return await self.reject(send)
        bank_root = '/v1/default/banks/' + principal.bank
        mcp = path in ('/mcp/' + principal.bank, '/mcp/' + principal.bank + '/')
        sid = headers.get(b'mcp-session-id')
        self.prune_sessions()
        session = self.sessions.get(sid)
        if sid is not None and (not mcp or session is None or session.principal != principal):
            return await self.reject(send)
        initialize = False
        body = b''
        if mcp and method in ('GET', 'DELETE'):
            if method == 'DELETE' and sid is None:
                return await self.reject(send)
        elif ((method == 'POST' and (mcp or path == bank_root + '/memories/recall'
                                    or (not principal.read_only and path == bank_root + '/memories')))
              or (not principal.read_only and method == 'PUT' and path == bank_root)):
            try:
                async with asyncio.timeout(5):
                    for _ in range(128):
                        message = await receive()
                        if message['type'] != 'http.request':
                            raise Refused()
                        body += message.get('body', b'')
                        if len(body) > MAX_BODY:
                            raise Refused()
                        if not message.get('more_body'):
                            break
                    else:
                        raise Refused()
                data = _json(body)
                if mcp:
                    if set(data) - {'jsonrpc', 'id', 'method', 'params'} or data.get('jsonrpc') != '2.0':
                        raise Refused()
                    operation = data.get('method')
                    if not isinstance(operation, str):
                        raise Refused()
                    initialize = operation == 'initialize'
                    if initialize and sid is not None:
                        raise Refused()
                    if operation == 'tools/call':
                        params = data.get('params')
                        allowed = {'recall'} if principal.read_only else {'recall', 'retain'}
                        if not isinstance(params, dict) or set(params) - {'name', 'arguments', '_meta'}:
                            raise Refused()
                        if not isinstance(params.get('name'), str) or params['name'] not in allowed:
                            raise Refused()
                        args = params.get('arguments', {})
                        if not isinstance(args, dict) or 'bank_id' in args:
                            raise Refused()
                        if params['name'] == 'recall' and not _query(args):
                            raise Refused()
                    elif operation not in ('initialize', 'ping', 'tools/list', 'notifications/initialized', 'notifications/cancelled'):
                        raise Refused()
                elif path.endswith('/memories/recall'):
                    if not _query(data):
                        raise Refused()
                elif 'bank_id' in data:
                    raise Refused()
            except (Refused, TimeoutError):
                return await self.reject(send)
        else:
            return await self.reject(send)

        # Body receipt can yield: recheck expiry/ownership and quota immediately
        # before dispatch/reservation, with no intervening await on admission.
        now = self.prune_sessions()
        if sid is not None and self.sessions.get(sid) is not session:
            return await self.reject(send)
        if initialize and len(self.sessions) + self.initializing >= MAX_SESSIONS:
            return await self.reject(send)
        if session is not None:
            session.last_used = now

        # Replay the bounded body once, then preserve disconnect/cancellation.
        replayed = False
        async def replay():
            nonlocal replayed
            if not replayed and body:
                replayed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        async def checked_send(message):
            if message['type'] == 'http.response.start':
                values = [v for k, v in message.get('headers', []) if k.lower() == b'mcp-session-id']
                if initialize and 200 <= message['status'] < 300 and values:
                    if len(values) != 1 or not 1 <= len(values[0]) <= 128:
                        raise RuntimeError('Invalid MCP session response')
                    existing = self.sessions.get(values[0])
                    if existing is not None and existing.principal != principal:
                        raise RuntimeError('MCP session collision')
                    self.sessions[values[0]] = _Session(principal, monotonic())
                if (mcp and sid is not None and self.sessions.get(sid) is session
                        and (message['status'] == 404
                             or (method == 'DELETE' and 200 <= message['status'] < 300))):
                    self.sessions.pop(sid, None)
            await send(message)

        if mcp:
            # Bind ownership in the SDK transport as well as this finite cache.
            # After cache expiry, legacy callers still cannot reuse a live
            # specialist session through upstream GET/DELETE transport routes.
            from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
            from mcp.server.auth.provider import AccessToken
            scope = dict(scope)
            scope['user'] = AuthenticatedUser(AccessToken(
                token=key, client_id='homelab_' + principal.name,
                subject=principal.schema, scopes=[]))
        token = _ADMITTED.set((self.tenant, principal))
        if initialize:
            self.initializing += 1
        try:
            return await self.app(scope, replay, checked_send)
        finally:
            if initialize:
                self.initializing -= 1
            _ADMITTED.reset(token)


def create_guarded_app(memory, **kwargs):
    """Public upstream factory seam. Never replace or construct a provider here."""
    if kwargs.get('mcp_mount_path', '/mcp') != '/mcp':
        raise ValueError('Only the default mcp_mount_path /mcp is supported')
    from importlib.metadata import version
    from hindsight_api.api import create_app
    from . import SpecialistTenantExtension, SpecialistOperationValidator
    if version('hindsight-api-slim') != '1.2.1':
        raise RuntimeError('Unsupported Hindsight version')
    if version('mcp') != '2.3.0':
        raise RuntimeError('Unsupported MCP SDK version')
    tenant = memory._tenant_extension
    validator = memory._operation_validator
    if not isinstance(tenant, SpecialistTenantExtension) or not isinstance(validator, SpecialistOperationValidator):
        raise RuntimeError('Both specialist extension slots are required')
    if tenant._keys != validator._auth._keys:
        raise RuntimeError('Extension key mappings differ')
    return SpecialistBoundary(create_app(memory, **kwargs), tenant)
