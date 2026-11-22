"""Offline connector tests; never use live HA or real credentials."""

import pathlib
import unittest

PATH = pathlib.Path(__file__).with_name('general_connector_v3.py')


def capabilities():
    return {'version': 3, 'ha_version': '2026.11.1', 'time_zone': 'Australia/Melbourne',
            'approval_ready': True, 'supported_actions': ['light.turn_on', 'light.turn_off'],
            'inventory': {'light.room': {'entity_id': 'light.room', 'state': 'on', 'attributes': {},
                'registry_fingerprint': 'a'*64, 'name': 'Room', 'area': None, 'device_name': 'Light'}}}


class FakeClient:
    def __init__(self, caps=None, reply=None):
        self.caps = capabilities() if caps is None else caps
        self.reply = reply
        self.calls = []

    def get_capabilities(self):
        self.calls.append(('capabilities',))
        return self.caps

    def control(self, action):
        self.calls.append(('control', action))
        return self.reply

    def propose(self, spec):
        self.calls.append(('propose', spec))
        return self.reply

    def get_proposal(self, identifier):
        self.calls.append(('proposal', identifier))
        return self.reply


class ConnectorTests(unittest.TestCase):
    def test_preview_pending_manager_status_is_readable_without_claiming_execution(self):
        import asyncio
        import general_connector_v3 as c
        from custom_components.house_manager_general import policy
        from custom_components.house_manager_general.engine import Manager
        from tests_general.test_manager_native import Boundary, BOT
        b = Boundary()
        b.inv = capabilities()['inventory']
        doc = policy.make_proposal('action', {'action': 'light.turn_off',
            'target': {'entity_id': 'light.room'}}, b.inv)
        manager = Manager(b, BOT.id, {doc['id']: {'status': 'preview_pending', 'proposal': doc}})
        status = asyncio.run(manager.status(BOT, doc['id']))
        client = FakeClient(reply=status)
        reply = c.handle_tool('get_home_proposal', {'proposal_id': doc['id']}, client)
        self.assertEqual(reply['response'], status)
        self.assertEqual(reply['response']['recorded_status'], 'preview_pending')
        self.assertIs(reply['device_state_verified'], False)
        self.assertIsNone(reply['response']['verified_at'])
        self.assertEqual(b.events, [])

    def test_transport_fixed_routes_and_no_retry(self):
        import general_connector_v3 as c
        import http.server
        import threading
        from unittest.mock import patch
        seen = []
        replies = [(200, b'{"version":3}'), (302, b''), (500, b'token-secret'),
                   (200, b'x' * (c.MAX_RESPONSE + 1)), (200, b'[]')]

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.command, self.path, self.headers.get('Authorization')))
                code, body = replies.pop(0)
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                if code == 302:
                    self.send_header('Location', '/leak')
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(c, 'BASE_URL', 'http://127.0.0.1:%d/api/house_manager_general' % server.server_port), patch.dict('os.environ', {'HTTP_PROXY': 'http://127.0.0.1:1', 'NO_PROXY': ''}):
                client = c.HAClient('test-nonadmin-token')
                self.assertEqual(client.get_capabilities(), {'version': 3})
                for operation in [client.get_capabilities, lambda: client.control({'action': 'light.turn_off', 'target': {'entity_id': 'light.room'}}), client.get_capabilities, client.get_capabilities]:
                    with self.assertRaisesRegex(RuntimeError, 'unavailable') as error:
                        operation()
                    self.assertNotIn('token-secret', str(error.exception))
                with self.assertRaises(ValueError):
                    client._request('POST', '/approve', {})
                with self.assertRaises(ValueError):
                    client.get_proposal('../secret')
                self.assertEqual(len(seen), 5)
                self.assertEqual(seen[2][:2], ('POST', '/api/house_manager_general/action'))
                self.assertTrue(all(auth == 'Bearer test-nonadmin-token' for _, _, auth in seen))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        for token in ['', 'x' + chr(10) + 'y', 'x y', chr(1), 'é', 'x'*16385]:
            with self.subTest(token=token[:10]), self.assertRaises(ValueError):
                c.HAClient(token)

    def test_tool_dispatch_validates_capabilities_before_mutation(self):
        import general_connector_v3 as c
        caps = capabilities()
        action = {'action': 'light.turn_off', 'target': {'entity_id': 'light.room'}, 'data': {}}
        client = FakeClient(caps, {'status': 'executed', 'device_state_verified': False, 'confirmation_required': False})
        reply = c.handle_tool('control_home_device', {'action': action}, client)
        self.assertEqual(reply['response'], client.reply)
        self.assertIs(reply['device_state_verified'], False)
        self.assertEqual(client.calls, [('capabilities',), ('control', action)])
        for args in [{'action': action, 'approved': True}, {'action': dict(action, action='script.turn_on')},
                     {'action': dict(action, target={'entity_id': 'light.other'})}]:
            before = len(client.calls)
            with self.subTest(args=args), self.assertRaises(ValueError):
                c.handle_tool('control_home_device', args, client)
            self.assertNotIn(('control', args['action']), client.calls[before:])
        for bad in [{}, dict(caps, version=2), dict(caps, approval_ready='yes'), dict(caps, inventory={}),
                    dict(caps, supported_actions=[]), dict(caps, time_zone='bad-zone')]:
            denied = FakeClient(bad, client.reply)
            with self.subTest(caps=bad), self.assertRaises(ValueError):
                c.handle_tool('control_home_device', {'action': action}, denied)
            self.assertEqual(denied.calls, [('capabilities',)])
        for name, args in [('approve_home_proposal', {}), ('get_home_capabilities', {'url': 'x'}),
                           ('get_home_proposal', {'proposal_id': '../x'})]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                c.handle_tool(name, args, client)

    def test_queue_and_status_preserve_actual_evidence_without_approval(self):
        import general_connector_v3 as c
        import hashlib
        import json
        identifier = 'house_manager_general_' + 'a'*32
        action = {'action': 'light.turn_off', 'target': {'entity_id': 'light.room'}, 'data': {}}
        spec = {'title': 'Evening', 'triggers': [{'type': 'time', 'at': '21:00:00'}], 'actions': [action]}
        doc = {'id': identifier, 'version': 3, 'kind': 'automation', 'payload': spec,
               'created_at': '2026-01-01T00:00:00+00:00', 'expires_at': '2026-01-01T00:15:00+00:00',
               'bindings': {'light.room': 'a'*64}}
        doc['sha256'] = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        queued = {'id': identifier, 'status': 'queued', 'sha256': doc['sha256'], 'confirmation_required': True}
        client = FakeClient(reply=queued)
        self.assertEqual(c.handle_tool('propose_home_automation', {'spec': spec}, client)['response'], queued)
        self.assertEqual(client.calls[-1], ('propose', spec))
        client.reply = {'id': identifier, 'status': 'uncertain', 'recorded_status': 'pending',
                        'proposal': doc, 'observed_at': '2026-01-01T01:00:00+00:00', 'verified_at': None}
        result = c.handle_tool('get_home_proposal', {'proposal_id': identifier}, client)
        self.assertEqual(result['response'], client.reply)
        self.assertIs(result['device_state_verified'], False)
        self.assertEqual(c.handle_tool('control_home_device', {'action': action}, FakeClient(reply=queued))['response'], queued)
        for bad in [{}, {'status': 'success'}, dict(queued, confirmation_required=False), dict(queued, id='../x'), dict(queued, sha256='bad')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                c.handle_tool('propose_home_automation', {'spec': spec}, FakeClient(reply=bad))
        for bad in [{}, dict(client.reply, id='house_manager_general_'+'b'*32),
                    dict(client.reply, proposal=dict(doc, sha256='b'*64)),
                    dict(client.reply, status='verified_enabled'), dict(client.reply, observed_at='yesterday')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                c.handle_tool('get_home_proposal', {'proposal_id': identifier}, FakeClient(reply=bad))
        unavailable = FakeClient(dict(capabilities(), approval_ready=False), queued)
        with self.assertRaises(ValueError):
            c.handle_tool('propose_home_automation', {'spec': spec}, unavailable)
        self.assertEqual(unavailable.calls, [('capabilities',)])

    def test_stdio_protocol_and_sanitized_tool_errors(self):
        import general_connector_v3 as c
        import io
        import json
        import subprocess
        import sys
        calls = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'get_home_capabilities', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'get_home_capabilities', 'arguments': {'url': 'secret-value'}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'approve'},
            {'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'control_home_device', 'arguments': {}}},
        ]
        wire = ''.join(json.dumps(item) + chr(10) for item in calls)
        output = io.StringIO()
        client = FakeClient()
        c.serve(io.BytesIO(wire.encode()), output, client)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['id'] for r in responses], [1, 2, 3, 4, 5])
        self.assertEqual(responses[0]['result']['serverInfo']['name'], 'house-manager-general-v3')
        self.assertEqual(len(responses[1]['result']['tools']), 12)
        self.assertIs(responses[2]['result']['isError'], False)
        self.assertIs(responses[3]['result']['isError'], True)
        self.assertNotIn('secret-value', output.getvalue())
        self.assertEqual(responses[4]['error']['code'], -32601)
        self.assertEqual(client.calls, [('capabilities',)])
        proc = subprocess.run([sys.executable, str(PATH)], input=json.dumps(calls[2])+chr(10), text=True, capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, '')
        self.assertEqual(len(json.loads(proc.stdout)['result']['tools']), 12)
        for raw in [b'[]\n', b'{broken}\n', b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n', b'x' * (c.MAX_REQUEST + 1)]:
            output = io.StringIO()
            c.serve(io.BytesIO(raw), output, client)
            self.assertIn('error', json.loads(output.getvalue()))

    def test_fan_percentage_contract_uses_exact_integers(self):
        import general_connector_v3 as c
        from custom_components.house_manager_general import policy
        from unittest.mock import patch
        inv = {'fan.room': {'entity_id': 'fan.room', 'state': 'on',
               'attributes': {'supported_features': 63, 'percentage_step': 10},
               'registry_fingerprint': 'a'*64, 'name': 'Dyson'}}
        for service in ('fan.turn_on', 'fan.set_percentage'):
            form = next(f for f in c.ACTION_SCHEMA['oneOf'] if service in f['properties']['action']['enum'])
            self.assertEqual(form['properties']['data']['properties']['percentage']['type'], 'integer')
            for value in (40, 40.0, 33.3, True):
                request = {'action': service, 'target': {'entity_id': 'fan.room'}, 'data': {'percentage': value}}
                with self.subTest(service=service, value=value):
                    client = c.HAClient('offline-placeholder')
                    with patch.object(client, '_request', side_effect=lambda method, path, body: policy.validate_action(body['action'], inv)) as send:
                        if type(value) is int:
                            self.assertEqual(client.control(request)['action'], request)
                        else:
                            with self.assertRaises(policy.PolicyError):
                                policy.validate_action(request, inv)
                            with self.assertRaises(ValueError):
                                client.control(request)
                            send.assert_not_called()

    def test_climate_temperature_contract_excludes_ranges(self):
        import general_connector_v3 as c
        from custom_components.house_manager_general import policy
        from unittest.mock import patch
        inv = {'climate.room': {'entity_id': 'climate.room', 'state': 'on',
               'attributes': {'supported_features': 3, 'min_temp': 1, 'max_temp': 37,
                              'hvac_modes': ['off', 'heat']},
               'registry_fingerprint': 'a'*64, 'name': 'Dyson'}}
        cases = [({'temperature': 22}, True),
                 ({'temperature': 22, 'hvac_mode': 'heat'}, True),
                 ({'target_temp_low': 18, 'target_temp_high': 24}, False),
                 ({'temperature': 22, 'target_temp_low': 18, 'target_temp_high': 24}, False)]
        for data, allowed in cases:
            request = {'action': 'climate.set_temperature',
                       'target': {'entity_id': 'climate.room'}, 'data': data}
            with self.subTest(data=data):
                client = c.HAClient('offline-placeholder')
                with patch.object(client, '_request', side_effect=lambda method, path, body: policy.validate_action(body['action'], inv)) as send:
                    if allowed:
                        self.assertEqual(client.control(request)['action'], request)
                    else:
                        with self.assertRaises(policy.PolicyError):
                            policy.validate_action(request, inv)
                        with self.assertRaises(ValueError):
                            client.control(request)
                        send.assert_not_called()
        forms = [f for f in c.ACTION_SCHEMA['oneOf'] if 'climate.set_temperature' in f['properties']['action']['enum']]
        self.assertEqual(len(forms), 1)
        self.assertEqual(set(forms[0]['properties']['data']['properties']), {'temperature', 'hvac_mode'})

    def test_general_families_require_parameter_data_and_support_color_forms(self):
        import general_connector_v3 as c
        cases = [
            ('light.turn_on', {'xy_color': [0.2, 0.3]}),
            ('fan.set_percentage', {'percentage': 40}),
            ('fan.set_preset_mode', {'preset_mode': 'auto'}),
            ('fan.oscillate', {'oscillating': True}),
            ('fan.set_direction', {'direction': 'reverse'}),
            ('media_player.volume_set', {'volume_level': 0.5}),
            ('media_player.volume_mute', {'is_volume_muted': True}),
            ('media_player.select_source', {'source': 'HDMI 1'}),
            ('media_player.select_sound_mode', {'sound_mode': 'Standard'}),
            ('select.select_option', {'option': 'Off'}),
            ('number.set_value', {'value': 12}),
            ('climate.set_temperature', {'temperature': 21}),
            ('climate.set_hvac_mode', {'hvac_mode': 'heat'}),
            ('climate.set_fan_mode', {'fan_mode': 'auto'}),
            ('climate.set_swing_mode', {'swing_mode': 'on'}),
            ('climate.set_preset_mode', {'preset_mode': 'eco'}),
        ]
        for service, data in cases:
            action = {'action': service, 'target': {'entity_id': service.split('.')[0]+'.room'}, 'data': data}
            with self.subTest(service=service, data=data):
                c.validate(c.ACTION_SCHEMA, action)
                if service != 'light.turn_on':
                    without_data = dict(action)
                    del without_data['data']
                    with self.assertRaises(ValueError):
                        c.validate(c.ACTION_SCHEMA, without_data)
        for data in [{}, {'hvac_mode': 'heat'}, {'target_temp_low': 20}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                c.validate(c.ACTION_SCHEMA, {'action': 'climate.set_temperature', 'target': {'entity_id': 'climate.room'}, 'data': data})

    def test_native_capabilities_domain_service_mapping(self):
        import general_connector_v3 as c
        caps = dict(capabilities(), supported_actions={'light': ['turn_on', 'turn_off']})
        action = {'action': 'light.turn_off', 'target': {'entity_id': 'light.room'}}
        client = FakeClient(caps, {'status': 'executed', 'confirmation_required': False, 'device_state_verified': False})
        self.assertEqual(c.handle_tool('get_home_capabilities', {}, client), caps)
        self.assertEqual(c.handle_tool('control_home_device', {'action': action}, client)['response'], client.reply)
        for supported in [{'light': 'turn_off'}, {'light': ['turn_off', 42]}, {'light': ['../shell']}, {'light': []}, {'shell_command': ['run']}]:
            with self.subTest(supported=supported), self.assertRaises(ValueError):
                c.validate_capabilities(dict(caps, supported_actions=supported))

    def test_transport_rejects_invalid_payloads_and_sizes_before_network(self):
        import general_connector_v3 as c
        from unittest.mock import Mock
        client = c.HAClient('test-token')
        client._opener = Mock()
        for operation in [lambda: client.control({'action': 'shell_command.run'}),
                          lambda: client.propose({'title': 'x', 'raw_yaml': 'x'}),
                          lambda: client._request('POST', '/action', {'action': 'x'*c.MAX_REQUEST}),
                          lambda: client._request('DELETE', '/proposals'),
                          lambda: client.get_proposal('house_manager_general_'+'A'*32)]:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()
        client._opener.open.assert_not_called()
        for raw in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                c.strict_json(raw)

    def test_cross_field_action_guards_and_unverified_results(self):
        import general_connector_v3 as c
        import copy
        caps = capabilities()
        good = {'action': 'light.turn_on', 'target': {'entity_id': 'light.room'}, 'data': {'brightness': 12}}
        for data in [{'brightness': 12, 'brightness_pct': 50}, {'rgb_color': [1, 2, 3], 'hs_color': [1, 2]}]:
            denied = FakeClient(caps)
            with self.subTest(data=data), self.assertRaises(ValueError):
                c.handle_tool('control_home_device', {'action': dict(good, data=data)}, denied)
            self.assertEqual(denied.calls, [('capabilities',)])
        for state in ['unavailable', 'unknown', '']:
            unavailable = copy.deepcopy(caps)
            unavailable['inventory']['light.room']['state'] = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                c.handle_tool('control_home_device', {'action': good}, FakeClient(unavailable))
        for reply in [{}, [], {'status': 'success'}, {'status': 'executed'},
                      {'status': 'executed', 'device_state_verified': True, 'confirmation_required': False},
                      {'status': 'executed', 'device_state_verified': False, 'confirmation_required': True}]:
            client = FakeClient(caps, reply)
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                c.handle_tool('control_home_device', {'action': good}, client)
            self.assertEqual(sum(call[0] == 'control' for call in client.calls), 1)

    def test_status_validates_bindings_and_lifetime_not_just_hash(self):
        import general_connector_v3 as c
        import hashlib
        import json
        identifier = 'house_manager_general_' + 'a'*32
        doc = {'version': 3, 'id': identifier, 'kind': 'action',
               'created_at': '2026-01-01T00:00:00+00:00', 'expires_at': '2026-01-01T00:15:00+00:00',
               'payload': {'action': 'light.turn_off', 'target': {'entity_id': 'light.room'}},
               'bindings': {'light.room': 'a'*64}}
        for changes in [{'bindings': {'light.other': 'a'*64}}, {'bindings': {'light.room': 'bad'}},
                        {'expires_at': '2026-01-02T00:15:00+00:00'}]:
            changed = dict(doc, **changes)
            changed['sha256'] = hashlib.sha256(json.dumps(changed, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            reply = {'id': identifier, 'status': 'executed', 'recorded_status': 'executed',
                     'proposal': changed, 'observed_at': '2026-01-02T01:00:00+00:00'}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                c.validate_status(reply, identifier)

    def test_valid_and_denied_literal_inputs(self):
        import general_connector_v3 as c
        good = {'action': 'light.turn_on', 'target': {'entity_id': 'light.room'}, 'data': {'brightness': 12}}
        c.validate(c.ACTION_SCHEMA, good)
        for change in [
            {'action': 'shell_command.run'}, {'target': {'area_id': 'room'}},
            {'target': {'entity_id': ['light.room']}}, {'data': {'brightness': True}},
            {'data': {'brightness': 256}}, {'data': {'rgb_color': [1, 2]}},
            {'data': {'unknown': 1}}, {'approved': True}, {'data': {'brightness': '{{x}}'}},
            {'target': {'entity_id': 'light.room/../x'}},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                c.validate(c.ACTION_SCHEMA, dict(good, **change))
        spec = {'title': 'Evening', 'triggers': [{'type': 'time', 'at': '21:00:00'}], 'actions': [good]}
        c.validate(c.SPEC_SCHEMA, spec)
        for change in [{'actions': []}, {'actions': [good] * 21}, {'title': 'x'*161},
                       {'triggers': [{'type': 'time', 'at': '25:00:00'}]}, {'enabled': True}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                c.validate(c.SPEC_SCHEMA, dict(spec, **change))

    def test_twelve_strict_tools(self):
        self.assertTrue(PATH.exists(), 'v3 connector is missing')
        import general_connector_v3 as c
        self.assertEqual({t['name'] for t in c.TOOLS}, {
            'get_home_capabilities', 'control_home_device',
            'propose_home_automation', 'get_home_proposal', 'list_managed_home_automations', 'get_managed_home_automation', 'propose_home_automation_edit',
            'set_managed_home_automation_state', 'get_home_diagnostics', 'check_home_configuration',
            'get_home_workload_health', 'restart_home_assistant'})
        for tool in c.TOOLS:
            self.assertIs(tool['inputSchema']['additionalProperties'], False)
        self.assertIn('oneOf', c.ACTION_SCHEMA)


if __name__ == '__main__':
    unittest.main()
