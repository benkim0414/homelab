"""Independent Discord REST human approval. No gateway, model token or HA HTTP approve route."""
import asyncio
import copy
import json
import re
from datetime import datetime, timedelta
from .engine import ApprovalError

def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False, allow_nan=False).encode('utf-8')

def _date(value):
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result

def _within_lifetime(doc, when):
    """No-expiry must be explicit and limited to automation mutations."""
    try:
        created = _date(doc['created_at'])
        if doc['expires_at'] is None:
            return doc['kind'] in ('automation', 'edit') and created <= when
        expires = _date(doc['expires_at'])
        return expires - created == timedelta(seconds=900) and created <= when < expires
    except (TypeError, ValueError, KeyError, AttributeError):
        return False

def approval_matches(message, doc, preview, settings):
    try:
        author = message['author']
        reference = message['message_reference']
        if not _within_lifetime(doc, _date(message['timestamp'])):
            return False
        return bool(message.get('type') == 19 and author['id'] == settings['discord_user_id'] and author.get('bot',False) is False and author.get('system',False) is False and 'webhook_id' not in message and message.get('edited_timestamp') is None and message['channel_id'] == settings['discord_channel_id'] and reference.get('channel_id') == settings['discord_channel_id'] and reference['message_id'] == preview['message_id'] and int(message['id']) > int(preview['message_id']) and _date(message['timestamp']) > _date(preview['timestamp']) and message['content'] == f"APPROVE {doc['id']} {doc['sha256']}")
    except (TypeError, ValueError, KeyError, AttributeError):
        return False

def preview_text(doc):
    # Exact unabridged proposal is always attached, including every trigger,
    # condition and action. The short summary never substitutes for that payload.
    if doc['kind'] == 'edit':
        from .policy import hash_json
        payload = doc['payload']
        intro = (f"APPROVAL: EDIT existing persistent routine {payload['target_id']}. "
                 f"Preserve runtime {payload['runtime_state']}; no force trigger. "
                 f"Before SHA256: {payload['base_config_hash']}\n"
                 f"After SHA256: {hash_json(payload['after'])}\n"
                 "Exact BEFORE and AFTER content is in the attachment. All future triggers/actions change as shown; appliance/climate actions may have HIGH CONSEQUENCE.")
    elif doc['kind'] == 'automation':
        intro = 'APPROVAL: Create AND ENABLE a persistent routine. Daily time/state triggers, conditions and ALL actions are in the attached exact JSON. HIGH CONSEQUENCE: appliance/climate actions, if listed, will run automatically on those triggers.'
    else:
        intro = 'APPROVAL: Execute the exact device action in the attached JSON once. HIGH CONSEQUENCE: this may activate an appliance or climate control.'
    summary = json.dumps(doc['payload'],sort_keys=True,ensure_ascii=False,allow_nan=False)
    if len(summary) > 1000:
        summary = summary[:1000]+' [abbreviated; read FULL attachment]'
    # Disable mentions at transport; an attachment remains authoritative even
    # when this optional human-readable summary exceeds the Discord text limit.
    lifetime = 'No expiry; current state/config/bindings must still match.' if doc['expires_at'] is None and doc['kind'] in ('automation', 'edit') else f"Expires: {doc['expires_at']}"
    return (f"{intro}\nPayload summary: {summary}\nRead the entire attached proposal before approving. {lifetime}\nSHA256: {doc['sha256']}\nThe next message contains only your approval line. Copy that entire message, then reply to THIS preview with the copied text.")

class DiscordREST:
    """Fixed-origin, bounded aiohttp adapter. Only GETs can be retried."""
    ORIGIN = 'https://discord.com/api/v10'
    def __init__(self, token, session=None, sleep=asyncio.sleep):
        self._token, self._session, self._sleep = token, session, sleep

    @staticmethod
    def _id(value):
        if not isinstance(value,str) or re.fullmatch('[0-9]{1,25}',value) is None:
            raise ApprovalError('invalid_discord_id')
        return value

    async def _request(self, method, path, **kwargs):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=20))
        attempts = 3 if method == 'GET' else 1
        for attempt in range(attempts):
            try:
                async with asyncio.timeout(25):
                    async with self._session.request(method, self.ORIGIN+path, headers={'Authorization':'Bot '+self._token}, allow_redirects=False, proxy=None, **kwargs) as response:
                        body = bytearray()
                        async for chunk in response.content.iter_chunked(8192):
                            body.extend(chunk)
                            if len(body) > 1048576:
                                raise ApprovalError('discord_unavailable',503)
                        if response.status == 429:
                            try:
                                delay = float(response.headers.get('Retry-After','1'))
                                if not 0 <= delay <= 30:
                                    delay = 30
                            except (TypeError,ValueError):
                                delay = 5
                            # A POST is NEVER repeated, even after rate limiting.
                            await self._sleep(max(0.1, min(30,delay)))
                            if method == 'GET' and attempt+1 < attempts:
                                continue
                            raise ApprovalError('discord_rate_limited',503)
                        if response.status != 200:
                            raise ApprovalError('discord_unavailable',503)
                        return json.loads(body)
            except asyncio.CancelledError:
                raise
            except ApprovalError:
                raise
            except Exception:
                if method == 'GET' and attempt+1 < attempts:
                    await self._sleep(min(2**attempt, 5))
                    continue
                raise ApprovalError('discord_unavailable',503) from None
        raise ApprovalError('discord_unavailable',503)

    async def me(self):
        return await self._request('GET','/users/@me')

    async def channel(self, channel):
        return await self._request('GET','/channels/'+self._id(channel))

    async def messages(self, channel, after, *, before=None):
        # Walk newest-to-oldest explicitly; a fixed `after` window can strand
        # a valid reply beyond its first 100 messages. Worker applies the floor.
        self._id(after)
        query='limit=100' if before is None else f'before={self._id(before)}&limit=100'
        return await self._request('GET',f'/channels/{self._id(channel)}/messages?{query}')

    async def get_message(self, channel, identifier):
        return await self._request('GET',f'/channels/{self._id(channel)}/messages/{self._id(identifier)}')

    async def send_preview(self, channel, content, filename, attachment):
        import aiohttp
        form = aiohttp.FormData()
        payload = {'content':content, 'allowed_mentions':{'parse':[]}, 'attachments':[{'id':0,'filename':filename}]}
        form.add_field('payload_json',json.dumps(payload),content_type='application/json')
        form.add_field('files[0]',attachment,filename=filename,content_type='application/json')
        return await self._request('POST',f'/channels/{self._id(channel)}/messages',data=form)

    async def send_approval(self, channel, content, preview_id):
        # One whole-message-copyable line, linked back to the authoritative preview.
        payload = {'content':content, 'allowed_mentions':{'parse':[], 'replied_user':False},
                   'message_reference':{'message_id':self._id(preview_id),
                                        'channel_id':self._id(channel),
                                        'fail_if_not_exists':True}}
        return await self._request('POST',f'/channels/{self._id(channel)}/messages',json=payload)

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._token = ''

class ApprovalWorker:
    def __init__(self, manager, rest, settings):
        self.manager, self.rest = manager, rest
        self.settings = {k:settings[k] for k in ['discord_user_id','discord_channel_id']}
        self.bot_id = None
        self.task = None
        self.stopping = False
        # Volatile read cursors only: restart rescans safely without changing
        # the persisted proposal/approval. Process at most one page per poll.
        self._poll_scans = {}

    async def initialize(self):
        self.manager.approval_ready = False
        me = await self.rest.me()
        channel = await self.rest.channel(self.settings['discord_channel_id'])
        recipients = channel.get('recipients',[])
        if me.get('bot') is not True or not isinstance(me.get('id'),str) or not me['id'].isdigit() or me['id'] == self.settings['discord_user_id'] or channel.get('id') != self.settings['discord_channel_id'] or channel.get('type') != 1 or len(recipients) != 1 or recipients[0].get('id') != self.settings['discord_user_id'] or recipients[0].get('bot',False) is not False:
            raise ApprovalError('discord_not_ready',503)
        self.bot_id = me['id']
        self.manager.approval_ready = True

    async def poll(self, identifier):
        record = self.manager.records[identifier]
        if record['status'] != 'awaiting_approval':
            self._poll_scans.pop(identifier, None)
            return
        if not _within_lifetime(record['proposal'], self.manager.now()):
            async with self.manager.operation_lock:
                # A chat approval may have won while this poll awaited the lock.
                # Never replace a completed/consumed record with an expiry.
                if record['status'] == 'awaiting_approval' and not record.get('approval'):
                    record['status'] = 'expired'
                    await self.manager.boundary.save(copy.deepcopy(self.manager.records))
            return
        floor,before,newest=self._poll_scans.get(identifier,(record['preview']['message_id'],None,record['preview']['message_id']))
        kwargs={} if before is None else {'before':before}
        messages = await self.rest.messages(self.settings['discord_channel_id'], floor, **kwargs)
        if (not isinstance(messages,list) or len(messages)>100
                or any(not isinstance(message,dict) or not isinstance(message.get('id'),str)
                       or re.fullmatch('[0-9]{1,25}',message['id']) is None for message in messages)):
            raise ApprovalError('discord_not_ready',503)
        ids=[int(message['id']) for message in messages]
        if len(set(ids))!=len(ids) or (before is not None and any(value>=int(before) for value in ids)):
            raise ApprovalError('discord_not_ready',503)
        for message in messages:
            if int(message['id'])<=int(floor):
                continue
            if not approval_matches(message, record['proposal'], record['preview'], self.settings):
                continue
            # Re-fetch the exact message before consuming; edits/webhooks/bot
            # identity are checked again against independently authenticated REST.
            fresh = await self.rest.get_message(self.settings['discord_channel_id'], message['id'])
            if fresh.get('id') != message['id'] or not approval_matches(fresh,record['proposal'],record['preview'],self.settings):
                continue
            async with self.manager.operation_lock:
                if record['status'] != 'awaiting_approval' or record.get('approval'):
                    return
                record['approval'] = {'message_id':fresh['id'], 'author_id':fresh['author']['id'], 'channel_id':fresh['channel_id'], 'reply_message_id':record['preview']['message_id'], 'sha256':record['proposal']['sha256'], 'timestamp':fresh['timestamp']}
                try:
                    await self.manager.boundary.save(copy.deepcopy(self.manager.records))
                except BaseException:
                    record['status'] = 'uncertain'
                    raise ApprovalError('uncertain',409) from None
            try:
                await self.manager.approve(identifier, record['proposal']['sha256'])
            except BaseException:
                # A consumed but invalidated reply is not another invitation to
                # approve/retry; retain its evidence and a terminal tombstone.
                async with self.manager.operation_lock:
                    if record['status'] == 'awaiting_approval':
                        record['status'] = 'uncertain'
                        try:
                            await self.manager.boundary.save(copy.deepcopy(self.manager.records))
                        except Exception:
                            pass
                raise
            return

        # Advance only after a full page without I/O failure. Complete a finite
        # sweep before sampling new arrivals, so a busy DM cannot starve it.
        high=str(max([int(newest),*ids]))
        if len(messages)<100 or min(ids)<=int(floor):
            self._poll_scans[identifier]=(high,None,high)
        else:
            self._poll_scans[identifier]=(floor,str(min(ids)),high)

    async def run(self):
        try:
            await self.initialize()
            while not self.stopping:
                for identifier, record in list(self.manager.records.items()):
                    if self.stopping:
                        break
                    try:
                        if record['status'] == 'queued':
                            await self.publish(identifier)
                        if record['status'] == 'awaiting_approval':
                            await self.poll(identifier)
                    except ApprovalError:
                        pass
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Fail closed and never print exceptions that might contain tokens.
            pass
        finally:
            self.manager.approval_ready = False
            await self.rest.close()

    async def stop(self):
        self.stopping = True
        self.manager.approval_ready = False
        if self.task is not None and self.task is not asyncio.current_task():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        else:
            await self.rest.close()

    async def publish(self, identifier):
        async with self.manager.operation_lock:
            record = self.manager.records[identifier]
            if record['status'] != 'queued':
                return
            doc = record['proposal']
            if not _within_lifetime(doc, self.manager.now()):
                record['status'] = 'expired'
                await self.manager.boundary.save(copy.deepcopy(self.manager.records))
                return
            record['status'] = 'preview_pending'
            await self.manager.boundary.save(copy.deepcopy(self.manager.records))
            try:
                attachment = canonical_json(doc)
                filename = doc['id']+'.json'
                content = preview_text(doc)
                response = await self.rest.send_preview(self.settings['discord_channel_id'], content, filename, attachment)
                identifier_sent = response['id']
                if not isinstance(identifier_sent,str) or not identifier_sent.isdigit():
                    raise ValueError('invalid response')
                final = await self.rest.get_message(self.settings['discord_channel_id'], identifier_sent)
                attachments = final.get('attachments',[])
                if final.get('id') != identifier_sent or final.get('channel_id') != self.settings['discord_channel_id'] or final.get('author',{}).get('id') != self.bot_id or final.get('author',{}).get('bot') is not True or final.get('content') != content or len(attachments) != 1 or attachments[0].get('filename') != filename or attachments[0].get('size') != len(attachment):
                    raise ValueError('preview mismatch')
                _date(final['timestamp'])
                approval_line = f"APPROVE {doc['id']} {doc['sha256']}"
                copied = await self.rest.send_approval(self.settings['discord_channel_id'], approval_line, identifier_sent)
                copy_id = copied['id']
                if not isinstance(copy_id,str) or not copy_id.isdigit() or int(copy_id) <= int(identifier_sent):
                    raise ValueError('invalid copy-message response')
                confirmed = await self.rest.get_message(self.settings['discord_channel_id'], copy_id)
                reference = confirmed.get('message_reference',{})
                if (confirmed.get('id') != copy_id or confirmed.get('channel_id') != self.settings['discord_channel_id']
                    or confirmed.get('author',{}).get('id') != self.bot_id
                    or confirmed.get('author',{}).get('bot') is not True
                    or confirmed.get('content') != approval_line or confirmed.get('attachments') != []
                    or reference.get('message_id') != identifier_sent
                    or reference.get('channel_id') != self.settings['discord_channel_id']
                    or _date(confirmed['timestamp']) < _date(final['timestamp'])):
                    raise ValueError('copy-message mismatch')
                # Keep approval bound to the original exact preview; the second
                # bot-authored message is only a copy aid, never human approval.
                record['preview'] = {'message_id':identifier_sent, 'timestamp':final['timestamp'],
                                     'copy_message_id':copy_id, 'copy_timestamp':confirmed['timestamp'],
                                     'attachment_sha256':__import__('hashlib').sha256(attachment).hexdigest()}
                record['status'] = 'awaiting_approval'
                await self.manager.boundary.save(copy.deepcopy(self.manager.records))
            except BaseException as exc:
                record['status'] = 'uncertain'
                try:
                    await self.manager.boundary.save(copy.deepcopy(self.manager.records))
                except Exception:
                    pass
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise ApprovalError('preview_uncertain_no_retry',409) from None
