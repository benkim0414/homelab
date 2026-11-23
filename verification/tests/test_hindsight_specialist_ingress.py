"""Synthetic transport fixtures. No database, credentials or provider requests."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'hindsight/extensions/specialist-memory/src'))
AVAILABLE = importlib.util.find_spec('hindsight_api') is not None


@unittest.skipUnless(AVAILABLE, 'requires isolated real Hindsight 1.2.1 environment')
class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        import homelab_hindsight_specialists as policy
        from homelab_hindsight_specialists.ingress import SpecialistBoundary
        self.policy = policy
        self.config = {'api_key': 'fixture-legacy', 'learning_coach_api_key': 'fixture-learning',
                       'career_advisor_api_key': 'fixture-career',
                       'operator_learning_coach_api_key': 'fixture-learning-operator',
                       'operator_career_advisor_api_key': 'fixture-career-operator'}
        self.patch = patch.object(policy, 'get_config', return_value=SimpleNamespace(database_schema='public'))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tenant = policy.SpecialistTenantExtension(self.config)
        self.calls = []
        async def downstream(scope, receive, send):
            from hindsight_api.models import RequestContext
            headers = dict(scope['headers'])
            text = headers.get(b'authorization', b'').decode()
            key = text[7:].strip() if text.lower().startswith('bearer ') else text.strip()
            ctx = RequestContext(api_key=key)
            tenant = await self.tenant.authenticate(ctx)
            self.calls.append((scope['method'], scope['path'], tenant.schema_name))
            response_headers = [(b'content-type', b'application/json')]
            if scope['path'].startswith('/mcp') and scope['method'] == 'POST':
                body = b''
                while True:
                    msg = await receive(); body += msg.get('body', b'')
                    if not msg.get('more_body'): break
                if json.loads(body).get('method') == 'initialize':
                    response_headers.append((b'mcp-session-id', b'fixture-session'))
            await send({'type': 'http.response.start', 'status': 200, 'headers': response_headers})
            await send({'type': 'http.response.body', 'body': b'{"fixture":true}'})
        self.boundary = SpecialistBoundary(downstream, self.tenant)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.boundary), base_url='http://fixture.invalid')
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {'Authorization': 'Bearer fixture-learning'}

    async def test_read_reaches_downstream_in_own_schema(self):
        r = await self.client.post('/v1/default/banks/infinite-recursion/memories/recall', headers=self.headers, json={'query':'fixture'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.calls, [('POST','/v1/default/banks/infinite-recursion/memories/recall','user_learning_coach')])

    async def test_other_bank_and_all_mutation_methods_never_dispatch(self):
        for path in ('/v1/default/banks/next-level/memories/recall', '/v1/default/banks/infinite-recursion/memories',
                     '/v1/default/banks/infinite-recursion/clone', '/v1/default/banks/infinite-recursion/files/retain',
                     '/v1/default/banks/infinite-recursion/future-endpoint', '/admin', '/v1/default/banks'):
            for method in ('GET','POST','PUT','PATCH','DELETE'):
                r = await self.client.request(method, path, headers=self.headers, json={'query':'fixture'})
                self.assertEqual(r.status_code,403,(method,path,r.text))
        self.assertEqual(self.calls,[])

    async def test_specialist_without_boundary_is_denied(self):
        from hindsight_api.models import RequestContext
        from hindsight_api.extensions.tenant import AuthenticationError
        with self.assertRaises(AuthenticationError):
            await self.tenant.authenticate(RequestContext(api_key='fixture-learning'))

    async def test_legacy_schema_and_authority_preserved(self):
        r = await self.client.delete('/arbitrary-legacy-path', headers={'Authorization':'Bearer fixture-legacy'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][2],'public')

    async def test_legacy_header_case_and_whitespace_match_upstream_http(self):
        r = await self.client.get('/arbitrary-legacy-path', headers={'Authorization':'bearer  fixture-legacy '})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][2],'public')

    async def test_career_read_uses_own_schema(self):
        r = await self.client.post('/v1/default/banks/next-level/memories/recall', headers={'Authorization':'Bearer fixture-career'}, json={'query':'fixture'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][2],'user_career_advisor')

    async def test_duplicate_credentials_and_oversized_body_never_dispatch(self):
        headers = [('Authorization','Bearer fixture-learning'),('authorization','Bearer fixture-legacy')]
        r = await self.client.post('/mcp/infinite-recursion', headers=headers, json={'jsonrpc':'2.0','method':'initialize'})
        self.assertEqual(r.status_code,401)
        r = await self.client.post('/v1/default/banks/infinite-recursion/memories/recall', headers=self.headers, content=b' ' * 65537)
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.calls,[])

    async def test_session_capacity_counts_pending_initializations(self):
        self.boundary.initializing = 64
        r = await self.client.post('/mcp/infinite-recursion', headers=self.headers,json={'jsonrpc':'2.0','id':1,'method':'initialize'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.calls,[])

    async def test_idle_session_expiry_denies_reuse_and_reclaims_capacity(self):
        path = '/mcp/infinite-recursion'
        init = {'jsonrpc':'2.0', 'id':1, 'method':'initialize'}
        with patch('homelab_hindsight_specialists.ingress.monotonic', create=True, return_value=100) as clock:
            with patch('homelab_hindsight_specialists.ingress.MAX_SESSIONS', 1):
                self.assertEqual((await self.client.post(path, headers=self.headers, json=init)).status_code, 200)
                self.assertEqual((await self.client.post(path, headers=self.headers, json=init)).status_code, 403)
                before = len(self.calls)
                clock.return_value = 3700
                h = {**self.headers, 'Mcp-Session-Id':'fixture-session'}
                self.assertEqual((await self.client.get(path, headers=h)).status_code, 403)
                self.assertEqual(len(self.calls), before)
                self.assertEqual(self.boundary.sessions, {})
                self.assertEqual((await self.client.post(path, headers=self.headers, json=init)).status_code, 200)
                self.assertEqual(self.boundary.initializing, 0)

    async def test_same_role_upstream_404_releases_session_without_retry(self):
        path = '/mcp/infinite-recursion'
        await self.client.post(path, headers=self.headers, json={'jsonrpc':'2.0','id':1,'method':'initialize'})
        async def session_not_found(scope, receive, send):
            self.calls.append(('session not found',))
            await send({'type':'http.response.start', 'status':404, 'headers':[]})
            await send({'type':'http.response.body', 'body':b'Session not found'})
        self.boundary.app = session_not_found
        before = len(self.calls)
        for key in ('fixture-career', 'fixture-learning-operator', 'fixture-legacy'):
            r = await self.client.get(path, headers={'Authorization':'Bearer '+key, 'Mcp-Session-Id':'fixture-session'})
            self.assertEqual(r.status_code, 403)
            self.assertIn(b'fixture-session', self.boundary.sessions)
        self.assertEqual(len(self.calls), before)
        h = {**self.headers, 'Mcp-Session-Id':'fixture-session'}
        self.assertEqual((await self.client.get(path, headers=h)).status_code, 404)
        self.assertEqual(self.boundary.sessions, {})
        self.assertEqual((await self.client.get(path, headers=h)).status_code, 403)
        self.assertEqual(len(self.calls), before + 1)

    async def test_initialize_prunes_abandoned_session_before_quota_check(self):
        path = '/mcp/infinite-recursion'
        body = {'jsonrpc':'2.0','id':1,'method':'initialize'}
        with patch('homelab_hindsight_specialists.ingress.monotonic', return_value=100) as clock:
            with patch('homelab_hindsight_specialists.ingress.MAX_SESSIONS', 1):
                await self.client.post(path, headers=self.headers, json=body)
                clock.return_value = 3700
                r = await self.client.post('/mcp/next-level', headers={'Authorization':'Bearer fixture-career'}, json=body)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(len(self.boundary.sessions), 1)
                self.assertEqual(self.calls[-1][2], 'user_career_advisor')
                r = await self.client.get(path, headers={**self.headers, 'Mcp-Session-Id':'fixture-session'})
                self.assertEqual(r.status_code, 403)

    async def test_only_admitted_same_role_requests_refresh_idle_deadline(self):
        path = '/mcp/infinite-recursion'
        with patch('homelab_hindsight_specialists.ingress.monotonic', return_value=100) as clock:
            await self.client.post(path, headers=self.headers, json={'jsonrpc':'2.0','id':1,'method':'initialize'})
            h = {**self.headers, 'Mcp-Session-Id':'fixture-session'}
            clock.return_value = 3600
            self.assertEqual((await self.client.get(path, headers=h)).status_code, 200)
            clock.return_value = 3700
            self.assertEqual((await self.client.get(path, headers=h)).status_code, 200)
            before = len(self.calls)
            clock.return_value = 7200
            for key in ('fixture-learning-operator', 'fixture-legacy', 'fixture-career'):
                r = await self.client.get(path, headers={'Authorization':'Bearer '+key, 'Mcp-Session-Id':'fixture-session'})
                self.assertEqual(r.status_code, 403)
            r = await self.client.post(path, headers=h, json={'jsonrpc':'2.0','method':'future-method'})
            self.assertEqual(r.status_code, 403)
            clock.return_value = 7300
            self.assertEqual((await self.client.get(path, headers=h)).status_code, 403)
            self.assertEqual(len(self.calls), before)
            self.assertEqual(self.boundary.sessions, {})

    async def test_session_expiring_during_body_receipt_never_dispatches(self):
        path = '/mcp/infinite-recursion'
        with patch('homelab_hindsight_specialists.ingress.monotonic', return_value=100) as clock:
            await self.client.post(path, headers=self.headers, json={'jsonrpc':'2.0','id':1,'method':'initialize'})
            before = len(self.calls)
            async def body():
                clock.return_value = 3700
                yield b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
            r = await self.client.post(path, headers={**self.headers,'Mcp-Session-Id':'fixture-session'}, content=body())
            self.assertEqual(r.status_code, 403)
            self.assertEqual(len(self.calls), before)
            self.assertEqual(self.boundary.sessions, {})

    async def test_pending_initialization_cancellation_preserves_shared_quota(self):
        import asyncio
        path = '/mcp/infinite-recursion'
        init = {'jsonrpc':'2.0','id':1,'method':'initialize'}
        for send_headers in (False, True):
            with self.subTest(send_headers=send_headers):
                self.boundary.sessions.clear()
                started = [asyncio.Event(), asyncio.Event()]
                release = asyncio.Event()
                opened = []
                async def pending(scope, receive, send):
                    index = len(opened)
                    opened.append(index)
                    if send_headers:
                        await send({'type':'http.response.start','status':200,
                                    'headers':[(b'mcp-session-id', ('fixture-'+str(index)).encode())]})
                    started[index].set()
                    await release.wait()
                    if not send_headers:
                        await send({'type':'http.response.start','status':200,
                                    'headers':[(b'mcp-session-id', ('fixture-'+str(index)).encode())]})
                    await send({'type':'http.response.body','body':b'{}'})
                self.boundary.app = pending
                with patch('homelab_hindsight_specialists.ingress.monotonic', return_value=100) as clock:
                    with patch('homelab_hindsight_specialists.ingress.MAX_SESSIONS', 2):
                        # At headers, an initialization may occupy both a live
                        # entry and its still-open reservation (conservative).
                        first = asyncio.create_task(self.client.post(path, headers=self.headers, json=init))
                        tasks = [first]
                        try:
                            await asyncio.wait_for(started[0].wait(), 2)
                            if not send_headers:
                                second = asyncio.create_task(self.client.post('/mcp/next-level', headers={'Authorization':'Bearer fixture-career'}, json=init))
                                tasks.append(second)
                                await asyncio.wait_for(started[1].wait(), 2)
                            self.assertEqual(self.boundary.initializing, len(tasks))
                            r = await self.client.post(path, headers=self.headers, json=init)
                            self.assertEqual(r.status_code, 403)
                            first.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await first
                            self.assertEqual(self.boundary.initializing, len(tasks) - 1)
                            release.set()
                            if len(tasks) == 2:
                                self.assertEqual((await tasks[1]).status_code, 200)
                            self.assertEqual(self.boundary.initializing, 0)
                            self.assertEqual(len(self.boundary.sessions), 1)
                            clock.return_value = 3700
                            r = await self.client.get(path, headers={**self.headers,'Mcp-Session-Id':'unknown'})
                            self.assertEqual(r.status_code, 403)
                            self.assertEqual(self.boundary.sessions, {})
                        finally:
                            for task in tasks:
                                task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_failed_delete_and_nonterminal_errors_keep_binding(self):
        path = '/mcp/infinite-recursion'
        await self.client.post(path, headers=self.headers, json={'jsonrpc':'2.0','id':1,'method':'initialize'})
        h = {**self.headers, 'Mcp-Session-Id':'fixture-session'}
        status = 500
        async def respond(scope, receive, send):
            await send({'type':'http.response.start','status':status,'headers':[]})
            await send({'type':'http.response.body','body':b'fixture'})
        self.boundary.app = respond
        for status in (400, 401, 403, 500):
            self.assertEqual((await self.client.delete(path, headers=h)).status_code, status)
            self.assertIn(b'fixture-session', self.boundary.sessions)
        status = 204
        self.assertEqual((await self.client.delete(path, headers=h)).status_code, 204)
        self.assertEqual(self.boundary.sessions, {})

    async def test_operator_save_is_separate_from_read_key(self):
        path='/v1/default/banks/infinite-recursion/memories'
        self.assertEqual((await self.client.post(path, headers=self.headers, json={'items':[]})).status_code,403)
        r=await self.client.post(path, headers={'Authorization':'Bearer fixture-learning-operator'}, json={'items':[]})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][2],'user_learning_coach')
        r=await self.client.post('/v1/default/banks/next-level/memories',headers={'Authorization':'Bearer fixture-learning-operator'},json={'items':[]})
        self.assertEqual(r.status_code,403)

    async def test_operator_creation_is_own_bank_only_and_body_bounded(self):
        path = '/v1/default/banks/infinite-recursion'
        headers = {'Authorization':'Bearer fixture-learning-operator'}
        r = await self.client.put(path,headers=headers,json={})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][2],'user_learning_coach')
        self.calls.clear()
        for target, auth, body in ((path,self.headers,b'{}'), (path,headers,b'not-json'),
                                   (path,headers,b' ' * 65537),('/v1/default/banks/next-level',headers,b'{}')):
            r = await self.client.put(target,headers=auth,content=body)
            self.assertEqual(r.status_code,403)
        self.assertEqual(self.calls,[])

    async def test_operator_document_readback_is_exact_and_own_bank_only(self):
        path = '/v1/default/banks/infinite-recursion/documents/acceptance-learning-001'
        operator = {'Authorization':'Bearer fixture-learning-operator'}
        r = await self.client.get(path,headers=operator)
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][2],'user_learning_coach')
        self.calls.clear()
        for target, headers in ((path,self.headers),
                                (path,{'Authorization':'Bearer fixture-career-operator'}),
                                (path.replace('infinite-recursion','next-level'),operator),
                                (path+'/extra',operator),
                                (path+'?bank_id=next-level',operator)):
            r = await self.client.get(target,headers=headers)
            self.assertEqual(r.status_code,403)
        self.assertEqual(self.calls,[])

    async def test_factory_rejects_mismatched_keys_and_other_server_versions(self):
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        config = {**self.config,'learning_coach_api_key':'different-synthetic-key'}
        engine._operation_validator = self.policy.SpecialistOperationValidator(config)
        with self.assertRaisesRegex(RuntimeError,'mappings differ'):
            create_guarded_app(engine,initialize_memory=False)
        with patch('importlib.metadata.version',return_value='999.0'):
            with self.assertRaisesRegex(RuntimeError,'Unsupported'):
                create_guarded_app(engine,initialize_memory=False)
        with patch('importlib.metadata.version',side_effect=lambda name: '1.2.1' if name == 'hindsight-api-slim' else '999.0'):
            with self.assertRaisesRegex(RuntimeError,'Unsupported MCP SDK'):
                create_guarded_app(engine,initialize_memory=False)

    async def test_factory_rejects_nondefault_mcp_mount_path(self):
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        for path in ('/custom', '/mcp/', '', None):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, 'mcp_mount_path'):
                    create_guarded_app(engine, initialize_memory=False, mcp_mount_path=path)

    async def test_optional_operator_keys_fail_closed_when_partial_or_duplicated(self):
        for overrides in ({'operator_career_advisor_api_key':None},
                          {'operator_career_advisor_api_key':'fixture-learning'},
                          {'operator_career_advisor_api_key':'fixture-learning-operator'}):
            with self.assertRaises(ValueError):
                self.policy.SpecialistTenantExtension({**self.config,**overrides})
        config = dict(self.config)
        del config['operator_career_advisor_api_key']
        with self.assertRaises(ValueError):
            self.policy.SpecialistTenantExtension(config)

    async def test_mcp_initialize_recall_and_session_reuse_binding(self):
        path='/mcp/infinite-recursion'
        init={'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}
        r=await self.client.post(path, headers=self.headers,json=init)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['mcp-session-id'],'fixture-session')
        h={**self.headers,'Mcp-Session-Id':'fixture-session'}
        recall={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'recall','arguments':{'query':'fixture'}}}
        self.assertEqual((await self.client.post(path,headers=h,json=recall)).status_code,200)
        before=len(self.calls)
        for name in ('retain','reflect','future-tool'):
            body={**recall,'params':{'name':name,'arguments':{'query':'fixture'}}}
            self.assertEqual((await self.client.post(path,headers=h,json=body)).status_code,403)
        self.assertEqual((await self.client.post('/mcp/next-level',headers={'Authorization':'Bearer fixture-career','Mcp-Session-Id':'fixture-session'},json=recall)).status_code,403)
        self.assertEqual((await self.client.post(path,headers={**h,'Mcp-Session-Id':'legacy-unknown'},json=recall)).status_code,403)
        self.assertEqual(len(self.calls),before)

    async def test_malformed_mcp_names_never_dispatch(self):
        for name in ([], {}, 7, True, None):
            for field in ('tool', 'method'):
                with self.subTest(name=name, field=field):
                    body = {'jsonrpc':'2.0', 'id':1, 'method':'tools/call',
                            'params':{'name':name, 'arguments':{'query':'fixture'}}}
                    if field == 'method':
                        body['method'] = name
                    r = await self.client.post('/mcp/infinite-recursion', headers=self.headers, json=body)
                    self.assertEqual(r.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_operator_and_legacy_cannot_reuse_specialist_session(self):
        path = '/mcp/infinite-recursion'
        await self.client.post(path,headers=self.headers,json={'jsonrpc':'2.0','id':1,'method':'initialize'})
        before = len(self.calls)
        for key in ('fixture-legacy','fixture-learning-operator'):
            headers = {'Authorization':'Bearer '+key,'Mcp-Session-Id':'fixture-session'}
            r = await self.client.post(path,headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list'})
            self.assertEqual(r.status_code,403)
        self.assertEqual(len(self.calls),before)
        r = await self.client.delete(path,headers={**self.headers,'Mcp-Session-Id':'fixture-session'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.boundary.sessions,{})

    async def test_owned_session_requires_credentials_even_for_get_stream(self):
        await self.client.post('/mcp/infinite-recursion',headers=self.headers,json={'jsonrpc':'2.0','id':1,'method':'initialize'})
        before = len(self.calls)
        async def session_stream(scope, receive, send):
            self.calls.append(('unauthenticated session stream',))
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'fixture event'})
        self.boundary.app = session_stream
        r = await self.client.get('/mcp/infinite-recursion',headers={'Mcp-Session-Id':'fixture-session'})
        self.assertEqual(r.status_code,401)
        self.assertEqual(len(self.calls),before)

    async def test_malformed_raw_targets_and_bodies_denied(self):
        for path in ('/v1/default/banks/infinite%2Drecursion/memories/recall','/v1/default/banks/infinite-recursion/memories/recall?bank_id=next-level'):
            self.assertEqual((await self.client.post(path,headers=self.headers,json={'query':'fixture'})).status_code,403)
        for body in ('{"query":"a","query":"b"}', '[]', '{"query":NaN}', '{"query":"x","bank_id":"next-level"}'):
            r=await self.client.post('/v1/default/banks/infinite-recursion/memories/recall',headers=self.headers,content=body)
            self.assertIn(r.status_code,(400,403))
        self.assertEqual(self.calls,[])


    def engine_fixture(self):
        from hindsight_api.engine.memory_engine import MemoryEngine
        from hindsight_api.engine.response_models import RecallResult
        from hindsight_api.engine.audit import AuditLogger
        from unittest.mock import AsyncMock
        engine = object.__new__(MemoryEngine)
        engine._tenant_extension = self.tenant
        engine._operation_validator = self.policy.SpecialistOperationValidator(self.config)
        engine._audit_logger = AuditLogger(lambda: self.fail('fixture audit database must not be reached'), lambda: 'public', False, [])
        engine._config_resolver = SimpleNamespace(get_bank_config=AsyncMock(return_value={}))
        engine._get_backend = AsyncMock(side_effect=AssertionError('fixture database must not be reached'))
        engine.resolve_bank_alias = AsyncMock(side_effect=lambda bank_id, **kw: bank_id)
        self.reads = []
        async def recall(bank_id, query, request_context, **kwargs):
            schema = await engine._authenticate_tenant(request_context)
            self.reads.append((bank_id, schema))
            return RecallResult(results=[])  # Explicit fixture, not a production recall.
        engine.recall_async = recall
        return engine

    def attachment_backend_fixture(self, engine):
        """Synthetic store/backend only; keep native document/profile/attachment code."""
        from contextlib import asynccontextmanager
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock
        conn = SimpleNamespace(fetch=AsyncMock(return_value=[]))
        @asynccontextmanager
        async def acquire():
            yield conn
        backend = SimpleNamespace(_wraps_backend=True, acquire=acquire, ops=object())
        engine._backend = backend
        engine._get_backend = AsyncMock(return_value=backend)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        document = dict(id='fixture-doc', bank_id='infinite-recursion',
                        original_text='synthetic document', content_hash='fixture-hash',
                        tags=[], retain_params=None, unit_count=0, world_count=0,
                        experience_count=0, observation_count=0, created_at=now, updated_at=now)
        store = SimpleNamespace(get_document_with_counts=AsyncMock(return_value=document))
        self.profile_rows = AsyncMock(return_value=dict(
            name='synthetic bank', disposition=dict(skepticism=3, literalism=3, empathy=3), mission='fixture'))
        for target, value in (
            ('hindsight_api.engine.memories.get_memories', lambda: store),
            ('hindsight_api.engine.memory_engine.bank_utils.get_bank_profile_if_exists', self.profile_rows),
        ):
            fixture = patch(target, value)
            fixture.start()
            self.addCleanup(fixture.stop)
        return conn

    async def test_native_document_handler_internal_profile_dependency(self):
        import httpx
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        conn = self.attachment_backend_fixture(engine)
        app = create_guarded_app(engine, initialize_memory=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture.invalid') as client:
            response = await client.get('/v1/default/banks/infinite-recursion/documents/fixture-doc',
                                        headers={'Authorization':'Bearer fixture-learning-operator'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['original_text'], 'synthetic document')
        self.profile_rows.assert_awaited_once()
        conn.fetch.assert_awaited_once()

    async def test_profile_dependency_scope_is_bound_and_revoked(self):
        import contextvars
        from hindsight_api.models import RequestContext
        from hindsight_api.extensions.operation_validator import BankReadContext
        from homelab_hindsight_specialists.ingress import _ADMITTED
        validator = self.policy.SpecialistOperationValidator(self.config)
        snapshots = []
        async def check(key, bank='infinite-recursion', operation='get_bank_profile', policy=validator):
            ctx = RequestContext(api_key=key, internal=True, tenant_id='forged', api_key_id='forged')
            return await policy.validate_bank_read(BankReadContext(bank, operation, ctx))
        async def downstream(scope, receive, send):
            admitted = _ADMITTED.get()
            snapshots.append(contextvars.copy_context())
            key = dict(scope['headers'])[b'authorization'].decode().removeprefix('Bearer ')
            is_content = scope['path'].endswith('/memories/recall') or '/documents/' in scope['path']
            self.assertEqual((await check(key)).allowed, is_content)
            for operation in ('get_bank_config', 'get_bank_stats', 'future_read'):
                self.assertFalse((await check(key, operation=operation)).allowed)
            self.assertFalse((await check(key, bank='next-level')).allowed)
            other_key = 'fixture-learning-operator' if key == 'fixture-learning' else 'fixture-learning'
            self.assertFalse((await check(other_key)).allowed)
            mismatched = self.policy.SpecialistOperationValidator({**self.config, 'career_advisor_api_key':'other-map'})
            self.assertFalse((await check(key, policy=mismatched)).allowed)
            for hook in ('validate_retain', 'validate_bank_write'):
                ctx = SimpleNamespace(bank_id='infinite-recursion', request_context=RequestContext(api_key='fixture-learning'))
                self.assertFalse((await getattr(validator, hook)(ctx)).allowed)
            self.assertIs(_ADMITTED.get(), admitted)
            await send({'type':'http.response.start', 'status':200, 'headers':[]})
            await send({'type':'http.response.body', 'body':b'{}'})
        self.boundary.app = downstream
        for key in ('fixture-learning', 'fixture-learning-operator'):
            headers = {'Authorization':'Bearer '+key}
            response = await self.client.post('/v1/default/banks/infinite-recursion/memories/recall', headers=headers, json={'query':'fixture'})
            self.assertEqual(response.status_code, 200)
        headers = {'Authorization':'Bearer fixture-learning-operator'}
        for method, suffix in (('GET','/documents/fixture-doc'), ('PUT',''), ('POST','/memories')):
            response = await self.client.request(method, '/v1/default/banks/infinite-recursion'+suffix, headers=headers, json={})
            self.assertEqual(response.status_code, 200)
        for snapshot in snapshots:
            # Run in a task created under a captured request context, proving
            # lifetime revocation even when a downstream task copied the value.
            import asyncio
            result = await snapshot.run(asyncio.create_task, check('fixture-learning-operator'))
            self.assertFalse(result.allowed)
        self.assertIsNone(_ADMITTED.get())
        for key in ('fixture-learning', 'fixture-learning-operator'):
            self.assertFalse((await check(key)).allowed)
        self.assertNotIn('get_bank_profile', self.policy.SAFE_BANK_READS)

    async def test_dependency_scope_revoked_on_exception_and_cancellation(self):
        import asyncio
        import contextvars
        from hindsight_api.models import RequestContext
        from hindsight_api.extensions.operation_validator import BankReadContext
        from homelab_hindsight_specialists.ingress import _ADMITTED
        validator = self.policy.SpecialistOperationValidator(self.config)
        snapshots = []
        started = asyncio.Event()
        async def downstream(scope, receive, send):
            snapshots.append(contextvars.copy_context())
            ctx = BankReadContext('infinite-recursion', 'get_bank_profile', RequestContext(api_key='fixture-learning'))
            self.assertTrue((await validator.validate_bank_read(ctx)).allowed)
            started.set()
            if scope['path'].endswith('/memories/recall'):
                await asyncio.Event().wait()
            raise RuntimeError('synthetic handler failure')
        self.boundary.app = downstream
        task = asyncio.create_task(self.client.post('/v1/default/banks/infinite-recursion/memories/recall',
                                                    headers=self.headers, json={'query':'fixture'}))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        # Same identity, different request: exception cleanup also revokes.
        async def failed(scope, receive, send):
            snapshots.append(contextvars.copy_context())
            raise RuntimeError('synthetic handler failure')
        self.boundary.app = failed
        with self.assertRaisesRegex(RuntimeError, 'synthetic handler failure'):
            await self.client.post('/v1/default/banks/infinite-recursion/memories/recall',
                                   headers=self.headers, json={'query':'fixture'})
        self.assertIsNone(_ADMITTED.get())
        for snapshot in snapshots:
            ctx = BankReadContext('infinite-recursion', 'get_bank_profile', RequestContext(api_key='fixture-learning'))
            result = await snapshot.run(asyncio.create_task, validator.validate_bank_read(ctx))
            self.assertFalse(result.allowed)

    async def test_direct_profile_config_and_cross_bank_reads_never_dispatch(self):
        from hindsight_api.models import RequestContext
        from hindsight_api.extensions.operation_validator import BankReadContext
        validator = self.policy.SpecialistOperationValidator(self.config)
        for key in ('fixture-learning', 'fixture-learning-operator', 'fixture-career', 'fixture-career-operator'):
            headers = {'Authorization':'Bearer '+key}
            own_bank = self.tenant.identify(key).bank
            for suffix in ('', '/profile', '/config', '/stats', '/audit-logs'):
                response = await self.client.get('/v1/default/banks/'+own_bank+suffix, headers=headers)
                self.assertEqual(response.status_code, 403)
            for bank in (own_bank, 'reserve-bank'):
                result = await validator.validate_bank_read(BankReadContext(
                    bank, 'get_bank_profile', RequestContext(api_key=key, internal=True, mcp_authenticated=True)))
                self.assertFalse(result.allowed)
            other = 'next-level' if own_bank == 'infinite-recursion' else 'infinite-recursion'
            response = await self.client.get('/v1/default/banks/'+other+'/documents/fixture-doc', headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_native_http_recall_can_use_attachment_profile_dependency(self):
        import httpx
        from hindsight_api.engine.response_models import RecallResult
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        conn = self.attachment_backend_fixture(engine)
        completed = []
        async def recall(bank_id, query, request_context, **kwargs):
            await engine._authenticate_tenant(request_context)
            await engine.attachments_for_documents(bank_id, ['fixture-doc'], request_context)
            completed.append(bank_id)
            return RecallResult(results=[])
        engine.recall_async = recall
        app = create_guarded_app(engine, initialize_memory=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture.invalid') as client:
            response = await client.post('/v1/default/banks/infinite-recursion/memories/recall', headers=self.headers, json={'query':'fixture'})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(completed, ['infinite-recursion'])
        self.profile_rows.assert_awaited_once()
        conn.fetch.assert_awaited_once()

    async def test_native_stateful_mcp_recall_propagates_per_request_dependency_scope(self):
        import asyncio
        import contextvars
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from hindsight_api.engine.response_models import RecallResult
        from hindsight_api.extensions.operation_validator import BankReadContext
        from hindsight_api.models import RequestContext
        from homelab_hindsight_specialists.ingress import create_guarded_app, _ADMITTED
        engine = self.engine_fixture()
        conn = self.attachment_backend_fixture(engine)
        completed, scopes, snapshots = [], [], []
        async def recall(bank_id, query, request_context, **kwargs):
            schema = await engine._authenticate_tenant(request_context)
            admission = _ADMITTED.get()
            self.assertEqual(admission[1], self.tenant.identify(request_context.api_key))
            scopes.append(admission[2])
            snapshots.append(contextvars.copy_context())
            await engine.attachments_for_documents(bank_id, ['fixture-doc'], request_context)
            cross = await engine._operation_validator.validate_bank_read(BankReadContext('next-level', 'get_bank_profile', request_context))
            self.assertFalse(cross.allowed)
            completed.append((bank_id, schema))
            return RecallResult(results=[])
        engine.recall_async = recall
        app = create_guarded_app(engine, http_api_enabled=False, mcp_api_enabled=True, initialize_memory=False)
        async with asyncio.timeout(20):
            async with app.app.router.lifespan_context(app.app):
                for key in ('fixture-learning', 'fixture-learning-operator'):
                    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), headers={'Authorization':'Bearer '+key}) as client:
                        async with streamable_http_client('http://fixture.invalid/mcp/infinite-recursion', http_client=client) as streams:
                            async with ClientSession(streams[0], streams[1]) as session:
                                await session.initialize()
                                # Initialization/listing must not grant the dependency;
                                # two recalls must carry separate request admissions.
                                await session.list_tools()
                                for _ in range(2):
                                    result = await session.call_tool('recall', {'query':'fixture'})
                                    self.assertFalse(result.is_error)
                                sid = next(s for s, v in app.sessions.items() if v.principal == self.tenant.identify(key)).decode()
                                for tool in ('get_bank', 'update_bank'):
                                    response = await client.post('http://fixture.invalid/mcp/infinite-recursion', headers={'Mcp-Session-Id':sid},
                                        json={'jsonrpc':'2.0','id':999,'method':'tools/call','params':{'name':tool,'arguments':{}}})
                                    self.assertEqual(response.status_code, 403)
        self.assertEqual(completed, [('infinite-recursion','user_learning_coach')] * 4)
        self.assertEqual(len({id(scope) for scope in scopes}), 4)
        self.assertTrue(all(not scope.active for scope in scopes))
        self.assertEqual(self.profile_rows.await_count, 4)
        self.assertEqual(conn.fetch.await_count, 4)
        self.assertIsNone(_ADMITTED.get())
        for snapshot in snapshots:
            ctx = BankReadContext('infinite-recursion', 'get_bank_profile', RequestContext(api_key='fixture-learning'))
            result = await snapshot.run(asyncio.create_task, engine._operation_validator.validate_bank_read(ctx))
            self.assertFalse(result.allowed)

    async def test_real_upstream_http_factory_permits_read_and_refuses_write(self):
        import httpx
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        app = create_guarded_app(engine, initialize_memory=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture.invalid') as client:
            r = await client.post('/v1/default/banks/infinite-recursion/memories/recall', headers=self.headers, json={'query':'fixture'})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(self.reads, [('infinite-recursion','user_learning_coach')])
            for method, suffix in (('POST','/memories'), ('DELETE',''), ('POST','/document-transfer/export')):
                r = await client.request(method, '/v1/default/banks/infinite-recursion'+suffix, headers=self.headers, json={})
                self.assertEqual(r.status_code,403)
        engine._get_backend.assert_not_called()

    async def test_real_mcp_legacy_client_keeps_public_schema(self):
        import asyncio
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        app = create_guarded_app(engine, http_api_enabled=False, mcp_api_enabled=True, initialize_memory=False)
        async with asyncio.timeout(20):
            async with app.app.router.lifespan_context(app.app):
                async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                             headers={'Authorization':'Bearer fixture-legacy'}) as client:
                    async with streamable_http_client('http://fixture.invalid/mcp/legacy-fixture-bank', http_client=client) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            result = await session.call_tool('recall', {'query':'fixture'})
                            self.assertFalse(result.is_error)
        self.assertEqual(self.reads,[('legacy-fixture-bank','public')])
        self.assertEqual(app.sessions,{})
        engine._get_backend.assert_not_called()

    async def test_real_mcp_sdk_and_upstream_server_read(self):
        import asyncio
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from homelab_hindsight_specialists.ingress import create_guarded_app
        engine = self.engine_fixture()
        app = create_guarded_app(engine, http_api_enabled=False, mcp_api_enabled=True, initialize_memory=False)
        async with asyncio.timeout(20):
            async with app.app.router.lifespan_context(app.app):
                async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), headers=self.headers) as client:
                    async with streamable_http_client('http://fixture.invalid/mcp/infinite-recursion', http_client=client) as streams:
                        async with ClientSession(streams[0], streams[1]) as session:
                            await session.initialize()
                            tools = await session.list_tools()
                            self.assertEqual([t.name for t in tools.tools], ['recall'])
                            result = await session.call_tool('recall', {'query':'fixture'})
                            self.assertFalse(result.is_error)
                            session_id = next(iter(app.sessions)).decode()
                            forbidden = {'jsonrpc':'2.0','id':999,'method':'tools/call',
                                         'params':{'name':'retain','arguments':{'content':'synthetic fixture'}}}
                            response = await client.post('http://fixture.invalid/mcp/infinite-recursion',
                                                         headers={'Mcp-Session-Id':session_id}, json=forbidden)
                            self.assertEqual(response.status_code,403)
                            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as anonymous:
                                response = await anonymous.get('http://fixture.invalid/mcp/infinite-recursion',
                                                               headers={'Mcp-Session-Id':session_id})
                                self.assertEqual(response.status_code,401)
                                # Simulate boundary idle pruning while native
                                # session state still exists. Ownership must
                                # survive without an unbounded tombstone map.
                                app.sessions.clear()
                                response = await anonymous.delete('http://fixture.invalid/mcp/infinite-recursion',
                                                                  headers={'Mcp-Session-Id':session_id})
                                self.assertEqual(response.status_code,401)
                                response = await anonymous.delete('http://fixture.invalid/mcp/infinite-recursion',
                                                                  headers={'Mcp-Session-Id':session_id,
                                                                           'Authorization':'Bearer fixture-legacy'})
                                self.assertEqual(response.status_code,404)
        self.assertEqual(self.reads, [('infinite-recursion','user_learning_coach')])
        engine._get_backend.assert_not_called()


if __name__=='__main__':
    unittest.main()
