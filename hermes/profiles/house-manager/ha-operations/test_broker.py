"""Credential-free local boundary tests; all HA/Kubernetes upstreams are synthetic."""
import copy
import hashlib
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import broker
import render

BOT = 'b' * 32
HEADERS = {'Authorization': 'Bearer synthetic.test.token', 'Content-Type': 'application/json'}


def fixtures():
    sts = {'metadata': {'uid': 'sts-uid', 'generation': 3, 'resourceVersion': '7'},
           'spec': {'replicas': 1, 'updateStrategy': {'type': 'RollingUpdate', 'rollingUpdate': {'partition': 0}},
                    'template': {'metadata': {'annotations': {'preserve': 'unchanged'}}}},
           'status': {'observedGeneration': 3, 'currentRevision': 'r1', 'updateRevision': 'r1',
                      'updatedReplicas': 1, 'readyReplicas': 1}}
    pod = {'metadata': {'uid': 'pod-uid', 'ownerReferences': [{'kind': 'StatefulSet', 'name': 'home-assistant',
                       'uid': 'sts-uid', 'controller': True}]},
           'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                      'containerStatuses': [{'ready': True, 'restartCount': 0, 'state': {'running': {}}}]}}
    return sts, pod


class PatchTests(unittest.TestCase):
    def test_exact_patch(self):
        sts, pod = fixtures()
        ops = broker.restart_patch(sts, pod, datetime.now(timezone.utc))
        self.assertEqual([o['path'] for o in ops], ['/metadata/resourceVersion', '/metadata/uid',
                         '/spec/template/metadata/annotations'])
        self.assertEqual(ops[-1]['value']['preserve'], 'unchanged')
        self.assertEqual(set(ops[-1]['value']), {'preserve', broker.STAMP})

    def test_unsafe_workloads_refused(self):
        edits = [lambda s,p: s['spec'].update(replicas=2),
                 lambda s,p: s['spec']['updateStrategy'].update(type='OnDelete'),
                 lambda s,p: s['spec']['updateStrategy']['rollingUpdate'].update(partition=1),
                 lambda s,p: s['status'].update(observedGeneration=2),
                 lambda s,p: s['status'].update(updateRevision='r2'),
                 lambda s,p: s['status'].update(updatedReplicas=0),
                 lambda s,p: p['metadata'].update(deletionTimestamp='now'),
                 lambda s,p: s['metadata'].update(deletionTimestamp='now'),
                 lambda s,p: p['metadata']['ownerReferences'][0].update(uid='different')]
        for edit in edits:
            with self.subTest(edit=edit):
                sts, pod = fixtures()
                edit(sts, pod)
                with self.assertRaises(broker.Refused):
                    broker.restart_patch(sts, pod, datetime.now(timezone.utc))

    def test_persistent_cooldown(self):
        for stamp in [datetime.now(timezone.utc).isoformat(), 'not-a-date',
                      (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()]:
            sts, pod = fixtures()
            sts['spec']['template']['metadata']['annotations'][broker.STAMP] = stamp
            with self.assertRaises(broker.Refused):
                broker.restart_patch(sts, pod, datetime.now(timezone.utc))
        sts['spec']['template']['metadata']['annotations'][broker.STAMP] = (
            datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        broker.restart_patch(sts, pod, datetime.now(timezone.utc))

    def test_output_redaction(self):
        sts, pod = fixtures()
        sts['spec']['credential'] = 'SENSITIVE_MARKER'
        pod['status']['conditions'][0]['message'] = 'SENSITIVE_MARKER'
        self.assertNotIn('SENSITIVE_MARKER', json.dumps(broker.summarize(sts, pod)))

    def test_render_includes_mandatory_check_source_and_matching_checksum(self):
        docs = render.render(BOT)
        source = next(d for d in docs if d['kind'] == 'ConfigMap')['data']['broker.py']
        self.assertEqual(source, (render.HERE/'broker.py').read_text())
        self.assertIn("/api/house_manager_general/check-config", source)
        self.assertIn('if config_check is None:', source)
        dep = next(d for d in docs if d['kind'] == 'Deployment')
        self.assertEqual(dep['spec']['template']['metadata']['annotations']['checksum/source'],
                         hashlib.sha256(source.encode()).hexdigest())

    def test_manifest_boundary(self):
        docs = render.render(BOT)
        role = next(d for d in docs if d['kind'] == 'Role')
        self.assertEqual(role['rules'], [
            {'apiGroups': ['apps'], 'resources': ['statefulsets'], 'resourceNames': ['home-assistant'], 'verbs': ['get','patch']},
            {'apiGroups': [''], 'resources': ['pods'], 'resourceNames': ['home-assistant-0'], 'verbs': ['get']}])
        self.assertNotIn('Secret', [d['kind'] for d in docs])
        dep = next(d for d in docs if d['kind'] == 'Deployment')
        self.assertFalse(dep['spec']['template']['spec']['automountServiceAccountToken'])
        self.assertEqual(dep['spec']['template']['spec']['serviceAccountName'], 'ha-operations')
        policies = [d for d in docs if d['kind'] == 'NetworkPolicy']
        ingress = next(d for d in policies if d['metadata']['name'] == 'ha-operations')['spec']['ingress']
        self.assertEqual(ingress[0]['from'][0]['podSelector']['matchLabels'], {'app':'hermes'})
        self.assertEqual(ingress[0]['from'][0]['namespaceSelector']['matchLabels'], {'kubernetes.io/metadata.name':'hermes'})
        with self.assertRaises(ValueError):
            render.render('')


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sts, self.pod = fixtures()
        self.calls = []
        self.auth_calls = []
        self.deny = False
        self.bad_readback = False
        self.fail_patch = False
        self.check_calls = []
        self.check_valid = True
        self.check_error = False
        async def config_check(token):
            self.check_calls.append(token)
            self.assertTrue(self.auth_calls)
            self.assertEqual(self.calls[-1][0], 'GET')
            if self.check_error:
                raise RuntimeError('SENSITIVE_MARKER')
            return {'valid': self.check_valid, 'checked_at': datetime.now(timezone.utc).isoformat()}
        async def auth(token, bot_id):
            self.auth_calls.append((token, bot_id))
            if self.deny:
                raise broker.Refused('authentication_denied')
        async def kube(method, path, payload=None):
            self.calls.append((method, path, payload))
            if method == 'PATCH':
                assert payload is not None
                if self.fail_patch:
                    raise RuntimeError('SENSITIVE_MARKER')
                if not self.bad_readback:
                    self.sts['spec']['template']['metadata']['annotations'] = payload[-1]['value']
                return copy.deepcopy(self.sts)
            return copy.deepcopy(self.sts if path == broker.STS else self.pod)
        self.client = TestClient(TestServer(broker.make_app(BOT, auth, kube, config_check)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def post(self, path='/v1/health', body='{}', headers=None):
        return await self.client.post(path, data=body, headers=HEADERS if headers is None else headers)

    async def test_health_authenticated(self):
        response = await self.post()
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())['health']['pod_ready'])
        self.assertEqual(self.auth_calls, [('synthetic.test.token', BOT)])
        self.assertEqual([c[:2] for c in self.calls], [('GET', broker.STS), ('GET', broker.POD)])

    async def test_restart_readback_and_cooldown(self):
        response = await self.post('/v1/restart')
        result = await response.json()
        self.assertEqual(response.status, 200)
        self.assertTrue(result['annotation_verified'])
        self.assertTrue(result['config_check_verified'])
        self.assertEqual(self.check_calls, ['synthetic.test.token'])
        self.assertFalse(result['rollout_verified'])
        self.assertEqual(self.calls[-1][:2], ('GET', broker.STS))
        self.assertEqual((await self.post('/v1/restart')).status, 403)
        self.assertEqual(sum(c[0] == 'PATCH' for c in self.calls), 1)

    async def test_auth_denied_prevents_kube(self):
        self.deny = True
        self.assertEqual((await self.post()).status, 403)
        self.assertEqual(self.calls, [])

    async def test_unsupported_input_never_reaches_kube(self):
        cases = [('/v1/health?namespace=other', '{}', HEADERS), ('/v1/other', '{}', HEADERS),
                 ('/v1/restart', '{"replicas":0}', HEADERS), ('/v1/health', '[]', HEADERS),
                 ('/v1/health', '{}', {**HEADERS,'Origin':'https://evil.invalid'}),
                 ('/v1/health', '{}', {'Content-Type':'application/json'}),
                 ('/v1/health', '{}', {**HEADERS,'Authorization':'Bearer invalid'})]
        for path, body, headers in cases:
            with self.subTest(path=path, body=body):
                self.assertEqual((await self.post(path, body, headers)).status, 403)
        self.assertEqual(self.calls, [])

    async def test_invalid_config_prevents_patch(self):
        self.check_valid = False
        response = await self.post('/v1/restart')
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())['error'], 'config_invalid')
        self.assertFalse(any(c[0] == 'PATCH' for c in self.calls))

    async def test_unavailable_config_check_prevents_patch_without_error_leak(self):
        self.check_error = True
        response = await self.post('/v1/restart')
        self.assertEqual(response.status, 503)
        self.assertNotIn('SENSITIVE_MARKER', await response.text())
        self.assertFalse(any(c[0] == 'PATCH' for c in self.calls))

    async def test_missing_callback_fails_closed_but_health_available(self):
        calls = []
        async def auth(token, bot_id):
            pass
        async def kube(method, path, payload=None):
            calls.append(method)
            return copy.deepcopy(self.sts if path == broker.STS else self.pod)
        async with TestClient(TestServer(broker.make_app(BOT, auth, kube))) as client:
            response = await client.post('/v1/restart', data='{}', headers=HEADERS)
            self.assertEqual(response.status, 403)
            self.assertEqual((await response.json())['error'], 'config_check_unavailable')
            response = await client.post('/v1/health', data='{}', headers=HEADERS)
            self.assertEqual(response.status, 200)
        self.assertNotIn('PATCH', calls)

    async def test_checks_not_cached(self):
        self.check_valid = False
        self.assertEqual((await self.post('/v1/restart')).status, 403)
        self.check_valid = True
        self.assertEqual((await self.post('/v1/restart')).status, 200)
        self.assertEqual(self.check_calls, ['synthetic.test.token', 'synthetic.test.token'])

    async def test_no_optimistic_success(self):
        self.bad_readback = True
        self.assertEqual((await self.post('/v1/restart')).status, 403)

    async def test_ambiguous_failure_no_retry_or_exception_leak(self):
        self.fail_patch = True
        response = await self.post('/v1/restart')
        self.assertEqual(response.status, 503)
        self.assertNotIn('SENSITIVE_MARKER', await response.text())
        self.assertEqual(sum(c[0] == 'PATCH' for c in self.calls), 1)


class ConfigCheckTests(unittest.IsolatedAsyncioTestCase):
    def test_receipt_validation(self):
        now = datetime.now(timezone.utc)
        broker.validate_check({'valid': True, 'checked_at': now.isoformat()}, now)
        for result in [None, {}, {'valid': 1, 'checked_at': now.isoformat()},
                       {'valid': True, 'checked_at': now.isoformat(), 'errors': 'SENSITIVE_MARKER'},
                       {'valid': False, 'checked_at': now.isoformat()},
                       {'valid': True, 'checked_at': 'invalid'},
                       {'valid': True, 'checked_at': now.replace(tzinfo=None).isoformat()},
                       {'valid': True, 'checked_at': (now-timedelta(seconds=61)).isoformat()},
                       {'valid': True, 'checked_at': (now+timedelta(seconds=6)).isoformat()}]:
            with self.subTest(result=result):
                with self.assertRaises(broker.Refused):
                    broker.validate_check(result, now)

    async def test_fixed_post_body_and_bearer(self):
        seen = []
        async def handler(request):
            seen.append((request.method, request.path, await request.read(), request.headers['Authorization']))
            return web.json_response({'valid': True, 'checked_at': datetime.now(timezone.utc).isoformat()})
        app = web.Application()
        app.router.add_post('/api/house_manager_general/check-config', handler)
        async with TestServer(app) as server, broker.ClientSession(trust_env=False) as session:
            with patch.object(broker, 'HA_CHECK', str(server.make_url('/api/house_manager_general/check-config'))):
                result = await broker.check_config(session, 'synthetic.test.token')
                broker.validate_check(result, datetime.now(timezone.utc))
        self.assertEqual(seen, [('POST','/api/house_manager_general/check-config',b'{}','Bearer synthetic.test.token')])

    async def test_redirect_error_malformed_and_oversized_rejected(self):
        for status, text in [(302, 'SENSITIVE_MARKER'), (500, 'SENSITIVE_MARKER'),
                             (200, 'invalid'), (200, 'x'*4097)]:
            hits = []
            async def handler(request):
                hits.append(request.path)
                return web.Response(status=status, text=text, headers={'Location':'/must-not-follow'})
            app = web.Application()
            app.router.add_route('*', '/{tail:.*}', handler)
            async with TestServer(app) as server, broker.ClientSession(trust_env=False) as session:
                with patch.object(broker, 'HA_CHECK', str(server.make_url('/check-config'))):
                    with self.assertRaises(broker.Refused) as caught:
                        await broker.check_config(session, 'synthetic.test.token')
                    self.assertNotIn('SENSITIVE_MARKER', str(caught.exception))
            self.assertEqual(hits, ['/check-config'])


class HAAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_websocket_handshake_and_identity_binding(self):
        for user, allowed in [({'id': BOT,'is_admin':False,'is_owner':False}, True),
                              ({'id':'a'*32,'is_admin':False,'is_owner':False}, False),
                              ({'id':BOT,'is_admin':True,'is_owner':False}, False),
                              ({'id':BOT,'is_admin':False,'is_owner':True}, False)]:
            received = []
            async def handler(request):
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                await ws.send_json({'type':'auth_required'})
                received.append(await ws.receive_json())
                await ws.send_json({'type':'auth_ok'})
                received.append(await ws.receive_json())
                await ws.send_json({'type':'result','id':1,'success':True,'result':user})
                await ws.close()
                return ws
            app = web.Application()
            app.router.add_get('/api/websocket', handler)
            async with TestServer(app) as server, broker.ClientSession(trust_env=False) as session:
                with patch.object(broker, 'HA_WS', str(server.make_url('/api/websocket'))):
                    if allowed:
                        await broker.authenticate(session, 'synthetic.test.token', BOT)
                    else:
                        with self.assertRaises(broker.Refused):
                            await broker.authenticate(session, 'synthetic.test.token', BOT)
                self.assertEqual(received[-1], {'id':1,'type':'auth/current_user'})


if __name__ == '__main__':
    unittest.main()
