"""Offline, stdlib-only tests of the shared v3 policy contract."""
import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'custom_components/house_manager_general/policy.py'
loader = importlib.util.spec_from_file_location('general_policy', PATH)
assert loader is not None and loader.loader is not None
policy = importlib.util.module_from_spec(loader)
loader.loader.exec_module(policy)


def inventory(domain='light', name='Lamp', **attributes):
    entity = domain + '.test'
    return {entity: {'entity_id': entity, 'state': 'on', 'attributes': attributes,
                     'registry_fingerprint': 'a' * 64, 'name': name,
                     'area': 'Living room', 'device_name': name}}


def action(service='light.turn_off', data=None):
    return {'action': service, 'target': {'entity_id': service.split('.')[0] + '.test'},
            'data': {} if data is None else data}


class PolicyTests(unittest.TestCase):
    def test_concrete_light_off_is_direct_and_copied(self):
        self.assertIsNotNone(policy, 'policy implementation missing')
        request = action()
        result = policy.validate_action(request, inventory())
        self.assertEqual(result, {'action': request, 'confirmation_required': False})
        self.assertIsNot(result['action'], request)

    def test_exact_target_schema_and_availability_fail_closed(self):
        bad = [dict(action(), extra=True), action('homeassistant.restart'),
               dict(action(), target={'entity_id': ['light.test']}),
               dict(action(), target={'area_id': 'living'}),
               dict(action(), target={'entity_id': 'light.*'}),
               action(data={'entity_id': 'light.other'}), action(data={'x': '{{ bad }}'})]
        for request in bad:
            with self.subTest(request=request), self.assertRaises(policy.PolicyError):
                policy.validate_action(request, inventory())
        for state in ('unavailable', 'unknown', None, ''):
            inv = inventory()
            inv['light.test']['state'] = state
            with self.subTest(state=state), self.assertRaises(policy.PolicyError):
                policy.validate_action(action(), inv)
        request = action()
        del request['data']
        self.assertEqual(policy.validate_action(request, inventory())['action']['data'], {})

    def test_light_advertised_colors_brightness_and_temperature(self):
        inv = inventory(supported_color_modes=['hs', 'rgb', 'xy', 'color_temp'],
                        min_color_temp_kelvin=2500, max_color_temp_kelvin=9000)
        for data in ({}, {'brightness': 255}, {'brightness_pct': 50}, {'hs_color': [360, 100]},
                     {'rgb_color': [0, 128, 255]}, {'xy_color': [0.3, 0.5]},
                     {'color_temp_kelvin': 3000}):
            with self.subTest(data=data):
                self.assertFalse(policy.validate_action(action('light.turn_on', data), inv)['confirmation_required'])
        for data in ({'brightness': True}, {'brightness': 256}, {'brightness_pct': -1},
                     {'rgb_color': [0, 0, 999]}, {'hs_color': [361, 0]},
                     {'xy_color': [float('nan'), 0]}, {'color_temp_kelvin': 2000},
                     {'rgb_color': [1, 2, 3], 'hs_color': [0, 1]},
                     {'brightness': 1, 'brightness_pct': 1}, {'transition': 5}):
            with self.subTest(data=data), self.assertRaises(policy.PolicyError):
                policy.validate_action(action('light.turn_on', data), inv)
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(action('light.turn_on', {'brightness': 10}), inventory())

    def test_fan_controls_obey_features_options_and_steps(self):
        inv = inventory('fan', 'Dyson ventilation', supported_features=63,
                        percentage_step=10, preset_modes=['Auto', 'Sleep'])
        cases = [('turn_on', {}), ('turn_off', {}), ('set_percentage', {'percentage': 40}),
                 ('set_preset_mode', {'preset_mode': 'Auto'}),
                 ('oscillate', {'oscillating': True}), ('set_direction', {'direction': 'reverse'}),
                 ('turn_on', {'percentage': 50})]
        for service, data in cases:
            with self.subTest(service=service):
                self.assertFalse(policy.validate_action(action('fan.' + service, data), inv)['confirmation_required'])
        for service, data in [('set_percentage', {'percentage': 45}),
                              ('set_percentage', {'percentage': True}),
                              ('set_preset_mode', {'preset_mode': 'heat'}),
                              ('oscillate', {'oscillating': 1}),
                              ('set_direction', {'direction': 'up'})]:
            with self.subTest(service=service), self.assertRaises(policy.PolicyError):
                policy.validate_action(action('fan.' + service, data), inv)
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(action('fan.set_percentage', {'percentage': 40}), inventory('fan'))

    def test_media_player_features_ranges_and_options(self):
        features = 1 | 2 | 4 | 8 | 128 | 256 | 512 | 2048 | 4096 | 16384 | 65536
        inv = inventory('media_player', 'Movingstyle TV', supported_features=features,
                        source_list=['HDMI 1'], sound_mode_list=['Standard'])
        cases = [('turn_on', {}), ('turn_off', {}), ('media_play', {}), ('media_pause', {}),
                 ('media_stop', {}), ('volume_set', {'volume_level': 0.5}),
                 ('volume_mute', {'is_volume_muted': True}),
                 ('select_source', {'source': 'HDMI 1'}), ('select_sound_mode', {'sound_mode': 'Standard'})]
        for service, data in cases:
            with self.subTest(service=service):
                self.assertFalse(policy.validate_action(action('media_player.' + service, data), inv)['confirmation_required'])
            with self.subTest(unsupported=service), self.assertRaises(policy.PolicyError):
                policy.validate_action(action('media_player.' + service, data), inventory('media_player'))
        for service, data in [('volume_set', {'volume_level': 2}),
                              ('volume_mute', {'is_volume_muted': 'yes'}),
                              ('select_source', {'source': 'http://bad'}),
                              ('select_sound_mode', {'sound_mode': 'Other'}), ('play_media', {'media_content_id': 'x'})]:
            with self.subTest(service=service), self.assertRaises(policy.PolicyError):
                policy.validate_action(action('media_player.' + service, data), inv)

    def test_switch_select_number_schemas_and_conservative_classification(self):
        for domain, service, data, attrs in [
                ('switch', 'turn_on', {}, {}),
                ('select', 'select_option', {'option': 'Run'}, {'options': ['Run', 'Off']}),
                ('number', 'set_value', {'value': 2.5}, {'min': 0, 'max': 5, 'step': 0.5})]:
            with self.subTest(domain=domain):
                self.assertTrue(policy.validate_action(action(domain + '.' + service, data),
                                                       inventory(domain, 'Unknown', **attrs))['confirmation_required'])
        for name, required in [('Dryer wrinkle prevention', True), ('Samsung purifier night light', False),
                               ('Purifier continuous monitoring', False), ('Unknown switch', True),
                               ('Dyson heater night light', True)]:
            with self.subTest(name=name):
                self.assertEqual(policy.validate_action(action('switch.turn_on'), inventory('switch', name))['confirmation_required'], required)
                self.assertFalse(policy.validate_action(action('switch.turn_off'), inventory('switch', name))['confirmation_required'])
        inv = inventory('select', 'Dryer', options=['Run', 'Stop', 'Off', 'Pause'])
        for option in ('Stop', 'Off', 'Pause'):
            self.assertFalse(policy.validate_action(action('select.select_option', {'option': option}), inv)['confirmation_required'])
        for request, inv in [
                (action('number.set_value', {'value': 2.2}), inventory('number', min=0, max=5, step=0.5)),
                (action('number.set_value', {'value': True}), inventory('number', min=0, max=5, step=1)),
                (action('select.select_option', {'option': 'Other'}), inventory('select', options=['Run'])),
                (action('switch.toggle'), inventory('switch')),
                (action('button.press'), inventory('button'))]:
            with self.subTest(request=request), self.assertRaises(policy.PolicyError):
                policy.validate_action(request, inv)

    def test_climate_controls_are_bounded_and_activation_requires_approval(self):
        inv = inventory('climate', 'Dyson', supported_features=441,
                        hvac_modes=['off', 'cool', 'heat'], min_temp=1, max_temp=37,
                        fan_modes=['focus', 'diffuse'], swing_modes=['on', 'off'],
                        preset_modes=['eco'])
        for service, data, approval in [
                ('turn_on', {}, True), ('turn_off', {}, False),
                ('set_hvac_mode', {'hvac_mode': 'heat'}, True),
                ('set_hvac_mode', {'hvac_mode': 'off'}, False),
                ('set_temperature', {'temperature': 22}, True),
                ('set_temperature', {'temperature': 22, 'hvac_mode': 'off'}, True),
                ('set_fan_mode', {'fan_mode': 'focus'}, False),
                ('set_swing_mode', {'swing_mode': 'on'}, False),
                ('set_preset_mode', {'preset_mode': 'eco'}, True)]:
            with self.subTest(service=service, data=data):
                self.assertEqual(policy.validate_action(action('climate.' + service, data), inv)['confirmation_required'], approval)
        for service, data in [('set_temperature', {'temperature': 38}),
                              ('set_temperature', {'temperature': True}),
                              ('set_temperature', {'target_temp_high': 25}),
                              ('set_hvac_mode', {'hvac_mode': 'auto'}),
                              ('set_fan_mode', {'fan_mode': 'arbitrary'})]:
            with self.subTest(service=service), self.assertRaises(policy.PolicyError):
                policy.validate_action(action('climate.' + service, data), inv)
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(action('climate.turn_on'), inventory('climate'))

    def test_discovered_devices_preserve_ventilation_and_accessories(self):
        cases = [
            # Fan Auto/Normal attributes cannot prove this device's separate
            # climate entity has not retained heating.
            ('fan', 'Dyson Pure Hot + Cool Link', 'turn_on', {}, {'supported_features': 59}, True),
            ('fan', 'Air purifier', 'turn_on', {}, {'supported_features': 56}, False),
            ('fan', 'Air purifier', 'set_preset_mode', {'preset_mode': 'sleep'},
             {'supported_features': 56, 'preset_modes': ['auto', 'low', 'medium', 'high', 'sleep']}, False),
            ('switch', 'Dyson Pure Hot + Cool Link Focus Mode', 'turn_on', {}, {}, False),
            ('switch', 'Dyson Pure Hot + Cool Link Continuous Monitoring', 'turn_on', {}, {}, False),
            ('select', 'Air purifier Lamp', 'select_option', {'option': 'high'}, {'options': ['off', 'high']}, False),
            ('select', 'Dryer', 'select_option', {'option': 'run'}, {'options': ['stop', 'run', 'pause']}, True),
            ('switch', 'Dryer Wrinkle prevent', 'turn_on', {}, {}, True),
            ('climate', 'Dyson Pure Hot + Cool Link', 'set_temperature', {'temperature': 22},
             {'supported_features': 393, 'min_temp': 1, 'max_temp': 37}, True),
        ]
        for domain, name, service, data, attrs, required in cases:
            with self.subTest(name=name, service=service):
                self.assertEqual(policy.validate_action(action(domain + '.' + service, data),
                                 inventory(domain, name, **attrs))['confirmation_required'], required)
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(action('fan.set_percentage', {'percentage': 50}),
                                   inventory('fan', 'Air purifier', supported_features=56))

    def test_automation_compiles_daily_state_conditions_and_literal_actions(self):
        self.assertTrue(callable(getattr(policy, 'validate_spec', None)), 'spec validator missing')
        inv = inventory()
        inv.update(inventory('sensor', 'Temperature'))
        spec = {'title': 'Evening lights', 'triggers': [
            {'type': 'time', 'at': '20:00:00'},
            {'type': 'state', 'entity_id': 'sensor.test', 'to': '23', 'for_seconds': 30}],
            'conditions': [{'type': 'state', 'entity_id': 'sensor.test', 'state': '23'},
                           {'type': 'time', 'after': '19:00:00', 'before': '23:00:00'}],
            'actions': [action()]}
        native = policy.validate_spec(spec, inv)
        self.assertEqual(native, {'alias': 'Evening lights', 'mode': 'single',
            'triggers': [{'trigger': 'time', 'at': '20:00:00'},
                         {'trigger': 'state', 'entity_id': 'sensor.test', 'to': '23', 'for': {'seconds': 30}}],
            'conditions': [{'condition': 'state', 'entity_id': 'sensor.test', 'state': '23'},
                           {'condition': 'time', 'after': '19:00:00', 'before': '23:00:00'}],
            'actions': [action()]})
        native['actions'][0]['data']['mutated'] = True
        self.assertEqual(spec['actions'][0]['data'], {})

    def test_automation_rejects_unbounded_raw_templates_and_unknown_entities(self):
        base = {'title': 'Routine', 'triggers': [{'type': 'time', 'at': '20:00:00'}], 'actions': [action()]}
        invalid = [dict(base, title='x' * 161), dict(base, title='{{bad}}'), dict(base, initial_state=False),
                   dict(base, actions=[]), dict(base, actions=[action()] * 21),
                   dict(base, triggers=[]), dict(base, triggers=base['triggers'] * 11),
                   dict(base, conditions=[{'type': 'time', 'after': '10:00:00', 'before': '11:00:00'}] * 11)]
        for trigger in [{'type': 'time', 'at': '24:00:00'}, {'type': 'time', 'at': '7:00:00'},
                        {'type': 'template', 'value_template': '{{ true }}'},
                        {'type': 'state', 'entity_id': 'sensor.missing', 'to': 'on'},
                        {'type': 'state', 'entity_id': 'light.test', 'to': '{{x}}'},
                        {'type': 'state', 'entity_id': 'light.test', 'to': 'on', 'for_seconds': True},
                        {'type': 'state', 'entity_id': 'light.test', 'to': 'on', 'for_seconds': -1}]:
            invalid.append(dict(base, triggers=[trigger]))
        for condition in [{'type': 'time', 'after': 'bad', 'before': '10:00:00'},
                          {'type': 'state', 'entity_id': 'sensor.missing', 'state': 'on'},
                          {'type': 'state', 'entity_id': 'light.test', 'state': '{{bad}}'},
                          {'type': 'or', 'conditions': []}]:
            invalid.append(dict(base, conditions=[condition]))
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(policy.PolicyError):
                policy.validate_spec(spec, inventory())
        for domain in ('sensor', 'binary_sensor'):
            inv = inventory()
            inv.update(inventory(domain))
            valid = dict(base, triggers=[{'type': 'state', 'entity_id': domain + '.test', 'to': 'off'}])
            self.assertEqual(policy.validate_spec(valid, inv)['triggers'][0]['entity_id'], domain + '.test')

    def test_action_proposal_is_hashed_detached_and_expires_in_fifteen_minutes(self):
        self.assertTrue(callable(getattr(policy, 'make_proposal', None)), 'proposal factory missing')
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc)
        request = action()
        doc = policy.make_proposal('action', request, inventory(), now=now)
        self.assertRegex(doc['id'], r'^house_manager_general_[0-9a-f]{32}$')
        self.assertEqual(doc['version'], 3)
        self.assertEqual(doc['kind'], 'action')
        self.assertEqual(doc['payload'], request)
        self.assertEqual(doc['bindings'], {'light.test': 'a' * 64})
        self.assertEqual(datetime.fromisoformat(doc['created_at']), now)
        self.assertEqual(datetime.fromisoformat(doc['expires_at']), now + timedelta(minutes=15))
        self.assertEqual(doc['sha256'], policy.hash_json({k: v for k, v in doc.items() if k != 'sha256'}))
        request['data']['tamper'] = True
        self.assertEqual(doc['payload']['data'], {})
        checked = policy.validate_proposal(doc, inventory(), expected_hash=doc['sha256'], now=now)
        self.assertEqual(checked, doc)
        self.assertIsNot(checked, doc)

    def test_proposal_integrity_expiry_bindings_and_fresh_schema(self):
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        inv = inventory()
        doc = policy.make_proposal('action', action(), inv, now=now)
        for changes in ({'payload': action('light.turn_on')}, {'id': 'bad'}, {'kind': 'admin'},
                        {'version': True}, {'bindings': {}}, {'extra': 'bad'},
                        {'created_at': now.replace(tzinfo=None).isoformat()},
                        {'expires_at': (now + timedelta(hours=1)).isoformat()}):
            changed = dict(doc, **changes)
            with self.subTest(changes=changes), self.assertRaises(policy.PolicyError):
                policy.validate_proposal(changed, inv, expected_hash=doc['sha256'], now=now)
            changed['sha256'] = policy.hash_json({k: v for k, v in changed.items() if k != 'sha256'})
            # Even a newly hashed malformed document must fail structural checks.
            if 'payload' not in changes:
                with self.subTest(rehashed=changes), self.assertRaises(policy.PolicyError):
                    policy.validate_proposal(changed, inv, now=now)
        for moment in (now - timedelta(seconds=1), now + timedelta(minutes=15)):
            with self.subTest(moment=moment), self.assertRaises(policy.PolicyError):
                policy.validate_proposal(doc, inv, now=moment)
        with self.assertRaises(policy.PolicyError):
            policy.validate_proposal(doc, inv, expected_hash='b' * 64, now=now)
        inv['light.test']['registry_fingerprint'] = 'b' * 64
        with self.assertRaises(policy.PolicyError):
            policy.validate_proposal(doc, inv, now=now)
        for fingerprint in ('A' * 64, 'a' * 63, None):
            inv['light.test']['registry_fingerprint'] = fingerprint
            with self.subTest(fingerprint=fingerprint), self.assertRaises(policy.PolicyError):
                policy.make_proposal('action', action(), inv, now=now)
        inv = inventory(supported_color_modes=['hs'])
        doc = policy.make_proposal('action', action('light.turn_on', {'brightness': 50}), inv, now=now)
        inv['light.test']['attributes']['supported_color_modes'] = ['onoff']
        with self.assertRaises(policy.PolicyError):
            policy.validate_proposal(doc, inv, now=now)
        for kind in ('admin', None, True):
            with self.subTest(kind=kind), self.assertRaises(policy.PolicyError):
                policy.make_proposal(kind, action(), inventory(), now=now)

    def test_automation_proposals_bind_all_references_and_keep_spec_payload(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        inv = inventory()
        inv.update(inventory('sensor'))
        inv.update(inventory('binary_sensor'))
        spec = {'title': 'Routine', 'triggers': [{'type': 'state', 'entity_id': 'sensor.test', 'to': 'on'}],
                'conditions': [{'type': 'state', 'entity_id': 'binary_sensor.test', 'state': 'off'}],
                'actions': [dict(action(), data={})]}
        doc = policy.make_proposal('automation', spec, inv, now=now)
        self.assertEqual(doc['payload'], spec)
        self.assertEqual(set(doc['bindings']), {'light.test', 'sensor.test', 'binary_sensor.test'})
        self.assertEqual(policy.validate_proposal(doc, inv, now=now), doc)
        inv['binary_sensor.test']['registry_fingerprint'] = 'b' * 64
        with self.assertRaises(policy.PolicyError):
            policy.validate_proposal(doc, inv, now=now)
        spec['title'] = 'Changed'
        self.assertEqual(doc['payload']['title'], 'Routine')

    def test_swing_feature_uses_native_swing_bit_not_target_humidity(self):
        request = action('climate.set_swing_mode', {'swing_mode': 'on'})
        inv = inventory('climate', supported_features=32, swing_modes=['on', 'off'])
        self.assertFalse(policy.validate_action(request, inv)['confirmation_required'])
        inv['climate.test']['attributes']['supported_features'] = 4
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(request, inv)

    def test_hash_is_canonical_strict_json_without_python_type_aliases(self):
        self.assertEqual(policy.hash_json({'b': 2, 'a': 1}), policy.hash_json({'a': 1, 'b': 2}))
        self.assertNotEqual(policy.hash_json({'a': 1}), policy.hash_json({'a': True}))
        circular = []
        circular.append(circular)
        for value in ({1: 'numeric key'}, (1, 2), {'x': float('inf')}, {'x': object()}, circular):
            with self.subTest(type=type(value)), self.assertRaises(policy.PolicyError):
                policy.hash_json(value)

    def test_hazardous_fan_zero_speed_and_explicit_stop_presets_are_direct(self):
        inv = inventory('fan', 'Heater fan', supported_features=63, percentage_step=10,
                        preset_modes=['off', 'pause', 'heat'])
        for request in (action('fan.set_percentage', {'percentage': 0}),
                        action('fan.set_preset_mode', {'preset_mode': 'off'}),
                        action('fan.set_preset_mode', {'preset_mode': 'pause'})):
            with self.subTest(request=request):
                self.assertFalse(policy.validate_action(request, inv)['confirmation_required'])
        self.assertTrue(policy.validate_action(action('fan.set_percentage', {'percentage': 10}), inv)['confirmation_required'])
        self.assertTrue(policy.validate_action(action('fan.turn_on'), inv)['confirmation_required'])

    def test_maintenance_controls_are_denied_even_when_advertised(self):
        cases = [(action('switch.turn_on'), inventory('switch', 'Factory reset')),
                 (action('select.select_option', {'option': 'Restart'}),
                  inventory('select', 'Purifier', options=['Restart'])),
                 (action('number.set_value', {'value': 1}),
                  inventory('number', 'Filter reset', min=0, max=1, step=1)),
                 (action('select.select_option', {'option': '{% bad %}'}),
                  inventory('select', options=['{% bad %}']))]
        for request, inv in cases:
            with self.subTest(request=request, inv=inv), self.assertRaises(policy.PolicyError):
                policy.validate_action(request, inv)

    def test_fresh_inventory_identity_and_numeric_advertisements_fail_closed(self):
        for fingerprint in (None, 'A' * 64, 'a' * 63):
            inv = inventory()
            inv['light.test']['registry_fingerprint'] = fingerprint
            with self.subTest(fingerprint=fingerprint), self.assertRaises(policy.PolicyError):
                policy.validate_action(action(), inv)
        for attrs in ({'supported_color_modes': None}, {'supported_color_modes': ['mystery']}):
            with self.subTest(attrs=attrs), self.assertRaises(policy.PolicyError):
                policy.validate_action(action('light.turn_on', {'brightness': 20}), inventory(**attrs))
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(action('number.set_value', {'value': 10 ** 1000}),
                                   inventory('number', min=0, max=100, step=1))

    def test_fan_percentage_requires_native_integer_type(self):
        inv = inventory('fan', 'Dyson', supported_features=63, percentage_step=10)
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(action('fan.set_percentage', {'percentage': 40.0}), inv)

    def test_read_only_unavailable_sensor_can_be_a_future_state_reference(self):
        inv = inventory()
        inv.update(inventory('sensor'))
        inv['sensor.test']['state'] = 'unavailable'
        spec = {'title': 'Recovery routine',
                'triggers': [{'type': 'state', 'entity_id': 'sensor.test', 'to': 'normal'}],
                'actions': [action()]}
        self.assertEqual(policy.validate_spec(spec, inv)['triggers'][0]['to'], 'normal')
        inv['light.test']['state'] = 'unavailable'
        with self.assertRaises(policy.PolicyError):
            policy.validate_spec(spec, inv)


if __name__ == '__main__':
    unittest.main()
