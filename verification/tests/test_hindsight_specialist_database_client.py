"""Explicitly synthetic UNIT fixtures only: no sockets, database or provider."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'hindsight/extensions/specialist-memory/validation/client.py'
AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ('httpx','httpx2','mcp'))


def load():
    if not PATH.exists():
        raise AssertionError('bounded acceptance client is missing')
    spec = importlib.util.spec_from_file_location('database_acceptance_client', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(AVAILABLE,'requires the dedicated native client dependency environment')
class PositiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_exception_group_reports_role_and_leaf_type_without_messages(self):
        c = load()
        async def fail(run, record):
            run.stage='mcp-inventory';run.role=record['role']
            raise ExceptionGroup('UNIT-SENSITIVE',[ValueError('UNIT-SENSITIVE')])
        fixture=SyntheticUnitService(c)
        with fixture.installed(),patch.object(c._Run,'mcp',fail):
            result=await c.seed_and_verify_positive('http://127.0.0.1:8123')
        self.assertEqual(result['detail'],{'role':'learning','leaf_types':['ValueError']})
        self.assertNotIn('UNIT-SENSITIVE',json.dumps(result))

    async def test_operator_save_does_not_require_bank_profile_administration(self):
        c = load()
        fixture = SyntheticUnitService(c, 'profile-denied')
        with fixture.installed():
            result = await c.seed_and_verify_positive('http://127.0.0.1:8123')
        self.assertIs(result['ok'], True)
        self.assertEqual(fixture.retains, 3)

    async def test_native_semantic_controls_are_not_schema_discovery(self):
        c = load()
        from mcp.types import CallToolResult, TextContent
        record = {'document': 'unit-document', 'text': 'Synthetic unit marker.'}
        good = {'results': [{'document_id': record['document'], 'text': record['text']}]}
        c._verify_recall(good, record)
        for bad in ({}, {'results': []}, {'error': 'UNIT ONLY', **good},
                    {'results': [{'document_id': 'wrong', 'text': record['text']}]},
                    {'results': [{'document_id': record['document'], 'text': 'wrong'}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                c._verify_recall(bad, record)
        structured = CallToolResult(content=[], structured_content=good)
        text = CallToolResult(content=[TextContent(type='text', text=json.dumps(good))])
        self.assertEqual(c._tool_payload(structured), good)
        self.assertEqual(c._tool_payload(text), good)
        # Native FastMCP emits both: structured content is authoritative, never merged.
        self.assertEqual(c._tool_payload(CallToolResult(content=text.content, structured_content=good)), good)
        for bad in (CallToolResult(content=[], is_error=True, structured_content=good),
                    CallToolResult(content=[]),
                    CallToolResult(content=text.content, structured_content=[]),
                    CallToolResult(content=text.content * 2)):
            with self.assertRaises(ValueError):
                c._tool_payload(bad)

    async def test_three_exact_writes_durable_readback_and_independent_mcp_sessions(self):
        c = load()
        fixture = SyntheticUnitService(c)
        with fixture.installed():
            result = await c.seed_and_verify_positive('http://127.0.0.1:8123')
        self.assertEqual(result, {'ok': True, 'checks': dict.fromkeys(c.POSITIVE_CHECKS, True),
                                 'counts': {'documents': 3, 'rest_recalls': 3, 'mcp_recalls': 3,
                                            'readonly_inventories': 2}})
        self.assertEqual(len(fixture.docs), 3)
        self.assertEqual(fixture.retains, 3)
        self.assertEqual(fixture.sessions, 3)
        self.assertEqual(fixture.events, ['initialize', 'list', 'recall'] * 2 + ['initialize', 'typed-recall'])
        self.assertTrue(all(x['trust_env'] is False and x['follow_redirects'] is False
                            for x in fixture.clients))

    async def test_transport_and_semantic_failures_stop_without_write_retry_and_redact(self):
        for mode, stage in (('retain-error', 'retain'), ('retain-false', 'retain'),
                            ('readback-wrong', 'document'), ('recall-empty', 'rest-recall'),
                            ('inventory-extra', 'mcp-inventory'), ('mcp-empty', 'mcp-recall')):
            with self.subTest(mode=mode):
                c = load()
                fixture = SyntheticUnitService(c, mode)
                with fixture.installed():
                    result = await c.seed_and_verify_positive('http://127.0.0.1:8123')
                self.assertIs(result['ok'], False)
                self.assertEqual(result['stage'], stage)
                self.assertLessEqual(fixture.retains, 1)
                self.assertNotIn('UNIT-SENSITIVE', json.dumps(result))
                self.assertEqual(set(result), {'ok', 'stage', 'exception', 'status'})


class SyntheticUnitService:
    """In-memory UNIT transport, never used by the actual acceptance client."""
    def __init__(self, c, mode=None):
        self.c, self.mode = c, mode
        self.docs, self.clients, self.events = {}, [], []
        self.retains = self.sessions = 0

    def installed(self):
        from contextlib import ExitStack, asynccontextmanager
        from mcp.types import CallToolResult, ListToolsResult, Tool
        import httpx
        service = self
        stack = ExitStack()
        original = self.c.httpx.AsyncClient
        def client(**kwargs):
            self.clients.append(kwargs)
            return original(**kwargs)
        def handle(request):
            path = request.url.path
            bank = path.split('/')[4]
            record = next(r for r in self.c.RECORDS if r['bank'] == bank)
            body = json.loads(request.content or '{}')
            if request.method == 'PUT':
                if self.mode == 'profile-denied':
                    return httpx.Response(403, json={'detail':'UNIT profile administration denied'})
                assert body == {}
                assert request.headers['authorization'] == 'Bearer ' + record['operator_key']
                return httpx.Response(200, json={'bank_id': bank})
            if path.endswith('/memories'):
                self.retains += 1
                assert body == {'items': [{'content': record['text'], 'document_id': record['document'],
                                          'context': 'Synthetic disposable acceptance fixture',
                                          'metadata': {'fixture': 'specialist-memory'}, 'tags': ['fixture']}], 'async': False}
                if self.mode == 'retain-error':
                    raise httpx.ReadError('UNIT-SENSITIVE fixture body and key')
                self.docs[record['document']] = record
                return httpx.Response(200, json={'success': self.mode != 'retain-false', 'bank_id': bank,
                                                'items_count': 1, 'async': False,
                                                'usage': dict.fromkeys(('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'thoughts_tokens'), 0)})
            if '/documents/' in path:
                return httpx.Response(200, json={'id': record['document'], 'bank_id': bank,
                                                'original_text': 'wrong' if self.mode == 'readback-wrong' else record['text'],
                                                'content_hash': 'unit-hash', 'memory_unit_count': 1})
            assert body['types'] == ['world'] and body['budget'] == 'low'
            assert body['include'] == {'chunks': {'max_tokens': 1024}}
            return httpx.Response(200, json={'results': [] if self.mode == 'recall-empty' else
                                            [{'document_id': record['document'], 'text': record['text']}]})
        @asynccontextmanager
        async def stream(url, **kwargs):
            self.sessions += 1
            record = next(r for r in self.c.RECORDS if url.endswith('/' + r['bank']))
            yield record, None
        class Session:
            def __init__(self, record, unused, **kwargs): self.record = record
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def initialize(self): service.events.append('initialize')
            async def list_tools(self):
                service.events.append('list')
                names = ['recall'] if self.record['role'] != 'legacy' else ['recall', 'retain']
                if service.mode == 'inventory-extra': names += ['reflect']
                return ListToolsResult(tools=[Tool(name=n, input_schema={'type': 'object', 'properties': {'query': {'type': 'string'}}}) for n in names])
            async def send_request(self, request, result_type):
                from mcp.types import CallToolRequest
                assert self.record['role'] == 'legacy'
                assert isinstance(request, CallToolRequest) and result_type is CallToolResult
                service.events.append('typed-recall')
                assert request.params.name == 'recall' and 'bank_id' not in request.params.arguments
                assert request.params.arguments == {**service.c._query(self.record),
                                                    'include_chunks': True, 'max_chunk_tokens': 1024}
                return CallToolResult(content=[], structured_content={'results': [
                    {'document_id': self.record['document'], 'text': self.record['text']}]})
            async def call_tool(self, name, args):
                assert self.record['role'] != 'legacy'
                service.events.append('recall')
                assert name == 'recall' and 'bank_id' not in args
                assert args['include_chunks'] is True and args['max_chunk_tokens'] == 1024
                return CallToolResult(content=[], structured_content={'results': [] if service.mode == 'mcp-empty' else
                                      [{'document_id': self.record['document'], 'text': self.record['text']}]})
        stack.enter_context(patch.object(self.c.httpx, 'AsyncHTTPTransport', return_value=httpx.MockTransport(handle)))
        stack.enter_context(patch.object(self.c.httpx, 'AsyncClient', side_effect=client))
        stack.enter_context(patch.object(self.c, 'streamable_http_client', stream))
        stack.enter_context(patch.object(self.c, 'ClientSession', Session))
        return stack


@unittest.skipUnless(AVAILABLE,'requires the dedicated native client dependency environment')
class DenialTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_denial_is_403_then_own_recall_contains_no_forbidden_markers(self):
        c = load()
        import httpx
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path.endswith('/memories/recall') and json.loads(request.content).get('query') != c.FORBIDDEN_TEXT:
                r = next(r for r in c.RECORDS if r['bank'] in request.url.path)
                return httpx.Response(200, json={'results': [{'document_id': r['document'], 'text': r['text']}]})
            return httpx.Response(403, json={'detail': 'UNIT synthetic denial'})
        with patch.object(c.httpx, 'AsyncHTTPTransport', return_value=httpx.MockTransport(handler)):
            report = await c.exercise_denials('http://127.0.0.1:8123')
        self.assertEqual(report, {'ok': True, 'checks': dict.fromkeys(c.DENIAL_CHECKS, True),
                                  'counts': {'denials': 42, 'own_recalls': 2}})
        self.assertEqual(len(seen), 44)
        self.assertEqual(sum(r.method == 'PUT' for r in seen), 2)
        self.assertTrue(any('x-bank-id' in r.headers for r in seen))
        self.assertTrue(any('/mcp/' in r.url.path for r in seen))

    async def test_unexpected_status_or_contaminated_recall_fails_closed(self):
        c = load()
        import httpx
        for status in (200, 401, 404, 500):
            with self.subTest(status=status), patch.object(c.httpx, 'AsyncHTTPTransport',
                    return_value=httpx.MockTransport(lambda r: httpx.Response(status, json={}))) as transport:
                report = await c.exercise_denials('http://127.0.0.1:8123')
                self.assertIs(report['ok'], False)
                self.assertEqual(report['stage'], 'denial')
                self.assertEqual(transport.call_args.kwargs, {'retries': 0})
        r = c.RECORDS[0]
        with self.assertRaises(ValueError):
            c._verify_recall({'results': [{'document_id': r['document'], 'text': r['text']}],
                              'chunks': {'unit': {'text': c.FORBIDDEN_TEXT}}}, r)

    async def test_budgets_and_redirect_refusal_apply_to_sdk_transport_too(self):
        c = load()
        import httpx
        run = c._Run('http://127.0.0.1:8123')
        request = httpx.Request('GET', run.url + '/mcp/infinite-recursion')
        for _ in range(100): await run.request_hook(request)
        with self.assertRaises(ValueError): await run.request_hook(request)
        for status in (301, 302, 307, 308):
            with self.assertRaises(ValueError):
                await run.response_hook(httpx.Response(status))


@unittest.skipUnless(AVAILABLE,'requires the dedicated native client dependency environment')
class CliTests(unittest.TestCase):
    def test_cli_is_json_only_and_rejects_incomplete_truthy_reports(self):
        import contextlib
        import io
        c = load()
        valid = {'ok': True, 'checks': dict.fromkeys(c.POSITIVE_CHECKS, True),
                 'counts': {'documents': 3, 'rest_recalls': 3, 'mcp_recalls': 3, 'readonly_inventories': 2}}
        variants = [valid, {}, {**valid, 'checks': {}}, {**valid, 'checks': []},
                    {**valid, 'checks': dict.fromkeys(c.POSITIVE_CHECKS, 1)},
                    {**valid, 'counts': {**valid['counts'], 'documents': True}},
                    {**valid, 'counts': {}}, {**valid, 'checks': {**valid['checks'], 'unknown': True}}]
        for i, report in enumerate(variants):
            async def fake(url): return report
            out = io.StringIO()
            with patch.object(c, 'seed_and_verify_positive', fake), contextlib.redirect_stdout(out):
                code = c.main(['positive', 'http://127.0.0.1:8123'])
            self.assertEqual(code, 0 if i == 0 else 1)
            json.loads(out.getvalue())
        for argv in ([], ['--help'], ['positive', 'UNIT-SENSITIVE.invalid'],
                     ['positive', 'http://10.254.240.3:8888'],
                     ['positive', 'http://10.254.240.3:8888', '--verified-target'],
                     ['unknown', 'http://127.0.0.1:8123']):
            out = io.StringIO()
            with contextlib.redirect_stdout(out): code = c.main(argv)
            self.assertEqual(code, 1)
            self.assertNotIn('UNIT-SENSITIVE', out.getvalue())
            self.assertIs(json.loads(out.getvalue())['ok'], False)


@unittest.skipUnless(AVAILABLE,'requires the dedicated native client dependency environment')
class NativeSdkTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_typed_wire_rejects_errors_empty_wrong_document_and_invalid_envelopes(self):
        c = load()
        import httpx2
        record = c.RECORDS[2]
        good = {'results': [{'document_id': record['document'], 'text': record['text']}]}
        cases = {
            'rpc-error': {'error': {'code': -32603, 'message': 'UNIT-SENSITIVE'}},
            'tool-error': {'result': {'content': [], 'structuredContent': good, 'isError': True}},
            'empty': {'result': {'content': [], 'structuredContent': {'results': []}}},
            'wrong-document': {'result': {'content': [], 'structuredContent': {'results': [
                {'document_id': 'wrong', 'text': record['text']}]}}},
            'wrong-text': {'result': {'content': [], 'structuredContent': {'results': [
                {'document_id': record['document'], 'text': 'wrong'}]}}},
            'payload-error': {'result': {'content': [], 'structuredContent': {**good, 'error': 'UNIT-SENSITIVE'}}},
            'missing-content': {'result': {'structuredContent': good}},
            'invalid-content': {'result': {'content': [{'type': 'text', 'text': 123}], 'structuredContent': good}},
            'non-object-payload': {'result': {'content': [], 'structuredContent': []}},
            'missing-payload': {'result': {'content': []}},
        }
        for name, reply in cases.items():
            with self.subTest(name=name):
                methods = []
                def wire(request):
                    self.assertEqual(request.method, 'POST')
                    data = json.loads(request.content)
                    methods.append(data['method'])
                    if data['method'] == 'initialize':
                        payload = {'result': {'protocolVersion': data['params']['protocolVersion'],
                                   'capabilities': {'tools': {}},
                                   'serverInfo': {'name': 'explicit-synthetic-unit-fixture', 'version': '1'}}}
                    elif data['method'] == 'notifications/initialized':
                        return httpx2.Response(202)
                    else:
                        self.assertEqual(data['method'], 'tools/call')
                        payload = reply
                    return httpx2.Response(200, json={'jsonrpc': '2.0', 'id': data['id'], **payload})
                with patch.object(c.httpx2, 'AsyncHTTPTransport', return_value=httpx2.MockTransport(wire)):
                    run = c._Run('http://127.0.0.1:8123')
                    with self.assertRaises(Exception) as caught:
                        await run.mcp(record)
                pending: list[BaseException] = [caught.exception]
                while pending:
                    error = pending.pop()
                    if isinstance(error, BaseExceptionGroup):
                        pending.extend(error.exceptions)
                    else:
                        self.assertIn(type(error).__name__, ('ValueError', 'ValidationError', 'McpError', 'MCPError'))
                self.assertEqual(run.stage, 'mcp-recall')
                self.assertEqual(methods, ['initialize', 'notifications/initialized', 'tools/call'])
                self.assertEqual(run.sent, 3)

    async def test_real_sdk_initializes_lists_and_recalls_through_synthetic_wire_only(self):
        c = load()
        import httpx2
        messages = []
        def wire(request):
            self.assertEqual(request.method, 'POST')
            data = json.loads(request.content)
            record = next(r for r in c.RECORDS if request.url.path.endswith('/' + r['bank']))
            messages.append((record['role'], data['method']))
            if record['role'] == 'legacy':
                self.assertNotEqual(data['method'], 'tools/list', 'legacy must not request inventory')
            if 'id' not in data:
                return httpx2.Response(202)
            method = data['method']
            if method == 'initialize':
                result = {'protocolVersion': data['params']['protocolVersion'], 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'explicit-synthetic-unit-fixture', 'version': '1'}}
            elif method == 'tools/list':
                result = {'tools': [{'name': 'recall', 'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}}}]}
            else:
                self.assertEqual(method, 'tools/call')
                self.assertEqual(data['params']['name'], 'recall')
                self.assertNotIn('bank_id', data['params']['arguments'])
                record = next(r for r in c.RECORDS if request.url.path.endswith('/' + r['bank']))
                result = {'content': [{'type': 'text', 'text': 'Mirrored text is not the authoritative semantic source.'}],
                          'structuredContent': {'results': [{'document_id': record['document'], 'text': record['text']}]}, 'isError': False}
            return httpx2.Response(200, json={'jsonrpc': '2.0', 'id': data['id'], 'result': result})
        url = 'http://10.254.240.3:8888'
        run = c._Run(url, verified_target=(url, '10.254.240.0/28'))
        with patch.object(c.httpx2, 'AsyncHTTPTransport', return_value=httpx2.MockTransport(wire)) as transport, \
                patch.object(c, 'streamable_http_client', wraps=c.streamable_http_client) as stream:
            for record in c.RECORDS: await run.mcp(record)
        self.assertEqual(run.sent, 11)
        self.assertEqual(transport.call_count, 3)
        self.assertTrue(all(call.kwargs == {'retries': 0} for call in transport.call_args_list))
        self.assertEqual(stream.call_count, 3)
        self.assertTrue(all(call.kwargs['max_sse_event_size'] == 65536 for call in stream.call_args_list))
        self.assertEqual(messages, [(role, method) for role in ('learning', 'career', 'legacy')
                                    for method in (['initialize', 'notifications/initialized', 'tools/call']
                                                   if role == 'legacy' else
                                                   ['initialize', 'notifications/initialized', 'tools/list', 'tools/call'])])


@unittest.skipUnless(AVAILABLE,'requires the dedicated native client dependency environment')
class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_parent_context_admits_only_exact_verified_target(self):
        c = load()
        url = 'http://10.254.240.3:8888'
        context = (url, '10.254.240.0/28')
        with self.assertRaises(ValueError): c._admit(url)
        self.assertEqual(c._admit(url, verified_target=context), url)
        for bad in ('http://10.254.240.4:8888', 'http://10.254.240.3:8889',
                    'http://127.0.0.1:8888', url+'/', url+'?q=1', url+'#x',
                    'http://user:pass@10.254.240.3:8888', 'http://localhost:8888',
                    'http://[::1]:8888', 'http://010.254.240.3:8888'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                c._admit(bad, verified_target=context)
        for target, subnet in ((url, '10.254.241.0/28'), (url, '10.254.240.0/24'),
                               ('http://10.254.240.0:8888', context[1]),
                               ('http://10.254.240.15:8888', context[1]),
                               ('http://8.8.8.8:8888', '8.8.8.0/28')):
            with self.assertRaises(ValueError):
                c._admit(target, verified_target=(target, subnet))
        fixture = SyntheticUnitService(c)
        with fixture.installed():
            report = await c.seed_and_verify_positive(url, verified_target=context)
        self.assertTrue(c.report_is_valid(report, 'positive'))
        self.assertEqual(fixture.retains, 3)
        import contextlib
        import io
        output = io.StringIO()
        # main owns asyncio.run, so exercise it on a separate UNIT thread.
        fixture = SyntheticUnitService(c)
        with fixture.installed(), contextlib.redirect_stdout(output):
            code = await asyncio.to_thread(c.main, ['positive', url], verified_target=context)
        self.assertEqual(code, 0)
        self.assertTrue(c.report_is_valid(json.loads(output.getvalue()), 'positive'))

    async def test_only_literal_bounded_loopback_without_credentials_is_admitted(self):
        c = load()
        for url in ('https://127.0.0.1:8123', 'http://localhost:8123',
                    'http://127.0.0.2:8123', 'http://127.0.0.1:80',
                    'http://127.0.0.1:65536', 'http://127.0.0.1:8123/',
                    'http://user:pass@127.0.0.1:8123', 'http://127.0.0.1:8123?q=1',
                    'http://127.0.0.1:8123#x', 'http://127.0.0.1:08123'):
            with self.subTest(url=url):
                result = await c.seed_and_verify_positive(url)
                self.assertEqual(result, {'ok': False, 'stage': 'admission',
                                          'exception': 'ValueError', 'status': None})
        self.assertEqual(c._admit('http://127.0.0.1:8123'), 'http://127.0.0.1:8123')
