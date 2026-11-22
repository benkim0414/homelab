#!/usr/bin/env python3
"""Scoped JSON-line MCP connector. HA enforces inventory and standing policy.

Only literal, single-entity actions and time/state automation forms are exposed.
No general HA route, service, approval, template, or device-test interface exists.
Fixed authenticated diagnostics/config-check/workload-health/restart operations
are additive; no Kubernetes credential is supplied to this connector.
HA_MCP_TOKEN must be an operator-provisioned non-admin bot credential; this client
cannot infer account privileges from an opaque token. HA enforces the bot identity.

Supported limited forms are published in TOOLS, ACTION_SCHEMA and SPEC_SCHEMA:
one entity_id per action, literal data objects only, time HH:MM:SS or exact state
triggers, state/time conditions, at most 20 actions/10 triggers/10 conditions.
No transition/effects, relative changes, area/device targets, templates, raw YAML,
scripts or arbitrary extra service parameters are exposed. Existing routines can
only be edited when verified v3-owned, using exact target/base-hash discovery and
a complete typed spec. The HA standing policy executes only safe routines;
hazardous/untrusted requests retain independent human approval through Discord
or the separately enrolled local /house-approve command. MCP cannot approve.
New automation create/edit proposals have explicit expires_at=null; device actions
and legacy finite proposals retain exact 900-second expiry. Null never renews an
existing proposal: its original immutable hash and ledger status remain binding.
Local numeric ceilings are deliberately bounded (number +/-1e6, climate +/-100,
Kelvin 1000..40000); fresh HA policy further restricts every parameter to actual
attributes/features. HA alone classifies appliance risk and enforces approval.
Tool results preserve the HA response under "response", with a separate explicit
device_state_verified=False: accepted service calls never prove physical state.
Historical proposal inspection verifies structure/hash, not current authorization;
expired proposals remain readable and cannot be approved through this interface.
"""
import json
import re
import urllib.request

BASE_URL = 'http://home-assistant.home-assistant.svc.cluster.local:8123/api/house_manager_general'
OPERATIONS_URL = 'http://ha-operations.hermes.svc.cluster.local:8080'
MAX_REQUEST = 65536
MAX_RESPONSE = 1048576
ID_PATTERN = r'^house_manager_general_[0-9a-f]{32}$'
ENTITY_PATTERN = r'^[a-z_]+\.[a-z0-9_]+$'


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}


def text(maximum=160):
    return {'type': 'string', 'minLength': 1, 'maxLength': maximum}


def number(low, high, integer=False):
    return {'type': 'integer' if integer else 'number', 'minimum': low, 'maximum': high}


ENTITY = {'type': 'string', 'pattern': ENTITY_PATTERN, 'maxLength': 255}
TIME = {'type': 'string', 'pattern': r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$'}
BOOL = {'type': 'boolean'}
ACTION_SCHEMA = {'oneOf': []}


def action_form(names, fields=None, required=None):
    data = obj(fields or {}, [] if required is None else required)
    ACTION_SCHEMA['oneOf'].append(obj({
        'action': {'type': 'string', 'enum': names.split()},
        'target': obj({'entity_id': ENTITY}), 'data': data}, ['action', 'target'] + (['data'] if required else [])))


action_form('light.turn_on', {
    'brightness': number(0, 255, True), 'brightness_pct': number(0, 100),
    'color_temp_kelvin': number(1000, 40000, True),
    'rgb_color': {'type': 'array', 'items': number(0, 255, True), 'minItems': 3, 'maxItems': 3},
    'hs_color': {'type': 'array', 'prefixItems': [number(0, 360), number(0, 100)], 'minItems': 2, 'maxItems': 2},
    'xy_color': {'type': 'array', 'items': number(0, 1), 'minItems': 2, 'maxItems': 2}})
action_form('light.turn_off')
action_form('fan.turn_on', {'percentage': number(0, 100, True), 'preset_mode': text()})
action_form('fan.set_percentage', {'percentage': number(0, 100, True)}, ['percentage'])
action_form('fan.set_preset_mode', {'preset_mode': text()}, ['preset_mode'])
action_form('fan.oscillate', {'oscillating': BOOL}, ['oscillating'])
action_form('fan.set_direction', {'direction': {'type': 'string', 'enum': ['forward', 'reverse']}}, ['direction'])
action_form('fan.turn_off switch.turn_on switch.turn_off media_player.turn_on media_player.turn_off media_player.media_play media_player.media_pause media_player.media_stop climate.turn_on climate.turn_off')
for service, field, schema in [
    ('media_player.volume_set', 'volume_level', number(0, 1)),
    ('media_player.volume_mute', 'is_volume_muted', BOOL),
    ('media_player.select_source', 'source', text()),
    ('media_player.select_sound_mode', 'sound_mode', text()),
    ('select.select_option', 'option', text()),
    ('number.set_value', 'value', number(-1000000, 1000000)),
    ('climate.set_hvac_mode', 'hvac_mode', text()),
    ('climate.set_fan_mode', 'fan_mode', text()),
    ('climate.set_swing_mode', 'swing_mode', text()),
    ('climate.set_preset_mode', 'preset_mode', text()),
]:
    action_form(service, {field: schema}, [field])
action_form('climate.set_temperature', {'temperature': number(-100, 100), 'hvac_mode': text()}, ['temperature'])
STATE_TRIGGER = obj({'type': {'const': 'state'}, 'entity_id': ENTITY, 'to': text(255),
                     'for_seconds': number(0, 86400, True)}, ['type', 'entity_id', 'to'])
SPEC_SCHEMA = obj({
    'title': text(),
    'triggers': {'type': 'array', 'minItems': 1, 'maxItems': 10, 'items': {'oneOf': [obj({'type': {'const': 'time'}, 'at': TIME}), STATE_TRIGGER]}},
    'conditions': {'type': 'array', 'maxItems': 10, 'items': {'oneOf': [obj({'type': {'const': 'state'}, 'entity_id': ENTITY, 'state': text(255)}), obj({'type': {'const': 'time'}, 'after': TIME, 'before': TIME})]}},
    'actions': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': ACTION_SCHEMA},
}, ['title', 'triggers', 'actions'])
HASH_SCHEMA = {'type':'string', 'pattern':r'^[0-9a-f]{64}$'}
TARGET_SCHEMA = {'type':'string', 'pattern':ID_PATTERN}
EDIT_SCHEMA = obj({'target_id':TARGET_SCHEMA, 'base_config_hash':HASH_SCHEMA, 'spec':SPEC_SCHEMA})
STATE_SCHEMA = obj({'target_id':TARGET_SCHEMA, 'base_config_hash':HASH_SCHEMA, 'enabled':BOOL})
TOOLS = []
for name, description, schema, readonly in [
    ('get_home_capabilities', 'Read fresh inventory, supported actions and approval readiness. No device testing.', obj({}), True),
    ('control_home_device', 'Request one literal device action. HA may accept a service call or queue independent Discord human approval. Accepted is NOT verified physical state. No retries or device testing.', obj({'action': ACTION_SCHEMA}), False),
    ('propose_home_automation', 'Create and enable a typed routine under server-enforced standing permission when every action is low-risk. Hazardous routines queue independent human approval. Verify the returned status; this tool cannot grant human approval. Never submit duplicates after uncertainty.', obj({'spec': SPEC_SCHEMA}), False),
    ('list_managed_home_automations', 'Read verified v3-owned native routines and drift/unavailable entries. Does not adopt or run routines.', obj({}), True),
    ('get_managed_home_automation', 'Read one verified v3-owned routine, exact native config, base hash and current on/off state.', obj({'target_id':TARGET_SCHEMA}), True),
    ('propose_home_automation_edit', 'Edit a verified owned routine with a COMPLETE typed spec and exact base hash, preserving ID/on-off state. Safe edits use server standing permission; hazardous edits queue independent human approval. Refuses drift. Cannot delete, force-trigger or approve.', EDIT_SCHEMA, False),
    ('set_managed_home_automation_state', 'Enable or disable one verified owned routine using its exact base hash. Server standing policy and fresh action/binding checks gate enabling; hazardous enabling is refused. No force-trigger or stopping running actions. Read back state.', STATE_SCHEMA, False),
    ('get_home_diagnostics', 'Read sanitized HA diagnostic counts. No logs, credentials, arbitrary attributes or configuration values.', obj({}), True),
    ('check_home_configuration', 'Run the native HA configuration check; return only valid boolean and timestamp, never raw errors or secrets. Does not restart.', obj({}), True),
    ('get_home_workload_health', 'Read fixed HA StatefulSet/pod health through the authenticated scoped broker. No logs, exec, Secrets or other workloads.', obj({}), True),
    ('restart_home_assistant', 'Request recoverable restart of the existing HA StatefulSet after a fresh native configuration check and rollout guards. Briefly interrupts HA. No image/storage/replica changes. Acceptance is NOT rollout success; follow with workload-health reads. Never blindly retry.', obj({}), False),
    ('get_home_proposal', 'Read proposal/status/evidence. Historical receipts are not fresh runtime state. Does not approve or test devices.', obj({'proposal_id': {'type': 'string', 'pattern': ID_PATTERN}}), True),
]:
    TOOLS.append({'name': name, 'description': description, 'inputSchema': schema,
                  'annotations': {'readOnlyHint': readonly, 'destructiveHint': not readonly, 'idempotentHint': readonly, 'openWorldHint': False}})


def validate(schema, value, depth=0):
    """Enforce exactly the JSON Schema subset published above (no dependencies)."""
    import math
    if depth > 20:
        raise ValueError('Input nesting limit')
    if 'oneOf' in schema:
        matches = 0
        for choice in schema['oneOf']:
            try:
                validate(choice, value, depth + 1)
                matches += 1
            except ValueError:
                pass
        if matches != 1:
            raise ValueError('Unsupported input form')
        return
    kind = schema.get('type')
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    if kind == 'number':
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Expected finite number')
    elif kind and type(value) is not types[kind]:
        raise ValueError('Invalid input type')
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
        raise ValueError('Invalid literal')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('Unsupported literal')
    if kind == 'object':
        if set(value) - set(schema['properties']) or set(schema['required']) - set(value):
            raise ValueError('Unknown or missing arguments')
        for key, child in value.items():
            validate(schema['properties'][key], child, depth + 1)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', MAX_REQUEST):
            raise ValueError('Array length outside limits')
        for index, child in enumerate(value):
            validate(schema['prefixItems'][index] if 'prefixItems' in schema else schema['items'], child, depth + 1)
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', MAX_REQUEST):
            raise ValueError('String length outside limits')
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
            raise ValueError('Invalid identifier or time')
        if any(ord(ch) < 32 for ch in value) or any(token in value for token in ('{{', '{%', '://')):
            raise ValueError('Only literal values are supported')
    elif kind in ('number', 'integer'):
        if not schema.get('minimum', -float('inf')) <= value <= schema.get('maximum', float('inf')):
            raise ValueError('Number outside limits')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def bad_constant(value):
        raise ValueError('Non-finite JSON')

    def finite_float(value):
        import math
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('Non-finite JSON')
        return parsed

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant, parse_float=finite_float)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HAClient:
    def __init__(self, token):
        import urllib.request
        if (type(token) is not str or not 1 <= len(token) <= 16384
                or any(not 33 <= ord(ch) <= 126 for ch in token)):
            raise ValueError('Invalid scoped credential')
        self._headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Content-Type': 'application/json'}
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _request(self, method, path, payload=None):
        import urllib.request
        import urllib.error
        fixed = {('GET', '/capabilities'), ('POST', '/action'), ('POST', '/proposals'), ('GET','/managed'), ('POST','/edits'),
                 ('POST','/managed-state'), ('GET','/diagnostics'), ('POST','/check-config'),
                 ('POST','/workload-health'), ('POST','/workload-restart')}
        if ((method, path) not in fixed
                and not (method == 'GET' and any(path.startswith(prefix)
                         and re.fullmatch(ID_PATTERN, path[len(prefix):]) for prefix in ('/proposals/', '/managed/')))):
            raise ValueError('Prohibited route')
        raw = None if payload is None else json.dumps(payload, allow_nan=False).encode('utf-8')
        if raw is not None and len(raw) > MAX_REQUEST:
            raise ValueError('Request exceeds limit')
        urls = {'/workload-health':OPERATIONS_URL+'/v1/health',
                '/workload-restart':OPERATIONS_URL+'/v1/restart'}
        url = urls[path] if path in urls else BASE_URL + path
        request = urllib.request.Request(url, data=raw, headers=self._headers, method=method)
        try:
            with self._opener.open(request, timeout=30 if path == '/workload-restart' else 10) as response:
                if response.status not in (200, 201, 202) or response.headers.get_content_type() != 'application/json':
                    raise ValueError('Unsupported response')
                raw_reply = response.read(MAX_RESPONSE + 1)
            if len(raw_reply) > MAX_RESPONSE:
                raise ValueError('Response exceeds limit')
            result = strict_json(raw_reply)
            if type(result) is not dict:
                raise ValueError('Expected object')
            return result
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            raise RuntimeError('Scoped HA unavailable; mutation outcome may be unknown; no automatic retry') from None

    def get_capabilities(self):
        return self._request('GET', '/capabilities')

    def control(self, action):
        validate(ACTION_SCHEMA, action)
        return self._request('POST', '/action', {'action': action})

    def propose(self, spec):
        validate(SPEC_SCHEMA, spec)
        return self._request('POST', '/proposals', {'spec': spec})

    def list_managed(self):
        return self._request('GET', '/managed')

    def get_managed(self, identifier):
        validate(TARGET_SCHEMA, identifier)
        return self._request('GET', '/managed/' + identifier)

    def propose_edit(self, request):
        validate(EDIT_SCHEMA, request)
        return self._request('POST', '/edits', request)

    def set_managed_state(self, request):
        validate(STATE_SCHEMA, request)
        return self._request('POST', '/managed-state', request)

    def diagnostics(self):
        return self._request('GET', '/diagnostics')

    def check_config(self):
        return self._request('POST', '/check-config', {})

    def workload_health(self):
        return self._request('POST', '/workload-health', {})

    def restart(self):
        return self._request('POST', '/workload-restart', {})

    def get_proposal(self, identifier):
        validate({'type': 'string', 'pattern': ID_PATTERN}, identifier)
        return self._request('GET', '/proposals/' + identifier)


def supported_services(supported):
    if type(supported) is list:
        services = supported
    elif type(supported) is dict:
        services = []
        for domain, names in supported.items():
            if (type(domain) is not str or re.fullmatch(r'[a-z_]+', domain) is None
                    or type(names) is not list or not names
                    or any(type(name) is not str or re.fullmatch(r'[a-z_]+', name) is None for name in names)):
                raise ValueError('Malformed supported actions')
            services.extend(domain + '.' + name for name in names)
    else:
        raise ValueError('Missing supported actions')
    if not services or any(type(service) is not str or re.fullmatch(r'[a-z_]+\.[a-z_]+', service) is None for service in services):
        raise ValueError('Malformed supported action')
    allowed = {service for form in ACTION_SCHEMA['oneOf'] for service in form['properties']['action']['enum']}
    if not set(services) <= allowed:
        raise ValueError('Unsupported action advertised by HA')
    return set(services)


def validate_capabilities(reply):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    if (type(reply) is not dict or type(reply.get('version')) is not int or reply['version'] != 3
            or type(reply.get('ha_version')) is not str or not reply['ha_version']
            or type(reply.get('approval_ready')) is not bool
            or type(reply.get('inventory')) is not dict
            or type(reply.get('time_zone')) is not str):
        raise ValueError('Incomplete v3 capabilities')
    try:
        ZoneInfo(reply['time_zone'])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Unsupported HA timezone') from None
    if reply['time_zone'] != 'Australia/Melbourne':
        raise ValueError('Unsupported HA timezone')
    if 'standing_permissions' in reply and type(reply['standing_permissions']) is not bool:
        raise ValueError('Invalid standing permission evidence')
    supported_services(reply.get('supported_actions'))
    for identifier, entry in reply['inventory'].items():
        validate(ENTITY, identifier)
        if (type(entry) is not dict or entry.get('entity_id') != identifier
                or type(entry.get('state')) is not str or type(entry.get('attributes')) is not dict
                or type(entry.get('registry_fingerprint')) is not str
                or re.fullmatch(r'[0-9a-f]{64}', entry['registry_fingerprint']) is None
                or not {'name', 'area', 'device_name'} <= set(entry)):
            raise ValueError('Incomplete inventory entry')
        for field in ('name', 'area', 'device_name'):
            if entry[field] is not None and type(entry[field]) is not str:
                raise ValueError('Invalid inventory metadata')
    return reply


def check_action(action, caps):
    validate(ACTION_SCHEMA, action)
    identifier = action['target']['entity_id']
    service = action['action']
    data = action.get('data', {})
    if service == 'light.turn_on':
        if ({'brightness', 'brightness_pct'} <= set(data)
                or len(set(data) & {'rgb_color', 'hs_color', 'xy_color', 'color_temp_kelvin'}) > 1):
            raise ValueError('Conflicting light parameters')
    if service not in supported_services(caps['supported_actions']):
        raise ValueError('Action not advertised by HA')
    if identifier not in caps['inventory'] or identifier.split('.')[0] != service.split('.')[0]:
        raise ValueError('Unknown or incompatible entity')
    if caps['inventory'][identifier]['state'] in ('unavailable', 'unknown', ''):
        raise ValueError('Entity unavailable')


def validate_queue(reply):
    if (type(reply) is not dict or reply.get('status') != 'queued'
            or reply.get('confirmation_required') is not True):
        raise ValueError('Incomplete queued receipt; outcome may be unknown')
    validate({'type': 'string', 'pattern': ID_PATTERN}, reply.get('id'))
    validate({'type': 'string', 'pattern': r'^[0-9a-f]{64}$'}, reply.get('sha256'))
    return reply


def timestamp(value):
    from datetime import datetime
    if type(value) is not str:
        raise ValueError('Missing timestamp')
    observed = datetime.fromisoformat(value)
    if observed.tzinfo is None:
        raise ValueError('Missing timezone')
    return observed


def canonical_hash(value):
    import hashlib
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def validate_managed(reply, identifier=None):
    if type(reply) is not dict or type(reply.get('config')) is not dict:
        raise ValueError('Missing managed config')
    validate(TARGET_SCHEMA, reply.get('target_id'))
    validate(TARGET_SCHEMA, reply.get('owner_record_id'))
    validate(HASH_SCHEMA, reply.get('config_hash'))
    validate({'type':'string','pattern':r'^automation\.[a-z0-9_]+$'}, reply.get('entity_id'))
    if (reply.get('runtime_state') not in ('on','off') or reply['config'].get('id') != reply['target_id']
            or identifier is not None and identifier != reply['target_id']
            or canonical_hash(reply['config']) != reply['config_hash']):
        raise ValueError('Invalid managed evidence')
    return reply


def validate_edit_payload(payload):
    if type(payload) is not dict or set(payload) != {'target_id','base_config_hash','before','after','spec','runtime_state'}:
        raise ValueError('Incomplete edit')
    validate(EDIT_SCHEMA,{k:payload[k] for k in ('target_id','base_config_hash','spec')})
    if (type(payload['before']) is not dict or type(payload['after']) is not dict
            or payload['before'].get('id') != payload['target_id']
            or payload['before'].get('initial_state') is not None
            or payload['runtime_state'] not in ('on','off')
            or canonical_hash(payload['before']) != payload['base_config_hash']):
        raise ValueError('Invalid edit base')
    spec=payload['spec']
    triggers=[]
    for item in spec['triggers']:
        row={k:v for k,v in item.items() if k not in ('type','for_seconds')}
        row['trigger']=item['type']
        if 'for_seconds' in item:row['for']={'seconds':item['for_seconds']}
        triggers.append(row)
    conditions=[dict({k:v for k,v in item.items() if k!='type'},condition=item['type']) for item in spec.get('conditions',[])]
    actions=[dict(item,data=item.get('data',{})) for item in spec['actions']]
    after=dict(payload['before'],alias=spec['title'],mode='single',triggers=triggers,conditions=conditions,actions=actions)
    if payload['after'] != after:
        raise ValueError('Edit after differs from complete spec')
    return spec


def validate_status(reply, identifier):
    import hashlib
    statuses = {'queued', 'preview_pending', 'awaiting_approval', 'pending', 'executed', 'verified_enabled',
                'changed', 'uncertain', 'expired', 'rejected', 'verified_edit', 'superseded'}
    if (type(reply) is not dict or reply.get('id') != identifier
            or reply.get('status') not in statuses or reply.get('recorded_status') not in statuses):
        raise ValueError('Incomplete proposal status')
    timestamp(reply.get('observed_at'))
    doc = reply.get('proposal')
    required = {'version', 'id', 'kind', 'created_at', 'expires_at', 'bindings', 'payload', 'sha256'}
    if (type(doc) is not dict or not required <= set(doc) or doc['id'] != identifier
            or type(doc['version']) is not int or doc['version'] != 3
            or doc['kind'] not in ('action', 'automation', 'edit') or type(doc['bindings']) is not dict
            or not doc['bindings']):
        raise ValueError('Incomplete proposal evidence')
    created = timestamp(doc['created_at'])
    if created > timestamp(reply['observed_at']):
        raise ValueError('Proposal not yet valid')
    if doc['expires_at'] is None:
        if doc['kind'] not in ('automation', 'edit'):
            raise ValueError('Invalid proposal lifetime')
    elif (timestamp(doc['expires_at']) - created).total_seconds() != 900:
        raise ValueError('Invalid proposal lifetime')
    # Historical/expired receipts remain readable, never actionable through MCP.
    payload = validate_edit_payload(doc['payload']) if doc['kind'] == 'edit' else doc['payload']
    validate(ACTION_SCHEMA if doc['kind'] == 'action' else SPEC_SCHEMA, payload)
    if doc['kind'] == 'action':
        referenced = {payload['target']['entity_id']}
    else:
        referenced = {action['target']['entity_id'] for action in payload['actions']}
        referenced.update(item['entity_id'] for item in payload['triggers'] + payload.get('conditions', []) if item['type'] == 'state')
    if set(doc['bindings']) != referenced:
        raise ValueError('Incomplete proposal bindings')
    for entity, fingerprint in doc['bindings'].items():
        validate(ENTITY, entity)
        validate({'type': 'string', 'pattern': r'^[0-9a-f]{64}$'}, fingerprint)
    unhashed = {key: value for key, value in doc.items() if key != 'sha256'}
    digest = hashlib.sha256(json.dumps(unhashed, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    if doc['sha256'] != digest:
        raise ValueError('Proposal hash mismatch')
    if reply['status'] == 'verified_enabled':
        if reply.get('runtime_state') != 'on' or reply['recorded_status'] != 'verified_enabled':
            raise ValueError('Enabled status lacks runtime evidence')
        validate({'type': 'string', 'pattern': r'^automation\.[a-z0-9_]+$'}, reply.get('entity_id'))
        timestamp(reply.get('verified_at'))
    if reply['status'] == 'verified_edit':
        if (doc['kind'] != 'edit' or reply['recorded_status'] != 'verified_edit'
                or reply.get('target_id') != doc['payload']['target_id']
                or reply.get('runtime_state') != doc['payload']['runtime_state']
                or type(reply.get('evidence')) is not dict
                or reply['evidence'].get('config_hash') != canonical_hash(doc['payload']['after'])):
            raise ValueError('Edit status lacks runtime evidence')
        validate({'type':'string','pattern':r'^automation\.[a-z0-9_]+$'}, reply.get('entity_id'))
        timestamp(reply.get('verified_at'))
    if reply['status'] == 'superseded':
        validate(TARGET_SCHEMA, reply.get('superseded_by'))
    return reply


def validate_standing_result(reply, args, client, *, editing):
    expected = 'verified_edit' if editing else 'verified_enabled'
    if (type(reply) is not dict or reply.get('status') != expected
            or reply.get('confirmation_required') is not False
            or reply.get('authorization') != {'source':'standing_policy', 'policy_id':'routine_automations_v1'}):
        raise ValueError('Unverified standing result; no automatic retry')
    validate(TARGET_SCHEMA, reply.get('id'))
    validate(HASH_SCHEMA, reply.get('config_hash'))
    timestamp(reply.get('verified_at'))
    observed = validate_status(client.get_proposal(reply['id']), reply['id'])
    payload = observed['proposal']['payload']
    spec = args['spec']
    normalized_spec = dict(spec, conditions=spec.get('conditions', []),
                           actions=[dict(action, data=action.get('data', {})) for action in spec['actions']])
    if (observed['status'] != expected or observed['entity_id'] != reply.get('entity_id')
            or observed['evidence']['config_hash'] != reply['config_hash']
            or 'runtime_state' in reply and reply['runtime_state'] != observed.get('runtime_state')
            or (payload['spec'] if editing else payload) != normalized_spec
            or editing and (payload['target_id'] != args['target_id']
                            or reply.get('target_id') != args['target_id']
                            or reply.get('runtime_state') != observed.get('runtime_state')
                            or payload['base_config_hash'] != args['base_config_hash'])):
        raise ValueError('Standing readback mismatch; no automatic retry')
    evidence = observed['evidence'].get('approval')
    if (type(evidence) is not dict or evidence.get('source') != 'standing_policy'
            or evidence.get('policy_id') != 'routine_automations_v1'
            or evidence.get('sha256') != observed['proposal']['sha256']):
        raise ValueError('Missing standing authorization evidence')
    timestamp(evidence.get('timestamp'))
    return observed


def handle_tool(name, args, client=None):
    tool = next((item for item in TOOLS if item['name'] == name), None)
    if tool is None:
        raise ValueError('Unknown tool')
    validate(tool['inputSchema'], args)
    if len(json.dumps(args, allow_nan=False).encode('utf-8')) > MAX_REQUEST:
        raise ValueError('Request exceeds limit')
    if client is None:
        import os
        client = HAClient(os.environ.get('HA_MCP_TOKEN', ''))
    if name == 'get_home_capabilities':
        return validate_capabilities(client.get_capabilities())
    if name == 'get_home_diagnostics':
        reply = client.diagnostics()
        schema = obj({'ha_version':text(40), 'entity_count':number(0,1000000,True),
                      'unavailable_count':number(0,1000000,True), 'unknown_count':number(0,1000000,True),
                      'enrolled_helper_count':number(0,100,True),
                      'entries':{'type':'array','maxItems':30,'items':obj({'entry_id':text(128),'domain':text(80),'state':text(80)})}})
        validate(schema, reply)
        return reply
    if name == 'check_home_configuration':
        reply = client.check_config()
        validate(obj({'valid':BOOL,'checked_at':text(80)}), reply)
        timestamp(reply['checked_at'])
        return reply
    if name == 'get_home_workload_health':
        reply = client.workload_health()
        health = obj({'workload':{'const':'home-assistant'}, 'kind':{'const':'StatefulSet'},
                      'desired_replicas':number(0,100,True), 'ready_replicas':number(0,100,True),
                      'updated_replicas':number(0,100,True), 'generation_observed':BOOL,
                      'revision_converged':BOOL, 'pod_present':BOOL, 'pod_running':BOOL,
                      'pod_terminating':BOOL, 'pod_ready':BOOL,
                      'containers':{'type':'array','maxItems':20,'items':obj({'ready':BOOL,
                          'restart_count':number(0,1000000,True),'waiting':BOOL,'terminated':BOOL})}})
        validate(obj({'ok':{'const':True},'health':health}), reply)
        return reply
    if name == 'restart_home_assistant':
        reply = client.restart()
        validate(obj({'ok':{'const':True},'restart_requested':{'const':True},
                      'annotation_verified':{'const':True}, 'rollout_verified':{'const':False},
                      'config_check_verified':{'const':True},'config_checked_at':text(80)}), reply)
        timestamp(reply['config_checked_at'])
        return reply
    if name == 'set_managed_home_automation_state':
        reply = client.set_managed_state(args)
        observed = validate_managed(client.get_managed(args['target_id']), args['target_id'])
        if (type(reply) is not dict or reply.get('status') != 'verified_state'
                or reply.get('receipt_type') != 'managed_state'
                or reply.get('target_id') != args['target_id']
                or reply.get('owner_record_id') != observed['owner_record_id']
                or reply.get('config_hash') != args['base_config_hash']
                or reply.get('confirmation_required') is not False
                or reply.get('authorization') != {'source':'standing_policy','policy_id':'routine_automations_v1'}
                or observed['config_hash'] != args['base_config_hash']
                or observed['runtime_state'] != ('on' if args['enabled'] else 'off')
                or reply.get('runtime_state') != observed['runtime_state']
                or reply.get('entity_id') != observed['entity_id']):
            raise ValueError('Automation state unverified; no automatic retry')
        timestamp(reply.get('verified_at'))
        return {'response':observed, 'device_state_verified':False}
    if name == 'get_home_proposal':
        reply = validate_status(client.get_proposal(args['proposal_id']), args['proposal_id'])
        return {'response': reply, 'device_state_verified': False}
    if name == 'get_managed_home_automation':
        return {'response':validate_managed(client.get_managed(args['target_id']),args['target_id']), 'device_state_verified':False}
    if name == 'list_managed_home_automations':
        reply=client.list_managed()
        if type(reply) is not dict or set(reply) != {'automations','unavailable'} or type(reply['automations']) is not list or type(reply['unavailable']) is not list:
            raise ValueError('Incomplete discovery')
        ids=[]
        for item in reply['automations']:
            validate_managed(item);ids.append(item['target_id'])
        for item in reply['unavailable']:
            validate(obj({'target_id':TARGET_SCHEMA,'reason':text()}),item);ids.append(item['target_id'])
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate discovery target')
        return {'response':reply, 'device_state_verified':False}
    if name in ('propose_home_automation', 'propose_home_automation_edit'):
        caps = validate_capabilities(client.get_capabilities())
        if not caps['approval_ready'] and not caps.get('standing_permissions',False):
            raise ValueError('Independent human approval unavailable')
        for action in args['spec']['actions']:
            check_action(action, caps)
        for item in args['spec']['triggers'] + args['spec'].get('conditions', []):
            if item['type'] == 'state' and item['entity_id'] not in caps['inventory']:
                raise ValueError('Unknown state entity')
        reply = client.propose_edit(args) if name == 'propose_home_automation_edit' else client.propose(args['spec'])
        if type(reply) is dict and reply.get('status') == 'queued':
            reply = validate_queue(reply)
        elif caps.get('standing_permissions') is True:
            reply = validate_standing_result(reply, args, client, editing=name == 'propose_home_automation_edit')
        else:
            raise ValueError('Unexpected immediate result; no automatic retry')
        return {'response': reply, 'device_state_verified': False}
    if name == 'control_home_device':
        caps = validate_capabilities(client.get_capabilities())
        action = args['action']
        check_action(action, caps)
        reply = client.control(action)
        if type(reply) is dict and reply.get('status') == 'queued':
            return {'response': validate_queue(reply), 'device_state_verified': False}
        if (type(reply) is not dict or reply.get('status') != 'executed'
                or reply.get('device_state_verified') is not False
                or reply.get('confirmation_required') is not False):
            raise ValueError('Incomplete action response; outcome may be unknown; do not retry automatically')
        return {'response': reply, 'device_state_verified': False}
    raise ValueError('Unsupported response')


def serve(input_stream=None, output_stream=None, client=None):
    import sys
    source = sys.stdin.buffer if input_stream is None else input_stream
    sink = sys.stdout if output_stream is None else output_stream
    while True:
        line = source.readline(MAX_REQUEST + 1)
        if not line:
            return
        request = {}
        oversized = len(line) > MAX_REQUEST
        try:
            if oversized:
                raise ValueError('Request exceeds limit')
            request = strict_json(line)
            if (type(request) is not dict or request.get('jsonrpc') != '2.0'
                    or set(request) - {'jsonrpc', 'id', 'method', 'params'}
                    or type(request.get('method')) is not str):
                raise ValueError('Invalid request')
            if 'id' not in request:
                continue  # Notifications never perform tools, especially mutations.
            if request['id'] is not None and type(request['id']) not in (int, str):
                raise ValueError('Invalid request ID')
            method = request['method']
            params = request.get('params', {})
            if type(params) is not dict:
                raise ValueError('Invalid parameters')
            if method == 'initialize':
                if set(params) - {'protocolVersion', 'capabilities', 'clientInfo', '_meta'}:
                    raise ValueError('Unknown initialize parameters')
                result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'house-manager-general-v3', 'version': '3.3.0'}}
            elif method in ('ping', 'tools/list'):
                if set(params) - {'_meta'}:
                    raise ValueError('Unknown parameters')
                result = {} if method == 'ping' else {'tools': TOOLS}
            elif method == 'tools/call':
                try:
                    if set(params) - {'name', 'arguments', '_meta'} or 'name' not in params:
                        raise ValueError('Invalid tool parameters')
                    value = handle_tool(params['name'], params.get('arguments', {}), client)
                    result = {'content': [{'type': 'text', 'text': json.dumps(value, allow_nan=False)}], 'isError': False}
                except Exception:
                    # A POST may have reached HA. Never echo exceptions or credentials.
                    result = {'content': [{'type': 'text', 'text': 'Request denied or HA result unavailable/unverified. A mutation outcome may be unknown; do not automatically retry. No approval was granted by this connector.'}], 'isError': True}
            else:
                response = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not supported'}}
                print(json.dumps(response), file=sink, flush=True)
                continue
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
        except Exception:
            identifier = request.get('id') if type(request) is dict else None
            if type(identifier) not in (str, int):
                identifier = None
            response = {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32600, 'message': 'Invalid request'}}
        print(json.dumps(response, allow_nan=False), file=sink, flush=True)
        if oversized:
            return  # Never interpret the remainder as a second request.


def main(argv=None):
    import sys
    args = sys.argv[1:] if argv is None else argv
    if args:
        print('Only stdio MCP is supported', file=sys.stderr)
        return 1
    serve()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
