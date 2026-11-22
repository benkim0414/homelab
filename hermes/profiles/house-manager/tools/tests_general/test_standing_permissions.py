"""Standing authority uses real policy and the existing no-device native boundary."""
import asyncio
import copy
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from custom_components.house_manager_general import policy as p
from custom_components.house_manager_general.engine import Manager, ApprovalError, STANDING_POLICY
from custom_components.house_manager_general.runtime import validate_records
from tests_general.test_manager_native import Boundary, BOT
from tests_general.test_edit_general import EditBoundary, SPEC

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def inventory():
    return {
        'light.test': {'entity_id':'light.test', 'state':'on', 'platform':'lifx', 'attributes':{},
                       'registry_fingerprint':'a'*64},
        'fan.test': {'entity_id':'fan.test', 'state':'off', 'platform':'smartthings', 'attributes':{
            'supported_features':63, 'percentage_step':10,
            'preset_mode':'auto', 'preset_modes':['auto', 'heat']},
            'registry_fingerprint':'b'*64},
        'switch.oven': {'entity_id':'switch.oven', 'state':'off', 'platform':'smartthings', 'attributes':{},
                        'registry_fingerprint':'c'*64},
        'climate.heater': {'entity_id':'climate.heater', 'state':'off', 'platform':'dyson_local',
            'attributes':{'supported_features':385, 'hvac_modes':['off', 'heat'],
                          'min_temp':10, 'max_temp':30}, 'registry_fingerprint':'d'*64},
    }


def setup(boundary=None, enabled=True, records=None):
    b = boundary or Boundary()
    b.inv = inventory()
    m = Manager(b, BOT.id, records or {}, now=lambda:NOW, standing_permissions=enabled)
    return b, m


def fan_action():
    return {'action':'fan.turn_on', 'target':{'entity_id':'fan.test'}, 'data':{'preset_mode':'auto'}}


class StandingTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_still_queues_and_needs_adapter(self):
        b, m = setup(enabled=False)
        with self.assertRaises(ApprovalError) as exc:
            await m.propose(BOT, {'spec':SPEC})
        self.assertEqual(exc.exception.code, 'approval_not_ready')
        m.approval_ready = True
        result = await m.propose(BOT, {'spec':SPEC})
        self.assertEqual(result['status'], 'queued')
        self.assertTrue(result['confirmation_required'])
        self.assertNotIn('approval', m.records[result['id']])
        self.assertNotIn('write', b.events)

    async def test_opt_in_create_has_policy_not_human_provenance_and_cannot_replay(self):
        b, m = setup()
        before = copy.deepcopy(b.rows)
        result = await asyncio.wait_for(m.propose(BOT, {'spec':SPEC}), 2)
        self.assertEqual(result['status'], 'verified_enabled')
        self.assertFalse(result['confirmation_required'])
        self.assertEqual(b.rows[0], before[0])
        record = m.records[result['id']]
        self.assertEqual(record['approval']['source'], 'standing_policy')
        self.assertEqual(record['approval']['policy_id'], STANDING_POLICY)
        self.assertEqual(record['approval']['sha256'], record['proposal']['sha256'])
        self.assertNotIn('message_id', record['preview'])
        self.assertNotIn('author_id', record['approval'])
        self.assertEqual((await m.status(BOT, result['id']))['status'], 'verified_enabled')
        self.assertEqual((await m.get_managed(BOT, result['id']))['owner_record_id'], result['id'])
        self.assertEqual(validate_records(m.records), m.records)
        events = b.events[:]
        with self.assertRaises(ApprovalError):
            await m.approve(result['id'], record['proposal']['sha256'])
        self.assertEqual(b.events, events)

    async def test_each_hazard_in_mixed_spec_still_queues(self):
        hazards = [
            {'action':'fan.turn_on', 'target':{'entity_id':'fan.test'}, 'data':{'preset_mode':'heat'}},
            {'action':'switch.turn_on', 'target':{'entity_id':'switch.oven'}},
            {'action':'climate.set_temperature', 'target':{'entity_id':'climate.heater'}, 'data':{'temperature':20}},
        ]
        for hazard in hazards:
            for position in range(3):
                with self.subTest(hazard=hazard, position=position):
                    b, m = setup(); m.approval_ready = True
                    spec = copy.deepcopy(SPEC)
                    spec['actions'] = [copy.deepcopy(SPEC['actions'][0]) for _ in range(3)]
                    spec['actions'][position] = hazard
                    result = await m.propose(BOT, {'spec':spec})
                    self.assertEqual(result['status'], 'queued')
                    self.assertTrue(result['confirmation_required'])
                    self.assertNotIn('write', b.events)
                    self.assertNotIn('approval', m.records[result['id']])
        b, m = setup()
        spec = copy.deepcopy(SPEC); spec['actions'] = [hazards[0]]
        with self.assertRaises(ApprovalError) as exc:
            await m.propose(BOT, {'spec':spec})
        self.assertEqual(exc.exception.code, 'approval_not_ready')

    async def test_fresh_gates_block_binding_state_policy_timezone_and_revocation_drift(self):
        for drift in ('binding', 'unavailable', 'heat', 'timezone', 'revoke'):
            for phase in ('save', 'prewrite'):
                with self.subTest(drift=drift, phase=phase):
                    b, m = setup()
                    spec = copy.deepcopy(SPEC); spec['actions'] = [fan_action()]
                    original_save, original_read, original_caps = b.save, b.read, b.capabilities
                    def mutate():
                        if drift == 'binding': b.inv['fan.test']['registry_fingerprint'] = 'e'*64
                        if drift == 'unavailable': b.inv['fan.test']['state'] = 'unavailable'
                        if drift == 'heat': b.inv['fan.test']['name'] = 'Heating fan'
                        if drift == 'revoke': m.standing_permissions = False
                    async def save(records):
                        await original_save(records)
                        if phase == 'save': mutate()
                    async def read():
                        rows = await original_read()
                        if phase == 'prewrite': mutate()
                        return rows
                    async def caps():
                        value = await original_caps()
                        if drift == 'timezone' and ((phase == 'save' and b.records) or (phase == 'prewrite' and b.lock.locked())):
                            value['time_zone'] = 'UTC'
                        return value
                    b.save, b.read, b.capabilities = save, read, caps
                    with self.assertRaises(ApprovalError):
                        await m.propose(BOT, {'spec':spec})
                    self.assertNotIn('write', b.events)
                    self.assertNotIn('reload', b.events)
                    record = next(iter(m.records.values()))
                    self.assertEqual(record['status'], 'uncertain')
                    with self.assertRaises(ApprovalError):
                        await m.approve(record['proposal']['id'], record['proposal']['sha256'])

    async def test_write_failure_and_restart_never_retry_or_auto_authorize_old_records(self):
        b, m = setup(); b.fail_write = True
        with self.assertRaises(ApprovalError): await m.propose(BOT, {'spec':SPEC})
        record = next(iter(m.records.values()))
        self.assertEqual(record['status'], 'uncertain')
        self.assertEqual(b.events.count('write'), 1)
        for status in ('queued', 'awaiting_approval', 'pending', 'uncertain'):
            doc = p.make_proposal('automation', SPEC, b.inv, now=NOW-timedelta(hours=1))
            legacy = {'status':status, 'proposal':doc}
            if status == 'awaiting_approval': legacy['preview'] = {'message_id':'1'}
            records = validate_records({doc['id']:legacy})
            before = copy.deepcopy(records)
            fresh = Manager(b, BOT.id, records, now=lambda:NOW, standing_permissions=True)
            events = b.events[:]
            await fresh.capabilities(BOT)
            await fresh.status(BOT, doc['id'])
            self.assertEqual(fresh.records, before)
            self.assertEqual(b.events, events)
        interrupted = copy.deepcopy(record)
        interrupted['status'] = 'awaiting_approval'
        self.assertEqual(validate_records({record['proposal']['id']:interrupted})[record['proposal']['id']]['status'], 'uncertain')

    def owned(self, state='off'):
        b = EditBoundary(); b.runtime_state = state
        b, m = setup(b)
        doc = p.make_proposal('automation', SPEC, b.inv, now=NOW-timedelta(hours=1))
        config = dict(p.validate_spec(SPEC, b.inv), id=doc['id'])
        b.rows.append(config)
        m.records[doc['id']] = {'status':'verified_enabled', 'proposal':doc,
            'preview':{'message_id':'1'}, 'approval':{'message_id':'2'},
            'verified_at':NOW.isoformat(), 'config_hash':p.hash_json(config)}
        body = {'target_id':doc['id'], 'base_config_hash':p.hash_json(config), 'spec':copy.deepcopy(SPEC)}
        body['spec']['triggers'][0]['at'] = '22:00:00'
        return b, m, doc['id'], body

    async def test_owned_edits_preserve_on_and_off_without_turn_on(self):
        for state in ('on', 'off'):
            b, m, target, body = self.owned(state)
            result = await asyncio.wait_for(m.propose_edit(BOT, body), 2)
            self.assertEqual(result['status'], 'verified_edit')
            self.assertEqual(result['runtime_state'], state)
            self.assertEqual(m.records[target]['status'], 'superseded')
            self.assertEqual(b.rows[-1]['id'], target)
            self.assertEqual(b.rows[-1]['triggers'][0]['at'], '22:00:00')
            self.assertFalse(any(event.startswith('enable') for event in b.events))
            self.assertNotIn('device', b.events)
            self.assertEqual(validate_records(m.records), m.records)

    async def test_owned_hazardous_edit_queues_and_unowned_or_stale_edit_fails(self):
        b, m, target, body = self.owned(); m.approval_ready = True
        body['spec']['actions'] = [{'action':'switch.turn_on', 'target':{'entity_id':'switch.oven'}}]
        result = await m.propose_edit(BOT, body)
        self.assertEqual(result['status'], 'queued')
        self.assertNotIn('write', b.events)
        for drift in ('owner', 'hash', 'config'):
            b, m, target, body = self.owned()
            if drift == 'owner': m.records[target]['status'] = 'uncertain'
            if drift == 'hash': body['base_config_hash'] = '0'*64
            if drift == 'config': b.rows[-1]['alias'] = 'operator edit'
            with self.assertRaises(ApprovalError): await m.propose_edit(BOT, body)
            self.assertNotIn('write', b.events)

    async def test_edit_rechecks_runtime_under_lock_and_failed_reload_is_uncertain(self):
        for drift in ('state', 'reload'):
            b, m, target, body = self.owned()
            if drift == 'state':
                original = b.save
                async def save(records):
                    await original(records)
                    b.runtime_state = 'on'
                b.save = save
            else:
                async def reload(identifier): b.runtime_state = 'on'
                b.reload_edit = reload
            with self.assertRaises(ApprovalError): await m.propose_edit(BOT, body)
            record = next(r for key, r in m.records.items() if key != target)
            self.assertEqual(record['status'], 'uncertain')
            if drift == 'state': self.assertNotIn('write', b.events)
            else: self.assertEqual(b.runtime_state, 'off')
            self.assertFalse(any(event.startswith('enable') for event in b.events))

    def state_fixture(self, state='off', action=None):
        b, m, target, edit = self.owned(state)
        if action is not None:
            spec = copy.deepcopy(SPEC); spec['actions'] = [action]
            doc = p.make_proposal('automation', spec, b.inv, now=NOW-timedelta(hours=1))
            doc['id'] = target
            doc['sha256'] = p.hash_json({k:v for k,v in doc.items() if k != 'sha256'})
            b.rows[-1] = dict(p.validate_spec(spec, b.inv), id=target)
            m.records[target].update(proposal=doc, config_hash=p.hash_json(b.rows[-1]))
        async def enable(entity):
            self.assertTrue(b.lock.locked())
            self.assertTrue(m.operation_lock.locked())
            b.events.append('enable:'+entity)
            b.runtime_state = 'on'
        b.enable = enable
        body = {'target_id':target, 'base_config_hash':m.records[target]['config_hash'], 'enabled':True}
        return b, m, target, body

    async def test_managed_state_toggles_verify_identity_config_and_never_trigger_actions(self):
        b, m, target, body = self.state_fixture()
        rows = copy.deepcopy(b.rows)
        for enabled in (True, False, False, True):
            body['enabled'] = enabled
            result = await m.set_managed_state(BOT, body)
            self.assertEqual(result['receipt_type'], 'managed_state')
            self.assertEqual(result['status'], 'verified_state')
            self.assertEqual(result['target_id'], target)
            self.assertEqual(result['runtime_state'], 'on' if enabled else 'off')
            self.assertEqual(result['authorization']['source'], 'standing_policy')
            self.assertNotIn('proposal', result)
            self.assertEqual(b.rows, rows)
            from general_connector_v3 import validate_status
            observed = validate_status(await m.status(BOT, target), target)
            self.assertEqual(observed['status'], 'verified_enabled' if enabled else 'changed')
            self.assertEqual((await m.get_managed(BOT, target))['runtime_state'], result['runtime_state'])
        self.assertEqual(b.events.count('disable:automation.managed'), 1)
        self.assertEqual(b.events.count('enable:automation.managed'), 2)
        self.assertNotIn('device', b.events)
        self.assertNotIn('write', b.events)
        self.assertFalse(any(event.startswith('reload') for event in b.events))
        self.assertEqual(validate_records(m.records), m.records)

    async def test_managed_state_hazard_enable_rejected_but_disable_allowed_even_unavailable(self):
        hazard = {'action':'switch.turn_on', 'target':{'entity_id':'switch.oven'}}
        for action in (hazard, dict(fan_action(), data={'preset_mode':'heat'})):
            b, m, target, body = self.state_fixture('on', action)
            with self.assertRaises(ApprovalError) as exc:
                await m.set_managed_state(BOT, body)
            self.assertEqual(exc.exception.code, 'approval_required')
            self.assertEqual(b.events, [])
            body['enabled'] = False
            b.inv[action['target']['entity_id']]['state'] = 'unavailable'
            result = await m.set_managed_state(BOT, body)
            self.assertEqual(result['runtime_state'], 'off')
            self.assertNotIn('device', b.events)

    async def test_managed_state_checks_opt_in_schema_ownership_hash_and_bindings(self):
        for drift in ('disabled', 'nonbool', 'extra', 'owner', 'hash', 'config', 'binding', 'unavailable', 'document'):
            b, m, target, body = self.state_fixture()
            if drift == 'disabled': m.standing_permissions = False
            if drift == 'nonbool': body['enabled'] = 1
            if drift == 'extra': body['force'] = True
            if drift == 'owner': m.records[target].pop('approval')
            if drift == 'hash': body['base_config_hash'] = '0'*64
            if drift == 'config': b.rows[-1]['alias'] = 'operator edit'
            if drift == 'binding': b.inv['light.test']['registry_fingerprint'] = 'f'*64
            if drift == 'unavailable': b.inv['light.test']['state'] = 'unavailable'
            if drift == 'document': m.records[target]['proposal']['payload']['title'] = 'tampered'
            with self.subTest(drift=drift):
                with self.assertRaises(ApprovalError): await m.set_managed_state(BOT, body)
                self.assertEqual(b.events, [])

    async def test_managed_state_rechecks_after_save_and_uncertainty_blocks_restart_retry(self):
        for drift in ('binding', 'heat', 'config', 'state', 'dispatch', 'readback'):
            b, m, target, body = self.state_fixture(action=fan_action())
            save, enable = b.save, b.enable
            async def changed_save(records):
                await save(records)
                if drift == 'binding': b.inv['fan.test']['registry_fingerprint'] = 'f'*64
                if drift == 'heat': b.inv['fan.test']['name'] = 'Heating fan'
                if drift == 'config': b.rows[-1]['alias'] = 'operator edit'
                if drift == 'state': b.runtime_state = 'on'
            async def changed_enable(entity):
                await enable(entity)
                if drift == 'dispatch': raise OSError('unknown dispatch result')
                if drift == 'readback': b.runtime_state = 'off'
            b.save, b.enable = changed_save, changed_enable
            with self.subTest(drift=drift):
                with self.assertRaises(ApprovalError) as exc:
                    await m.set_managed_state(BOT, body)
                self.assertEqual(exc.exception.code, 'uncertain_no_retry')
                self.assertEqual((await m.status(BOT, target))['status'], 'uncertain')
                records = validate_records(m.records)
                for status in ('pending', 'uncertain'):
                    records[target]['managed_state_operation']['status'] = status
                    restarted = Manager(b, BOT.id, records, now=lambda:NOW, standing_permissions=True)
                    events = b.events[:]
                    with self.assertRaises(ApprovalError): await restarted.set_managed_state(BOT, body)
                    self.assertEqual(b.events, events)
                if drift not in ('dispatch', 'readback'):
                    self.assertFalse(any(event.startswith('enable') for event in b.events))
                self.assertNotIn('device', b.events)

    async def test_managed_state_handles_verified_edit_receipt(self):
        b, m, target, edit = self.owned()
        edited = await m.propose_edit(BOT, edit)
        async def enable(entity): b.runtime_state = 'on'
        b.enable = enable
        result = await m.set_managed_state(BOT, {'target_id':target,
            'base_config_hash':edited['config_hash'], 'enabled':True})
        self.assertEqual(result['owner_record_id'], edited['id'])
        self.assertEqual(result['runtime_state'], 'on')
        from general_connector_v3 import validate_status
        self.assertEqual(validate_status(await m.status(BOT, edited['id']), edited['id'])['status'], 'changed')

    async def test_authorization_limits_and_input_opt_in_are_not_bypassed(self):
        for value in ('true', 1, None):
            with self.assertRaises(ValueError): Manager(Boundary(), BOT.id, {}, standing_permissions=value)
        b, m = setup()
        for user in (None, SimpleNamespace(id='stranger', is_admin=False), SimpleNamespace(id=BOT.id, is_admin=True)):
            with self.assertRaises(ApprovalError): await m.propose(user, {'spec':SPEC})
        with self.assertRaises(ApprovalError): await m.propose(BOT, {'spec':SPEC, 'standing_permissions':True})
        bad = copy.deepcopy(SPEC); bad['actions'].append({'action':'script.turn_on', 'target':{'entity_id':'script.unknown'}})
        with self.assertRaises(ApprovalError): await m.propose(BOT, {'spec':bad})
        self.assertEqual(b.events, [])
        await m.propose(BOT, {'spec':SPEC})
        with self.assertRaises(ApprovalError) as exc: await m.propose(BOT, {'spec':SPEC})
        self.assertEqual(exc.exception.code, 'proposal_rate_limit')
        b, m = setup(); m.records = {str(i):{} for i in range(1000)}
        with self.assertRaises(ApprovalError) as exc: await m.propose(BOT, {'spec':SPEC})
        self.assertEqual(exc.exception.code, 'ledger_full')


if __name__ == '__main__':
    unittest.main()
