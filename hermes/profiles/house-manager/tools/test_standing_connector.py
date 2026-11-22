"""Adversarial offline connector contracts, using real engine receipts.

No live credentials, HA runtime, network or mutations. EngineBridge runs the real
Manager/policy against the existing in-memory native Boundary fixture. Mutated
receipts below are explicit adversarial test inputs, not execution evidence.
"""
import asyncio
import copy
import io
import json
import unittest
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import Mock, patch

import general_connector_v3 as c
from custom_components.house_manager_general.engine import Manager
from tests_general.test_manager_native import Boundary, BOT
from tests_general.test_edit_general import EditBoundary

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
SPEC = {'title': 'Routine lamp off', 'triggers': [{'type': 'time', 'at': '23:00:00'}],
        'conditions': [], 'actions': [{'action': 'light.turn_off',
                                     'target': {'entity_id': 'light.test'}, 'data': {}}]}


class EngineBridge:
    def __init__(self, standing=True):
        self.runner = asyncio.Runner()
        self.boundary = Boundary()
        self.boundary.inv = {'light.test': {'entity_id': 'light.test', 'state': 'on',
                             'attributes': {}, 'registry_fingerprint': 'a' * 64, 'platform':'lifx',
                             'name': 'Lamp', 'area': None, 'device_name': 'Lamp'}}
        self.manager = Manager(self.boundary, BOT.id, {}, now=lambda: NOW,
                               standing_permissions=standing)
        self.calls = []

    def close(self):
        self.runner.close()

    def get_capabilities(self):
        self.calls.append(('capabilities',))
        caps: Any = self.runner.run(self.manager.capabilities(BOT))
        caps['supported_actions'] = {'light': ['turn_off', 'turn_on']}
        return caps

    def propose(self, spec):
        self.calls.append(('propose', copy.deepcopy(spec)))
        return self.runner.run(self.manager.propose(BOT, {'spec': spec}))

    def propose_edit(self, args):
        self.calls.append(('edit', copy.deepcopy(args)))
        return self.runner.run(self.manager.propose_edit(BOT, args))

    def get_proposal(self, identifier):
        self.calls.append(('proposal', identifier))
        return self.runner.run(self.manager.status(BOT, identifier))

    def get_managed(self, identifier):
        self.calls.append(('managed', identifier))
        return self.runner.run(self.manager.get_managed(BOT, identifier))

    def set_managed_state(self, args):
        self.calls.append(('state', copy.deepcopy(args)))
        return self.runner.run(self.manager.set_managed_state(BOT, args))


class SnapshotClient:
    """Fresh deep copies permit one corrupt response without mutating its peers."""
    def __init__(self, caps, receipt, observed):
        self.caps: Any = copy.deepcopy(caps)
        self.receipt: Any = copy.deepcopy(receipt)
        self.observed: Any = copy.deepcopy(observed)
        self.calls = []

    def get_capabilities(self):
        self.calls.append('capabilities')
        return copy.deepcopy(self.caps)

    def propose(self, spec):
        self.calls.append('propose')
        return copy.deepcopy(self.receipt)

    def propose_edit(self, args):
        self.calls.append('edit')
        return copy.deepcopy(self.receipt)

    def get_proposal(self, identifier):
        self.calls.append(('proposal', identifier))
        return copy.deepcopy(self.observed)

    def get_managed(self, identifier):
        self.calls.append(('managed', identifier))
        return copy.deepcopy(self.observed)

    def set_managed_state(self, args):
        self.calls.append('state')
        return copy.deepcopy(self.receipt)


class StandingConnectorTests(unittest.TestCase):
    def bridge(self, standing=True):
        bridge = EngineBridge(standing)
        self.addCleanup(bridge.close)
        return bridge

    def snapshots(self):
        bridge = self.bridge()
        caps = bridge.get_capabilities()
        receipt = bridge.propose(copy.deepcopy(SPEC))
        observed = bridge.get_proposal(receipt['id'])
        return caps, receipt, observed

    def test_real_engine_standing_create_requires_fresh_status_and_keeps_no_physical_claim(self):
        bridge = self.bridge()
        result = c.handle_tool('propose_home_automation', {'spec': copy.deepcopy(SPEC)}, bridge)
        self.assertEqual(result['response']['status'], 'verified_enabled')
        self.assertFalse(result['device_state_verified'])
        self.assertEqual([call[0] for call in bridge.calls], ['capabilities', 'propose', 'proposal'])
        self.assertEqual(bridge.boundary.events.count('write'), 1)
        self.assertNotIn('device', bridge.boundary.events)

    def test_real_engine_schema_optional_defaults_are_not_false_mismatches(self):
        bridge = self.bridge()
        spec = copy.deepcopy(SPEC)
        del spec['conditions']
        del spec['actions'][0]['data']
        result = c.handle_tool('propose_home_automation', {'spec': spec}, bridge)
        self.assertEqual(result['response']['status'], 'verified_enabled')
        self.assertEqual(bridge.boundary.events.count('write'), 1)

    def test_real_engine_standing_edit_preserves_state_and_checks_fresh_status(self):
        bridge = self.bridge()
        created = c.handle_tool('propose_home_automation', {'spec': copy.deepcopy(SPEC)}, bridge)['response']
        target = created['id']
        # The edit fixture models pinned HA restore-on-reload without a device.
        edited_boundary = EditBoundary()
        edited_boundary.inv = bridge.boundary.inv
        edited_boundary.rows = bridge.boundary.rows
        edited_boundary.runtime_state = 'off'
        bridge.manager.boundary = bridge.boundary = edited_boundary
        bridge.manager.now = lambda: NOW + timedelta(minutes=1)
        managed = bridge.get_managed(target)
        args = {'target_id': target, 'base_config_hash': managed['config_hash'],
                'spec': dict(copy.deepcopy(SPEC), title='Changed title')}
        result = c.handle_tool('propose_home_automation_edit', args, bridge)
        self.assertEqual(result['response']['status'], 'verified_edit')
        self.assertEqual(result['response']['runtime_state'], 'off')
        self.assertEqual([call[0] for call in bridge.calls][-3:], ['capabilities', 'edit', 'proposal'])
        self.assertNotIn('device', edited_boundary.events)

    def test_default_permission_queues_and_does_not_read_as_immediate(self):
        bridge = self.bridge(False)
        bridge.manager.approval_ready = True
        result = c.handle_tool('propose_home_automation', {'spec': copy.deepcopy(SPEC)}, bridge)
        self.assertEqual(result['response']['status'], 'queued')
        self.assertTrue(result['response']['confirmation_required'])
        self.assertEqual([call[0] for call in bridge.calls], ['capabilities', 'propose'])
        self.assertNotIn('write', bridge.boundary.events)
        caps, receipt, observed = self.snapshots()
        del caps['standing_permissions']
        client = SnapshotClient(caps, receipt, observed)
        with self.assertRaises(ValueError):
            c.handle_tool('propose_home_automation', {'spec': SPEC}, client)
        self.assertNotIn(('proposal', receipt['id']), client.calls)

    def test_standing_disabled_and_no_human_adapter_denies_before_propose(self):
        bridge = self.bridge(False)
        with self.assertRaises(ValueError):
            c.handle_tool('propose_home_automation', {'spec': SPEC}, bridge)
        self.assertEqual(bridge.calls, [('capabilities',)])
        self.assertFalse(bridge.boundary.events)

    def test_wrong_immediate_policy_confirmation_status_hash_and_entity_rejected(self):
        caps, receipt, observed = self.snapshots()
        changes = [dict(authorization={'source': 'human', 'policy_id': 'routine_automations_v1'}),
                   dict(authorization={'source': 'standing_policy', 'policy_id': 'other'}),
                   dict(confirmation_required=True), dict(status='executed'),
                   dict(config_hash='b' * 64), dict(entity_id='automation.other'),
                   dict(runtime_state='off'),
                   dict(verified_at='not a date')]
        for change in changes:
            with self.subTest(change=change):
                client = SnapshotClient(caps, dict(receipt, **change), observed)
                with self.assertRaises(ValueError):
                    c.handle_tool('propose_home_automation', {'spec': SPEC}, client)
                self.assertEqual(client.calls.count('propose'), 1)

    def test_wrong_fresh_policy_spec_doc_hash_binding_state_and_status_rejected(self):
        caps, receipt, observed = self.snapshots()
        for corruption in ['policy', 'authorization_hash', 'spec', 'doc_hash', 'binding',
                           'off', 'changed', 'entity', 'config_hash']:
            with self.subTest(corruption=corruption):
                client = SnapshotClient(caps, receipt, observed)
                status = client.observed
                if corruption == 'policy':
                    status['evidence']['approval']['policy_id'] = 'other'
                elif corruption == 'authorization_hash':
                    status['evidence']['approval']['sha256'] = 'b' * 64
                elif corruption == 'spec':
                    status['proposal']['payload']['title'] = 'Different valid spec'
                    status['proposal']['sha256'] = c.canonical_hash({k: v for k, v in status['proposal'].items() if k != 'sha256'})
                    status['evidence']['approval']['sha256'] = status['proposal']['sha256']
                elif corruption == 'doc_hash':
                    status['proposal']['sha256'] = 'b' * 64
                elif corruption == 'binding':
                    status['proposal']['bindings'] = {}
                elif corruption == 'off':
                    status['runtime_state'] = 'off'
                elif corruption == 'changed':
                    status['status'] = 'changed'
                elif corruption == 'entity':
                    status['entity_id'] = 'automation.other'
                else:
                    status['evidence']['config_hash'] = 'b' * 64
                with self.assertRaises(ValueError):
                    c.handle_tool('propose_home_automation', {'spec': SPEC}, client)
                self.assertEqual(client.calls.count('propose'), 1)
                self.assertEqual(client.calls.count(('proposal', receipt['id'])), 1)

    def test_fresh_read_failure_is_sanitized_stdio_error_without_retry(self):
        caps, receipt, observed = self.snapshots()
        client = SnapshotClient(caps, receipt, observed)
        client.get_proposal = Mock(side_effect=RuntimeError('credential-secret'))
        wire = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'propose_home_automation', 'arguments': {'spec': SPEC}}}
        output = io.StringIO()
        c.serve(io.BytesIO((json.dumps(wire) + '\n').encode()), output, client)
        response = json.loads(output.getvalue())
        self.assertTrue(response['result']['isError'])
        self.assertNotIn('credential-secret', output.getvalue())
        self.assertEqual(client.calls.count('propose'), 1)
        client.get_proposal.assert_called_once_with(receipt['id'])

    def state_snapshots(self):
        bridge = self.bridge()
        created = bridge.propose(copy.deepcopy(SPEC))
        target = created['id']
        managed = bridge.get_managed(target)
        args = {'target_id': target, 'base_config_hash': managed['config_hash'], 'enabled': True}
        receipt = bridge.set_managed_state(args)
        observed = bridge.get_managed(target)
        return args, receipt, observed

    def test_state_operation_returns_fresh_managed_not_historical_receipt(self):
        args, receipt, observed = self.state_snapshots()
        client = SnapshotClient({}, receipt, observed)
        result = c.handle_tool('set_managed_home_automation_state', args, client)
        self.assertEqual(result, {'response': observed, 'device_state_verified': False})
        self.assertEqual(client.calls, ['state', ('managed', args['target_id'])])

    def test_state_fresh_config_hash_target_entity_state_rejected(self):
        args, receipt, observed = self.state_snapshots()
        for change in [dict(runtime_state='off'), dict(entity_id='automation.other'),
                       dict(target_id='house_manager_general_' + 'f' * 32),
                       dict(config_hash='f' * 64)]:
            with self.subTest(change=change):
                client = SnapshotClient({}, receipt, dict(observed, **change))
                with self.assertRaises(ValueError):
                    c.handle_tool('set_managed_home_automation_state', args, client)
                self.assertEqual(client.calls.count('state'), 1)

    def test_state_request_strict_types_and_no_extra_authority(self):
        args, receipt, observed = self.state_snapshots()
        for changes in [dict(enabled=1), dict(enabled='on'), dict(target_id='../x'),
                        dict(base_config_hash='bad'), dict(approved=True),
                        dict(stop_actions=True), dict(service='automation.trigger')]:
            with self.subTest(changes=changes):
                client = SnapshotClient({}, receipt, observed)
                with self.assertRaises(ValueError):
                    c.handle_tool('set_managed_home_automation_state', dict(args, **changes), client)
                self.assertEqual(client.calls, [])


DIAGNOSTICS = {'ha_version': '2026.11.1', 'entity_count': 12, 'unavailable_count': 1,
               'unknown_count': 0, 'enrolled_helper_count': 0, 'entries': []}
CHECK = {'valid': True, 'checked_at': NOW.isoformat()}
HEALTH = {'ok': True, 'health': {'workload': 'home-assistant', 'kind': 'StatefulSet',
          'desired_replicas': 1, 'ready_replicas': 1, 'updated_replicas': 1,
          'generation_observed': True, 'revision_converged': True,
          'pod_present': True, 'pod_running': True, 'pod_terminating': False, 'pod_ready': True,
          'containers': [{'ready': True, 'restart_count': 0, 'waiting': False, 'terminated': False}]}}
RESTART = {'ok': True, 'restart_requested': True, 'annotation_verified': True, 'rollout_verified': False,
           'config_check_verified':True, 'config_checked_at':NOW.isoformat()}
ZEROARG = [('get_home_diagnostics', 'diagnostics', DIAGNOSTICS, 'GET', '/diagnostics', None),
           ('check_home_configuration', 'check_config', CHECK, 'POST', '/check-config', {}),
           ('get_home_workload_health', 'workload_health', HEALTH, 'POST', '/workload-health', {}),
           ('restart_home_assistant', 'restart', RESTART, 'POST', '/workload-restart', {})]


class ScopedOperationsConnectorTests(unittest.TestCase):
    def test_four_zeroarg_tools_exact_schema_and_routes(self):
        for name, method, reply, verb, route, payload in ZEROARG:
            with self.subTest(name=name):
                tool = next(tool for tool in c.TOOLS if tool['name'] == name)
                self.assertEqual(tool['inputSchema'], c.obj({}))
                client = c.HAClient('offline-placeholder')
                with patch.object(client, '_request', return_value=copy.deepcopy(reply)) as request:
                    self.assertEqual(c.handle_tool(name, {}, client), reply)
                    request.assert_called_once_with(verb, route, payload) if payload is not None else request.assert_called_once_with(verb, route)
                for args in [{'url': 'http://evil'}, {'namespace': 'default'}, {'entry_id': 'other'},
                             {'force': True}, {'token': 'secret'}, {'path': '/api/config'}, {'body': {}}, [], None]:
                    with patch.object(client, '_request') as request:
                        with self.assertRaises(ValueError):
                            c.handle_tool(name, args, client)
                        request.assert_not_called()

    def test_result_schemas_reject_extra_secrets_wrong_types_missing_and_false_success(self):
        for name, method, good, _, _, _ in ZEROARG:
            variants = [dict(copy.deepcopy(good), token='secret'), {}, []]
            if method == 'diagnostics':
                variants += [dict(good, entity_count=True), dict(good, unavailable_count=-1)]
            if method == 'check_config':
                variants += [dict(good, valid=1), dict(good, checked_at='2026-11-22T00:00:00')]
            if method == 'workload_health':
                variants += [dict(good, health=dict(good['health'], workload='other')),
                             dict(good, ok=1),
                             dict(good, health=dict(good['health'], containers=[{'ready': True, 'logs': 'secret'}]))]
            if method == 'restart':
                variants += [dict(good, rollout_verified=True), dict(good, annotation_verified=False),
                             dict(good, ok=1), dict(good, restart_requested=1),
                             dict(good, annotation_verified=1), dict(good, rollout_verified=0)]
            for bad in variants:
                with self.subTest(name=name, bad=bad):
                    client = Mock()
                    getattr(client, method).return_value = bad
                    with self.assertRaises(ValueError):
                        c.handle_tool(name, {}, client)
                    getattr(client, method).assert_called_once_with()

    def test_false_config_check_is_valid_diagnostic_not_restart_success(self):
        client = Mock()
        client.check_config.return_value = dict(CHECK, valid=False)
        self.assertEqual(c.handle_tool('check_home_configuration', {}, client)['valid'], False)
        client.restart.assert_not_called()

    def test_transport_no_arbitrary_new_routes_or_methods_before_network(self):
        client = c.HAClient('offline-placeholder')
        client._opener = Mock()
        for method, path in [('GET', '/workload-health'), ('GET', '/workload-restart'),
                             ('POST', '/diagnostics'), ('GET', '/check-config'),
                             ('POST', '/config'), ('POST', '/options'),
                             ('POST', '/workload-restart?force=true'), ('POST', '/workload-restart/../exec'),
                             ('POST', '/v1/restart'), ('POST', 'http://other/api'),
                             ('POST', '/managed-state/other')]:
            with self.subTest(method=method, path=path), self.assertRaises(ValueError):
                client._request(method, path, {})
        client._opener.open.assert_not_called()

    def test_broker_fixed_origin_timeout_and_body_no_retry_or_redirect(self):
        client = c.HAClient('offline-placeholder')
        response = Mock(status=200)
        response.headers.get_content_type.return_value = 'application/json'
        response.read.return_value = json.dumps(RESTART).encode()
        client._opener = Mock()
        client._opener.open.return_value.__enter__ = Mock(return_value=response)
        client._opener.open.return_value.__exit__ = Mock(return_value=False)
        self.assertEqual(client.restart(), RESTART)
        request = client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, c.OPERATIONS_URL + '/v1/restart')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), {})
        self.assertEqual(client._opener.open.call_args.kwargs, {'timeout': 30})
        client._opener.open.reset_mock()
        client._opener.open.side_effect = RuntimeError('private credential')
        with self.assertRaises(RuntimeError) as caught:
            client.restart()
        self.assertNotIn('private credential', str(caught.exception))
        client._opener.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
