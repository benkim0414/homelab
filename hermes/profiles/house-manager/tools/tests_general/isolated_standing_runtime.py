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
    parent=Path(tempfile.gettempdir())
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
        light=registry.async_get_or_create('light','lifx','lamp',config_entry=entry,suggested_object_id='isolated_light')
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
        from general_connector_v3 import validate_standing_result
        manager=Manager(boundary,'b'*32,{},standing_permissions=True)
        bot=NS(id='b'*32,is_admin=False,is_active=True)
        calls=[]
        native_call=hass.services.async_call
        async def scoped_call(service_registry,domain,service,service_data=None,**kwargs):
            assert domain=='automation','physical device calls forbidden'
            assert service in ('reload','turn_on','turn_off')
            assert boundary.lock.locked()
            calls.append(service)
            return await native_call(domain,service,service_data,**kwargs)
        with patch.object(type(hass.services),'async_call',scoped_call):
            created=await manager.propose(bot,{'spec':spec})
            assert created['status']=='verified_enabled'
            assert created['authorization']['source']=='standing_policy'
            assert not manager.approval_ready,'routine must not need Discord'
            initial=await manager.get_managed(bot,created['id'])
            disabled=await manager.set_managed_state(bot,{'target_id':created['id'],
                'base_config_hash':initial['config_hash'],'enabled':False})
            assert disabled['runtime_state']=='off'
            manager.last_proposal_at=None
            edit_spec=copy.deepcopy(spec);edit_spec['triggers'][0]['at']='22:30:00'
            edited=await manager.propose_edit(bot,{'target_id':created['id'],
                'base_config_hash':initial['config_hash'],'spec':edit_spec})
            assert edited['status']=='verified_edit' and edited['runtime_state']=='off'
            current=await manager.get_managed(bot,created['id'])
            assert current['entity_id']==initial['entity_id']
            assert current['config']['triggers'][0]['at']=='22:30:00'
            enabled=await manager.set_managed_state(bot,{'target_id':created['id'],
                'base_config_hash':current['config_hash'],'enabled':True})
            assert enabled['runtime_state']=='on'
            async with boundary.lock:
                rows=await boundary.read()
                assert rows[:-1]==unowned
            assert await boundary.loaded('unrelated')==unrelated
            await hass.async_block_till_done()
        print(json.dumps({'status':'PASS','ha_version':__version__,'standing_create':True,
            'standing_edit_preserved_off':True,'owned_enable_disable':True,
            'exact_identity_preserved':True,'unrelated_preserved':True,
            'independent_approval_ready':False,'physical_device_calls':0,'network_calls':0,
            'native_automation_services':calls,'deployment':False},sort_keys=True))

if __name__=='__main__':
    for name in ('connect','connect_ex','bind','listen'):setattr(socket.socket,name,deny)
    asyncio.run(main())
