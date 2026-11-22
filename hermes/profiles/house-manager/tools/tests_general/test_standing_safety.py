"""Pure persisted-authority regressions; no HA, network, or device writes."""
import copy
import unittest
from custom_components.house_manager_general import policy as p


class StandingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.inv = {
            'light.lamp': {'entity_id': 'light.lamp', 'state': 'off',
                'attributes': {}, 'registry_fingerprint': 'a'*64, 'platform': 'lifx'},
            'fan.purifier': {'entity_id': 'fan.purifier', 'state': 'off',
                'attributes': {'supported_features': 63, 'percentage_step': 10,
                    'preset_mode': 'auto', 'preset_modes': ['auto', 'ventilation', 'heat']},
                'registry_fingerprint': 'b'*64, 'platform': 'dyson_local'},
        }
        self.spec = {'title': 'Routine', 'triggers': [{'type': 'time', 'at': '22:00:00'}],
                     'actions': [self.action('light.turn_on', 'light.lamp')]}

    @staticmethod
    def action(command, entity, **data):
        return {'action': command, 'target': {'entity_id': entity}, 'data': data}

    def safe(self, action):
        spec = dict(self.spec, actions=[action])
        return p.standing_safe('automation', spec, self.inv)

    def edit(self):
        target = 'house_manager_general_' + 'c'*32
        native = dict(p.validate_spec(self.spec, self.inv), id=target)
        return {'target_id': target, 'base_config_hash': p.hash_json(native),
                'before': copy.deepcopy(native), 'after': copy.deepcopy(native),
                'spec': copy.deepcopy(self.spec), 'runtime_state': 'on'}

    def test_exact_direct_platforms_only_for_every_action(self):
        for platform in ('lifx', 'smartthings', 'dyson_local'):
            self.inv['light.lamp']['platform'] = platform
            self.assertTrue(p.standing_safe('automation', self.spec, self.inv))
        for platform in (None, '', 'template', 'group', 'proxy', 'unknown', 'LIFX', [], 1):
            self.inv['light.lamp']['platform'] = platform
            self.assertFalse(p.standing_safe('automation', self.spec, self.inv))
        self.inv['light.lamp'].pop('platform')
        self.assertFalse(p.standing_safe('automation', self.spec, self.inv))
        self.inv['light.lamp']['platform'] = 'lifx'
        self.inv['fan.purifier']['platform'] = 'template'
        mixed = dict(self.spec, actions=self.spec['actions'] + [self.action('fan.turn_off', 'fan.purifier')])
        self.assertFalse(p.standing_safe('automation', mixed, self.inv))

    def test_retained_heat_cannot_become_future_unapproved_heating(self):
        for mode in ('auto', 'heat', None):
            self.inv['fan.purifier']['attributes']['preset_mode'] = mode
            for command, data in (('turn_on', {}), ('turn_on', {'percentage': 40}),
                                  ('set_percentage', {'percentage': 40})):
                action = self.action('fan.' + command, 'fan.purifier', **data)
                self.assertFalse(self.safe(action))
        # Immediate auto-mode power remains compatible; persisted power does not.
        self.inv['fan.purifier']['attributes']['preset_mode'] = 'auto'
        action = self.action('fan.turn_on', 'fan.purifier')
        self.assertFalse(p.validate_action(action, self.inv)['confirmation_required'])
        self.assertFalse(self.safe(action))

    def test_explicit_validated_ventilation_and_stops_remain_safe(self):
        for preset in ('auto', 'ventilation'):
            for command in ('turn_on', 'set_preset_mode'):
                self.assertTrue(self.safe(self.action('fan.' + command, 'fan.purifier', preset_mode=preset)))
        self.assertTrue(self.safe(self.action('fan.turn_off', 'fan.purifier')))
        self.assertTrue(self.safe(self.action('fan.set_percentage', 'fan.purifier', percentage=0)))
        self.assertFalse(self.safe(self.action('fan.turn_on', 'fan.purifier', preset_mode='unadvertised')))
        self.inv['fan.purifier']['device_name'] = 'Boiler heater'
        self.assertFalse(self.safe(self.action('fan.turn_on', 'fan.purifier', preset_mode='ventilation')))
        self.inv['fan.purifier']['attributes']['preset_modes'] = ['auto']
        self.assertFalse(self.safe(self.action('fan.turn_on', 'fan.purifier')))

    def test_hot_cool_device_without_advertised_heat_is_not_persistently_safe(self):
        self.inv['fan.purifier']['device_name'] = 'Dyson Pure Hot + Cool Link'
        self.inv['fan.purifier']['attributes']['preset_modes'] = ['auto', 'normal']
        for data in ({}, {'preset_mode':'auto'}, {'percentage':40}):
            action = self.action('fan.turn_on', 'fan.purifier', **data)
            self.assertTrue(p.validate_action(action, self.inv)['confirmation_required'])
            self.assertFalse(self.safe(action))
        self.assertFalse(p.validate_action(self.action('fan.turn_off', 'fan.purifier'), self.inv)['confirmation_required'])
        self.assertTrue(self.safe(self.action('fan.turn_off', 'fan.purifier')))

    def test_boiler_light_requires_immediate_and_standing_approval(self):
        self.inv['light.lamp']['name'] = 'Boiler heating relay'
        action = self.spec['actions'][0]
        self.assertTrue(p.validate_action(action, self.inv)['confirmation_required'])
        self.assertFalse(self.safe(action))
        self.assertTrue(self.safe(self.action('light.turn_off', 'light.lamp')))

    def test_media_activation_also_respects_hazard_metadata(self):
        self.inv['media_player.relay'] = {'entity_id': 'media_player.relay', 'state': 'off',
            'attributes': {'supported_features': 384}, 'name': 'Oven controller',
            'platform': 'smartthings', 'registry_fingerprint': 'd'*64}
        self.assertFalse(self.safe(self.action('media_player.turn_on', 'media_player.relay')))
        self.assertTrue(self.safe(self.action('media_player.turn_off', 'media_player.relay')))

    def test_proxy_immediate_off_also_requires_approval_missing_legacy_is_compatible(self):
        for platform in ('template', 'group', 'proxy', 'unknown', None, [], 1):
            self.inv['light.lamp']['platform'] = platform
            for command in ('turn_on', 'turn_off'):
                action = self.action('light.' + command, 'light.lamp')
                self.assertTrue(p.validate_action(action, self.inv)['confirmation_required'])
        self.inv['light.lamp'].pop('platform')
        action = self.action('light.turn_off', 'light.lamp')
        self.assertFalse(p.validate_action(action, self.inv)['confirmation_required'])
        self.assertFalse(self.safe(action))

    def test_complete_spec_is_validated_and_function_does_not_mutate(self):
        before = copy.deepcopy((self.spec, self.inv))
        self.assertTrue(p.standing_safe('automation', self.spec, self.inv))
        self.assertEqual((self.spec, self.inv), before)
        for change in ({'variables': {}}, {'triggers': []}, {'conditions': [{'type': 'template'}]}, {'actions': []}):
            self.assertFalse(p.standing_safe('automation', dict(self.spec, **change), self.inv))
        for kind, payload in (('action', self.spec['actions'][0]), ('other', self.spec), ('automation', None), ('edit', {})):
            self.assertFalse(p.standing_safe(kind, payload, self.inv))

    def test_edit_canonical_shape_and_optional_null_initial_state(self):
        payload = self.edit()
        self.assertTrue(p.standing_safe('edit', payload, self.inv))
        for side in ('before', 'after'):
            payload[side]['initial_state'] = None
        payload['base_config_hash'] = p.hash_json(payload['before'])
        self.assertTrue(p.standing_safe('edit', payload, self.inv))
        # Canonical state triggers, durations, and conditions also round-trip.
        self.spec['triggers'] = [{'type': 'state', 'entity_id': 'light.lamp', 'to': 'on', 'for_seconds': 5}]
        self.spec['conditions'] = [{'type': 'state', 'entity_id': 'light.lamp', 'state': 'on'},
                                   {'type': 'time', 'after': '01:00:00', 'before': '23:00:00'}]
        self.assertTrue(p.standing_safe('edit', self.edit(), self.inv))

    def test_owned_before_extras_cannot_be_preserved_by_safe_edit(self):
        for key, value in (('variables', {'danger': '{{ states("sensor.test") }}'}),
                           ('trigger_variables', {}), ('description', 'extra'),
                           ('action', [{'service': 'script.hazard'}])):
            payload = self.edit()
            # Mirrors the real merge: both sides retain the extra, hash matches.
            for side in ('before', 'after'):
                payload[side][key] = copy.deepcopy(value)
            payload['base_config_hash'] = p.hash_json(payload['before'])
            self.assertFalse(p.standing_safe('edit', payload, self.inv))
        payload = self.edit()
        payload['before']['actions'][0]['data']['brightness'] = '{{ 1 }}'
        payload['base_config_hash'] = p.hash_json(payload['before'])
        self.assertFalse(p.standing_safe('edit', payload, self.inv))

    def test_after_extras_and_noncanonical_native_shape_rejected(self):
        for side in ('before', 'after'):
            for key, value in (('variables', {}), ('initial_state', True), ('initial_state', False),
                               ('mode', 'parallel'), ('alias', '{{ danger }}')):
                payload = self.edit()
                payload[side][key] = value
                payload['base_config_hash'] = p.hash_json(payload['before'])
                self.assertFalse(p.standing_safe('edit', payload, self.inv))
        payload = self.edit()
        payload['before']['triggers'][0]['variables'] = {'danger': '{{ 1 }}'}
        payload['base_config_hash'] = p.hash_json(payload['before'])
        self.assertFalse(p.standing_safe('edit', payload, self.inv))


if __name__ == '__main__':
    unittest.main()
