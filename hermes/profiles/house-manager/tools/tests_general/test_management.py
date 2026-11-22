"""Local boundary tests; no live services, storage or HA runtime."""
import copy
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from custom_components.house_manager_general import management as m
from custom_components.house_manager_general.engine import ApprovalError


class Storage:
    def __init__(self):
        self.config = {'require_admin': False}
        self.value = {'views': [{'title': 'Existing', 'cards': []}]}
        self.saves = []

    async def async_load(self, force):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.saves.append(copy.deepcopy(value))
        self.value = copy.deepcopy(value)


class ManagementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = NS(id='b' * 32, is_admin=False, is_active=True)
        self.states = {
            'input_boolean.routine': NS(state='off', attributes={}),
            'input_number.routine': NS(state='1', attributes={'min': 0, 'max': 10, 'step': 0.5}),
            'input_select.routine': NS(state='Quiet', attributes={'options': ['Quiet', 'Normal']}),
            'sensor.temperature': NS(state='20', attributes={}),
        }
        self.entries = {key: NS(id='registry_' + key, entity_id=key,
                               platform=key.split('.')[0], unique_id='unique_' + key,
                               disabled_by=None) for key in self.states}
        self.registry = NS(async_get=self.entries.get)
        self.entry = NS(entry_id='entry_one', domain='met', disabled_by=None, state=NS(value='loaded'))
        self.storage = Storage()
        self.calls = []

        async def call(domain, service, data, **kwargs):
            self.calls.append((domain, service, data, kwargs))
            state = self.states[data['entity_id']]
            state.state = ('on' if service == 'turn_on' else 'off') if domain == 'input_boolean' else str(data.get('value', data.get('option')))

        self.hass = NS(states=NS(get=self.states.get, async_all=lambda: list(self.states.values())),
                       services=NS(async_call=call), data={'lovelace': NS(dashboards={'routine-board': self.storage})},
                       config_entries=NS(async_get_entry=lambda key: self.entry if key == 'entry_one' else None,
                                         async_reload=AsyncMock(return_value=True)))
        self.modules = {'homeassistant.const': NS(__version__='2026.11.1'),
                        'homeassistant.helpers.entity_registry': NS(async_get=lambda hass: self.registry),
                        'homeassistant.components.lovelace.dashboard': NS(LovelaceStorage=Storage),
                        'homeassistant.components.lovelace.const': NS(LOVELACE_DATA='lovelace')}
        self.patcher = patch.object(m, 'import_module', side_effect=self.modules.__getitem__)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.manager = m.Management(self.hass, self.user.id,
                                   helper_bindings={key: entry.id for key, entry in self.entries.items() if key.startswith('input_')},
                                   reload_entries={'entry_one': 'met'}, dashboard_paths=('routine-board',))

    async def invoke(self, operation, **body):
        return await self.manager.request(self.user, dict(operation=operation, **body))

    async def test_three_typed_helper_values_and_readback(self):
        for operation, entity, value in [('set_boolean', 'input_boolean.routine', True),
                                         ('set_number', 'input_number.routine', 2.5),
                                         ('select_option', 'input_select.routine', 'Normal')]:
            result = await self.invoke(operation, entity_id=entity, value=value)
            self.assertEqual(result['status'], 'verified')
        self.assertEqual([(d, s) for d, s, _, _ in self.calls],
                         [('input_boolean', 'turn_on'), ('input_number', 'set_value'), ('input_select', 'select_option')])
        self.assertTrue(all(kwargs == {'blocking': True} for _, _, _, kwargs in self.calls))

    async def test_helper_validation_rejects_type_range_step_option_and_extra(self):
        for operation, entity, value in [('set_boolean', 'input_boolean.routine', 1),
                                         ('set_number', 'input_number.routine', True),
                                         ('set_number', 'input_number.routine', float('nan')),
                                         ('set_number', 'input_number.routine', float('inf')),
                                         ('set_number', 'input_number.routine', 11),
                                         ('set_number', 'input_number.routine', 1.1),
                                         ('select_option', 'input_select.routine', '{{secret}}'),
                                         ('set_boolean', 'input_number.routine', True)]:
            with self.subTest(value=value):
                with self.assertRaises(ApprovalError):
                    await self.invoke(operation, entity_id=entity, value=value)
        with self.assertRaises(ApprovalError):
            await self.invoke('set_boolean', entity_id='input_boolean.routine', value=True, service='restart')
        self.assertFalse(self.calls)

    async def test_unknown_unenrolled_and_registry_drift_refused(self):
        for key in ['input_boolean.other', 'switch.heater', 'input_boolean.*']:
            with self.assertRaises(ApprovalError):
                await self.invoke('set_boolean', entity_id=key, value=True)
        self.entries['input_boolean.routine'].id = 'replacement'
        with self.assertRaises(ApprovalError):
            await self.invoke('set_boolean', entity_id='input_boolean.routine', value=True)
        self.assertFalse(self.calls)

    async def test_auth_and_version_fail_before_read_or_write(self):
        for user in [None, NS(id='other', is_admin=True, is_active=True),
                     NS(id=self.user.id, is_admin=True, is_active=True),
                     NS(id=self.user.id, is_admin=False, is_active=False)]:
            with self.assertRaises(ApprovalError):
                await self.manager.request(user, {'operation': 'diagnostics'})
        self.modules['homeassistant.const'].__version__ = 'next'
        with self.assertRaises(ApprovalError):
            await self.invoke('set_boolean', entity_id='input_boolean.routine', value=True)
        self.assertFalse(self.calls)

    async def test_reload_only_enrolled_nonsecurity_entry_no_secret_reads(self):
        result = await self.invoke('reload_entry', entry_id='entry_one')
        self.assertEqual(result, {'status': 'verified', 'entry_id': 'entry_one', 'state': 'loaded'})
        self.hass.config_entries.async_reload.assert_awaited_once_with('entry_one')
        for domain in ['auth', 'hue', 'homekit', 'mqtt', 'lock', 'tailscale']:
            self.entry.domain = domain
            with self.assertRaises(ApprovalError):
                await self.invoke('reload_entry', entry_id='entry_one')
        with self.assertRaises(ApprovalError):
            await self.invoke('reload_entry', entry_id='other')
        self.assertEqual(self.hass.config_entries.async_reload.await_count, 1)

    async def test_reload_failure_is_not_success_or_automatically_retried(self):
        self.hass.config_entries.async_reload.return_value = False
        with self.assertRaises(ApprovalError) as caught:
            await self.invoke('reload_entry', entry_id='entry_one')
        self.assertEqual(caught.exception.code, 'management_uncertain')
        self.assertEqual(self.hass.config_entries.async_reload.await_count, 1)

    async def test_append_sensor_view_preserves_existing_and_disables_actions(self):
        before = copy.deepcopy(self.storage.value)
        result = await self.invoke('append_sensor_view', dashboard='routine-board',
                                   title='Temperatures', path='temperatures', entities=['sensor.temperature'])
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(self.storage.value['views'][:1], before['views'])
        card = self.storage.value['views'][-1]['cards'][0]
        self.assertFalse(card['show_header_toggle'])
        for action in ['tap_action', 'hold_action', 'double_tap_action']:
            self.assertEqual(card['entities'][0][action], {'action': 'none'})
        with self.assertRaises(ApprovalError):
            await self.invoke('append_sensor_view', dashboard='routine-board', title='Duplicate',
                              path='temperatures', entities=['sensor.temperature'])
        self.assertEqual(len(self.storage.saves), 1)

    async def test_dashboard_blocks_controls_yaml_admin_and_arbitrary_config(self):
        body = dict(dashboard='routine-board', title='Safe', path='safe', entities=['sensor.temperature'])
        for changes in [{'entities': ['switch.heater']}, {'entities': ['sensor.missing']},
                        {'dashboard': '../config'}, {'title': '{{states}}'}, {'cards': []},
                        {'entities': ['sensor.temperature', 'sensor.temperature']}]:
            with self.assertRaises(ApprovalError):
                await self.invoke('append_sensor_view', **dict(body, **changes))
        self.storage.config['require_admin'] = True
        with self.assertRaises(ApprovalError):
            await self.invoke('append_sensor_view', **body)
        self.assertFalse(self.storage.saves)

    async def test_diagnostics_only_counts_and_enrolled_status_no_attributes(self):
        self.states['sensor.temperature'].attributes['password'] = 'DO_NOT_RETURN'
        result = await self.invoke('diagnostics')
        self.assertNotIn('DO_NOT_RETURN', str(result))
        self.assertEqual(result['ha_version'], '2026.11.1')
        self.assertEqual(result['entity_count'], len(self.states))
        self.assertEqual(result['entries'], [{'entry_id': 'entry_one', 'domain': 'met', 'state': 'loaded'}])

    async def test_empty_enrollment_denies_every_mutation(self):
        manager = m.Management(self.hass, self.user.id)
        for body in [dict(operation='set_boolean', entity_id='input_boolean.routine', value=True),
                     dict(operation='reload_entry', entry_id='entry_one'),
                     dict(operation='append_sensor_view', dashboard='routine-board', title='Safe',
                          path='safe', entities=['sensor.temperature'])]:
            with self.assertRaises(ApprovalError):
                await manager.request(self.user, body)
        self.assertFalse(self.calls)
        self.assertFalse(self.storage.saves)
        self.hass.config_entries.async_reload.assert_not_awaited()
        for domain in ['mqtt', 'lock', 'hue', 'auth']:
            with self.assertRaises(ApprovalError):
                m.Management(self.hass, self.user.id, reload_entries={'entry_one': domain})

    async def test_helper_unavailable_disabled_and_bad_native_bounds(self):
        entity = 'input_number.routine'
        self.states[entity].state = 'unavailable'
        with self.assertRaises(ApprovalError):
            await self.invoke('set_number', entity_id=entity, value=2)
        self.states[entity].state = '1'
        self.entries[entity].disabled_by = 'user'
        with self.assertRaises(ApprovalError):
            await self.invoke('set_number', entity_id=entity, value=2)
        self.entries[entity].disabled_by = None
        self.states[entity].attributes['step'] = 0
        with self.assertRaises(ApprovalError):
            await self.invoke('set_number', entity_id=entity, value=2)
        self.assertFalse(self.calls)

    async def test_dashboard_failed_save_sanitized_and_not_retried(self):
        self.storage.async_save = AsyncMock(side_effect=RuntimeError('private URL'))
        with self.assertRaises(ApprovalError) as caught:
            await self.invoke('append_sensor_view', dashboard='routine-board', title='Safe',
                              path='safe', entities=['sensor.temperature'])
        self.assertEqual(caught.exception.code, 'management_uncertain')
        self.storage.async_save.assert_awaited_once()

    async def test_no_generic_operations(self):
        for operation in ['service', 'rest', 'websocket', 'template', 'delete_helper', 'automation_enable', 'options']:
            with self.assertRaises(ApprovalError):
                await self.invoke(operation)

    async def test_post_write_mismatch_and_exception_sanitized(self):
        self.hass.services.async_call = AsyncMock(return_value=None)
        with self.assertRaises(ApprovalError) as caught:
            await self.invoke('set_boolean', entity_id='input_boolean.routine', value=True)
        self.assertEqual(caught.exception.code, 'management_uncertain')
        self.hass.services.async_call = AsyncMock(side_effect=RuntimeError('private token'))
        with self.assertRaises(ApprovalError) as caught:
            await self.invoke('set_boolean', entity_id='input_boolean.routine', value=True)
        self.assertEqual(str(caught.exception), 'management_uncertain')


if __name__ == '__main__':
    unittest.main()
