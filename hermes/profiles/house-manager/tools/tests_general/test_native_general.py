import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from custom_components.house_manager_general import native

class NativeTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_is_registered_only_and_attribute_allowlisted(self):
        entry = NS(entity_id='fan.test', id='r', unique_id='u', config_entry_id='c', device_id='d', platform='test', area_id=None, name=None, original_name='Fan', disabled_by=None)
        device = NS(id='d', identifiers={('test','d')}, connections=set(), manufacturer='Dyson', model='Fan', name='Ventilation', name_by_user=None, area_id=None)
        er = NS(entities={'r':entry}, async_get=lambda key:entry)
        dr = NS(async_get=lambda key:device)
        ar = NS(async_get_area=lambda key:None)
        modules = {'homeassistant.helpers.entity_registry':NS(async_get=lambda h:er), 'homeassistant.helpers.device_registry':NS(async_get=lambda h:dr), 'homeassistant.helpers.area_registry':NS(async_get=lambda h:ar), 'homeassistant.const':NS(__version__='2026.11.1')}
        hass = NS(config=NS(time_zone='Australia/Melbourne'), states=NS(get=lambda key:NS(state='on',attributes={'preset_modes':['auto'],'token':'NEVER','friendly_name':'fan'})))
        boundary = native.NativeBoundary(hass, {}, NS(mutation_lock=asyncio.Lock()), None)
        with patch.object(native, 'import_module', side_effect=modules.__getitem__):
            caps = await boundary.capabilities()
        self.assertEqual(set(caps['inventory']), {'fan.test'})
        row = caps['inventory']['fan.test']
        self.assertEqual(row['device_name'], 'Ventilation')
        self.assertNotIn('token', row['attributes'])
        self.assertRegex(row['registry_fingerprint'], '^[0-9a-f]{64}$')

    async def test_native_feature_flags_are_plain_json_before_policy_validation(self):
        import enum
        import json
        from custom_components.house_manager_general import policy

        class FanFeature(enum.IntFlag):
            PRESET_MODE = 8
            TURN_OFF = 16
            TURN_ON = 32

        entry = NS(entity_id='fan.test', id='r', unique_id='u', config_entry_id='c',
                   device_id='d', platform='test', area_id=None, name=None,
                   original_name='Air purifier', disabled_by=None)
        device = NS(id='d', identifiers={('test', 'd')}, connections=set(),
                    manufacturer='Samsung', model='Purifier', name='Air purifier',
                    name_by_user=None, area_id=None)
        modules = {
            'homeassistant.helpers.entity_registry': NS(async_get=lambda h: NS(entities={'r': entry})),
            'homeassistant.helpers.device_registry': NS(async_get=lambda h: NS(async_get=lambda k: device)),
            'homeassistant.helpers.area_registry': NS(async_get=lambda h: NS(async_get_area=lambda k: None)),
            'homeassistant.const': NS(__version__='2026.11.1'),
        }
        features = FanFeature.PRESET_MODE | FanFeature.TURN_OFF | FanFeature.TURN_ON
        state = NS(state='off', attributes={'supported_features': features,
                   'preset_modes': ['auto', 'sleep'], 'preset_mode': 'sleep'})
        hass = NS(config=NS(time_zone='Australia/Melbourne'), states=NS(get=lambda k: state))
        boundary = native.NativeBoundary(hass, {}, NS(mutation_lock=asyncio.Lock()), None)
        with patch.object(native, 'import_module', side_effect=modules.__getitem__):
            caps = await boundary.capabilities()
        attrs = caps['inventory']['fan.test']['attributes']
        self.assertIs(type(attrs['supported_features']), int)
        self.assertEqual(attrs['supported_features'], 56)
        spec = {'title': '11 pm sleep', 'triggers': [{'type': 'time', 'at': '23:00:00'}],
                'actions': [{'action': 'fan.set_preset_mode',
                             'target': {'entity_id': 'fan.test'},
                             'data': {'preset_mode': 'sleep'}}]}
        doc = policy.make_proposal('automation', spec, caps['inventory'])
        self.assertEqual(doc['payload']['actions'][0]['data']['preset_mode'], 'sleep')
        self.assertEqual(caps, json.loads(json.dumps(caps)))
        # Normalize trusted HA attributes, not arbitrary incoming request types.
        speed_inventory = json.loads(json.dumps(caps['inventory']))
        speed_inventory['fan.test']['attributes'].update(supported_features=57, percentage_step=1)
        speed_action = {'action': 'fan.turn_on', 'target': {'entity_id': 'fan.test'},
                        'data': {'percentage': 32}}
        self.assertEqual(policy.validate_action(speed_action, speed_inventory)['action']['data'],
                         {'percentage': 32})
        speed_action['data']['percentage'] = FanFeature.TURN_ON
        with self.assertRaises(policy.PolicyError):
            policy.validate_action(speed_action, speed_inventory)

    async def test_native_mutations_use_original_lock_and_targeted_services(self):
        calls = []
        async def call(*args, **kwargs): calls.append((args,kwargs))
        async def executor(fn,*args): return fn(*args)
        rows = []
        def writer(path, value): rows[:] = value
        config = {'id':'house_manager_general_'+'a'*32}
        registry = NS(async_get_entity_id=lambda *args:'automation.actual')
        entity = NS(unique_id=config['id'], raw_config=config)
        hass = NS(config=NS(path=lambda path:'/isolated/'+path), async_add_executor_job=executor, services=NS(async_call=call), states=NS(get=lambda key:NS(state='on')), data={'component':NS(get_entity=lambda key:entity)})
        async def save(records): pass
        b = native.NativeBoundary(hass, {}, NS(mutation_lock=asyncio.Lock(),path='automations.yaml'), NS(async_save=save))
        async def validate(hass,key,value): self.assertEqual(key,config['id'])
        modules = {'homeassistant.components.config.view':NS(_read=lambda path:rows, _write=writer), 'homeassistant.components.automation.config':NS(async_validate_config_item=validate), 'homeassistant.helpers.entity_registry':NS(async_get=lambda h:registry), 'homeassistant.components.automation.const':NS(DATA_COMPONENT='component')}
        with patch.object(native,'import_module',side_effect=modules.__getitem__):
            with self.assertRaises(Exception): await b.write([config])
            async with b.lock:
                await b.validate(config)
                await b.write([config])
                self.assertEqual(await b.read(), [config])
                await b.reload(config['id'])
            with self.assertRaises(native.ApprovalError):
                await b.reload(config['id'])
            with self.assertRaises(native.ApprovalError):
                await b.reload_edit(config['id'])
            async with b.lock:
                self.assertEqual((await b.loaded(config['id']))['raw_config'],config)
                await b.enable('automation.actual')
            await b.execute({'action':'fan.turn_off','target':{'entity_id':'fan.test'},'data':{}})
        self.assertEqual(calls[0][0], ('automation','reload',{'id':config['id']}))
        self.assertEqual(calls[1][0], ('automation','turn_on',{'entity_id':'automation.actual'}))
        self.assertEqual(calls[2][0], ('fan','turn_off',{'entity_id':'fan.test'}))

    def test_discovery_accepts_only_exact_native_shared_view(self):
        class View:
            path = 'automations.yaml'
            mutation_lock = asyncio.Lock()
        view = View()
        def handler_for(view):
            async def handler(request): return view
            return handler
        routes = [NS(resource=NS(canonical='/api/config/automation/config/{config_key}'),method=m,handler=handler_for(view)) for m in ['GET','POST','DELETE']]
        self.assertIs(native.discover_native_view(routes, View), view)
        with self.assertRaises(Exception): native.discover_native_view(routes[:-1], View)
        settings = {'bot_user_id':'b'*32,'discord_token':'FAKE','discord_channel_id':'123','discord_user_id':'456'}
        self.assertEqual(native.validate_settings(settings), settings)
        with self.assertRaises(Exception): native.validate_settings(dict(settings, discord_user_id='*'))

    async def test_json_body_rejects_duplicate_keys_and_unknown_content(self):
        class Content:
            async def iter_chunked(self, n): yield b'{"action":1,"action":2}'
        request = NS(content_type='application/json',content_length=None,content=Content())
        with self.assertRaises(native.ApprovalError) as caught: await native.read_body(request)
        self.assertEqual(caught.exception.code, 'invalid_request')
        request.content_type = 'text/plain'
        with self.assertRaises(native.ApprovalError): await native.read_body(request)

    def test_identity_fingerprint_includes_classification_metadata(self):
        entry=NS(id='r',entity_id='fan.test',platform='x',unique_id='u',config_entry_id='c',device_id=None,name='Fan',original_name='Fan',area_id=None)
        first=native.fingerprint(entry,None)
        entry.name='Heater'
        self.assertNotEqual(first,native.fingerprint(entry,None))
        entry.device_id='missing'
        with self.assertRaises(native.ApprovalError): native.fingerprint(entry,None)

if __name__ == '__main__': unittest.main()
