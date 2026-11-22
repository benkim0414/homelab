"""Version-pinned internal HA boundary; imports lazy for stdlib tests."""
import asyncio
import copy
import hashlib
import inspect
import json
import re
from importlib import import_module
from .engine import ApprovalError

ATTRIBUTES = frozenset('friendly_name supported_features preset_modes preset_mode percentage_step percentage oscillating direction supported_color_modes color_mode brightness min_color_temp_kelvin max_color_temp_kelvin min_mireds max_mireds source_list sound_mode_list volume_level is_volume_muted options min max step hvac_modes hvac_mode min_temp max_temp target_temp_step temperature_unit fan_modes swing_modes swing_horizontal_modes target_temp_high target_temp_low current_temperature'.split())
DOMAINS = frozenset('light fan media_player switch select number climate sensor binary_sensor'.split())
SUPPORTED_ACTIONS = {'light':['turn_on','turn_off'], 'fan':['turn_on','turn_off','set_percentage','set_preset_mode','oscillate','set_direction'], 'media_player':['turn_on','turn_off','media_play','media_pause','media_stop','volume_set','volume_mute','select_source','select_sound_mode'], 'switch':['turn_on','turn_off'], 'select':['select_option'], 'number':['set_value'], 'climate':['turn_on','turn_off','set_hvac_mode','set_temperature','set_fan_mode','set_swing_mode','set_preset_mode']}

def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def fingerprint(entry, device):
    if entry is None or not entry.unique_id or not entry.config_entry_id or (entry.device_id and (device is None or entry.device_id != device.id)):
        raise ApprovalError('unbound_entity', 409)
    return _hash({'entity_registry_id':entry.id, 'name':entry.name, 'original_name':entry.original_name, 'area_id':entry.area_id, 'entity_id':entry.entity_id, 'platform':entry.platform, 'unique_id':entry.unique_id, 'config_entry_id':entry.config_entry_id, 'device_id':entry.device_id, 'device':None if device is None else {'id':device.id, 'identifiers':sorted([list(v) for v in device.identifiers]), 'connections':sorted([list(v) for v in device.connections]), 'manufacturer':device.manufacturer, 'model':device.model, 'name':device.name, 'name_by_user':device.name_by_user}})

class NativeBoundary:
    def __init__(self, hass, settings, view, store):
        self.hass, self.view, self.store = hass, view, store
        self.lock = view.mutation_lock

    def _locked(self):
        if not self.lock.locked():
            raise ApprovalError('native_lock_required', 503)

    async def read(self):
        self._locked()
        reader = import_module('homeassistant.components.config.view')._read
        def exact(path):
            import os
            value = reader(path)
            if value is None and os.path.exists(path):
                raise ApprovalError('invalid_native_config', 409)
            return [] if value is None else value
        return await self.hass.async_add_executor_job(exact, self.hass.config.path(self.view.path))

    async def write(self, rows):
        self._locked()
        writer = import_module('homeassistant.components.config.view')._write
        task = asyncio.ensure_future(self.hass.async_add_executor_job(writer, self.hass.config.path(self.view.path), rows))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def validate(self, config):
        await import_module('homeassistant.components.automation.config').async_validate_config_item(self.hass, config['id'], config)

    async def save(self, records):
        await self.store.async_save(records)

    async def reload(self, identifier):
        # Pinned 2026.11.1 reload does not acquire the config mutation lock.
        # Both creates and edits retain it across write, reload and readback.
        self._locked()
        await self.hass.services.async_call('automation', 'reload', {'id':identifier}, blocking=True)

    async def reload_edit(self, identifier):
        await self.reload(identifier)

    async def loaded(self, identifier):
        registry = import_module('homeassistant.helpers.entity_registry').async_get(self.hass)
        entity_id = registry.async_get_entity_id('automation', 'automation', identifier)
        if not entity_id:
            return None
        key = import_module('homeassistant.components.automation.const').DATA_COMPONENT
        component = self.hass.data.get(key)
        entity = component.get_entity(entity_id) if component else None
        state = self.hass.states.get(entity_id)
        if not entity or entity.unique_id != identifier or not state or not isinstance(entity.raw_config, dict):
            return None
        return {'entity_id':entity_id, 'state':state.state, 'raw_config':copy.deepcopy(entity.raw_config)}

    async def enable(self, entity_id):
        self._locked()
        await self.hass.services.async_call('automation', 'turn_on', {'entity_id':entity_id}, blocking=True)

    async def disable(self, entity_id):
        self._locked()
        await self.hass.services.async_call('automation', 'turn_off',
            {'entity_id':entity_id, 'stop_actions':False}, blocking=True)

    async def execute(self, action):
        # The manager has just validated the typed allowlist against fresh HA
        # inventory. No arbitrary service names enter through a public view.
        domain, service = action['action'].split('.')
        if service not in SUPPORTED_ACTIONS.get(domain, []):
            raise ApprovalError('invalid_action')
        await self.hass.services.async_call(domain, service, dict(action['data'], entity_id=action['target']['entity_id']), blocking=True)

    async def capabilities(self):
        er = import_module('homeassistant.helpers.entity_registry').async_get(self.hass)
        dr = import_module('homeassistant.helpers.device_registry').async_get(self.hass)
        ar = import_module('homeassistant.helpers.area_registry').async_get(self.hass)
        inventory = {}
        for entry in er.entities.values():
            key = entry.entity_id
            if key.split('.')[0] not in DOMAINS or entry.disabled_by:
                continue
            state = self.hass.states.get(key)
            device = dr.async_get(entry.device_id) if entry.device_id else None
            try:
                fp = fingerprint(entry, device)
            except (ApprovalError, ValueError, TypeError):
                continue
            area_id = entry.area_id or (device.area_id if device else None)
            area = ar.async_get_area(area_id) if area_id else None
            # Do not expose arbitrary integration attributes, URLs or secrets.
            attrs = {k:copy.deepcopy(v) for k,v in (state.attributes.items() if state else []) if k in ATTRIBUTES}
            try:
                # HA keeps IntFlag/StrEnum values in native State attributes.
                # Authorize against the same plain JSON types exposed over HTTP;
                # keep strict incoming-action validation unchanged.
                attrs = json.loads(json.dumps(attrs, allow_nan=False))
            except (ValueError, TypeError):
                continue
            inventory[key] = {'entity_id':key, 'state':state.state if state else 'unavailable', 'attributes':attrs, 'registry_fingerprint':fp, 'platform':entry.platform, 'name':entry.name or entry.original_name or key, 'area':area.name if area else None, 'device_name':(device.name_by_user or device.name) if device else None}
        return {'version':3, 'ha_version':import_module('homeassistant.const').__version__, 'time_zone':self.hass.config.time_zone, 'inventory':inventory, 'supported_actions':copy.deepcopy(SUPPORTED_ACTIONS)}

NATIVE_PATH = '/api/config/automation/config/{config_key}'

def discover_native_view(routes, native_type):
    found = {}
    for route in routes:
        if route.resource.canonical != NATIVE_PATH or route.method not in {'GET','POST','DELETE'}:
            continue
        try:
            view = inspect.getclosurevars(route.handler).nonlocals['view']
        except (TypeError, KeyError):
            raise ApprovalError('native_boundary_unavailable', 503) from None
        if route.method in found:
            raise ApprovalError('native_boundary_unavailable', 503)
        found[route.method] = view
    if set(found) != {'GET','POST','DELETE'}:
        raise ApprovalError('native_boundary_unavailable', 503)
    view = found['GET']
    if type(view) is not native_type or any(v is not view for v in found.values()) or view.path != 'automations.yaml' or not isinstance(view.mutation_lock, asyncio.Lock):
        raise ApprovalError('native_boundary_unavailable', 503)
    return view

def validate_settings(value):
    keys = {'bot_user_id','discord_token','discord_channel_id','discord_user_id'}
    optional = {'chat_approver_user_id', 'standing_permissions'}
    if (not isinstance(value, dict) or not keys <= set(value)
            or set(value) - keys - optional
            or not all(isinstance(v,str) and v for k,v in value.items() if k != 'standing_permissions')
            or 'standing_permissions' in value and type(value['standing_permissions']) is not bool):
        raise ApprovalError('invalid_settings')
    if not re.fullmatch('[0-9a-f]{32}', value['bot_user_id']) or any(re.fullmatch('[0-9]{1,25}',value[k]) is None for k in ['discord_channel_id','discord_user_id']) or len(value['discord_token']) > 256 or any(c.isspace() for c in value['discord_token']):
        raise ApprovalError('invalid_settings')
    if 'chat_approver_user_id' in value and (not re.fullmatch('[0-9a-f]{32}', value['chat_approver_user_id']) or value['chat_approver_user_id'] == value['bot_user_id']):
        raise ApprovalError('invalid_settings')
    return copy.deepcopy(value)

def _pairs(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result

def _constant(value):
    raise ValueError('nonfinite')

async def read_body(request):
    if request.content_type != 'application/json':
        raise ApprovalError('invalid_request')
    if request.content_length is not None and request.content_length > 65536:
        raise ApprovalError('body_too_large', 413)
    data = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.content.iter_chunked(4096):
                data.extend(chunk)
                if len(data) > 65536:
                    raise ApprovalError('body_too_large', 413)
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError, TimeoutError):
        raise ApprovalError('invalid_request') from None
