"""Validate Hermes HTTP probe contracts without credentials or model requests."""
import copy
import io
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = yaml.safe_load((ROOT / 'hermes/configmap.yaml').read_text())['data']
PROBE = types.ModuleType('hermes_healthcheck')
exec(compile(DATA['healthcheck.py'], 'hermes/configmap.yaml:healthcheck.py', 'exec'), PROBE.__dict__)


class HermesProbeTests(unittest.TestCase):
    def response(self, body, mode='ready', status=200):
        response = io.BytesIO(body)
        response.status = status
        with patch.object(PROBE.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = response
            result = PROBE.check(mode)
            args, kwargs = build.return_value.open.call_args
            self.assertEqual(args[0], 'http://127.0.0.1:9119' + (
                '/api/health' if mode == 'live' else '/api/status'))
            self.assertEqual(kwargs['timeout'], 3)
            self.assertEqual(build.call_args.args[0].proxies, {})
            self.assertIsInstance(build.call_args.args[1], PROBE.NoRedirect)
            return result

    def ready(self):
        return {'auth_required': True, 'auth_providers': ['basic'],
                'components': {'dashboard': {'status': 'ok'}, 'storage': {'status': 'ok'}}}

    def test_rejects_http_success_with_wrong_body_or_status(self):
        for body in (b'<html>login</html>', b'{', b'[]', b'null', b'{}', b'x' * 65537):
            for mode in ('live', 'ready'):
                with self.subTest(body=body[:20], mode=mode):
                    self.assertEqual(self.response(body, mode), 1)
        self.assertEqual(self.response(json.dumps(self.ready()).encode(), status=302), 1)

    def test_liveness_checks_identity_without_auth_or_upstream_dependencies(self):
        self.assertEqual(self.response(b'{"ok": true, "version": "0.22.2"}', 'live'), 0)
        for payload in ({'ok': 1, 'version': '0.22.2'}, {'ok': True, 'version': ''}):
            self.assertEqual(self.response(json.dumps(payload).encode(), 'live'), 1)

    def test_readiness_rejects_auth_drift_and_dashboard_or_storage_failure(self):
        self.assertEqual(self.response(json.dumps(self.ready()).encode()), 0)
        changes = [{'auth_required': False}, {'auth_required': 1},
                   {'auth_providers': []}, {'auth_providers': 'basic'},
                   {'auth_providers': ['nous']}, {'components': {}}, {'components': None}]
        for component in ('dashboard', 'storage'):
            for value in ({'status': 'error'}, {'status': 'unknown'}, None):
                components = copy.deepcopy(self.ready()['components'])
                components[component] = value
                changes.append({'components': components})
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(self.response(json.dumps(self.ready() | change).encode()), 1)

    def test_gateway_outage_and_resource_advice_do_not_disable_browser_chat(self):
        payload = self.ready() | {'gateway_running': False, 'overall': 'degraded',
                                  'memory': {'pressure': 'critical'}}
        payload['components']['gateway'] = {'status': 'stopped'}
        self.assertEqual(self.response(json.dumps(payload).encode()), 0)

    def test_transport_failure_and_redirect_fail_without_following(self):
        with patch.object(PROBE.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = TimeoutError('unavailable')
            self.assertEqual(PROBE.check('ready'), 1)
        self.assertIsNone(PROBE.NoRedirect().redirect_request(
            None, None, 302, 'login', {}, 'https://example.invalid/login'))
        self.assertEqual(PROBE.check('unknown'), 1)
