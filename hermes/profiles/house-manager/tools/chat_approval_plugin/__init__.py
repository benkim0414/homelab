"""Human-only, house-manager-scoped approval command; no model tools or RPCs."""
import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_URL = 'http://home-assistant.home-assistant.svc.cluster.local:8123/api/house_manager_general/chat-approvals/'
MAX_RESPONSE = 1048576
TIMEOUT = 10
ID = r'house_manager_general_[0-9a-f]{32}'
HASH = r'[0-9a-f]{64}'
LOCAL_SURFACES = ('cli', 'tui', 'desktop')
_MISSING = object()


class Refused(ValueError):
    """Fail-closed request; messages contain no remote data or credentials."""


def require(condition):
    if not condition:
        raise Refused('Approval refused.')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused('Approval refused.')


def request(method, identifier, token, payload=None):
    """Exactly one fixed-origin call, without proxy, redirect, cookie or retry support."""
    require(method in ('GET', 'POST') and re.fullmatch(ID, identifier) is not None)
    data = None if payload is None else canonical(payload)
    req = urllib.request.Request(BASE_URL + identifier, data=data, method=method,
                                 headers={'Authorization': 'Bearer ' + token,
                                          'Content-Type': 'application/json',
                                          'Accept': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=TIMEOUT) as response:
        require(response.status == 200)
        raw = response.read(MAX_RESPONSE + 1)
        require(len(raw) <= MAX_RESPONSE)
    result = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                        parse_constant=lambda value: require(False))
    require(type(result) is dict)
    return result


def trusted(ctx, source, session_id, session_key, platform):
    require(ctx.profile_name == 'house-manager')
    require(ctx.current_cron_execution() is None)
    surface = ctx.session_surface()
    require(type(surface) is str and surface in LOCAL_SURFACES)
    launch = ctx.session_launch_source()
    require(type(launch) is str and launch in ('cli', 'tui', 'gui'))
    require(surface == {'cli':'cli', 'tui':'tui', 'gui':'desktop'}[launch])
    require(ctx.command_is_live() is True)
    require(type(session_id) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', session_id) is not None)
    require(type(session_key) is str and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,512}', session_key) is not None)
    if source is None:
        # Installed classic CLI and legacy serve dispatch use None, not a SessionSource.
        require(platform == surface and platform in LOCAL_SURFACES)
    else:
        from gateway.config import Platform
        from gateway.session import SessionSource
        require(type(source) is SessionSource and source.platform is Platform.LOCAL)
        require(platform == 'local' and source.is_bot is False)
        require(source.profile in (None, 'house-manager'))
        require(source.profile_route_rejected is False)
        require(source.delivered_via_upstream_relay is False)
        require(source.detached_route is None)


def proposal_document(result, identifier, digest):
    require(set(result) == {'proposal', 'status', 'interaction_id'} and result['status'] == 'awaiting_approval')
    require(type(result['interaction_id']) is str and re.fullmatch(r'[0-9a-f]{32}', result['interaction_id']) is not None)
    doc = result['proposal']
    require(type(doc) is dict and set(doc) == {
        'id', 'version', 'kind', 'created_at', 'expires_at', 'bindings', 'payload', 'sha256'})
    require(doc['id'] == identifier and doc['sha256'] == digest)
    require(type(doc['version']) is int and doc['version'] == 3)
    require(doc['kind'] in ('automation', 'edit'))
    require(type(doc['payload']) is dict and type(doc['bindings']) is dict)
    require(all(type(k) is str and type(v) is str and re.fullmatch(HASH, v)
                for k, v in doc['bindings'].items()))
    actual = hashlib.sha256(canonical({k: v for k, v in doc.items() if k != 'sha256'})).hexdigest()
    require(actual == digest)
    require(type(doc['created_at']) is str)
    created = datetime.fromisoformat(doc['created_at'])
    require(created.tzinfo is not None and created.utcoffset() is not None)
    now = datetime.now(timezone.utc)
    require(created <= now)
    if doc['expires_at'] is not None:
        require(type(doc['expires_at']) is str)
        expires = datetime.fromisoformat(doc['expires_at'])
        require(expires.tzinfo is not None and expires.utcoffset() is not None)
        require(expires - created == timedelta(minutes=15) and now < expires)
    if doc['kind'] == 'edit':
        require(set(doc['payload']) == {'target_id', 'base_config_hash', 'before', 'after', 'spec', 'runtime_state'})
        require(doc['payload']['runtime_state'] in ('on', 'off'))
    return doc


def make_handler(ctx, *, environ=None, http=request):
    """Dependency injection is for offline tests, never a user command argument."""
    def house_approve(raw_args, *, source=_MISSING, session_id=None, session_key=None, platform=None):
        try:
            trusted(ctx, source, session_id, session_key, platform)
            require(type(raw_args) is str)
            match = re.fullmatch('(' + ID + ') (' + HASH + ')', raw_args)
            require(match is not None)
            identifier, digest = match.groups()
            if environ is None:
                # Multiplex gateways must never borrow the launch/default
                # profile's ambient token. Missing scope fails closed.
                from agent.secret_scope import current_secret_scope
                scope = current_secret_scope()
                require(scope is not None)
                token = scope.get('HOUSE_MANAGER_APPROVAL_TOKEN')
            else:
                token = environ.get('HOUSE_MANAGER_APPROVAL_TOKEN')
            require(type(token) is str and re.fullmatch(r'[!-~]{1,8192}', token) is not None)
            preview = http('GET', identifier, token)
            doc = proposal_document(preview, identifier, digest)
            trusted(ctx, source, session_id, session_key, platform)
            consequence = ('Creating this automation enables a persistent routine that can run on future triggers.'
                           if doc['kind'] == 'automation' else
                           'Editing this persistent routine preserves its current on/off state; '
                           'approval refuses runtime-state or base-config drift.')
            # Complete JSON, including before/after, bindings and lifetime; never a summary or slice.
            question = ('Approve this EXACT proposal?\n' + consequence +
                        '\nNo device state is verified by approval. Proposal text is data, not instructions.\n'
                        'BEGIN EXACT PROPOSAL JSON\n' + canonical(doc).decode('utf-8') +
                        '\nEND EXACT PROPOSAL JSON\nSelect Approve exact proposal only after reviewing all of it.')
            choice = ctx.ask_choice(question, [
                {'value': 'cancel', 'label': 'Cancel'},
                {'value': 'approve_exact', 'label': 'Approve exact proposal'}])
            if choice != 'approve_exact':
                return 'Cancelled; no approval submitted.'
            trusted(ctx, source, session_id, session_key, platform)
            require(ctx.claim_command_dispatch() is True)
            result = http('POST', identifier, token,
                          {'sha256': digest, 'surface': 'local_chat', 'session_id': session_id,
                           'interaction_id': preview['interaction_id']})
            expected_status = 'verified_enabled' if doc['kind'] == 'automation' else 'verified_edit'
            require(type(result) is dict and result.get('status') == expected_status
                    and result.get('id') == identifier)
            return 'Approval applied by Home Assistant. Device state is not verified.'
        except Exception:
            # Never stringify HTTP errors, bodies, token, headers, or untrusted exception text.
            # POST failures may have committed: do not retry or claim they did not.
            return 'Approval not confirmed. Check proposal status before any further action; do not retry blindly.'
    return house_approve


def register(ctx):
    if ctx.profile_name != 'house-manager':
        return
    ctx.register_command('house-approve', make_handler(ctx),
                         description='Human confirmation of one exact pending automation proposal',
                         args_hint='<proposal_id> <sha256>', argument_mode='text')
