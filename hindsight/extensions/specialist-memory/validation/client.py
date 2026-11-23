"""Disposable acceptance TEST-ONLY client, excluded by the service .dockerignore.

Public synthetic keys/markers ONLY; no environment, credentials or settings reads.
The parent must verify listener ownership and supply its fresh verified URL.
"""
import asyncio
import json
import ipaddress
import re

import httpx
import httpx2
from mcp import ClientSession
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult
from mcp.client.streamable_http import streamable_http_client

FIXTURE_CONFIG = {
    'api_key': 'fixture-legacy',
    'learning_coach_api_key': 'fixture-learning',
    'career_advisor_api_key': 'fixture-career',
    'operator_learning_coach_api_key': 'fixture-learning-operator',
    'operator_career_advisor_api_key': 'fixture-career-operator',
}
RECORDS = (
    {'role': 'learning', 'schema': 'user_learning_coach', 'bank': 'infinite-recursion',
     'key': 'fixture-learning', 'operator_key': 'fixture-learning-operator',
     'document': 'fixture-learning-marker', 'text': 'Synthetic learning marker: a paper crane rests on a blue shelf.'},
    {'role': 'career', 'schema': 'user_career_advisor', 'bank': 'next-level',
     'key': 'fixture-career', 'operator_key': 'fixture-career-operator',
     'document': 'fixture-career-marker', 'text': 'Synthetic career marker: a wooden kite rests on a green shelf.'},
    {'role': 'legacy', 'schema': 'public', 'bank': 'legacy-validation',
     'key': 'fixture-legacy', 'operator_key': 'fixture-legacy',
     'document': 'fixture-legacy-marker', 'text': 'Synthetic legacy marker: a silver bell rests on a yellow shelf.'},
)
DENIAL_CHECKS = ('readonly_mutations_denied', 'crossbank_paths_denied', 'bank_header_denied',
                 'bank_arguments_denied', 'unknown_routes_tools_denied', 'own_recall_uncontaminated')
FORBIDDEN_TEXT = 'Synthetic forbidden marker: an orange pebble must never be retained.'
FORBIDDEN_DOCUMENT = 'fixture-forbidden-marker'
POSITIVE_CHECKS = ('synchronous_retain', 'durable_documents', 'rest_recall',
                   'readonly_inventory', 'mcp_recall', 'legacy_compatibility')


def _require(condition):
    if not condition:
        raise ValueError()


def _admit(url, *, verified_target=None):
    host = '127.0.0.1'
    if verified_target is not None:
        _require(type(verified_target) is tuple and len(verified_target) == 2)
        expected, subnet = verified_target
        _require(isinstance(url, str) and url == expected)
        match = re.fullmatch(r'http://([0-9.]+):[1-9][0-9]{3,4}', url)
        _require(match is not None)
        host = match[1]
        address = ipaddress.IPv4Address(host)
        network = ipaddress.IPv4Network(subnet, strict=True)
        _require(network.is_private and network.prefixlen == 28 and address in network
                 and address not in (network.network_address, network.broadcast_address)
                 and not address.is_loopback and not address.is_link_local)
    _require(isinstance(url, str) and re.fullmatch(r'http://' + re.escape(host) + r':[1-9][0-9]{3,4}', url))
    _require(1024 <= int(url.rsplit(':', 1)[1]) <= 65535)
    return url


def _tool_payload(result):
    _require(result.is_error is False and result.result_type == 'complete')
    # Native dict tools send mirrored text too: use structured exclusively.
    payload = result.structured_content
    if payload is None:
        _require(len(result.content) == 1 and result.content[0].type == 'text')
        payload = json.loads(result.content[0].text)
    _require(isinstance(payload, dict))
    return payload


def _verify_recall(payload, record):
    _require(isinstance(payload, dict) and 'error' not in payload)
    results = payload.get('results')
    _require(isinstance(results, list) and bool(results))
    _require(any(isinstance(r, dict) and r.get('document_id') == record['document']
                 and r.get('text') == record['text'] for r in results))
    serialized = json.dumps(payload)
    _require(FORBIDDEN_TEXT not in serialized and FORBIDDEN_DOCUMENT not in serialized)
    _require(not any(r['text'] in serialized or r['document'] in serialized
                     for r in RECORDS if r['document'] != record['document']))


def _query(record):
    return {'query': record['text'], 'types': ['world'], 'budget': 'low', 'max_tokens': 1024}


class _Run:
    def __init__(self, url, *, verified_target=None):
        self.stage, self.sent, self.url = 'admission', 0, _admit(url, verified_target=verified_target)

    async def request_hook(self, request):
        self.sent += 1
        _require(self.sent <= 100 and str(request.url).startswith(self.url + '/'))

    async def response_hook(self, response):
        # MCP 2.3 otherwise follows redirects independently of follow_redirects.
        _require(not 300 <= response.status_code < 400)

    def client(self, library, key):
        return library.AsyncClient(transport=library.AsyncHTTPTransport(retries=0),
            trust_env=False, follow_redirects=False, timeout=30,
            headers={'Authorization': 'Bearer ' + key},
            event_hooks={'request': [self.request_hook], 'response': [self.response_hook]})

    async def rest(self, client, record, method, suffix='', body=None, status=200, headers=None):
        response = await client.request(method, self.url + '/v1/default/banks/' + record['bank'] + suffix,
                                        json=body, headers=headers)
        if response.status_code != status:
            response.raise_for_status()
            raise ValueError()
        return response.json()

    async def mcp(self, record):
        self.role = record['role']
        async with self.client(httpx2, record['key']) as client:
            async with streamable_http_client(self.url + '/mcp/' + record['bank'], http_client=client,
                                              max_sse_event_size=65536) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as session:
                    self.stage = 'mcp-initialize'
                    await session.initialize()
                    if record['role'] != 'legacy':
                        self.stage = 'mcp-inventory'
                        tools = await session.list_tools()
                        names = [t.name for t in tools.tools]
                        _require(tools.next_cursor is None and names == ['recall'])
                    self.stage = 'mcp-recall'
                    arguments = {**_query(record), 'include_chunks': True, 'max_chunk_tokens': 1024}
                    if record['role'] == 'legacy':
                        # TEST-ONLY: typed recall without the oversized legacy catalog.
                        # call_tool() would automatically fetch inventory to validate output.
                        result = await session.send_request(CallToolRequest(
                            params=CallToolRequestParams(name='recall', arguments=arguments)), CallToolResult)
                    else:
                        result = await session.call_tool('recall', arguments)
                    _verify_recall(_tool_payload(result), record)

    async def denials(self):
        denied = 0
        for record in RECORDS[:2]:
            root = '/v1/default/banks/' + record['bank']
            mcp = '/mcp/' + record['bank']
            query = {**_query(record), 'query': FORBIDDEN_TEXT}
            def rpc(name='recall', arguments=None):
                return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': name, 'arguments': query if arguments is None else arguments}}
            item = {'content': FORBIDDEN_TEXT, 'document_id': FORBIDDEN_DOCUMENT}
            probes = [(method, root + suffix, {'items': [item], 'async': False, **query}, None)
                      for method, suffix in (('POST', '/memories'), ('PUT', ''), ('PATCH', ''), ('DELETE', ''),
                          ('POST', '/clone'), ('POST', '/files/retain'), ('POST', '/memories/reflect'),
                          ('DELETE', '/documents/' + record['document']), ('PATCH', '/documents/' + record['document']),
                          ('GET', '/fixture-unknown-route'))]
            for other in RECORDS:
                if other != record:
                    probes += [('POST', '/v1/default/banks/' + other['bank'] + '/memories/recall', query, None),
                               ('POST', '/mcp/' + other['bank'], rpc(), None)]
            other_bank = RECORDS[1 if record == RECORDS[0] else 0]['bank']
            probes += [('POST', root + '/memories/recall', query, {'x-bank-id': other_bank}),
                       ('POST', mcp, rpc(), {'x-bank-id': other_bank}),
                       ('POST', root + '/memories/recall', {**query, 'bank_id': other_bank}, None),
                       ('POST', mcp, rpc(arguments={**query, 'bank_id': other_bank}), None),
                       ('POST', mcp, rpc('retain', item), None),
                       ('POST', mcp, rpc('fixture-unknown-tool'), None),
                       ('POST', mcp, {'jsonrpc': '2.0', 'id': 1, 'method': 'fixture/unknown'}, None)]
            async with self.client(httpx, record['key']) as client:
                self.stage = 'denial'
                for method, path, body, headers in probes:
                    response = await client.request(method, self.url + path, json=body, headers=headers)
                    _require(response.status_code == 403)
                    denied += 1
                self.stage = 'own-recall'
                _verify_recall(await self.rest(client, record, 'POST', '/memories/recall',
                    {**_query(record), 'include': {'chunks': {'max_tokens': 1024}}}), record)
        _require(denied == 42)
        return {'ok': True, 'checks': dict.fromkeys(DENIAL_CHECKS, True),
                'counts': {'denials': denied, 'own_recalls': 2}}

    async def positive(self):
        for record in RECORDS:
            async with self.client(httpx, record['operator_key']) as client:
                # Retain lazily creates its own bank through validate_create_bank.
                # Profile administration is deliberately outside this test.
                self.stage = 'retain'
                result = await self.rest(client, record, 'POST', '/memories', {
                    'items': [{'content': record['text'], 'document_id': record['document'],
                               'context': 'Synthetic disposable acceptance fixture',
                               'metadata': {'fixture': 'specialist-memory'}, 'tags': ['fixture']}], 'async': False})
                _require(result.get('success') is True and result.get('async') is False
                         and result.get('bank_id') == record['bank']
                         and type(result.get('items_count')) is int and result['items_count'] == 1)
                usage = result.get('usage')
                _require(isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] == 0
                         for k in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'thoughts_tokens')))
                self.stage = 'document'
                doc = await self.rest(client, record, 'GET', '/documents/' + record['document'])
                _require(doc.get('id') == record['document'] and doc.get('bank_id') == record['bank']
                         and doc.get('original_text') == record['text'] and isinstance(doc.get('content_hash'), str)
                         and bool(doc['content_hash']) and type(doc.get('memory_unit_count')) is int
                         and doc['memory_unit_count'] > 0)
            async with self.client(httpx, record['key']) as client:
                self.stage = 'rest-recall'
                _verify_recall(await self.rest(client, record, 'POST', '/memories/recall',
                    {**_query(record), 'include': {'chunks': {'max_tokens': 1024}}}), record)
            await self.mcp(record)
        return {'ok': True, 'checks': dict.fromkeys(POSITIVE_CHECKS, True),
                'counts': {'documents': 3, 'rest_recalls': 3, 'mcp_recalls': 3, 'readonly_inventories': 2}}


async def _execute(url, operation, *, verified_target=None):
    run = None
    try:
        run = _Run(url, verified_target=verified_target)
        async with asyncio.timeout(180):
            return await getattr(run, operation)()
    except Exception as exc:
        name = type(exc).__name__
        report = {'ok': False, 'stage': run.stage if run else 'admission',
                'exception': name if name in ('ValueError', 'ReadError', 'ConnectError', 'TimeoutError',
                    'ReadTimeout', 'HTTPStatusError', 'ExceptionGroup', 'McpError') else 'RuntimeError',
                'status': exc.response.status_code if isinstance(exc, (httpx.HTTPStatusError, httpx2.HTTPStatusError)) else None}
        if isinstance(exc, BaseExceptionGroup):
            pending=list(exc.exceptions)[:8];leaves=[]
            for _ in range(32):
                if not pending or len(leaves)>=8:break
                child=pending.pop(0)
                if isinstance(child,BaseExceptionGroup):pending.extend(child.exceptions[:8])
                else:
                    label=type(child).__name__
                    leaves.append(label if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',label) else 'RuntimeError')
            role=getattr(run,'role',None)
            report['detail']={'role':role if role in ('learning','career','legacy') else None,'leaf_types':leaves}
        return report


async def seed_and_verify_positive(url, *, verified_target=None):
    return await _execute(url, 'positive', verified_target=verified_target)


async def exercise_denials(url, *, verified_target=None):
    return await _execute(url, 'denials', verified_target=verified_target)


def report_is_valid(report, phase):
    checks = POSITIVE_CHECKS if phase == 'positive' else DENIAL_CHECKS
    counts = ({'documents': 3, 'rest_recalls': 3, 'mcp_recalls': 3, 'readonly_inventories': 2}
              if phase == 'positive' else {'denials': 42, 'own_recalls': 2})
    return (phase in ('positive', 'denials') and isinstance(report, dict) and report.get('ok') is True
            and isinstance(report.get('checks'), dict) and set(report['checks']) == set(checks)
            and all(value is True for value in report['checks'].values())
            and isinstance(report.get('counts'), dict) and report['counts'] == counts
            and all(type(value) is int for value in report['counts'].values()))


def main(argv=None, *, verified_target=None):
    import contextlib
    import logging
    import sys
    argv = sys.argv[1:] if argv is None else argv
    report = {'ok': False, 'stage': 'admission', 'exception': 'ValueError', 'status': None}
    phase = argv[0] if argv else ''
    previous = logging.root.manager.disable
    try:
        _require(len(argv) == 2 and phase in ('positive', 'denials'))
        _admit(argv[1], verified_target=verified_target)
        logging.disable(logging.CRITICAL)
        # The SDK can log transport exception text; never expose it via CLI.
        with open('/dev/null', 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            report = asyncio.run((seed_and_verify_positive if phase == 'positive' else exercise_denials)(argv[1], **({'verified_target': verified_target} if verified_target is not None else {})))
    except Exception:
        pass
    finally:
        logging.disable(previous)
    valid = report_is_valid(report, phase)
    if not valid and (not isinstance(report, dict) or report.get('ok') is not False):
        report = {'ok': False, 'stage': 'report', 'exception': 'ValueError', 'status': None}
    print(json.dumps(report, sort_keys=True))
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())
