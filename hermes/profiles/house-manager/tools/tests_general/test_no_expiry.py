"""No-expiry is explicit and scoped to new automation mutations only."""
import copy
import unittest
from datetime import datetime, timezone, timedelta
from custom_components.house_manager_general import policy as p
from tests_general.test_policy import inventory, action
from tests_general import test_edit_general as edits
SPEC = edits.SPEC

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=3650)


def rehash(doc):
    doc['sha256'] = p.hash_json({k: v for k, v in doc.items() if k != 'sha256'})
    return doc


class LifetimeTests(unittest.TestCase):
    def test_new_automation_is_explicit_no_expiry_and_valid_after_years(self):
        doc = p.make_proposal('automation', SPEC, inventory(), now=NOW)
        self.assertIn('expires_at', doc)
        self.assertIsNone(doc['expires_at'])
        self.assertEqual(p.validate_proposal(doc, inventory(), doc['sha256'], now=LATER), doc)
        with self.assertRaises(p.PolicyError):
            p.validate_proposal(doc, inventory(), now=NOW-timedelta(seconds=1))
        drift = inventory(); drift['light.test']['registry_fingerprint'] = 'b'*64
        with self.assertRaises(p.PolicyError):
            p.validate_proposal(doc, drift, now=LATER)
        with self.assertRaises(p.PolicyError):
            p.validate_proposal(doc, inventory(), 'b'*64, now=LATER)
        legacy = rehash(dict(doc, expires_at=(NOW+timedelta(seconds=900)).isoformat()))
        self.assertEqual(p.validate_proposal(legacy, inventory(), now=NOW), legacy)
        with self.assertRaises(p.PolicyError):
            p.validate_proposal(legacy, inventory(), now=LATER)
        for changes in ({'expires_at': (NOW+timedelta(days=1)).isoformat()}, {'expires_at': False}):
            with self.assertRaises(p.PolicyError):
                p.validate_proposal(rehash(dict(doc, **changes)), inventory(), now=NOW)
        missing = copy.deepcopy(doc); del missing['expires_at']; rehash(missing)
        with self.assertRaises(p.PolicyError):
            p.validate_proposal(missing, inventory(), now=NOW)

    def test_actions_still_expire_at_exactly_900_seconds_and_cannot_be_null(self):
        doc = p.make_proposal('action', action(), inventory(), now=NOW)
        self.assertEqual(datetime.fromisoformat(doc['expires_at'])-NOW, timedelta(seconds=900))
        p.validate_proposal(doc, inventory(), now=NOW+timedelta(seconds=899))
        for moment in (NOW+timedelta(seconds=900), LATER):
            with self.assertRaises(p.PolicyError): p.validate_proposal(doc, inventory(), now=moment)
        with self.assertRaises(p.PolicyError):
            p.validate_proposal(rehash(dict(doc, expires_at=None)), inventory(), now=NOW)


class MutationLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_after_years_preserves_freshness_and_single_consumption(self):
        fixture = edits.EditTests()
        for drift in (None, 'config', 'runtime', 'binding', 'legacy', 'expired'):
            with self.subTest(drift=drift):
                b, m, target = fixture.setup_manager()
                q = await fixture.queue_edit(m, target)
                doc = m.records[q['id']]['proposal']
                self.assertIsNone(doc['expires_at'])
                m.now = lambda: LATER
                if drift == 'config': b.rows[-1]['alias'] = 'manual'
                if drift == 'runtime': b.runtime_state = 'on'
                if drift == 'binding': b.inv['light.test']['registry_fingerprint'] = 'b'*64
                if drift == 'legacy':
                    doc['expires_at'] = (NOW+timedelta(seconds=900)).isoformat(); rehash(doc)
                if drift == 'expired':
                    from custom_components.house_manager_general.runtime import validate_records
                    m.records[q['id']]['status'] = 'expired'
                    m = edits.Manager(b, edits.BOT.id, validate_records(m.records), now=lambda:LATER)
                if drift:
                    before = copy.deepcopy(b.rows)
                    with self.assertRaises(edits.ApprovalError): await m.approve(q['id'], doc['sha256'])
                    self.assertEqual(b.rows, before)
                    self.assertNotIn('write', b.events)
                else:
                    self.assertEqual((await m.approve(q['id'], q['sha256']))['status'], 'verified_edit')
                    with self.assertRaises(edits.ApprovalError): await m.approve(q['id'], q['sha256'])

    async def test_create_after_years_is_single_use(self):
        from tests_general.test_manager_native import Boundary, BOT
        b = Boundary(); b.inv = inventory()
        m = edits.Manager(b, BOT.id, {}, now=lambda: NOW); m.approval_ready = True
        q = await m.propose(BOT, {'spec': SPEC})
        m.records[q['id']].update(status='awaiting_approval', preview={'message_id':'1'}, approval={'message_id':'2'})
        m.now = lambda: LATER
        self.assertEqual((await m.approve(q['id'], q['sha256']))['status'], 'verified_enabled')
        with self.assertRaises(edits.ApprovalError): await m.approve(q['id'], q['sha256'])


class DiscordLifetimeTests(unittest.IsolatedAsyncioTestCase):
    def test_message_lifetime_is_scoped_and_legacy_expiry_remains(self):
        from custom_components.house_manager_general.discord import approval_matches, preview_text
        from tests_general.test_worker_general import DOC, PREVIEW, SETTINGS, message
        msg = message(); msg['timestamp'] = LATER.isoformat()
        self.assertFalse(approval_matches(msg, DOC, PREVIEW, SETTINGS))
        for kind in ('automation', 'edit'):
            doc = dict(DOC, expires_at=None, kind=kind)
            self.assertTrue(approval_matches(msg, doc, PREVIEW, SETTINGS))
        doc = dict(DOC, expires_at=None)
        self.assertIn('No expiry', preview_text(doc))
        self.assertNotIn('Expires: None', preview_text(doc))
        for changes in ({'kind':'action'}, {'created_at':(LATER+timedelta(seconds=1)).isoformat()}):
            self.assertFalse(approval_matches(msg, dict(doc, **changes), PREVIEW, SETTINGS))

    async def test_worker_publishes_polls_after_years_and_never_revives_tombstones(self):
        import asyncio
        from types import SimpleNamespace as NS
        from custom_components.house_manager_general.discord import ApprovalWorker
        from tests_general.test_worker_general import DOC, PREVIEW, SETTINGS, message
        for kind in ('automation', 'edit', 'action', 'legacy', 'expired'):
            doc = dict(DOC, kind='automation' if kind in ('legacy','expired') else kind, expires_at=None)
            if kind == 'legacy': doc['expires_at'] = DOC['expires_at']
            if kind == 'edit':
                fixture = edits.EditTests(); b, m, target = fixture.setup_manager()
                q = await fixture.queue_edit(m, target); doc = m.records[q['id']]['proposal']
            record = {'status':'expired' if kind == 'expired' else 'queued', 'proposal':doc}
            events = []
            async def save(records): pass
            async def approve(*args): events.append('approved'); record['status'] = 'executed'
            class REST:
                async def send_preview(self, channel, content, filename, attachment):
                    events.append('preview'); self.content=content; self.filename=filename; self.attachment=attachment
                    return {'id':'100'}
                async def send_approval(self, channel, content, preview_id): self.command=content; return {'id':'102'}
                async def messages(self, *args): return [self.human()]
                def human(self):
                    msg=message(); msg.update(id='103', timestamp=(LATER+timedelta(seconds=1)).isoformat(), content=f"APPROVE {doc['id']} {doc['sha256']}"); return msg
                async def get_message(self, channel, identifier):
                    if identifier == '103': return self.human()
                    result={'id':identifier,'channel_id':'33','author':{'id':'44','bot':True},'timestamp':LATER.isoformat()}
                    if identifier == '100': result.update(content=self.content,attachments=[{'filename':self.filename,'size':len(self.attachment)}])
                    else: result.update(content=self.command,attachments=[],message_reference={'message_id':'100','channel_id':'33'})
                    return result
            manager=NS(records={doc['id']:record}, operation_lock=asyncio.Lock(), boundary=NS(save=save), now=lambda:LATER, approve=approve)
            worker=ApprovalWorker(manager, REST(), SETTINGS); worker.bot_id='44'
            await worker.publish(doc['id'])
            await worker.poll(doc['id'])
            await worker.poll(doc['id'])
            if kind in ('automation','edit'): self.assertEqual(events,['preview','approved'])
            else: self.assertEqual(events,[]); self.assertEqual(record['status'],'expired')
            if kind == 'legacy':
                # An already-published legacy finite document expires in poll too.
                record.update(status='awaiting_approval',preview=PREVIEW)
                await worker.poll(doc['id'])
                self.assertEqual(record['status'],'expired'); self.assertEqual(events,[])
