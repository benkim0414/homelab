"""Stdlib tests for the general manager/native authority boundary."""
import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.house_manager_general.engine import Manager, ApprovalError

BOT = SimpleNamespace(id='b'*32, is_admin=False)

class Boundary:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.rows = [{'id':'existing', 'alias':'Untouched', 'initial_state':False}]
        self.records = {}
        self.events = []
        self.fail_write = False
        self.inv = {}
        self.runtime_state = None
    async def capabilities(self):
        return {'version':3, 'ha_version':'2026.11.1', 'time_zone':'Australia/Melbourne', 'inventory':self.inv}
    async def save(self, records):
        self.events.append('save:'+next(iter(records.values()))['status'])
        self.records = copy.deepcopy(records)
    async def read(self):
        assert self.lock.locked()
        return copy.deepcopy(self.rows)
    async def write(self, rows):
        assert self.lock.locked()
        self.events.append('write')
        if self.fail_write: raise OSError('private')
        self.rows = copy.deepcopy(rows)
    async def validate(self, config): pass
    async def reload(self, identifier):
        assert self.lock.locked()
        self.events.append('reload')
        # Installed HA acceptance: no initial_state means activation at reload.
        self.runtime_state = 'on'
    async def loaded(self, identifier):
        return {'entity_id':'automation.new', 'state':self.runtime_state, 'raw_config':copy.deepcopy(self.rows[-1])}
    async def enable(self, entity):
        assert self.lock.locked()
        self.events.append('enable:'+entity)
    async def execute(self, action): self.events.append('device')

class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_retained_fan_heat_requires_approval_before_activation(self):
        for ready, retained, modes in ((False, 'heat', ['auto', 'heat']),
                                        (True, 'heat', ['auto', 'heat']),
                                        (False, 'warm', []), (True, 'heating', [])):
            for data, service in (({}, 'turn_on'), ({'percentage': 40}, 'turn_on'),
                                  ({'percentage': 40}, 'set_percentage')):
                with self.subTest(ready=ready, service=service, data=data):
                    b = Boundary()
                    b.inv = {'fan.dyson': {'entity_id': 'fan.dyson', 'state': 'off',
                        'attributes': {'supported_features': 63, 'percentage_step': 10,
                                       'preset_mode': retained, 'preset_modes': modes},
                        'registry_fingerprint': 'a'*64, 'name': 'Dyson fan'}}
                    m = Manager(b, BOT.id, {})
                    m.approval_ready = ready
                    request = {'action': 'fan.' + service, 'target': {'entity_id': 'fan.dyson'}, 'data': data}
                    if ready:
                        result = await m.action(BOT, {'action': request})
                        self.assertEqual(result['status'], 'queued')
                    else:
                        with self.assertRaises(ApprovalError) as caught:
                            await m.action(BOT, {'action': request})
                        self.assertEqual(caught.exception.code, 'approval_not_ready')
                    self.assertNotIn('device', b.events)

    async def test_heating_capable_fan_unknown_modes_are_conservative(self):
        for mode in (None, '', 'unknown', 'unavailable', 'boost', 42):
            for service, data in (('turn_on', {}), ('turn_on', {'percentage': 40}),
                                  ('set_percentage', {'percentage': 40})):
                with self.subTest(mode=mode, service=service, data=data):
                    b = Boundary()
                    attrs = {'supported_features': 63, 'percentage_step': 10,
                             'preset_modes': ['auto', 'heat', 'boost']}
                    if mode is not None:
                        attrs['preset_mode'] = mode
                    b.inv = {'fan.dyson': {'entity_id': 'fan.dyson', 'state': 'off',
                        'attributes': attrs, 'registry_fingerprint': 'a'*64, 'name': 'Dyson'}}
                    m = Manager(b, BOT.id, {})
                    with self.assertRaises(ApprovalError) as caught:
                        await m.action(BOT, {'action': {'action': 'fan.' + service,
                            'target': {'entity_id': 'fan.dyson'}, 'data': data}})
                    self.assertEqual(caught.exception.code, 'approval_not_ready')
                    self.assertNotIn('device', b.events)

    async def test_fan_safety_and_validated_ventilation_remain_direct(self):
        cases = [
            ('heat', ['heat', 'auto', 'ventilation'], 'turn_off', {}),
            ('heat', ['heat', 'auto', 'ventilation'], 'set_percentage', {'percentage': 0}),
            ('heat', ['heat', 'auto', 'ventilation'], 'turn_on', {'percentage': 0}),
            ('heat', ['heat', 'auto', 'ventilation'], 'turn_on', {'preset_mode': 'auto'}),
            ('heat', ['heat', 'auto', 'ventilation'], 'turn_on', {'preset_mode': 'ventilation'}),
            ('heat', ['heat', 'auto', 'ventilation'], 'set_preset_mode', {'preset_mode': 'ventilation'}),
            ('auto', ['heat', 'auto'], 'turn_on', {}),
            ('auto', ['heat', 'auto'], 'set_percentage', {'percentage': 40}),
            (None, ['auto'], 'turn_on', {}),
            ('unknown', ['auto'], 'set_percentage', {'percentage': 40}),
        ]
        for current, modes, service, data in cases:
            with self.subTest(current=current, modes=modes, service=service, data=data):
                b = Boundary()
                b.inv = {'fan.dyson': {'entity_id': 'fan.dyson', 'state': 'off',
                    'attributes': {'supported_features': 63, 'percentage_step': 10,
                                   'preset_mode': current, 'preset_modes': modes},
                    'registry_fingerprint': 'a'*64, 'name': 'Dyson purifier'}}
                m = Manager(b, BOT.id, {})
                result = await m.action(BOT, {'action': {'action': 'fan.' + service,
                    'target': {'entity_id': 'fan.dyson'}, 'data': data}})
                self.assertEqual(result['status'], 'executed')
                self.assertEqual(b.events.count('device'), 1)
        # Only schema-validated advertised, exclusive preset overrides count.
        b = Boundary()
        b.inv = {'fan.dyson': {'entity_id': 'fan.dyson', 'state': 'off',
            'attributes': {'supported_features': 63}, 'registry_fingerprint': 'a'*64}}
        m = Manager(b, BOT.id, {})
        for data in ({'preset_mode': 'ventilation'}, {'preset_mode': 'auto', 'percentage': 40}):
            b.inv['fan.dyson']['attributes'].update(preset_mode='heat', preset_modes=['heat', 'auto'])
            b.events.clear()
            with self.assertRaises(ApprovalError) as caught:
                await m.action(BOT, {'action': {'action': 'fan.turn_on',
                    'target': {'entity_id': 'fan.dyson'}, 'data': data}})
            self.assertEqual(caught.exception.code, 'invalid_action')
            self.assertNotIn('device', b.events)

    async def test_direct_dispatch_refuses_fresh_heating_classification_drift(self):
        for ready in (False, True):
            for service, data in (('turn_on', {}), ('turn_on', {'percentage': 40}),
                                  ('set_percentage', {'percentage': 40})):
                with self.subTest(ready=ready, service=service, data=data):
                    class DriftBoundary(Boundary):
                        async def save(self, records):
                            await super().save(records)
                            self.inv['fan.dyson']['attributes']['preset_mode'] = 'heat'
                    b = DriftBoundary()
                    b.inv = {'fan.dyson': {'entity_id': 'fan.dyson', 'state': 'off',
                        'attributes': {'supported_features': 63, 'percentage_step': 10,
                                       'preset_mode': 'auto', 'preset_modes': ['auto', 'heat']},
                        'registry_fingerprint': 'a'*64, 'name': 'Dyson'}}
                    m = Manager(b, BOT.id, {})
                    m.approval_ready = ready
                    with self.assertRaises(ApprovalError):
                        await m.action(BOT, {'action': {'action': 'fan.' + service,
                            'target': {'entity_id': 'fan.dyson'}, 'data': data}})
                    self.assertNotIn('device', b.events)
                    record = next(iter(b.records.values()))
                    self.assertEqual(record['status'], 'uncertain')
                    self.assertIs(record['device_dispatch_attempted'], False)
                    self.assertNotIn('verified_at', record)

    async def test_fan_heating_modes_wait_for_human_approval(self):
        for service in ('set_preset_mode', 'turn_on'):
            for mode in ('heat', 'heating', 'warm', 'auto', 'ventilation'):
                with self.subTest(service=service, mode=mode):
                    b = Boundary()
                    b.inv = {'fan.dyson': {'entity_id': 'fan.dyson', 'state': 'on',
                        'attributes': {'supported_features': 63,
                                       'preset_modes': ['heat', 'heating', 'warm', 'auto', 'ventilation']},
                        'registry_fingerprint': 'a'*64, 'name': 'Dyson fan', 'device_name': 'Dyson'}}
                    m = Manager(b, BOT.id, {})
                    m.approval_ready = True
                    request = {'action': 'fan.' + service, 'target': {'entity_id': 'fan.dyson'},
                               'data': {'preset_mode': mode}}
                    result = await m.action(BOT, {'action': request})
                    if mode in ('auto', 'ventilation'):
                        self.assertEqual(result['status'], 'executed')
                        self.assertEqual(b.events.count('device'), 1)
                    else:
                        self.assertEqual(result['status'], 'queued')
                        self.assertNotIn('device', b.events)
                        record = m.records[result['id']]
                        record.update(status='awaiting_approval', preview={'message_id': '42'})
                        approved = await m.approve(result['id'], result['sha256'])
                        self.assertEqual(approved['status'], 'executed')
                        self.assertEqual(b.events.count('device'), 1)

    async def test_approved_create_is_atomic_append_enable_and_receipt(self):
        from custom_components.house_manager_general import engine
        b = Boundary(); m = Manager(b, BOT.id, {})
        doc = {'id':'house_manager_general_'+'a'*32, 'kind':'automation', 'sha256':'c'*64, 'payload':{'alias':'New','triggers':[], 'actions':[], 'mode':'single'}, 'bindings':{}}
        m.records[doc['id']] = {'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}
        import hashlib, json
        fake_policy = SimpleNamespace(validate_spec=lambda d,*a,**k:d, validate_proposal=lambda d,*a,**k:d, hash_json=lambda d:hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest())
        with patch.object(engine, 'p', fake_policy):
            receipt = await m.approve(doc['id'], doc['sha256'])
        self.assertEqual(receipt['status'], 'verified_enabled')
        self.assertEqual(b.rows[0], {'id':'existing', 'alias':'Untouched', 'initial_state':False})
        self.assertNotIn('initial_state', b.rows[1])
        self.assertEqual(b.events, ['save:pending','write','reload','enable:automation.new','save:verified_enabled'])
        with self.assertRaises(ApprovalError): await m.approve(doc['id'], doc['sha256'])

    async def test_queue_is_persisted_and_bounded_without_discord_side_effect(self):
        from custom_components.house_manager_general import engine
        b = Boundary(); m = Manager(b, BOT.id, {})
        m.approval_ready = True
        doc = {'id':'house_manager_general_'+'d'*32, 'kind':'automation','sha256':'e'*64}
        with patch.object(engine.p, 'make_proposal', return_value=doc, create=True):
            queued = await m.propose(BOT, {'spec':{'title':'new'}})
            self.assertEqual(queued['status'], 'queued')
            self.assertEqual(b.records[doc['id']]['proposal'], doc)
            with self.assertRaises(ApprovalError): await m.propose(BOT, {'spec':{'title':'spam'}})
        self.assertEqual(b.events, ['save:queued'])
        stranger = SimpleNamespace(id='x'*32,is_admin=False)
        with self.assertRaises(ApprovalError): await m.capabilities(stranger)

    async def test_direct_low_risk_action_and_status_observation(self):
        from custom_components.house_manager_general import engine
        b = Boundary(); m = Manager(b, BOT.id, {})
        action = {'action':'fan.turn_off','target':{'entity_id':'fan.test'},'data':{}}
        b.inv={'fan.test':{'entity_id':'fan.test','state':'on','attributes':{'supported_features':48},'registry_fingerprint':'a'*64}}
        with patch.object(engine.p, 'validate_action', return_value={'action':action,'confirmation_required':False}):
            result = await m.action(BOT, {'action':action})
        self.assertEqual(result['status'], 'executed')
        self.assertFalse(result['device_state_verified'])
        self.assertEqual(b.events, ['save:pending','device','save:executed'])
        self.assertEqual(b.records[result['id']]['status'],'executed')
        identifier = 'house_manager_general_'+'f'*32
        m.records[identifier] = {'status':'uncertain','proposal':{'kind':'action'},'approval':{'message_id':'101'},'preview':{'message_id':'100'}}
        observed=await m.status(BOT,identifier)
        self.assertEqual(observed['recorded_status'],'uncertain')
        self.assertEqual(observed['evidence']['approval']['message_id'],'101')
        self.assertEqual(observed['evidence']['preview']['message_id'],'100')
        with self.assertRaises(ApprovalError): await m.status(BOT, 'v2-owned')

    async def test_real_policy_spec_compiles_before_native_create(self):
        from custom_components.house_manager_general import policy
        b=Boundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64,'name':'Lamp','area':None,'device_name':'Lamp'}}
        doc=policy.make_proposal('automation',{'title':'Daily lamp off','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        await m.approve(doc['id'],doc['sha256'])
        self.assertEqual(b.rows[-1]['alias'],'Daily lamp off')
        self.assertEqual(b.rows[-1]['triggers'],[{'trigger':'time','at':'21:00:00'}])
        self.assertNotIn('title',b.rows[-1])

    def test_rate_limit_survives_restart_from_ledger_created_time(self):
        from datetime import datetime,timezone
        now=datetime(2026,11,13,tzinfo=timezone.utc)
        identifier='house_manager_general_'+'a'*32
        m=Manager(Boundary(),BOT.id,{identifier:{'status':'queued','proposal':{'created_at':now.isoformat()}}},now=lambda:now)
        self.assertEqual(m.last_proposal_at,now)

    async def test_create_keeps_native_ui_writer_out_until_activation_and_readback(self):
        from custom_components.house_manager_general import policy
        class CompetingBoundary(Boundary):
            async def write(self, rows):
                await super().write(rows)
                async def native_ui_write():
                    async with self.lock:
                        self.rows[-1]['alias']='Concurrent UI edit'
                self.writer=asyncio.create_task(native_ui_write())
                await asyncio.sleep(0)
                self.writer_was_blocked=not self.writer.done()
            async def reload(self, identifier):
                await asyncio.sleep(0)
                self.activated_alias=self.rows[-1]['alias']
                await super().reload(identifier)
            async def enable(self, entity):
                self.enabled_alias=self.rows[-1]['alias']
                await super().enable(entity)
        b=CompetingBoundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        doc=policy.make_proposal('automation',{'title':'Approved routine','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        try:
            result=await m.approve(doc['id'],doc['sha256'])
        finally:
            await b.writer
        self.assertTrue(b.writer_was_blocked)
        self.assertEqual(result['status'],'verified_enabled')
        self.assertEqual(b.activated_alias,'Approved routine')
        self.assertEqual(b.enabled_alias,'Approved routine')
        self.assertEqual(b.rows[-1]['alias'],'Concurrent UI edit')

    async def test_reload_edit_drift_is_uncertain_after_reload_activation_without_explicit_enable_or_retry(self):
        from custom_components.house_manager_general import policy
        class DriftBoundary(Boundary):
            async def reload(self,identifier):
                await super().reload(identifier)
                self.rows[-1]['alias']='Admin edit'
        b=DriftBoundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        doc=policy.make_proposal('automation',{'title':'New','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        with self.assertRaises(ApprovalError): await m.approve(doc['id'],doc['sha256'])
        self.assertEqual(m.records[doc['id']]['status'],'uncertain')
        self.assertFalse(any(event.startswith('enable') for event in b.events))
        # The postreload check cannot undo/prevent the initial activation.
        self.assertEqual(b.runtime_state, 'on')
        events=b.events[:]
        with self.assertRaises(ApprovalError): await m.approve(doc['id'],doc['sha256'])
        self.assertEqual(b.events,events)

    async def test_native_prewrite_rechecks_fresh_policy_expiry_bindings_and_timezone_under_lock(self):
        from datetime import datetime, timezone, timedelta
        from custom_components.house_manager_general import policy
        for drift in ('policy', 'expiry', 'bindings', 'timezone', None):
            with self.subTest(drift=drift):
                clock = [datetime(2026, 11, 13, tzinfo=timezone.utc)]
                class PrewriteBoundary(Boundary):
                    zone = 'Australia/Melbourne'
                    fresh_under_lock = False
                    async def capabilities(self):
                        caps = await super().capabilities()
                        caps['time_zone'] = self.zone
                        self.fresh_under_lock = self.lock.locked()
                        return caps
                    async def read(self):
                        rows = await super().read()
                        if 'write' not in self.events:
                            self.fresh_under_lock = False
                            if drift == 'policy':
                                self.inv['fan.test']['attributes']['preset_modes'] = ['auto']
                            elif drift == 'expiry':
                                clock[0] += timedelta(minutes=15)
                            elif drift == 'bindings':
                                self.inv['fan.test']['registry_fingerprint'] = 'b'*64
                            elif drift == 'timezone':
                                self.zone = 'UTC'
                        return rows
                    async def write(self, rows):
                        assert self.fresh_under_lock, 'fresh check required after native read and before write'
                        await super().write(rows)
                b = PrewriteBoundary()
                b.inv = {'fan.test': {'entity_id': 'fan.test', 'state': 'on',
                    'attributes': {'supported_features': 63, 'preset_modes': ['heat', 'auto']},
                    'registry_fingerprint': 'a'*64, 'name': 'Dyson'}}
                doc = policy.make_proposal('automation', {'title': 'Daily fan',
                    'triggers': [{'type': 'time', 'at': '21:00:00'}],
                    'actions': [{'action': 'fan.set_preset_mode', 'target': {'entity_id': 'fan.test'},
                                 'data': {'preset_mode': 'heat'}}]}, b.inv, now=clock[0])
                if drift == 'expiry':
                    # Preserve coverage of legacy finite automation proposals.
                    doc['expires_at'] = (clock[0] + timedelta(seconds=900)).isoformat()
                    doc['sha256'] = policy.hash_json({k:v for k,v in doc.items() if k != 'sha256'})
                m = Manager(b, BOT.id, {doc['id']: {'status': 'awaiting_approval',
                    'proposal': doc, 'preview': {'message_id': '42'}}}, now=lambda: clock[0])
                if drift:
                    with self.assertRaises(ApprovalError):
                        await m.approve(doc['id'], doc['sha256'])
                    self.assertNotIn('write', b.events)
                    self.assertNotIn('reload', b.events)
                    self.assertIsNone(b.runtime_state)
                    self.assertEqual(m.records[doc['id']]['status'], 'uncertain')
                else:
                    self.assertEqual((await m.approve(doc['id'], doc['sha256']))['status'], 'verified_enabled')
                    self.assertEqual(b.runtime_state, 'on')

    async def test_timezone_drift_blocks_requests_before_any_effect(self):
        class WrongZone(Boundary):
            async def capabilities(self):
                caps=await super().capabilities(); caps['time_zone']='UTC'; return caps
        b=WrongZone(); m=Manager(b,BOT.id,{})
        with self.assertRaises(ApprovalError): await m.action(BOT,{'action':{}})
        with self.assertRaises(ApprovalError): await m.propose(BOT,{'spec':{}})
        self.assertEqual(b.events,[])

    async def test_promoted_bot_is_rejected_even_though_other_admins_may_read(self):
        m=Manager(Boundary(),BOT.id,{})
        with self.assertRaises(ApprovalError): await m.capabilities(SimpleNamespace(id=BOT.id,is_admin=True))
        self.assertEqual((await m.capabilities(SimpleNamespace(id='human',is_admin=True)))['version'],3)

    async def test_native_write_failure_is_tombstoned_and_duplicate_approvals_serialize(self):
        from custom_components.house_manager_general import policy
        b=Boundary(); b.fail_write=True
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        doc=policy.make_proposal('automation',{'title':'New','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        results=await asyncio.gather(m.approve(doc['id'],doc['sha256']),m.approve(doc['id'],doc['sha256']),return_exceptions=True)
        self.assertTrue(all(isinstance(result,ApprovalError) for result in results))
        self.assertEqual(b.events.count('write'),1)
        self.assertEqual(b.records[doc['id']]['status'],'uncertain')
        self.assertEqual(len(b.rows),1)

    async def test_existing_native_id_cannot_be_adopted_and_ledger_full_blocks_queue(self):
        from custom_components.house_manager_general import policy
        b=Boundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        doc=policy.make_proposal('automation',{'title':'New','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        b.rows.append({'id':doc['id'],'alias':'Operator owned'})
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        with self.assertRaises(ApprovalError): await m.approve(doc['id'],doc['sha256'])
        self.assertEqual(b.rows[-1]['alias'],'Operator owned')
        self.assertNotIn('write',b.events)
        m.records={str(i):{} for i in range(1000)}; m.approval_ready=True
        with self.assertRaises(ApprovalError) as caught: await m.propose(BOT,{'spec':{}})
        self.assertEqual(caught.exception.code,'ledger_full')

    async def test_ha_annotated_yaml_collections_compare_by_exact_json_content(self):
        from custom_components.house_manager_general import policy
        class YamlMap(dict): pass
        class YamlList(list): pass
        class AnnotatedBoundary(Boundary):
            async def read(self): return YamlList(YamlMap(row) for row in await super().read())
            async def loaded(self,identifier):
                value=await super().loaded(identifier); value['raw_config']=YamlMap(value['raw_config']); return value
        b=AnnotatedBoundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        doc=policy.make_proposal('automation',{'title':'New','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        self.assertEqual((await m.approve(doc['id'],doc['sha256']))['status'],'verified_enabled')

    async def test_postreload_timezone_drift_blocks_explicit_enable_not_reload_activation(self):
        from custom_components.house_manager_general import policy
        class ZoneDriftBoundary(Boundary):
            phase=False; zone='Australia/Melbourne'
            async def capabilities(self):
                caps=await super().capabilities(); caps['time_zone']=self.zone; return caps
            async def reload(self,identifier):
                await super().reload(identifier); self.phase=True
            async def read(self):
                rows=await super().read()
                if self.phase: self.zone='UTC'
                return rows
        b=ZoneDriftBoundary()
        b.inv={'light.test':{'entity_id':'light.test','state':'on','attributes':{},'registry_fingerprint':'a'*64}}
        doc=policy.make_proposal('automation',{'title':'New','triggers':[{'type':'time','at':'21:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':'light.test'}}]},b.inv)
        m=Manager(b,BOT.id,{doc['id']:{'status':'awaiting_approval','proposal':doc,'preview':{'message_id':'42'}}})
        with self.assertRaises(ApprovalError): await m.approve(doc['id'],doc['sha256'])
        self.assertFalse(any(event.startswith('enable') for event in b.events))
        # The postreload check cannot undo/prevent the initial activation.
        self.assertEqual(b.runtime_state, 'on')

if __name__ == '__main__': unittest.main()
