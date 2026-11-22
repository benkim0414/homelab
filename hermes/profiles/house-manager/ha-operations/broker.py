"""Fixed HA health/restart API. No shell, exec, logs, generic proxy or stored HA token."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import ssl

from aiohttp import ClientSession, ClientTimeout, TraceConfig, web

HA_WS = 'ws://home-assistant.home-assistant.svc.cluster.local:8123/api/websocket'
HA_CHECK = 'http://home-assistant.home-assistant.svc.cluster.local:8123/api/house_manager_general/check-config'
STS = '/apis/apps/v1/namespaces/home-assistant/statefulsets/home-assistant'
POD = '/api/v1/namespaces/home-assistant/pods/home-assistant-0'
STAMP = 'house-manager.homelab/restarted-at'
SA = Path('/var/run/secrets/kubernetes.io/serviceaccount')
MAX_RESPONSE = 1048576


class Refused(Exception):
    pass


async def no_redirect(*args):
    raise Refused('redirect_refused')


async def authenticate(session, token, bot_id):
    """Validate with HA itself, then bind exact non-admin identity; never decode JWTs."""
    async with asyncio.timeout(12):
        async with session.ws_connect(HA_WS, max_msg_size=65536, heartbeat=None) as ws:
            if (await ws.receive_json()).get('type') != 'auth_required':
                raise Refused('authentication_unavailable')
            await ws.send_json({'type': 'auth', 'access_token': token})
            if (await ws.receive_json()).get('type') != 'auth_ok':
                raise Refused('authentication_denied')
            await ws.send_json({'id': 1, 'type': 'auth/current_user'})
            result = await ws.receive_json()
            user = result.get('result')
            if (result.get('id') != 1 or result.get('type') != 'result'
                    or result.get('success') is not True or not isinstance(user, dict)
                    or user.get('id') != bot_id or user.get('is_admin') is not False
                    or user.get('is_owner') is not False):
                raise Refused('authentication_denied')


async def check_config(session, token):
    """Call only HA's authenticated read-only native config validation facade."""
    async with asyncio.timeout(30):
        async with session.post(HA_CHECK, data=b'{}',
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                allow_redirects=False, timeout=ClientTimeout(total=30, connect=5)) as response:
            if response.status != 200:
                raise Refused('config_check_unavailable')
            body = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                body.extend(chunk)
                if len(body) > 4096:
                    raise Refused('config_check_unavailable')
            try:
                return json.loads(body)
            except (ValueError, UnicodeError):
                raise Refused('config_check_unavailable') from None


def validate_check(result, now):
    if (not isinstance(result, dict) or set(result) != {'valid', 'checked_at'}
            or type(result.get('valid')) is not bool
            or not isinstance(result.get('checked_at'), str)):
        raise Refused('config_check_unavailable')
    if result['valid'] is not True:
        raise Refused('config_invalid')
    try:
        checked_at = datetime.fromisoformat(result['checked_at'])
        offset = checked_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError()
        age = (now - checked_at).total_seconds()
        if not -5 <= age <= 60:
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise Refused('config_check_unavailable') from None
    return checked_at.isoformat()


class Kubernetes:
    def __init__(self, session):
        self.session = session
        self.context = ssl.create_default_context(cafile=str(SA / 'ca.crt'))

    async def __call__(self, method, path, payload=None):
        if (method, path) not in {('GET', STS), ('PATCH', STS), ('GET', POD)}:
            raise Refused('unsupported_operation')
        # Read each time: the projected token rotates. It never enters responses/logs.
        headers = {'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()}
        if payload is not None:
            headers['Content-Type'] = 'application/json-patch+json'
        async with self.session.request(method, 'https://kubernetes.default.svc' + path,
                headers=headers, data=None if payload is None else json.dumps(payload),
                ssl=self.context, allow_redirects=False) as response:
            if response.status not in (200, 201):
                raise Refused('kubernetes_request_failed')
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE:
                    raise Refused('response_too_large')
            return json.loads(body)


def summarize(sts, pod):
    status = sts.get('status', {})
    pstatus = pod.get('status', {})
    # No raw metadata, configuration, conditions/messages, container args or logs.
    return {'workload': 'home-assistant', 'kind': 'StatefulSet',
            'desired_replicas': sts['spec'].get('replicas'),
            'ready_replicas': status.get('readyReplicas', 0),
            'updated_replicas': status.get('updatedReplicas', 0),
            'generation_observed': status.get('observedGeneration') == sts['metadata']['generation'],
            'revision_converged': status.get('currentRevision') == status.get('updateRevision'),
            'pod_present': True,
            'pod_running': pstatus.get('phase') == 'Running',
            'pod_terminating': bool(pod['metadata'].get('deletionTimestamp')),
            'pod_ready': any(c.get('type') == 'Ready' and c.get('status') == 'True'
                             for c in pstatus.get('conditions', [])),
            'containers': [{'ready': c.get('ready') is True,
                            'restart_count': c.get('restartCount', 0),
                            'waiting': 'waiting' in c.get('state', {}),
                            'terminated': 'terminated' in c.get('state', {})}
                           for c in pstatus.get('containerStatuses', [])]}


def restart_patch(sts, pod, now):
    spec, meta, status = sts['spec'], sts['metadata'], sts.get('status', {})
    strategy = spec.get('updateStrategy', {})
    if (meta.get('deletionTimestamp') or spec.get('replicas') != 1
            or strategy.get('type') != 'RollingUpdate'
            or strategy.get('rollingUpdate', {}).get('partition', 0) != 0
            or status.get('observedGeneration') != meta['generation']
            or not status.get('currentRevision')
            or status.get('currentRevision') != status.get('updateRevision')
            or status.get('updatedReplicas') != 1
            or pod['metadata'].get('deletionTimestamp')
            or not any(o.get('kind') == 'StatefulSet' and o.get('name') == 'home-assistant'
                       and o.get('uid') == meta['uid'] and o.get('controller') is True
                       for o in pod['metadata'].get('ownerReferences', []))):
        raise Refused('unsafe_or_in_progress_rollout')
    annotations = dict(spec['template']['metadata'].get('annotations') or {})
    if STAMP in annotations:
        try:
            last = datetime.fromisoformat(annotations[STAMP])
            if last.tzinfo is None or (now - last).total_seconds() < 300:
                raise Refused('restart_cooldown')
        except (ValueError, TypeError):
            raise Refused('invalid_restart_stamp') from None
    annotations[STAMP] = now.isoformat()
    return [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': meta['resourceVersion']},
            {'op': 'test', 'path': '/metadata/uid', 'value': meta['uid']},
            {'op': 'add', 'path': '/spec/template/metadata/annotations', 'value': annotations}]


def make_app(bot_id, authenticate_request, kube, config_check=None):
    if re.fullmatch('[0-9a-f]{32}', bot_id) is None:
        raise ValueError('Exact non-secret HA bot user ID required')
    lock = asyncio.Lock()

    @web.middleware
    async def boundary(request, handler):
        try:
            if (request.method != 'POST' or request.path not in ('/v1/health', '/v1/restart')
                    or request.query_string or 'Origin' in request.headers
                    or request.headers.get('Content-Type') != 'application/json'
                    or request.headers.get('Content-Encoding')
                    or len(request.headers.getall('Authorization', [])) != 1):
                raise Refused('invalid_request')
            header = request.headers['Authorization']
            if not re.fullmatch(r'Bearer [A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', header) or len(header) > 8192:
                raise Refused('authentication_denied')
            if await request.read() != b'{}':
                raise Refused('empty_object_required')
            await authenticate_request(header[7:], bot_id)
            return await handler(request)
        except Refused as error:
            # All messages above are fixed constants. Never stringify upstream exceptions.
            return web.json_response({'ok': False, 'error': error.args[0]}, status=403)
        except Exception:
            return web.json_response({'ok': False, 'error': 'operation_unavailable'}, status=503)

    async def operate(request):
        async with lock:
            sts = await kube('GET', STS)
            pod = await kube('GET', POD)
            if request.path == '/v1/health':
                return web.json_response({'ok': True, 'health': summarize(sts, pod)})
            if config_check is None:
                raise Refused('config_check_unavailable')
            # Fresh validation under the restart lock; never cache or borrow admin auth.
            result = await config_check(request.headers['Authorization'][7:])
            checked_at = validate_check(result, datetime.now(timezone.utc))
            patch = restart_patch(sts, pod, datetime.now(timezone.utc))
            await kube('PATCH', STS, patch)
            # Never retry an ambiguous patch. Read exact target before claiming acceptance.
            readback = await kube('GET', STS)
            expected = patch[-1]['value'][STAMP]
            if (readback['metadata']['uid'] != sts['metadata']['uid']
                    or readback['spec']['template']['metadata']['annotations'].get(STAMP) != expected):
                raise Refused('restart_not_verified')
            return web.json_response({'ok': True, 'restart_requested': True,
                                      'annotation_verified': True, 'rollout_verified': False,
                                      'config_check_verified': True, 'config_checked_at': checked_at})

    app = web.Application(middlewares=[boundary], client_max_size=16)
    app.router.add_post('/v1/health', operate)
    app.router.add_post('/v1/restart', operate)
    return app


async def application():
    trace = TraceConfig()
    trace.on_request_redirect.append(no_redirect)
    session = ClientSession(timeout=ClientTimeout(total=15, connect=5),
                            trust_env=False, trace_configs=[trace])
    try:
        kube = Kubernetes(session)
        async def auth(token, bot_id):
            await authenticate(session, token, bot_id)
        async def config_check(token):
            return await check_config(session, token)
        app = make_app(os.environ['HA_BOT_USER_ID'], auth, kube, config_check)
    except BaseException:
        await session.close()
        raise
    async def cleanup(app):
        await session.close()
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    web.run_app(application(), host='0.0.0.0', port=8080, access_log=None,
                print=None, handler_cancellation=True)
