"""Pure, fail-closed household policy; no Home Assistant dependencies or I/O."""
import copy
import re
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta


class PolicyError(ValueError):
    """A request cannot be safely authorized."""


def _require(ok, message='Unsupported or malformed request'):
    if not ok:
        raise PolicyError(message)


def _keys(value, required, optional=()):
    _require(type(value) is dict and set(required) <= value.keys()
             and value.keys() <= set(required) | set(optional))


def _entity(entity, inventory, available=True):
    _require(type(entity) is str and re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z0-9_]+', entity))
    _require(type(inventory) is dict and entity in inventory, 'Unknown entity')
    item = inventory[entity]
    _require(type(item) is dict and item.get('entity_id') == entity)
    _require(type(item.get('state')) is str and item['state'] != '')
    if available:
        _require(item['state'] not in ('unknown', 'unavailable'))
    _require(type(item.get('attributes')) is dict)
    _fingerprint(item.get('registry_fingerprint'))
    return item


def _number(value, low, high, integer=False):
    import math
    _require(type(value) in ((int,) if integer else (int, float)))
    _require(type(low) in (int, float) and type(high) in (int, float))
    try:
        _require(math.isfinite(value) and math.isfinite(low) and math.isfinite(high)
                 and low <= value <= high)
    except OverflowError:
        raise PolicyError('Numeric value cannot be represented safely') from None


def _light(service, data, attrs):
    _require(service in ('turn_on', 'turn_off'))
    if service == 'turn_off':
        _keys(data, ())
        return
    _keys(data, (), ('brightness', 'brightness_pct', 'rgb_color', 'hs_color',
                     'xy_color', 'color_temp_kelvin'))
    modes = attrs.get('supported_color_modes', [])
    colors = set(data) & {'rgb_color', 'hs_color', 'xy_color', 'color_temp_kelvin'}
    _require(len(colors) <= 1 and not {'brightness', 'brightness_pct'} <= data.keys())
    for key, value in data.items():
        if key in ('brightness', 'brightness_pct'):
            _require(type(modes) is list and any(m in ('brightness', 'color_temp', 'hs', 'xy', 'rgb', 'rgbw', 'rgbww', 'white') for m in modes))
            _number(value, 0, 255 if key == 'brightness' else 100, key == 'brightness')
        elif key == 'color_temp_kelvin':
            _require('color_temp' in modes)
            _number(value, attrs.get('min_color_temp_kelvin'), attrs.get('max_color_temp_kelvin'), True)
        else:
            mode = key.split('_')[0]
            _require(mode in modes and type(value) is list and len(value) == (3 if mode == 'rgb' else 2))
            for index, component in enumerate(value):
                high = 255 if mode == 'rgb' else (1 if mode == 'xy' else (360 if index == 0 else 100))
                _number(component, 0, high, mode == 'rgb')


def _feature(attrs, bit):
    features = attrs.get('supported_features', 0)
    _require(type(features) is int and features >= 0 and features & bit == bit,
             'Device does not advertise this feature')


def _option(value, options):
    _require(type(value) is str and type(options) is list and value in options)
    _literal(value)


def _literal(value):
    _require(type(value) is str and 0 < len(value) <= 512
             and not any(token in value for token in ('{{', '}}', '{%', '%}', '://')))


def _step(value, low, high, step):
    _number(value, low, high)
    _number(step, 0.000000001, 1000000000)
    quotient = (value - low) / step
    _require(abs(quotient - round(quotient)) <= 0.000001)


def _fan(service, data, attrs):
    schemas = {'turn_on': ((), ('percentage', 'preset_mode')),
               'turn_off': ((), ()), 'set_percentage': (('percentage',), ()),
               'set_preset_mode': (('preset_mode',), ()),
               'oscillate': (('oscillating',), ()), 'set_direction': (('direction',), ())}
    _require(service in schemas)
    _keys(data, *schemas[service])
    if service in ('turn_on', 'turn_off'):
        _feature(attrs, 32 if service == 'turn_on' else 16)
    _require(not {'percentage', 'preset_mode'} <= data.keys())
    for key, value in data.items():
        if key == 'percentage':
            _feature(attrs, 1)
            _require(type(value) is int)
            _step(value, 0, 100, attrs.get('percentage_step'))
        elif key == 'preset_mode':
            _feature(attrs, 8)
            _option(value, attrs.get('preset_modes'))
        elif key == 'oscillating':
            _feature(attrs, 2)
            _require(type(value) is bool)
        elif key == 'direction':
            _feature(attrs, 4)
            _option(value, ['forward', 'reverse'])


def _media(service, data, attrs):
    commands = {'turn_on': (128, None), 'turn_off': (256, None),
                'media_play': (16384, None), 'media_pause': (1, None),
                'media_stop': (4096, None), 'volume_set': (4, 'volume_level'),
                'volume_mute': (8, 'is_volume_muted'), 'select_source': (2048, 'source'),
                'select_sound_mode': (65536, 'sound_mode')}
    _require(service in commands)
    bit, key = commands[service]
    _feature(attrs, bit)
    _keys(data, (key,) if key else ())
    if key == 'volume_level':
        _number(data[key], 0, 1)
    elif key == 'is_volume_muted':
        _require(type(data[key]) is bool)
    elif key:
        _option(data[key], attrs.get('source_list' if key == 'source' else 'sound_mode_list'))


def _switch(service, data, attrs):
    _require(service in ('turn_on', 'turn_off'))
    _keys(data, ())


def _select(service, data, attrs):
    _require(service == 'select_option')
    _keys(data, ('option',))
    _option(data['option'], attrs.get('options'))


def _numeric(service, data, attrs):
    _require(service == 'set_value')
    _keys(data, ('value',))
    _step(data['value'], attrs.get('min'), attrs.get('max'), attrs.get('step'))


def _climate(service, data, attrs):
    modes = attrs.get('hvac_modes')
    if service in ('turn_on', 'turn_off'):
        _keys(data, ())
        _feature(attrs, 256 if service == 'turn_on' else 128)
        _require(type(modes) is list and any(mode != 'off' for mode in modes))
        if service == 'turn_off':
            _option('off', modes)
    elif service == 'set_hvac_mode':
        _keys(data, ('hvac_mode',))
        _option(data['hvac_mode'], modes)
    elif service == 'set_temperature':
        _feature(attrs, 1)
        _keys(data, ('temperature',), ('hvac_mode',))
        _number(data['temperature'], attrs.get('min_temp'), attrs.get('max_temp'))
        if 'target_temp_step' in attrs:
            _step(data['temperature'], attrs.get('min_temp'), attrs.get('max_temp'), attrs['target_temp_step'])
        if 'hvac_mode' in data:
            _option(data['hvac_mode'], modes)
    else:
        schemas = {'set_fan_mode': ('fan_mode', 'fan_modes', 8),
                   'set_swing_mode': ('swing_mode', 'swing_modes', 32),
                   'set_preset_mode': ('preset_mode', 'preset_modes', 16)}
        _require(service in schemas)
        key, options, bit = schemas[service]
        _feature(attrs, bit)
        _keys(data, (key,))
        _option(data[key], attrs.get(options))


def _confirmation(domain, service, data, item):
    if domain == 'climate':
        return (service in ('turn_on', 'set_temperature', 'set_preset_mode')
                or (service == 'set_hvac_mode' and data['hvac_mode'] != 'off'))
    if service in ('turn_off', 'media_stop', 'media_pause'):
        return False
    if domain == 'select' and data['option'].casefold() in ('off', 'stop', 'pause'):
        return False
    if domain == 'fan' and ((service in ('turn_on', 'set_percentage') and data.get('percentage') == 0)
                            or (service == 'set_preset_mode' and data['preset_mode'].casefold() in ('off', 'stop', 'pause'))):
        return False
    # A power/speed command can resume the trusted retained heating preset.
    if domain == 'fan':
        attrs = item['attributes']
        current = attrs.get('preset_mode')
        advertised = attrs.get('preset_modes', [])
        heating_capable = any(type(value) is str and re.search(r'heat|warm', value.casefold())
                              for value in ([current] + (advertised if type(advertised) is list else [])))
        # _fan already requires an advertised, literal preset and forbids
        # combining it with percentage. An explicit auto/ventilation preset
        # therefore replaces retained heat; bare power/speed commands do not.
        mode = data.get('preset_mode', current) if service in ('turn_on', 'set_percentage', 'set_preset_mode') else None
        if type(mode) is str and re.search(r'heat|warm', mode.casefold()):
            return True
        if (heating_capable and service in ('turn_on', 'set_percentage', 'set_preset_mode')
                and mode not in ('auto', 'ventilation')):
            return True
    metadata = ' '.join(str(item.get(key, '')) for key in
                        ('entity_id', 'name', 'device_name')).casefold().replace('_', ' ')
    dangerous = any(word in metadata for word in
                    ('dryer', 'washer', 'washing', 'oven', 'cook', 'heat', 'boiler',
                     'kettle', 'stove', 'furnace', 'radiator', 'laundry', 'tumble'))
    if domain in ('select', 'switch', 'number', 'fan') and dangerous:
        return True
    if domain in ('select', 'switch', 'number'):
        accessory = any(word in metadata for word in ('light', 'lamp', 'night', 'focus', 'continuous monitoring'))
        purifier = 'purifier' in metadata or 'dyson pure hot + cool link' in metadata
        return not (purifier and accessory)
    return False


def validate_action(action, inventory):
    _keys(action, ('action', 'target'), ('data',))
    _keys(action['target'], ('entity_id',))
    entity = action['target']['entity_id']
    item = _entity(entity, inventory)
    command = action['action']
    _require(type(command) is str and re.fullmatch(r'[a-z_]+\.[a-z_]+', command))
    domain, service = command.split('.')
    _require(entity.split('.')[0] == domain)
    data = action.get('data', {})
    _require(type(data) is dict)
    handlers = {'light': _light, 'fan': _fan, 'media_player': _media,
                'switch': _switch, 'select': _select, 'number': _numeric, 'climate': _climate}
    _require(domain in handlers)
    handlers[domain](service, data, item['attributes'])
    maintenance_text = ' '.join(str(item.get(key, '')) for key in ('entity_id', 'name', 'device_name'))
    maintenance_text += ' ' + ' '.join(value for value in data.values() if type(value) is str)
    _require(not re.search(r'\b(reset|restart|reboot|factory|firmware)\b',
                           maintenance_text.casefold().replace('_', ' ')), 'Maintenance controls are prohibited')
    return {'action': {'action': action['action'], 'target': {'entity_id': entity},
                       'data': copy.deepcopy(data)},
            'confirmation_required': _confirmation(domain, service, data, item)}


def _time(value):
    _require(type(value) is str and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]', value))


def _state_reference(value, inventory):
    entity = value['entity_id']
    _entity(entity, inventory, available=False)
    _require(entity.split('.')[0] in ('light', 'fan', 'media_player', 'switch', 'select',
                                      'number', 'climate', 'sensor', 'binary_sensor'))


def validate_spec(spec, inventory):
    _keys(spec, ('title', 'triggers', 'actions'), ('conditions',))
    _literal(spec['title'])
    _require(len(spec['title']) <= 160 and bool(spec['title'].strip()))
    for key, minimum, maximum in (('triggers', 1, 10), ('conditions', 0, 10), ('actions', 1, 20)):
        values = spec.get(key, [])
        _require(type(values) is list and minimum <= len(values) <= maximum)
    triggers = []
    for trigger in spec['triggers']:
        _require(type(trigger) is dict)
        kind = trigger.get('type')
        if kind == 'time':
            _keys(trigger, ('type', 'at'))
            _time(trigger['at'])
        elif kind == 'state':
            _keys(trigger, ('type', 'entity_id', 'to'), ('for_seconds',))
            _state_reference(trigger, inventory)
            _literal(trigger['to'])
            if 'for_seconds' in trigger:
                _number(trigger['for_seconds'], 0, 2147483647, True)
        else:
            raise PolicyError('Unsupported trigger')
        native = {key: copy.deepcopy(value) for key, value in trigger.items()
                  if key not in ('type', 'for_seconds')}
        native['trigger'] = trigger['type']
        if 'for_seconds' in trigger:
            native['for'] = {'seconds': trigger['for_seconds']}
        triggers.append(native)
    conditions = []
    for condition in spec.get('conditions', []):
        _require(type(condition) is dict)
        if condition.get('type') == 'state':
            _keys(condition, ('type', 'entity_id', 'state'))
            _state_reference(condition, inventory)
            _literal(condition['state'])
        elif condition.get('type') == 'time':
            _keys(condition, ('type', 'after', 'before'))
            _time(condition['after'])
            _time(condition['before'])
        else:
            raise PolicyError('Unsupported condition')
        native = {key: copy.deepcopy(value) for key, value in condition.items() if key != 'type'}
        native['condition'] = condition['type']
        conditions.append(native)
    return {'alias': spec['title'], 'mode': 'single', 'triggers': triggers,
            'conditions': conditions,
            'actions': [validate_action(a, inventory)['action'] for a in spec['actions']]}


def _json_types(value):
    if type(value) is dict:
        _require(all(type(key) is str for key in value))
        for child in value.values():
            _json_types(child)
    elif type(value) is list:
        for child in value:
            _json_types(child)
    else:
        _require(value is None or type(value) in (str, bool, int, float))


def hash_json(value):
    """SHA256 of canonical UTF-8 JSON (sorted keys, compact, no NaN)."""
    try:
        _json_types(value)
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PolicyError('Not canonical JSON') from None
    return hashlib.sha256(encoded).hexdigest()


def _now(value):
    if value is None:
        return datetime.now(timezone.utc)
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() is not None, 'Clock must be timezone-aware')
    return value.astimezone(timezone.utc)


def _fingerprint(value):
    _require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value), 'Invalid fingerprint')
    return value


def _payload(kind, payload, inventory):
    _require(type(kind) is str and kind in ('action', 'automation', 'edit'))
    if kind == 'edit':
        _keys(payload, ('target_id', 'base_config_hash', 'before', 'after', 'spec', 'runtime_state'))
        _require(type(payload['target_id']) is str and re.fullmatch(r'house_manager_general_[0-9a-f]{32}', payload['target_id']))
        _require(payload['runtime_state'] in ('on', 'off'))
        before = payload['before']
        _require(type(before) is dict and before.get('id') == payload['target_id'])
        _require(before.get('initial_state') is None, 'Explicit initial_state is unsafe for editing')
        _require(hash_json(before) == _fingerprint(payload['base_config_hash']), 'Base config changed')
        spec, bindings = _payload('automation', payload['spec'], inventory)
        after = dict(before, **validate_spec(spec, inventory))
        _require(payload['after'] == after, 'After config differs from complete spec')
        return dict(copy.deepcopy(payload), spec=spec), bindings
    if kind == 'action':
        normalized = validate_action(payload, inventory)['action']
        references = {normalized['target']['entity_id']}
    else:
        native = validate_spec(payload, inventory)
        normalized = copy.deepcopy(payload)
        normalized['conditions'] = normalized.get('conditions', [])
        normalized['actions'] = native['actions']
        references = {a['target']['entity_id'] for a in normalized['actions']}
        references.update(t['entity_id'] for t in normalized['triggers'] if t['type'] == 'state')
        references.update(c['entity_id'] for c in normalized['conditions'] if c['type'] == 'state')
    bindings = {entity: _fingerprint(inventory[entity].get('registry_fingerprint'))
                for entity in sorted(references)}
    return normalized, bindings


def make_proposal(kind, payload, inventory, now=None):
    now = _now(now)
    normalized, bindings = _payload(kind, payload, inventory)
    doc = {'id': 'house_manager_general_' + uuid.uuid4().hex, 'version': 3,
           'kind': kind, 'created_at': now.isoformat(),
           'expires_at': (now + timedelta(minutes=15)).isoformat() if kind == 'action' else None,
           'bindings': bindings, 'payload': normalized}
    doc['sha256'] = hash_json(doc)
    return doc


def validate_proposal(doc, inventory, expected_hash=None, now=None):
    """Recheck an immutable document; consuming/replay protection belongs to the ledger."""
    _keys(doc, ('id', 'version', 'kind', 'created_at', 'expires_at', 'bindings', 'payload', 'sha256'))
    _require(type(doc['id']) is str and re.fullmatch(r'house_manager_general_[0-9a-f]{32}', doc['id']))
    _require(type(doc['version']) is int and doc['version'] == 3)
    _require(type(doc['kind']) is str and doc['kind'] in ('action', 'automation', 'edit'))
    digest = _fingerprint(doc['sha256'])
    _require(expected_hash is None or _fingerprint(expected_hash) == digest, 'Hash does not match approval')
    _require(hash_json({k: v for k, v in doc.items() if k != 'sha256'}) == digest, 'Document changed')
    current = _now(now)
    try:
        _require(type(doc['created_at']) is str)
        created = _now(datetime.fromisoformat(doc['created_at']))
        if doc['expires_at'] is None:
            _require(doc['kind'] in ('automation', 'edit'), 'Invalid proposal lifetime')
            expires = None
        else:
            _require(type(doc['expires_at']) is str)
            expires = _now(datetime.fromisoformat(doc['expires_at']))
            _require(expires - created == timedelta(minutes=15), 'Invalid proposal lifetime')
    except (ValueError, TypeError):
        raise PolicyError('Invalid proposal timestamps') from None
    _require(created <= current and (expires is None or current < expires), 'Proposal expired or not yet valid')
    normalized, bindings = _payload(doc['kind'], doc['payload'], inventory)
    _require(normalized == doc['payload'], 'Payload is not normalized')
    _require(type(doc['bindings']) is dict and doc['bindings'] == bindings, 'Entity binding changed')
    return copy.deepcopy(doc)
