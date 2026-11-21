import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from custom_components.house_manager_general import runtime

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_seven_authenticated_routes_no_approval(self):
        views=[]
        class View: pass
        hass=NS(http=NS(register_view=views.append))
        with patch.object(runtime,'import_module',side_effect=lambda name: NS(HomeAssistantView=View) if name=='homeassistant.components.http' else NS()):
            runtime.register_views(hass,NS())
        self.assertEqual({v.url for v in views},{'/api/house_manager_general/capabilities','/api/house_manager_general/action','/api/house_manager_general/proposals','/api/house_manager_general/proposals/{identifier}', '/api/house_manager_general/managed', '/api/house_manager_general/managed/{identifier}', '/api/house_manager_general/edits'})
        self.assertTrue(all(v.requires_auth for v in views))
        self.assertFalse(any(hasattr(v,'approve') for v in views))

    def test_ledger_load_tombstones_pending_and_rejects_unknown_ownership(self):
        identifier='house_manager_general_'+'a'*32
        doc={'id':identifier,'sha256':'b'*64,'created_at':'2026-11-13T00:00:00+00:00'}
        records=runtime.validate_records({identifier:{'status':'pending','proposal':doc}})
        self.assertEqual(records[identifier]['status'],'uncertain')
        with self.assertRaises(ValueError): runtime.validate_records({'house_manager_v2':{}})

    async def test_setup_uses_private_store_non_admin_and_stop_cleanup(self):
        from custom_components.house_manager_general import native, discord
        settings={'bot_user_id':'b'*32,'discord_token':'FAKE','discord_channel_id':'33','discord_user_id':'22'}
        captured={}; tasks=[]; events=[]
        class Store:
            def __init__(self,*args,**kwargs): captured.update(kwargs)
            async def async_load(self): return None
            async def async_save(self,records): pass
        async def user(identifier): return NS(is_admin=False,is_active=True)
        def create_task(coro, name):
            coro.close()
            tasks.append(name)
            return None
        def listen(event,callback): events.append(callback)
        hass=NS(data={},config=NS(time_zone='Australia/Melbourne'),auth=NS(async_get_user=user),http=NS(app=NS(router=NS(routes=lambda:[]))),async_create_background_task=create_task,bus=NS(async_listen_once=listen))
        modules={'homeassistant.const':NS(__version__='2026.11.1',EVENT_HOMEASSISTANT_STOP='stop'),'homeassistant.components.config.automation':NS(EditAutomationConfigView=object),'homeassistant.helpers.storage':NS(Store=Store)}
        with patch.object(runtime,'import_module',side_effect=modules.__getitem__), patch.object(native,'discover_native_view',return_value=NS(mutation_lock=asyncio.Lock())), patch.object(runtime,'register_views'):
            self.assertTrue(await runtime.setup(hass, {runtime.DOMAIN:settings}))
        self.assertEqual(captured,{'private':True,'atomic_writes':True})
        self.assertIn(runtime.DOMAIN,hass.data)
        self.assertEqual(len(tasks),1)
        self.assertEqual(len(events),1)
        self.assertFalse(hass.data[runtime.DOMAIN].approval_ready)
        await events[0](None)

    async def test_package_delegates_setup(self):
        from custom_components import house_manager_general
        from unittest.mock import AsyncMock
        with patch.object(runtime,'setup',new=AsyncMock(return_value=True)) as setup:
            self.assertTrue(await house_manager_general.async_setup('hass',{}))
        setup.assert_awaited_once_with('hass',{})

if __name__ == '__main__': unittest.main()
