"""Small, version-pinned standing-management boundary (not registered by itself).

Public entry: ``await Management(...).request(authenticated_user, body)``.
The runtime must obtain the user from HA authentication, never from body fields.

All enrollments are TRUSTED operator configuration, not request parameters:
* helper_bindings: exact entity_id -> entity-registry entry id. Enrollment asserts
  the operator audited downstream automations/scripts/integrations and established
  that ALL advertised input values are nonhazardous. Identity alone does NOT prove
  this; leave empty when that audit is absent. No helper state writes by default.
* reload_entries: exact entry_id -> domain, limited further to built-in met/sun.
  Reload emits sensor lifecycle events; enroll only after downstream safety review.
* dashboard_paths: existing, non-admin, storage dashboard URL paths. Append-only
  sensor views; no replacement, resources, custom cards, actions or exposure edits.

Diagnostics omit logs, issue text, config entry data/options, arbitrary attributes,
URLs, credentials and integration diagnostic downloads. Helper definitions are not
created/edited/deleted. Automation enable/disable is deliberately absent: native
raw configs require complete action/binding/safety validation, not name heuristics.

Pinned public HA 2026.11.1 sources inspected read-only: lovelace/dashboard.py,
lovelace/const.py, input_{boolean,number,select}/{entity,services}.py,
config/config_entries.py, met/__init__.py and sun/__init__.py. No extra HA process.
"""
import asyncio
import copy
import math
import re
from importlib import import_module
from typing import Any

from .engine import ApprovalError, HA_VERSION
from .policy import hash_json

HELPER_DOMAINS = frozenset({'input_boolean', 'input_number', 'input_select'})
RELOAD_DOMAINS = frozenset({'met', 'sun'})
OPERATIONS = frozenset({'diagnostics', 'set_boolean', 'set_number', 'select_option',
                        'reload_entry', 'append_sensor_view'})
ENTITY = re.compile(r'[a-z][a-z0-9_]*\.[a-z0-9_]+')
PATH = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def _check(condition, code='invalid_management_request', status=400):
    if not condition:
        raise ApprovalError(code, status)


def _keys(body, names):
    _check(type(body) is dict and set(body) == set(names))


def _literal(value, maximum=160):
    _check(type(value) is str and 0 < len(value) <= maximum and bool(value.strip())
           and not any(ord(char) < 32 for char in value)
           and not any(token in value for token in ('{{', '}}', '{%', '%}', '://', '<', '>')))


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class Management:
    """No generic privileged dispatcher and no administrator impersonation.

    Each mutation calls one fixed native method/service and reads back its target.
    Errors after mutation starts are uncertain, sanitized, and never retried here.
    The per-instance lock serializes this boundary only; native UI edits are not
    locked by HA Lovelace. Treat concurrent native dashboard edits as unsupported.
    """

    def __init__(self, hass, bot_user_id, *, helper_bindings=None,
                 reload_entries=None, dashboard_paths=()):
        _check(type(bot_user_id) is str and re.fullmatch(r'[0-9a-f]{32}', bot_user_id))
        helpers = {} if helper_bindings is None else helper_bindings
        entries = {} if reload_entries is None else reload_entries
        _check(type(helpers) is dict and type(entries) is dict
               and type(dashboard_paths) in (tuple, list))
        _check(len(helpers) <= 100 and len(entries) <= 30 and len(dashboard_paths) <= 20)
        for entity, identifier in helpers.items():
            _check(type(entity) is str and ENTITY.fullmatch(entity)
                   and entity.split('.')[0] in HELPER_DOMAINS)
            _check(type(identifier) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', identifier))
        for identifier, domain in entries.items():
            _check(type(identifier) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier)
                   and type(domain) is str and domain in RELOAD_DOMAINS)
        for path in dashboard_paths:
            _check(type(path) is str and len(path) <= 80 and PATH.fullmatch(path) and '-' in path)
        self.hass, self.bot_user_id = hass, bot_user_id
        self.helper_bindings = copy.deepcopy(helpers)
        self.reload_entries = copy.deepcopy(entries)
        self.dashboard_paths = frozenset(dashboard_paths)
        self.lock = asyncio.Lock()

    def _authorize(self, user):
        _check(user is not None and user.id == self.bot_user_id
               and not user.is_admin and user.is_active, 'forbidden', 403)
        _check(import_module('homeassistant.const').__version__ == HA_VERSION,
               'management_version_mismatch', 503)

    async def request(self, user, body):
        self._authorize(user)
        _check(type(body) is dict and type(body.get('operation')) is str
               and body['operation'] in OPERATIONS)
        # Private copy prevents caller mutation while an operation is waiting.
        body = copy.deepcopy(body)
        async with self.lock:
            self._authorize(user)
            operation = body['operation']
            if operation == 'diagnostics':
                _keys(body, ('operation',))
                return self._diagnostics()
            if operation == 'reload_entry':
                return await self._reload(body)
            if operation == 'append_sensor_view':
                return await self._append_view(body)
            return await self._helper_value(body)

    def _helper(self, entity) -> Any:
        _check(type(entity) is str and entity in self.helper_bindings,
               'helper_not_enrolled', 403)
        registry = import_module('homeassistant.helpers.entity_registry').async_get(self.hass)
        entry = registry.async_get(entity)
        _check(entry is not None and entry.entity_id == entity
               and entry.id == self.helper_bindings[entity] and entry.unique_id
               and entry.platform == entity.split('.')[0] and not entry.disabled_by,
               'helper_binding_changed', 409)
        state = self.hass.states.get(entity)
        _check(state is not None and state.state not in ('unknown', 'unavailable'),
               'helper_unavailable', 409)
        return state

    async def _helper_value(self, body):
        _keys(body, ('operation', 'entity_id', 'value'))
        entity, value, operation = body['entity_id'], body['value'], body['operation']
        state = self._helper(entity)
        domain = entity.split('.')[0]
        expected: Any
        if operation == 'set_boolean':
            _check(domain == 'input_boolean' and type(value) is bool)
            service, data, expected = ('turn_on' if value else 'turn_off'), {}, ('on' if value else 'off')
        elif operation == 'set_number':
            _check(domain == 'input_number' and _finite(value))
            low, high, step = (state.attributes.get(key) for key in ('min', 'max', 'step'))
            _check(all(_finite(item) for item in (low, high, step))
                   and low <= value <= high and 0 < step <= 1e9)
            quotient = (value - low) / step
            _check(_finite(quotient) and abs(quotient - round(quotient)) <= 1e-6)
            service, data, expected = 'set_value', {'value': value}, value
        else:
            _check(operation == 'select_option' and domain == 'input_select')
            _literal(value, 512)
            options = state.attributes.get('options')
            _check(isinstance(options, list) and value in options)
            service, data, expected = 'select_option', {'option': value}, value
        try:
            await self.hass.services.async_call(domain, service, dict(data, entity_id=entity), blocking=True)
            current = self._helper(entity)
            if domain == 'input_number':
                _check(math.isclose(float(current.state), expected, rel_tol=1e-9, abs_tol=1e-9))
            else:
                _check(current.state == expected)
        except Exception:
            raise ApprovalError('management_uncertain', 503) from None
        return {'status': 'verified', 'entity_id': entity, 'state': current.state}

    def _entry(self, identifier) -> Any:
        _check(type(identifier) is str and identifier in self.reload_entries,
               'entry_not_enrolled', 403)
        entry = self.hass.config_entries.async_get_entry(identifier)
        _check(entry is not None and entry.entry_id == identifier
               and entry.domain == self.reload_entries[identifier]
               and entry.domain in RELOAD_DOMAINS and not entry.disabled_by,
               'entry_binding_changed', 409)
        return entry

    async def _reload(self, body):
        _keys(body, ('operation', 'entry_id'))
        identifier = body['entry_id']
        entry = self._entry(identifier)
        _check(entry.state.value in ('loaded', 'setup_retry', 'setup_error'),
               'entry_not_reloadable', 409)
        try:
            _check(await self.hass.config_entries.async_reload(identifier))
            current = self._entry(identifier)
            _check(current is entry and current.state.value == 'loaded')
        except Exception:
            raise ApprovalError('management_uncertain', 503) from None
        return {'status': 'verified', 'entry_id': identifier, 'state': 'loaded'}

    def _dashboard(self, path) -> Any:
        _check(type(path) is str and path in self.dashboard_paths,
               'dashboard_not_enrolled', 403)
        key = import_module('homeassistant.components.lovelace.const').LOVELACE_DATA
        data = self.hass.data.get(key)
        dashboard = data.dashboards.get(path) if data else None
        expected = import_module('homeassistant.components.lovelace.dashboard').LovelaceStorage
        _check(type(dashboard) is expected and isinstance(dashboard.config, dict)
               and dashboard.config.get('require_admin') is False,
               'unsupported_dashboard', 409)
        return dashboard

    async def _append_view(self, body):
        _keys(body, ('operation', 'dashboard', 'title', 'path', 'entities'))
        _literal(body['title'])
        _check(type(body['path']) is str and len(body['path']) <= 80 and PATH.fullmatch(body['path']))
        entities = body['entities']
        _check(type(entities) is list and 1 <= len(entities) <= 30
               and all(type(entity) is str and ENTITY.fullmatch(entity)
                       and entity.split('.')[0] in ('sensor', 'binary_sensor') for entity in entities))
        _check(len(set(entities)) == len(entities))
        _check(all(self.hass.states.get(entity) is not None for entity in entities), 'unknown_sensor', 409)
        dashboard = self._dashboard(body['dashboard'])
        # async_load(False) uses the native cache; no filesystem paths or YAML.
        try:
            before: Any = copy.deepcopy(await dashboard.async_load(False))
            _check(type(before) is dict and type(before.get('views')) is list
                   and len(before['views']) < 30 and 'strategy' not in before,
                   'unsupported_dashboard', 409)
            _check(all(type(view) is dict and view.get('path') != body['path'] for view in before['views']),
                   'duplicate_view', 409)
            after = copy.deepcopy(before)
            rows = [{'entity': entity, 'tap_action': {'action': 'none'},
                     'hold_action': {'action': 'none'}, 'double_tap_action': {'action': 'none'}}
                    for entity in entities]
            after['views'].append({'title': body['title'], 'path': body['path'],
                                   'cards': [{'type': 'entities', 'show_header_toggle': False, 'entities': rows}]})
            # Bound preserved native content; never return it (may contain secrets).
            _check(len(str(after)) <= 262144, 'dashboard_too_large', 413)
            hash_json(after)
        except ApprovalError:
            raise
        except Exception:
            raise ApprovalError('unsupported_dashboard', 409) from None
        try:
            await dashboard.async_save(after)
            _check(self._dashboard(body['dashboard']) is dashboard)
            _check(hash_json(await dashboard.async_load(False)) == hash_json(after))
        except Exception:
            raise ApprovalError('management_uncertain', 503) from None
        return {'status': 'verified', 'dashboard': body['dashboard'], 'path': body['path']}

    def _diagnostics(self):
        states = self.hass.states.async_all()
        entries = []
        for identifier in sorted(self.reload_entries):
            entry = self._entry(identifier)
            # No title, unique_id, data, options, reason or diagnostic payload.
            state = entry.state.value
            _check(state in ('loaded', 'not_loaded', 'setup_retry', 'setup_error',
                             'migration_error', 'failed_unload', 'unload_in_progress', 'setup_in_progress'))
            entries.append({'entry_id': identifier, 'domain': entry.domain, 'state': state})
        return {'ha_version': HA_VERSION, 'entity_count': len(states),
                'unavailable_count': sum(state.state == 'unavailable' for state in states),
                'unknown_count': sum(state.state == 'unknown' for state in states),
                'enrolled_helper_count': len(self.helper_bindings), 'entries': entries}
