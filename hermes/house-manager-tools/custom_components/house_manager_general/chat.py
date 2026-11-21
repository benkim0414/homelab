"""Opt-in human-chat adapter, isolated from the model's HA bot identity.

The credential belongs to a separate non-admin HA user, configured explicitly by
an operator. Surface/session labels are audit metadata, NOT authentication. Only
an installed trusted command handler may hold this credential. Do not expose it
through MCP, file/shell tools, model context, or the ordinary HA bot environment.
"""
import copy
import re
import uuid
from datetime import timedelta
from .engine import ApprovalError, ID, HEX, CHAT_INTERACTION_SECONDS


class ChatApprovals:
    def __init__(self, manager, user_id):
        self.manager, self.user_id = manager, user_id

    def authorize(self, user):
        if (not self.user_id or user is None or user.id != self.user_id
                or user.id == self.manager.bot_user_id or user.is_admin
                or not user.is_active):
            raise ApprovalError('forbidden', 403)

    async def get(self, user, identifier):
        self.authorize(user)
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ApprovalError('invalid_identifier')
        async with self.manager.operation_lock:
            record = self.manager.records.get(identifier)
            if (not record or record['status'] != 'awaiting_approval'
                    or not record.get('preview') or record.get('approval')
                    or record['proposal'].get('kind') not in ('automation', 'edit')):
                raise ApprovalError('not_approvable', 409)
            doc = await self.manager._check(record['proposal'], record['proposal']['sha256'])
            # The full trusted preview issues a fresh interaction. Another fetch
            # invalidates the older prompt; this never rewrites the proposal hash.
            started = self.manager.now()
            preview = {'interaction_id': uuid.uuid4().hex, 'sha256': doc['sha256'],
                       'author_id': user.id, 'timestamp': started.isoformat(),
                       'expires_at': (started+timedelta(seconds=CHAT_INTERACTION_SECONDS)).isoformat()}
            record['chat_preview'] = preview
            try:
                await self.manager.boundary.save(copy.deepcopy(self.manager.records))
            except BaseException:
                record.pop('chat_preview', None)
                raise ApprovalError('preview_unavailable', 503) from None
            return {'status': 'awaiting_approval', 'proposal': copy.deepcopy(doc),
                    'interaction_id': preview['interaction_id']}

    async def approve(self, user, identifier, body):
        self.authorize(user)
        if (not isinstance(body, dict) or set(body) != {'sha256', 'surface', 'session_id', 'interaction_id'}
                or not isinstance(body['sha256'], str) or not HEX.fullmatch(body['sha256'])
                or body['surface'] != 'local_chat'
                or not isinstance(body['session_id'], str)
                or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', body['session_id'])
                or not isinstance(body['interaction_id'], str)
                or not re.fullmatch(r'[0-9a-f]{32}', body['interaction_id'])):
            raise ApprovalError('invalid_request')
        # Manager checks kind/status/hash/freshness and persists approval+pending
        # together while holding the same operation lock used by Discord. A race
        # has exactly one winner. Never retry an uncertain write.
        return await self.manager.approve(identifier, body['sha256'], chat_evidence={
            'transport': 'hermes_command', 'author_id': user.id,
            'surface': body['surface'], 'session_id': body['session_id'],
            'interaction_id': body['interaction_id'],
        })
