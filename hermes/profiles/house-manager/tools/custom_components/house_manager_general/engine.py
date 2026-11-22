"""Internal approval coordinator shared by isolated approval adapters.

Authenticated approval adapters and explicitly opted-in standing policy share the
same execution path. Pending and uncertain records are never automatically retried.
"""
import asyncio
import copy
import re
from datetime import datetime, timezone
from . import policy as p

HA_VERSION = '2026.11.1'
TIME_ZONE = 'Australia/Melbourne'
ID = re.compile(r'house_manager_general_[0-9a-f]{32}')
HEX = re.compile(r'[0-9a-f]{64}')
CHAT_INTERACTION_SECONDS = 300
STANDING_POLICY = 'routine_automations_v1'

def native_hash(value):
    """HA annotates YAML dict/list/str subclasses; hash content, not annotations.

    This applies ONLY to trusted native readback, never incoming proposals. Do
    not normalize keys or non-JSON YAML types, which would hide definition drift.
    """
    def plain(item):
        if isinstance(item,dict):
            if not all(isinstance(key,str) for key in item):
                raise ValueError('non-string native key')
            return {str(key):plain(child) for key,child in item.items()}
        if isinstance(item,list):
            return [plain(child) for child in item]
        if isinstance(item,str):
            return str(item)
        if item is None or type(item) in (bool,int,float):
            return item
        raise ValueError('non-json native value')
    return p.hash_json(plain(value))

class ApprovalError(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)

class Manager:
    def __init__(self, boundary, bot_user_id, records, now=None, *, standing_permissions=False):
        if type(standing_permissions) is not bool:
            raise ValueError('standing_permissions must be a boolean')
        self.standing_permissions = standing_permissions
        self.boundary, self.bot_user_id = boundary, bot_user_id
        self.records = copy.deepcopy(records)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.operation_lock = asyncio.Lock()
        self.approval_ready = False
        self.last_proposal_at = None
        for record in self.records.values():
            value = record.get('proposal',{}).get('created_at')
            if isinstance(value,str):
                created = datetime.fromisoformat(value)
                if created.tzinfo is None:
                    raise ValueError('invalid ledger clock')
                if self.last_proposal_at is None or created > self.last_proposal_at:
                    self.last_proposal_at = created

    def authorize(self, user):
        if user is None or (user.id == self.bot_user_id and user.is_admin) or (user.id != self.bot_user_id and not user.is_admin):
            raise ApprovalError('forbidden', 403)

    async def capabilities(self, user):
        self.authorize(user)
        caps = await self._fresh()
        return dict(caps, approval_ready=self.approval_ready,
                    standing_permissions=self.standing_permissions)

    async def propose(self, user, body):
        self.authorize(user)
        if not isinstance(body, dict) or set(body) != {'spec'}:
            raise ApprovalError('invalid_request')
        async with self.operation_lock:
            caps = await self._fresh()
            return await self._submit('automation', body['spec'], caps)

    def _owner(self, target):
        if not isinstance(target, str) or not ID.fullmatch(target):
            raise ApprovalError('not_managed', 404)
        # Prefix/alias are not ownership. Only a completed, authenticated v3
        # create or subsequent verified edit receipt may authorize replacement.
        owners = []
        for key, record in self.records.items():
            doc = record.get('proposal', {})
            owns = (doc.get('kind') == 'automation' and key == target
                    or doc.get('kind') == 'edit' and doc.get('payload', {}).get('target_id') == target)
            if (owns and doc.get('version') == 3 and record.get('status') in ('verified_enabled', 'verified_edit')
                    and record.get('preview') and record.get('approval') and record.get('verified_at')
                    and record.get('managed_state_operation', {}).get('status') not in ('pending', 'uncertain')
                    and isinstance(record.get('config_hash'), str) and HEX.fullmatch(record['config_hash'])):
                owners.append((key, record))
        if len(owners) != 1:
            raise ApprovalError('not_managed', 404)
        return owners[0]

    async def _managed(self, target):
        owner_id, owner = self._owner(target)
        loaded = await self._exact(target, owner['config_hash'])
        if loaded['state'] not in ('on', 'off'):
            raise ApprovalError('runtime_state_unavailable', 409)
        return {'target_id':target, 'owner_record_id':owner_id,
                'config_hash':owner['config_hash'], 'config':copy.deepcopy(loaded['raw_config']),
                'runtime_state':loaded['state'], 'entity_id':loaded['entity_id']}

    async def get_managed(self, user, target):
        self.authorize(user)
        await self._fresh()
        async with self.operation_lock, self.boundary.lock:
            return await self._managed(target)

    async def _enable_check(self, owner, current):
        caps = await self._fresh()
        try:
            doc = p.validate_proposal(copy.deepcopy(owner['proposal']), caps['inventory'],
                                      expected_hash=owner['proposal']['sha256'], now=self.now())
            if not self._standing_safe(doc['kind'], doc['payload'], caps['inventory']):
                raise ApprovalError('approval_required', 409)
            config = (doc['payload']['after'] if doc['kind'] == 'edit' else
                      dict(p.validate_spec(doc['payload'], caps['inventory']), id=doc['id']))
            if p.hash_json(config) != current['config_hash']:
                raise ApprovalError('native_config_changed', 409)
        except (ValueError, TypeError, KeyError):
            raise ApprovalError('invalid_proposal', 409) from None

    async def set_managed_state(self, user, body):
        """Toggle an owned definition, never trigger it; uncertain writes consume authority."""
        self.authorize(user)
        if (not isinstance(body, dict) or set(body) != {'target_id', 'base_config_hash', 'enabled'}
                or type(body['enabled']) is not bool
                or not isinstance(body['base_config_hash'], str) or not HEX.fullmatch(body['base_config_hash'])):
            raise ApprovalError('invalid_request')
        async with self.operation_lock, self.boundary.lock:
            if not self.standing_permissions:
                raise ApprovalError('standing_permissions_required', 403)
            await self._fresh()
            current = await self._managed(body['target_id'])
            if current['config_hash'] != body['base_config_hash']:
                raise ApprovalError('native_config_changed', 409)
            owner = self.records[current['owner_record_id']]
            if body['enabled']:
                await self._enable_check(owner, current)
            desired = 'on' if body['enabled'] else 'off'
            evidence = {'source':'standing_policy', 'policy_id':STANDING_POLICY}
            operation = {'status':'pending', 'target_id':body['target_id'],
                         'config_hash':current['config_hash'], 'runtime_state':desired,
                         'authorization':evidence, 'timestamp':self.now().isoformat()}
            owner['managed_state_operation'] = operation
            try:
                await self.boundary.save(copy.deepcopy(self.records))
                # Fresh identity/config/state gates after persistence and before dispatch.
                await self._fresh()
                if not self.standing_permissions:
                    raise ApprovalError('standing_permissions_required', 403)
                latest = await self._exact(body['target_id'], current['config_hash'])
                if latest['entity_id'] != current['entity_id'] or latest['state'] != current['runtime_state']:
                    raise ApprovalError('runtime_state_changed', 409)
                if body['enabled']:
                    await self._enable_check(owner, current)
                if latest['state'] != desired:
                    if body['enabled']:
                        await self.boundary.enable(current['entity_id'])
                    else:
                        await self.boundary.disable(current['entity_id'])
                loaded = await self._exact(body['target_id'], current['config_hash'])
                if loaded['entity_id'] != current['entity_id'] or loaded['state'] != desired:
                    raise ApprovalError('runtime_state_changed', 409)
                if body['enabled']:
                    await self._enable_check(owner, current)
                receipt = {'receipt_type':'managed_state', 'status':'verified_state',
                           'target_id':body['target_id'], 'owner_record_id':current['owner_record_id'],
                           'entity_id':loaded['entity_id'], 'config_hash':current['config_hash'],
                           'runtime_state':desired, 'verified_at':self.now().isoformat(),
                           'confirmation_required':False, 'authorization':evidence}
                # The original create/edit receipt retains its original state
                # meaning; this separate state-change receipt must not rewrite
                # history (verified_enabled must never describe an off routine).
                owner['managed_state_operation'] = copy.deepcopy(receipt)
                await self.boundary.save(copy.deepcopy(self.records))
                return receipt
            except BaseException as exc:
                owner['managed_state_operation'] = dict(operation, status='uncertain')
                try:
                    await self.boundary.save(copy.deepcopy(self.records))
                except Exception:
                    pass
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise ApprovalError('uncertain_no_retry', 409) from None

    async def list_managed(self, user):
        self.authorize(user)
        await self._fresh()
        async with self.operation_lock, self.boundary.lock:
            targets = set()
            for key, record in self.records.items():
                doc = record.get('proposal', {})
                if doc.get('kind') == 'automation':
                    targets.add(key)
                elif doc.get('kind') == 'edit':
                    targets.add(doc['payload']['target_id'])
            automations, unavailable = [], []
            for target in sorted(targets):
                try:
                    automations.append(await self._managed(target))
                except ApprovalError as exc:
                    unavailable.append({'target_id':target, 'reason':exc.code})
            return {'automations':automations, 'unavailable':unavailable}

    async def propose_edit(self, user, body):
        self.authorize(user)
        if (not isinstance(body, dict) or set(body) != {'target_id','base_config_hash','spec'}
                or not isinstance(body['base_config_hash'], str) or not HEX.fullmatch(body['base_config_hash'])):
            raise ApprovalError('invalid_request')
        async with self.operation_lock:
            caps = await self._fresh()
            async with self.boundary.lock:
                current = await self._managed(body['target_id'])
                if current['config_hash'] != body['base_config_hash']:
                    raise ApprovalError('native_config_changed', 409)
                before = current['config']
                if before.get('initial_state') is not None:
                    raise ApprovalError('unsafe_initial_state', 409)
                try:
                    # Native annotated YAML -> plain canonical JSON for the
                    # immutable proposal, never normalize untrusted input.
                    import json
                    before = json.loads(json.dumps(before, allow_nan=False))
                    after = dict(before, **p.validate_spec(copy.deepcopy(body['spec']), caps['inventory']))
                except (ValueError, TypeError, KeyError):
                    raise ApprovalError('invalid_proposal') from None
                payload = {'target_id':body['target_id'],
                    'base_config_hash':body['base_config_hash'], 'before':before,
                    'after':after, 'spec':body['spec'], 'runtime_state':current['runtime_state']}
            # Execution reacquires the native lock and rechecks ownership/base/state.
            return await self._submit('edit', payload, caps)

    async def _edit(self, record, doc, expected_hash):
        payload = doc['payload']
        target = payload['target_id']
        config = copy.deepcopy(payload['after'])
        async with self.boundary.lock:
            await self.boundary.validate(copy.deepcopy(config))
            current = await self._managed(target)
            if (current['config_hash'] != payload['base_config_hash']
                    or current['runtime_state'] != payload['runtime_state']):
                raise ApprovalError('native_config_changed', 409)
            previous_id = current['owner_record_id']
            rows = await self.boundary.read()
            self._rows(rows)
            matches = [i for i, row in enumerate(rows) if row.get('id') == target]
            if len(matches) != 1 or native_hash(rows[matches[0]]) != payload['base_config_hash']:
                raise ApprovalError('native_config_changed', 409)
            await self._check(doc, expected_hash)
            # HA preserves the existing entity's state through targeted reload
            # when initial_state is absent/None. Explicit policies are rejected.
            # Persist an explicit off state before removal; never turn on edits.
            latest = await self._exact(target, payload['base_config_hash'])
            if latest['state'] != payload['runtime_state'] or latest['entity_id'] != current['entity_id']:
                raise ApprovalError('runtime_state_changed', 409)
            if payload['runtime_state'] == 'off':
                await self.boundary.disable(current['entity_id'])
            replacement = copy.deepcopy(rows)
            replacement[matches[0]] = config
            record['config_hash'] = p.hash_json(config)
            await self._check(doc, expected_hash)
            await self.boundary.write(replacement)
            if native_hash(await self.boundary.read()) != native_hash(replacement):
                raise ApprovalError('native_config_changed', 409)
            await self.boundary.reload_edit(target)
            await self._check(doc, expected_hash)
            loaded = await self._exact(target, record['config_hash'])
            if loaded['entity_id'] != current['entity_id']:
                raise ApprovalError('runtime_state_changed', 409)
            state_mismatch = loaded['state'] != payload['runtime_state']
            if payload['runtime_state'] == 'off':
                await self.boundary.disable(loaded['entity_id'])
                loaded = await self._exact(target, record['config_hash'])
                if loaded['state'] != 'off':
                    raise ApprovalError('runtime_state_changed', 409)
            if state_mismatch:
                # Fail safe for an unexpected activation, but never turn a
                # currently-off routine on or claim normal restoration worked.
                raise ApprovalError('runtime_state_changed', 409)
        record.update(status='verified_edit', verified_at=self.now().isoformat(), target_id=target,
                      preserved_state=payload['runtime_state'], previous_record_id=previous_id)
        self.records[previous_id].update(status='superseded', superseded_by=doc['id'])
        await self.boundary.save(copy.deepcopy(self.records))
        return {'id':doc['id'], 'target_id':target, 'status':'verified_edit',
                'entity_id':loaded['entity_id'], 'runtime_state':loaded['state'],
                'config_hash':record['config_hash'], 'verified_at':record['verified_at']}

    async def action(self, user, body):
        self.authorize(user)
        if not isinstance(body, dict) or set(body) != {'action'}:
            raise ApprovalError('invalid_request')
        async with self.operation_lock:
            caps = await self._fresh()
            try:
                checked = p.validate_action(copy.deepcopy(body['action']), caps['inventory'])
            except (ValueError, TypeError, KeyError):
                raise ApprovalError('invalid_action') from None
            if checked['confirmation_required']:
                return await self._queue('action', checked['action'], caps)
            if len(self.records) >= 1000:
                raise ApprovalError('ledger_full',429)
            doc = p.make_proposal('action',checked['action'],caps['inventory'],now=self.now())
            record = {'status':'pending','proposal':doc}
            self.records[doc['id']] = record
            try:
                await self.boundary.save(copy.deepcopy(self.records))
                await self._check(doc,doc['sha256'], require_direct=True)
                record['device_dispatch_attempted'] = True
                await self.boundary.execute(checked['action'])
                record['status'] = 'executed'
                record['verified_at'] = self.now().isoformat()
                await self.boundary.save(copy.deepcopy(self.records))
            except BaseException as exc:
                record['status'] = 'uncertain'
                # Pending persisted records omit dispatch evidence: a crash at
                # the service boundary is unknown, not proof of non-dispatch.
                record.setdefault('device_dispatch_attempted', False)
                try:
                    await self.boundary.save(copy.deepcopy(self.records))
                except Exception:
                    pass
                if isinstance(exc,asyncio.CancelledError):
                    raise
                raise ApprovalError('uncertain_no_retry', 409) from None
            return {'id':doc['id'],'status':'executed', 'device_state_verified':False, 'confirmation_required':False}

    async def status(self, user, identifier):
        self.authorize(user)
        if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier not in self.records:
            raise ApprovalError('not_found', 404)
        record = copy.deepcopy(self.records[identifier])
        result = {'id':identifier, 'status':record['status'], 'recorded_status':record['status'], 'proposal':record['proposal'], 'verified_at':record.get('verified_at'), 'observed_at':self.now().isoformat(), 'evidence':{'preview':record.get('preview'), 'approval':record.get('approval'), 'config_hash':record.get('config_hash')}}
        result['evidence']['managed_state_operation'] = record.get('managed_state_operation')
        if record.get('managed_state_operation', {}).get('status') in ('pending', 'uncertain'):
            result.update(status='uncertain', runtime_state=None)
            return result
        if record['status'] == 'superseded':
            result['superseded_by'] = record.get('superseded_by')
        if record['status'] in ('verified_enabled', 'verified_edit'):
            try:
                await self._fresh()
                target = record['proposal']['payload']['target_id'] if record['status'] == 'verified_edit' else identifier
                result['target_id'] = target
                async with self.boundary.lock:
                    loaded = await self._exact(target, record['config_hash'])
                result['runtime_state'] = loaded['state']
                result['entity_id'] = loaded['entity_id']
                expected_state = record.get('preserved_state', 'on')
                result['status'] = record['status'] if loaded['state'] == expected_state else 'changed'
            except Exception:
                result['status'] = 'uncertain'
                result['runtime_state'] = None
        return result

    def _standing_safe(self, kind, payload, inventory):
        return self.standing_permissions and p.standing_safe(kind, copy.deepcopy(payload), inventory)

    async def _submit(self, kind, payload, caps):
        """Only a new request may use standing authority; never drain old records."""
        try:
            standing = self._standing_safe(kind, payload, caps['inventory'])
        except (ValueError, TypeError, KeyError):
            raise ApprovalError('invalid_proposal') from None
        queued = await self._queue(kind, payload, caps, standing=standing)
        if not standing:
            return queued
        try:
            result = await self._approve_locked(queued['id'], queued['sha256'])
        except BaseException:
            # Even rejection at the initial fresh gate consumes this standing
            # attempt; never leave an interrupted policy receipt retryable.
            self.records[queued['id']]['status'] = 'uncertain'
            try:
                await self.boundary.save(copy.deepcopy(self.records))
            except Exception:
                pass
            raise
        return dict(result, confirmation_required=False,
                    authorization={'source':'standing_policy', 'policy_id':STANDING_POLICY})

    async def _queue(self, kind, payload, caps, *, standing=False):
        if not standing and not self.approval_ready:
            raise ApprovalError('approval_not_ready', 503)
        # Tombstones are never evicted; a full ledger requires operator review.
        if len(self.records) >= 1000:
            raise ApprovalError('ledger_full', 429)
        if self.last_proposal_at is not None and (self.now() - self.last_proposal_at).total_seconds() < 60:
            raise ApprovalError('proposal_rate_limit', 429)
        try:
            doc = p.make_proposal(kind, copy.deepcopy(payload), caps['inventory'], now=self.now())
        except (ValueError, TypeError, KeyError):
            raise ApprovalError('invalid_proposal') from None
        if doc['id'] in self.records:
            raise ApprovalError('operation_exists_no_retry', 409)
        self.records[doc['id']] = {'status':'queued', 'proposal':copy.deepcopy(doc)}
        if standing:
            evidence = {'source':'standing_policy', 'policy_id':STANDING_POLICY,
                        'sha256':doc['sha256'], 'timestamp':self.now().isoformat()}
            # No human message/identity is fabricated. Persisted interrupted
            # records become tombstones under the existing runtime validator.
            self.records[doc['id']].update(status='awaiting_approval',
                preview=copy.deepcopy(evidence), approval=copy.deepcopy(evidence))
        self.last_proposal_at = self.now()
        try:
            await self.boundary.save(copy.deepcopy(self.records))
        except BaseException:
            self.records[doc['id']]['status'] = 'uncertain'
            raise ApprovalError('uncertain', 409) from None
        return {'id':doc['id'], 'status':'queued', 'sha256':doc['sha256'], 'confirmation_required':True}

    async def _fresh(self):
        caps = await self.boundary.capabilities()
        if caps.get('time_zone') != TIME_ZONE or caps.get('ha_version') != HA_VERSION:
            raise ApprovalError('runtime_not_ready', 503)
        return caps

    async def _check(self, doc, expected_hash, *, require_direct=False):
        if not isinstance(expected_hash, str) or not HEX.fullmatch(expected_hash):
            raise ApprovalError('invalid_hash')
        caps = await self._fresh()
        try:
            validated = p.validate_proposal(copy.deepcopy(doc), caps['inventory'], expected_hash=expected_hash, now=self.now())
            approval = self.records.get(doc['id'], {}).get('approval', {})
            if approval.get('source') == 'standing_policy':
                if (approval.get('policy_id') != STANDING_POLICY or approval.get('sha256') != expected_hash
                        or not self._standing_safe(validated['kind'], validated['payload'], caps['inventory'])):
                    raise ApprovalError('approval_required_no_dispatch', 409)
            if require_direct and p.validate_action(validated['payload'], caps['inventory'])['confirmation_required']:
                raise ApprovalError('approval_required_no_dispatch', 409)
            return validated
        except (ValueError, TypeError, KeyError):
            raise ApprovalError('invalid_proposal', 409) from None

    @staticmethod
    def _rows(rows):
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ApprovalError('invalid_native_config', 409)

    async def approve(self, identifier, expected_hash, *, chat_evidence=None):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ApprovalError('invalid_identifier')
        async with self.operation_lock:
            return await self._approve_locked(identifier, expected_hash, chat_evidence=chat_evidence)

    async def _approve_locked(self, identifier, expected_hash, *, chat_evidence=None):
        """Shared execution path; caller must hold operation_lock."""
        assert self.operation_lock.locked()
        record = self.records.get(identifier)
        if not record or record['status'] != 'awaiting_approval' or not record.get('preview'):
            raise ApprovalError('operation_exists_no_retry', 409)
        if chat_evidence is not None and (record.get('approval') or record['proposal'].get('kind') not in ('automation', 'edit')):
            raise ApprovalError('operation_exists_no_retry', 409)
        if chat_evidence is not None:
            preview = record.get('chat_preview', {})
            if (not preview or preview.get('interaction_id') != chat_evidence.get('interaction_id')
                    or preview.get('author_id') != chat_evidence.get('author_id')
                    or preview.get('sha256') != expected_hash):
                raise ApprovalError('chat_preview_mismatch', 409)
            try:
                started = datetime.fromisoformat(preview['timestamp'])
                expires = datetime.fromisoformat(preview['expires_at'])
                valid = (started.tzinfo is not None and expires.tzinfo is not None
                         and (expires-started).total_seconds() == CHAT_INTERACTION_SECONDS
                         and started <= self.now() < expires)
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                raise ApprovalError('chat_preview_expired', 409)
        doc = await self._check(record['proposal'], expected_hash)
        try:
            if chat_evidence is not None:
                record['approval'] = dict(copy.deepcopy(chat_evidence), sha256=expected_hash,
                                          timestamp=self.now().isoformat())
            record['status'] = 'pending'
            await self.boundary.save(copy.deepcopy(self.records))
            if doc['kind'] == 'action':
                await self._check(doc, expected_hash)
                await self.boundary.execute(copy.deepcopy(doc['payload']))
                record['status'] = 'executed'
                record['verified_at'] = self.now().isoformat()
                await self.boundary.save(copy.deepcopy(self.records))
                return {'id':identifier, 'status':'executed', 'device_state_verified':False}
            if doc['kind'] == 'edit':
                return await self._edit(record, doc, expected_hash)
            caps = await self._fresh()
            config = dict(p.validate_spec(copy.deepcopy(doc['payload']), caps['inventory']), id=identifier)
            record['config_hash'] = p.hash_json(config)
            async with self.boundary.lock:
                await self.boundary.validate(copy.deepcopy(config))
                rows = await self.boundary.read()
                self._rows(rows)
                if any(row.get('id') == identifier for row in rows):
                    raise ApprovalError('already_exists', 409)
                # Last authorization gate before persistence: fresh policy,
                # expiry, bindings and timezone under the native lock. Reload
                # can activate this definition before explicit turn_on.
                await self._check(doc, expected_hash)
                await self.boundary.write(rows + [config])
                if native_hash(await self.boundary.read()) != native_hash(rows + [config]):
                    raise ApprovalError('uncertain', 409)
                # Pinned reload does not reacquire the native config lock.
                # Keep UI writers out from persistence through activation and
                # exact readback; detecting drift only after reload is too late.
                await self.boundary.reload(identifier)
                await self._check(doc, expected_hash)
                loaded = await self._exact(identifier, record['config_hash'])
                await self._check(doc, expected_hash)
                await self.boundary.enable(loaded['entity_id'])
                loaded = await self._exact(identifier, record['config_hash'])
                if loaded['state'] != 'on':
                    raise ApprovalError('uncertain', 409)
            record['status'] = 'verified_enabled'
            record['verified_at'] = self.now().isoformat()
            await self.boundary.save(copy.deepcopy(self.records))
            return {'id':identifier, 'status':'verified_enabled', 'entity_id':loaded['entity_id'], 'config_hash':record['config_hash'], 'verified_at':record['verified_at']}
        except BaseException as exc:
            record['status'] = 'uncertain'
            try:
                await self.boundary.save(copy.deepcopy(self.records))
            except Exception:
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ApprovalError('uncertain', 409) from None

    async def _exact(self, identifier, config_hash):
        rows = await self.boundary.read()
        self._rows(rows)
        matches = [row for row in rows if row.get('id') == identifier]
        loaded = await self.boundary.loaded(identifier)
        if len(matches) != 1 or native_hash(matches[0]) != config_hash or not loaded or loaded['raw_config'].get('id') != identifier or native_hash(loaded['raw_config']) != config_hash:
            raise ApprovalError('native_config_changed', 409)
        return loaded
