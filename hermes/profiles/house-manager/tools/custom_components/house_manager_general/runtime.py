"""Scoped request routes and an opt-in, separately authenticated chat adapter."""
import asyncio
import copy
from importlib import import_module
from .engine import ApprovalError, ID, HEX
from .native import read_body

DOMAIN = 'house_manager_general'

async def setup(hass, config):
    from .engine import Manager, HA_VERSION, TIME_ZONE
    from .native import NativeBoundary, discover_native_view, validate_settings
    from .discord import ApprovalWorker, DiscordREST
    try:
        settings = validate_settings(config.get(DOMAIN))
        const = import_module('homeassistant.const')
        if const.__version__ != HA_VERSION or hass.config.time_zone != TIME_ZONE:
            return False
        bot = await hass.auth.async_get_user(settings['bot_user_id'])
        if bot is None or bot.is_admin or not bot.is_active:
            return False
        if 'chat_approver_user_id' in settings:
            approver = await hass.auth.async_get_user(settings['chat_approver_user_id'])
            if approver is None or approver.is_admin or not approver.is_active:
                return False
        view = discover_native_view(hass.http.app.router.routes(), import_module('homeassistant.components.config.automation').EditAutomationConfigView)
        store = import_module('homeassistant.helpers.storage').Store(hass,1,DOMAIN+'.ledger',private=True,atomic_writes=True)
        records = validate_records(await store.async_load())
        # Persist crash-recovery tombstones before exposing requests or worker.
        await store.async_save(records)
        manager = Manager(NativeBoundary(hass,settings,view,store),settings['bot_user_id'],records,
                          standing_permissions=settings.get('standing_permissions', False))
        worker = ApprovalWorker(manager, DiscordREST(settings['discord_token']), settings)
        register_views(hass,manager,settings.get('chat_approver_user_id'))
        hass.data[DOMAIN] = manager
        async def stop(event):
            await worker.stop()
        hass.bus.async_listen_once(const.EVENT_HOMEASSISTANT_STOP,stop)
        worker.task = hass.async_create_background_task(worker.run(),DOMAIN+' approval worker')
        return True
    except Exception:
        # Do not leak settings, enrollment, exception reprs or secret values.
        return False

def validate_records(value):
    if value is None:
        return {}
    if not isinstance(value,dict) or len(value) > 1000:
        raise ValueError('invalid ledger')
    records = copy.deepcopy(value)
    for identifier,record in records.items():
        if not isinstance(identifier,str) or not ID.fullmatch(identifier) or not isinstance(record,dict) or record.get('status') not in {'queued','preview_pending','awaiting_approval','pending','uncertain','expired','executed','verified_enabled','verified_edit','superseded'}:
            raise ValueError('invalid ledger')
        doc = record.get('proposal')
        if not isinstance(doc,dict) or doc.get('id') != identifier or not isinstance(doc.get('sha256'),str) or not HEX.fullmatch(doc['sha256']):
            raise ValueError('invalid ledger')
        if record['status'] in {'pending','preview_pending'} or record.get('approval') and record['status'] == 'awaiting_approval':
            record['status'] = 'uncertain'
    return records

def register_views(hass, manager, chat_approver_user_id=None):
    View = import_module('homeassistant.components.http').HomeAssistantView
    web = import_module('aiohttp.web')
    async def respond(operation):
        try:
            async with asyncio.timeout(30):
                return web.json_response(await operation())
        except ApprovalError as exc:
            return web.json_response({'error':exc.code},status=exc.status)
        except Exception:
            return web.json_response({'error':'unavailable'},status=503)

    class Capabilities(View):
        url = '/api/house_manager_general/capabilities'
        name = 'api:house_manager_general:capabilities'
        requires_auth = True
        async def get(self,request):
            return await respond(lambda:manager.capabilities(request.get('hass_user')))

    class Action(View):
        url = '/api/house_manager_general/action'
        name = 'api:house_manager_general:action'
        requires_auth = True
        async def post(self,request):
            async def operation():
                user = request.get('hass_user')
                manager.authorize(user)
                return await manager.action(user,await read_body(request))
            return await respond(operation)

    class Proposals(View):
        url = '/api/house_manager_general/proposals'
        name = 'api:house_manager_general:proposals'
        requires_auth = True
        async def post(self,request):
            async def operation():
                user = request.get('hass_user')
                manager.authorize(user)
                return await manager.propose(user,await read_body(request))
            return await respond(operation)

    class Status(View):
        url = '/api/house_manager_general/proposals/{identifier}'
        name = 'api:house_manager_general:status'
        requires_auth = True
        async def get(self,request,identifier):
            return await respond(lambda:manager.status(request.get('hass_user'),identifier))

    class Managed(View):
        url = '/api/house_manager_general/managed'
        name = 'api:house_manager_general:managed'
        requires_auth = True
        async def get(self, request):
            return await respond(lambda:manager.list_managed(request.get('hass_user')))

    class ManagedItem(View):
        url = '/api/house_manager_general/managed/{identifier}'
        name = 'api:house_manager_general:managed_item'
        requires_auth = True
        async def get(self, request, identifier):
            return await respond(lambda:manager.get_managed(request.get('hass_user'), identifier))

    class Edits(View):
        url = '/api/house_manager_general/edits'
        name = 'api:house_manager_general:edits'
        requires_auth = True
        async def post(self, request):
            async def operation():
                user = request.get('hass_user')
                manager.authorize(user)
                return await manager.propose_edit(user, await read_body(request))
            return await respond(operation)

    for cls in [Capabilities,Action,Proposals,Status,Managed,ManagedItem,Edits]:
        hass.http.register_view(cls())
    if getattr(manager, 'standing_permissions', False):
        from datetime import datetime, timezone
        from .management import Management
        management = Management(hass, manager.bot_user_id)
        check_lock = asyncio.Lock()

        class Diagnostics(View):
            url = '/api/house_manager_general/diagnostics'
            name = 'api:house_manager_general:diagnostics'
            requires_auth = True
            async def get(self, request):
                return await respond(lambda:management.request(request.get('hass_user'),
                                                               {'operation':'diagnostics'}))

        class ManagedState(View):
            url = '/api/house_manager_general/managed-state'
            name = 'api:house_manager_general:managed_state'
            requires_auth = True
            async def post(self, request):
                async def operation():
                    user = request.get('hass_user')
                    manager.authorize(user)
                    return await manager.set_managed_state(user, await read_body(request))
                return await respond(operation)

        class CheckConfig(View):
            url = '/api/house_manager_general/check-config'
            name = 'api:house_manager_general:check_config'
            requires_auth = True
            async def post(self, request):
                async def operation():
                    # Bind exactly the active non-admin operational bot, not a
                    # body-supplied identity. Do not return configuration/errors.
                    management._authorize(request.get('hass_user'))
                    if await read_body(request) != {}:
                        raise ApprovalError('invalid_request')
                    async with check_lock:
                        checker = import_module('homeassistant.config').async_check_ha_config_file
                        result = await checker(hass)
                        return {'valid':result is None, 'checked_at':datetime.now(timezone.utc).isoformat()}
                return await respond(operation)

        for cls in [Diagnostics, ManagedState, CheckConfig]:
            hass.http.register_view(cls())
    if chat_approver_user_id is not None:
        from .chat import ChatApprovals
        adapter = ChatApprovals(manager, chat_approver_user_id)

        class ChatApproval(View):
            url = '/api/house_manager_general/chat-approvals/{identifier}'
            name = 'api:house_manager_general:chat_approval'
            requires_auth = True
            async def get(self, request, identifier):
                return await respond(lambda:adapter.get(request.get('hass_user'), identifier))
            async def post(self, request, identifier):
                async def operation():
                    user = request.get('hass_user')
                    adapter.authorize(user)
                    return await adapter.approve(user, identifier, await read_body(request))
                return await respond(operation)

        hass.http.register_view(ChatApproval())
