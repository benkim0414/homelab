"""Local HA 2026.11.1 chat-approval compatibility probe; no production access.
Run with .test-venv/bin/python tests_general/isolated_edit_runtime.py.
Only temporary config below this worktree and synthetic automation services.
"""
import asyncio
import copy
import json
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def deny(*args,**kwargs):
    raise AssertionError('network forbidden')

async def main():
    from aiohttp import web
    from homeassistant import loader
    from homeassistant.const import __version__
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntries, ConfigEntry
    from homeassistant.components.config.automation import async_setup as setup_native, EditAutomationConfigView
    from homeassistant.helpers import trigger, area_registry, category_registry, device_registry, entity_registry, floor_registry, issue_registry, label_registry, restore_state
    from homeassistant.helpers.storage import Store
    from homeassistant.setup import async_setup_component
    from custom_components.house_manager_general.native import NativeBoundary, discover_native_view
    from custom_components.house_manager_general.engine import Manager, ApprovalError
    from custom_components.house_manager_general.chat import ChatApprovals
    from custom_components.house_manager_general import policy as p
    assert __version__=='2026.11.1'
    parent=ROOT/'.test-state';parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        root=Path(directory)
        hass=HomeAssistant(str(root));hass.config.time_zone='Australia/Melbourne';hass.config.skip_pip=True
        app=web.Application()
        def register(view):view.register(hass,app,app.router)
        hass.http=NS(app=app,register_view=register)
        loader.async_setup(hass)
        await trigger.async_setup(hass)
        hass.config_entries=ConfigEntries(hass,{})
        await hass.config_entries.async_initialize()
        device_registry.async_setup(hass)
        await asyncio.gather(*(module.async_load(hass,load_empty=True) for module in [area_registry,category_registry,device_registry,entity_registry,floor_registry,issue_registry,label_registry,restore_state]))
        assert setup_native(hass)
        view=discover_native_view(app.router.routes(),EditAutomationConfigView)
        store=Store(hass,1,'isolated_edit',private=True,atomic_writes=True)
        boundary=NativeBoundary(hass,{},view,store)
        entry=ConfigEntry(version=1,minor_version=1,domain='isolated',title='Synthetic',data={},options={},source='user',unique_id='isolated',discovery_keys={},subentries_data=[])
        hass.config_entries._entries[entry.entry_id]=entry
        registry=entity_registry.async_get(hass)
        light=registry.async_get_or_create('light','isolated','lamp',config_entry=entry,suggested_object_id='isolated_light')
        hass.states.async_set(light.entity_id,'off',{})
        unowned=[{'id':'unrelated','alias':'Unrelated','initial_state':False,'triggers':[],'actions':[]}]
        (root/'configuration.yaml').write_text('automation: !include automations.yaml\n')
        async with boundary.lock:await boundary.write(copy.deepcopy(unowned))
        assert await async_setup_component(hass,'automation',{'automation':copy.deepcopy(unowned)})
        from homeassistant.components.automation.const import DATA_COMPONENT
        unrelated=await boundary.loaded('unrelated')
        unrelated_object=hass.data[DATA_COMPONENT].get_entity(unrelated['entity_id'])
        caps=await boundary.capabilities()
        spec={'title':'Synthetic managed lamp','triggers':[{'type':'time','at':'23:00:00'}],'actions':[{'action':'light.turn_off','target':{'entity_id':light.entity_id}}]}
        clock=[__import__('datetime').datetime.now(__import__('datetime').timezone.utc)]
        manager=Manager(boundary,'b'*32,{},now=lambda:clock[0]);manager.approval_ready=True
        bot=NS(id='b'*32,is_admin=False)
        human=NS(id='c'*32,is_admin=False,is_active=True)
        chat=ChatApprovals(manager,human.id)
        async def confirmation(identifier,sha):
            preview=await chat.get(human,identifier)
            return {'sha256':sha,'surface':'local_chat','session_id':'isolated_runtime',
                    'interaction_id':preview['interaction_id']}
        queued=await manager.propose(bot,{'spec':spec})
        target=queued['id'];calls=[];phase=['create'];expected_entity=[None]
        native_call=hass.services.async_call
        async def scoped_call(service_registry,domain,service,service_data=None,**kwargs):
            data=service_data or {}
            assert domain=='automation','device services forbidden'
            if service=='reload':
                assert data=={'id':target}
                assert boundary.lock.locked(), 'create/edit must hold native mutation lock through reload'
            elif service=='turn_on':assert phase[0]=='create' and boundary.lock.locked() and data=={'entity_id':expected_entity[0]}
            elif service=='turn_off':assert boundary.lock.locked() and data=={'entity_id':expected_entity[0],'stop_actions':False}
            else:raise AssertionError('prohibited service')
            calls.append({'service':service,'data':data,'locked':boundary.lock.locked()})
            result=await native_call(domain,service,service_data,**kwargs)
            if service=='reload':expected_entity[0]=(await boundary.loaded(target))['entity_id']
            return result
        manager.records[target].update(status='awaiting_approval',preview={'message_id':'1'})
        assert manager.records[target]['proposal']['expires_at'] is None
        clock[0]+=__import__('datetime').timedelta(days=3650)
        with patch.object(type(hass.services),'async_call',scoped_call):
            assert (await chat.get(human,target))['proposal']['sha256']==queued['sha256']
            await asyncio.wait_for(chat.approve(human,target,await confirmation(target,queued['sha256'])),30)
            assert manager.records[target]['approval']['transport']=='hermes_command'
            phase[0]='edit'
            states=[]
            for state in ('off','on'):
                # Synthetic setup: directly change only this temporary entity.
                entity=hass.data[DATA_COMPONENT].get_entity(expected_entity[0])
                if state=='off':await entity.async_turn_off()
                else:await entity.async_turn_on()
                await hass.async_block_till_done()
                assert (await boundary.loaded(target))['state']==state
                before=await manager.get_managed(bot,target)
                clock[0]+=__import__('datetime').timedelta(minutes=2)
                spec['triggers'][0]['at']='22:30:00' if state=='off' else '22:00:00'
                edit=await manager.propose_edit(bot,{'target_id':target,'base_config_hash':before['config_hash'],'spec':spec})
                manager.records[edit['id']].update(status='awaiting_approval',preview={'message_id':'3'})
                assert manager.records[edit['id']]['proposal']['expires_at'] is None
                clock[0]+=__import__('datetime').timedelta(days=3650)
                receipt=await asyncio.wait_for(chat.approve(human,edit['id'],await confirmation(edit['id'],edit['sha256'])),30)
                assert receipt['status']=='verified_edit' and receipt['runtime_state']==state
                loaded=await boundary.loaded(target)
                assert loaded['state']==state and loaded['entity_id']==expected_entity[0]
                async with boundary.lock:
                    rows=await boundary.read()
                    assert rows[:-1]==unowned and rows[-1]['id']==target
                    assert rows[-1]['actions']==before['config']['actions']
                    assert rows[-1]['triggers'][0]['at']==spec['triggers'][0]['at']
                    assert p.hash_json(json.loads(json.dumps(rows[-1])))==receipt['config_hash']
                assert await boundary.loaded('unrelated')==unrelated
                assert hass.data[DATA_COMPONENT].get_entity(unrelated['entity_id']) is unrelated_object
                states.append(state)
            assert (await store.async_load())[target]['status']=='superseded'
            await hass.async_block_till_done()
        print(json.dumps({'status':'PASS','approval_transport':'hermes_command','ha_version':__version__,'no_expiry_after_3650_days':True,'states_preserved':states,'exact_id_preserved':True,'unrelated_config_and_runtime_preserved':True,'device_calls':0,'network_calls':0,'services':calls,'deployment':False},sort_keys=True))

if __name__=='__main__':
    for name in ('connect','connect_ex','bind','listen'):setattr(socket.socket,name,deny)
    asyncio.run(main())
