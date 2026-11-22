"""Standing routes remain opt-in, identity bound, and secret-free."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from custom_components.house_manager_general import runtime, management


class StandingRoutesTests(unittest.IsolatedAsyncioTestCase):
    def routes(self, enabled=True):
        views = []
        class View:
            pass
        checker = AsyncMock(return_value=None)
        modules = {'homeassistant.components.http':NS(HomeAssistantView=View),
                   'aiohttp.web':NS(json_response=lambda body,status=200:NS(body=body,status=status)),
                   'homeassistant.config':NS(async_check_ha_config_file=checker)}
        hass = NS(http=NS(register_view=views.append))
        manager = NS(standing_permissions=enabled,bot_user_id='b'*32)
        with patch.object(runtime,'import_module',side_effect=modules.__getitem__):
            runtime.register_views(hass,manager)
        return {view.url:view for view in views}, checker, modules

    def test_standing_routes_absent_unless_enabled(self):
        old,_,_ = self.routes(False)
        current,_,_ = self.routes()
        self.assertEqual(len(old),7)
        self.assertEqual(set(current)-set(old),{
            '/api/house_manager_general/managed-state',
            '/api/house_manager_general/check-config',
            '/api/house_manager_general/diagnostics'})
        self.assertTrue(all(view.requires_auth for view in current.values()))

    async def test_configuration_check_binds_identity_and_never_returns_error_values(self):
        routes,checker,modules = self.routes()
        view=routes['/api/house_manager_general/check-config']
        user=NS(id='b'*32,is_admin=False,is_active=True)
        with patch.object(runtime,'import_module',side_effect=modules.__getitem__), \
             patch.object(management,'import_module',return_value=NS(__version__='2026.11.1')), \
             patch.object(runtime,'read_body',new=AsyncMock(return_value={})):
            valid=await view.post({'hass_user':user})
            self.assertEqual(valid.status,200)
            self.assertIs(valid.body['valid'],True)
            checker.return_value='sensitive validation error must not escape'
            invalid=await view.post({'hass_user':user})
            self.assertEqual(set(invalid.body),{'valid','checked_at'})
            self.assertIs(invalid.body['valid'],False)
            for forbidden in (None,NS(id='c'*32,is_admin=False,is_active=True),
                              NS(id=user.id,is_admin=True,is_active=True),
                              NS(id=user.id,is_admin=False,is_active=False)):
                denied=await view.post({'hass_user':forbidden})
                self.assertEqual(denied.status,403)
            self.assertEqual(checker.await_count,2)

    async def test_configuration_check_rejects_arguments(self):
        routes,checker,modules=self.routes()
        view=routes['/api/house_manager_general/check-config']
        with patch.object(runtime,'import_module',side_effect=modules.__getitem__), \
             patch.object(management,'import_module',return_value=NS(__version__='2026.11.1')), \
             patch.object(runtime,'read_body',new=AsyncMock(return_value={'path':'/etc/passwd'})):
            denied=await view.post({'hass_user':NS(id='b'*32,is_admin=False,is_active=True)})
            self.assertEqual(denied.status,400)
            checker.assert_not_awaited()
