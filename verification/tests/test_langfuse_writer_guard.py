"""SYNTHETIC adapter tests only: no cluster, credentials or production writes."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "langfuse/recovery/writer_guard.py"
SPEC = importlib.util.spec_from_file_location("langfuse_writer_guard", SOURCE)
assert SPEC is not None and SPEC.loader is not None
w = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = w
SPEC.loader.exec_module(w)


class SyntheticClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SyntheticFence:
    def __init__(self, api):
        self.api = api
        self.lost = False
        self.finished = False

    def check(self, deadline):
        self.api.events.append("fence_check")
        # Lost even when a transient writer subsequently disappeared.
        return not self.lost

    def finish(self, deadline):
        self.finished = True
        self.api.events.append("fence_finish")
        return not self.lost


class SyntheticAPI:
    def __init__(self, clock):
        self.clock = clock
        self.objects = {}
        for name in w.TARGETS:
            self.objects[name] = w.Resource(name, "synthetic-uid-" + name, "1", {
                "replicas": 2 if name.endswith("web") else 1,
                "selector": {"matchLabels": {"app": name}},
                "template": {"spec": {"containers": [{
                    "name": name, "image": "synthetic.invalid/fixture@sha256:" + "a" * 64,
                    "env": [{"name": "SYNTHETIC", "value": "fixture"}]}]}}}, generation=1)
        self.events = []
        self.writes = []
        self.drain = True
        self.stop = True
        self.fail_write: str | None = None
        self.fail_readback = False
        self.clean = True
        self.evidence_transform = lambda e: e
        self.before_scale = lambda: None
        self.after_scale = lambda: None
        self.fence_object = SyntheticFence(self)
        self.storage = {store: {
            "pvc": {"uid": "synthetic-claim-" + store, "resourceVersion": "1",
                    "spec": {"volumeName": "synthetic-pv-" + store}},
            "pv": {"uid": "synthetic-pv-" + store, "resourceVersion": "1",
                   "spec": {"persistentVolumeReclaimPolicy": "Delete"}},
            "volume_handle": "synthetic-volume-" + store,
            "consumers": [], "retention": {"verified": "synthetic-retain"},
            "health_ref": "synthetic-health"}
            for store in ("postgresql", "clickhouse", "valkey", "seaweedfs")}

    def read(self, name, deadline):
        self.events.append("read:" + name)
        if self.fail_readback and self.writes:
            raise OSError("SENSITIVE PROVIDER ERROR")
        return copy.deepcopy(self.objects[name])

    def evidence(self, approval, resources, phase, challenge, deadline):
        self.events.append("evidence:" + phase)
        return self.evidence_transform(w.Evidence(
            approval.operation_id, copy.deepcopy(resources), copy.deepcopy(self.storage),
            approval.client_idle_ref, "synthetic-image-migration-comparison", self.clock(),
            tuple((r.name, r.images()) for r in resources), self.clean, True, True,
            "synthetic-exact-safety", challenge))

    def scale(self, before, replicas, deadline):
        self.before_scale()
        self.events.append("scale:" + before.name + ":" + str(replicas))
        if self.objects[before.name] != before:
            raise RuntimeError("synthetic CAS conflict")
        if self.fail_write == before.name:
            raise OSError("SENSITIVE PROVIDER ERROR")
        updated = replace(before.scaled(replicas), version=str(int(before.version) + 1),
                          generation=before.generation + 1)
        self.objects[before.name] = copy.deepcopy(updated)
        self.writes.append((before.name, replicas))
        self.after_scale()
        return copy.deepcopy(updated)

    def drained(self, deadline):
        self.events.append("drain")
        return self.drain

    def stopped(self, name, deadline):
        self.events.append("stopped:" + name)
        return self.stop

    def fence(self, deadline):
        self.events.append("fence_acquire")
        return self.fence_object


class WriterGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-writer-guard-")
        self.directory = Path(self.temp.name)
        os.chmod(self.directory, 0o700)
        self.clock = SyntheticClock()
        self.api = SyntheticAPI(self.clock)
        self.approval = w.Approval("synthetic-operation", "synthetic-approval",
                                   "synthetic-recipient", "synthetic-custody",
                                   "synthetic-destination", "synthetic-client-idle", 1000.0)
        self.expected = tuple(copy.deepcopy(self.api.objects[n]) for n in w.TARGETS)
        self.journal = w.Journal(self.directory / "operation.jsonl")
        self.guard = self.make_guard()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.journal.close)

    def make_guard(self, **options):
        return w.WriterGuard(self.api, self.journal, self.approval, self.expected,
                             clock=self.clock, sleep=self.clock.sleep,
                             timeout=50, drain_timeout=3, **options)

    def capture(self, checkpoint, deadline):
        self.api.events.append("synthetic_capture")
        checkpoint()
        self.clock.sleep(1)
        checkpoint()

    def records(self):
        return [json.loads(line) for line in
                (self.directory / "operation.jsonl").read_text().splitlines()]

    def test_success_order_private_journal_and_explicit_resume(self):
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "CAPTURED")
        self.assertTrue(result.capture_complete)
        self.assertEqual(self.api.writes, [(w.TARGETS[0], 0), (w.TARGETS[1], 0)])
        events = self.api.events
        self.assertLess(events.index("scale:langfuse-web:0"), events.index("drain"))
        self.assertLess(events.index("drain"), events.index("scale:langfuse-worker:0"))
        self.assertLess(events.index("fence_acquire"), events.index("synthetic_capture"))
        self.assertLess(events.index("synthetic_capture"), events.index("fence_finish"))
        self.assertEqual(stat.S_IMODE((self.directory / "operation.jsonl").stat().st_mode), 0o600)
        resumed = self.guard.resume()
        self.assertEqual(resumed.state, "RESUMED")
        self.assertFalse(resumed.paused)
        self.assertEqual(self.api.writes[-2:], [(w.TARGETS[0], 2), (w.TARGETS[1], 1)])
        for original in self.expected:
            self.assertEqual(self.api.objects[original.name].spec, original.spec)
            self.assertEqual(self.api.objects[original.name].uid, original.uid)
        intents = [r for r in self.records() if r["event"] == "mutation_intent"]
        verified = [r for r in self.records() if r["event"] == "mutation_verified"]
        self.assertEqual(len(intents), 4)
        self.assertEqual(len(verified), 4)

    def test_intent_is_durable_before_every_write(self):
        def inspect():
            self.assertEqual(self.records()[-1]["event"], "mutation_intent")
        self.api.before_scale = inspect
        with patch.object(w.os, "fsync", wraps=os.fsync) as fsync:
            self.guard.run(self.capture)
            self.guard.resume()
            self.assertGreaterEqual(fsync.call_count, 8)

    def test_drain_timeout_only_web_paused_no_auto_resume(self):
        self.api.drain = False
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "INCOMPLETE")
        self.assertEqual(result.paused, ("langfuse-web",))
        self.assertFalse(result.capture_complete)
        self.assertEqual(self.api.writes, [("langfuse-web", 0)])
        self.assertNotIn("synthetic_capture", self.api.events)
        self.assertEqual(self.guard.resume().state, "RESUMED")
        self.assertEqual(self.api.writes[-1], ("langfuse-web", 2))

    def test_termination_timeout_never_stops_worker(self):
        self.api.stop = False
        self.assertEqual(self.guard.run(self.capture).state, "INCOMPLETE")
        self.assertEqual(self.api.writes, [("langfuse-web", 0)])

    def test_partial_pause_unknown_write_requires_manual_recovery(self):
        self.api.fail_write = "langfuse-worker"
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.paused, ("langfuse-web",))
        self.assertEqual(result.uncertain, ("langfuse-worker",))
        self.assertNotIn("SENSITIVE", result.reason)
        with self.assertRaises(w.Refused):
            self.guard.resume()
        self.assertEqual(self.api.writes, [("langfuse-web", 0)])

    def test_capture_failure_can_only_explicitly_resume_unchanged_resources(self):
        def fail(checkpoint, deadline):
            raise RuntimeError("PRIVATE CAPTURE DETAIL")
        result = self.guard.run(fail)
        self.assertEqual(result.state, "INCOMPLETE")
        self.assertEqual(len(self.api.writes), 2)
        self.assertFalse(result.capture_complete)
        self.assertNotIn("PRIVATE", result.reason)
        self.assertTrue(self.api.fence_object.finished)
        self.assertEqual(self.guard.resume().state, "RESUMED")
        self.assertFalse(self.guard.result().capture_complete)

    def test_cancellation_during_capture_does_not_resume(self):
        cancelled = [False]
        self.guard = self.make_guard(cancelled=lambda: cancelled[0])
        def cancel(checkpoint, deadline):
            cancelled[0] = True
            checkpoint()
        result = self.guard.run(cancel)
        self.assertEqual(result.reason, "cancelled")
        self.assertEqual(len(self.api.writes), 2)
        self.assertEqual(result.state, "INCOMPLETE")

    def test_keyboard_interrupt_does_not_resume(self):
        def interrupt(checkpoint, deadline):
            raise KeyboardInterrupt()
        self.assertEqual(self.guard.run(interrupt).state, "INCOMPLETE")
        self.assertEqual(len(self.api.writes), 2)

    def test_capture_deadline_is_not_success(self):
        def late(checkpoint, deadline):
            self.clock.sleep(51)
        self.assertEqual(self.guard.run(late).state, "INCOMPLETE")
        self.assertFalse(self.guard.complete)

    def test_transient_writer_during_capture_invalidates_whole_interval(self):
        def writer(checkpoint, deadline):
            self.api.fence_object.lost = True
        result = self.guard.run(writer)
        self.assertFalse(result.capture_complete)
        self.assertEqual(result.state, "INCOMPLETE")

    def test_stale_uid_and_version_refuse_before_write(self):
        for change in ({"uid": "synthetic-replacement"}, {"version": "0"}):
            with self.subTest(change=change):
                self.api.objects["langfuse-web"] = replace(self.expected[0], **change)
                guard = self.make_guard()
                self.assertEqual(guard.run(self.capture).state, "INCOMPLETE")
                self.assertEqual(self.api.writes, [])

    def test_atomic_cas_catches_race_after_evidence(self):
        def race():
            self.api.objects["langfuse-web"] = replace(self.expected[0], version="2")
        self.api.before_scale = race
        self.assertEqual(self.guard.run(self.capture).state, "MANUAL_RECOVERY")
        self.assertEqual(self.api.writes, [])

    def test_manual_spec_or_replica_or_uid_version_drift_never_overwritten(self):
        for drift in ("spec", "replicas", "uid", "version"):
            with self.subTest(drift=drift):
                api = SyntheticAPI(self.clock)
                self.api = api
                guard = self.make_guard()
                guard.run(self.capture)
                before = api.objects["langfuse-worker"]
                if drift == "spec":
                    spec = copy.deepcopy(before.spec)
                    spec["template"]["metadata"] = {"annotations": {"manual": "change"}}
                    api.objects[before.name] = replace(before, spec=spec)
                elif drift == "replicas":
                    api.objects[before.name] = before.scaled(3)
                else:
                    api.objects[before.name] = replace(before, **{drift: "synthetic-drift"})
                changed = copy.deepcopy(api.objects)
                self.assertEqual(guard.resume().state, "MANUAL_RECOVERY")
                self.assertEqual(api.objects, changed)
                self.assertEqual(len(api.writes), 2)

    def test_dirty_migration_blocks_resume(self):
        self.guard.run(self.capture)
        self.api.clean = False
        self.assertEqual(self.guard.resume().state, "MANUAL_RECOVERY")
        self.assertEqual(len(self.api.writes), 2)

    def test_migration_rechecked_before_each_resume_write(self):
        self.guard.run(self.capture)
        self.api.after_scale = lambda: setattr(self.api, "clean", False)
        result = self.guard.resume()
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.paused, ("langfuse-worker",))
        self.assertEqual(len(self.api.writes), 3)
        with self.assertRaises(w.Refused):
            self.guard.resume()

    def test_resume_failure_and_readback_failure_are_not_retried(self):
        self.guard.run(self.capture)
        self.api.fail_write = "langfuse-web"
        result = self.guard.resume()
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.uncertain, ("langfuse-web",))
        with self.assertRaises(w.Refused):
            self.guard.resume()

    def test_write_applied_but_readback_failed_remains_unknown(self):
        self.api.after_scale = lambda: setattr(self.api, "fail_readback", True)
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.uncertain, ("langfuse-web",))
        self.assertEqual(self.api.objects["langfuse-web"].spec["replicas"], 0)
        self.assertEqual(result.paused, ())

    def test_post_ack_version_only_race_uses_readback_for_next_cas(self):
        def status_update():
            name = self.api.writes[-1][0]
            current = self.api.objects[name]
            self.api.objects[name] = replace(current, version=str(int(current.version) + 1))
        self.api.after_scale = status_update
        self.assertEqual(self.guard.run(self.capture).state, "CAPTURED")
        for name in w.TARGETS:
            self.assertEqual(self.guard.current[name], self.api.objects[name])
            self.assertEqual(self.guard.paused[name], self.api.objects[name])
            self.assertEqual(self.guard.current[name].version, "3")
        # SyntheticAPI's exact CAS rejects use of the older patch acknowledgement.
        self.assertEqual(self.guard.resume().state, "RESUMED")
        verified = [r for r in self.records() if r["event"] == "mutation_verified"]
        self.assertEqual([r["resource"]["version"] for r in verified], ["3", "3", "5", "5"])
        self.assertEqual([r["acknowledged_version"] for r in verified], ["2", "2", "4", "4"])

    def test_missing_invalid_generation_or_spec_aba_refuses(self):
        for boundary in ("before", "ack", "readback"):
            for generation in (None, 0, True, "2", 1, 3, 4):
                with self.subTest(boundary=boundary, generation=generation):
                    self.api = SyntheticAPI(self.clock)
                    if boundary == "before":
                        # Invalid baseline generation cannot justify a postwrite RV reconciliation.
                        if type(generation) is int and generation > 0:
                            continue
                        self.api.objects[w.TARGETS[0]] = replace(self.api.objects[w.TARGETS[0]],
                                                               generation=generation)
                    self.expected = tuple(copy.deepcopy(self.api.objects[n]) for n in w.TARGETS)
                    if boundary == "before":
                        with self.assertRaises(w.Refused):
                            self.make_guard()
                        self.assertEqual(self.api.writes, [])
                        continue
                    guard = self.make_guard()
                    real_scale = self.api.scale
                    def changed(before, replicas, deadline):
                        ack = real_scale(before, replicas, deadline)
                        if boundary == "ack":
                            return replace(ack, generation=generation)
                        if boundary == "readback":
                            # Same final spec but changed generation includes spec ABA.
                            self.api.objects[before.name] = replace(ack, version="3", generation=generation)
                        return ack
                    self.api.scale = changed
                    result = guard.run(self.capture)
                    self.assertEqual(result.state, "MANUAL_RECOVERY")
                    self.assertEqual(result.reason, "mutation_readback_failed")
                    self.assertEqual(result.uncertain, ("langfuse-web",))
                    self.assertEqual(self.api.writes, [("langfuse-web", 0)])

    def test_mutation_ack_and_readback_identity_or_full_spec_drift_refuses(self):
        for boundary in ("ack", "readback"):
            for drift in ("uid", "name", "kind", "namespace", "replicas", "spec"):
                with self.subTest(boundary=boundary, drift=drift):
                    self.api = SyntheticAPI(self.clock)
                    guard = self.make_guard()
                    real_scale = self.api.scale
                    def changed(before, replicas, deadline):
                        ack = real_scale(before, replicas, deadline)
                        if drift in ("spec", "replicas"):
                            spec = copy.deepcopy(ack.spec)
                            if drift == "replicas":
                                spec["replicas"] = 7
                            else:
                                spec["strategy"] = {"type": "Recreate"}
                            bad = replace(ack, spec=spec)
                        else:
                            bad = replace(ack, **{drift: "synthetic-conflict"})
                        if boundary == "ack":
                            return bad
                        self.api.objects[before.name] = replace(bad, version="3")
                        return ack
                    self.api.scale = changed
                    result = guard.run(self.capture)
                    self.assertEqual(result.state, "MANUAL_RECOVERY")
                    self.assertEqual(result.reason, "mutation_readback_failed")
                    self.assertEqual(result.uncertain, ("langfuse-web",))
                    self.assertEqual(result.paused, ())
                    self.assertEqual(self.api.writes, [("langfuse-web", 0)])

    def test_invalid_or_stale_mutation_versions_refuse_even_with_matching_spec(self):
        cases = [(v, "3") for v in (None, "", "0", "1", "opaque", "-2", "２", 2)]
        cases += [("2", v) for v in (None, "", "0", "1", "opaque", "-3", "３", 3)]
        cases += [("4", "3")]  # Readback predates the acknowledged patch.
        for ack_version, read_version in cases:
            with self.subTest(ack=ack_version, readback=read_version):
                self.api = SyntheticAPI(self.clock)
                guard = self.make_guard()
                real_scale = self.api.scale
                def changed(before, replicas, deadline):
                    ack = real_scale(before, replicas, deadline)
                    self.api.objects[before.name] = replace(ack, version=read_version)
                    return replace(ack, version=ack_version)
                self.api.scale = changed
                result = guard.run(self.capture)
                self.assertEqual(result.state, "MANUAL_RECOVERY")
                self.assertEqual(result.reason, "mutation_readback_failed")
                self.assertEqual(result.uncertain, ("langfuse-web",))
                self.assertEqual(self.api.writes, [("langfuse-web", 0)])

    def test_resume_readback_failure_remains_unknown(self):
        self.guard.run(self.capture)
        self.api.after_scale = lambda: setattr(self.api, "fail_readback", True)
        result = self.guard.resume()
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.uncertain, ("langfuse-web",))
        self.assertEqual(len(self.api.writes), 3)

    def test_original_zero_is_never_resumed(self):
        self.api.objects["langfuse-web"] = self.expected[0].scaled(0)
        self.expected = tuple(copy.deepcopy(self.api.objects[n]) for n in w.TARGETS)
        guard = self.make_guard()
        self.assertEqual(guard.run(self.capture).state, "CAPTURED")
        self.assertEqual(guard.resume().state, "RESUMED")
        self.assertEqual(self.api.writes, [("langfuse-worker", 0), ("langfuse-worker", 1)])

    def test_missing_approval_fields_refuse(self):
        for field in ("authorization_ref", "recipient_ref", "custody_ref", "destination_ref",
                      "client_idle_ref", "operation_id"):
            with self.subTest(field=field):
                original = self.approval
                self.approval = replace(self.approval, **{field: ""})
                self.assertEqual(self.make_guard().run(self.capture).state, "INCOMPLETE")
                self.assertEqual(self.api.writes, [])
                self.approval = original

    def test_missing_stale_or_unbound_evidence_refuses(self):
        changes = [dict(observed_at=0), dict(observed_at=101), dict(clean_migrations=False),
                   dict(migration_ref=""), dict(migration_images=()), dict(resources=()),
                   dict(client_idle_ref=""), dict(manual_sync=False), dict(pvc_proofs={}),
                   dict(no_concurrent_operation=False), dict(challenge="synthetic-old-request")]
        for change in changes:
            with self.subTest(change=change):
                self.api.evidence_transform = lambda e: replace(e, **change)
                self.assertEqual(self.make_guard().run(self.capture).state, "INCOMPLETE")
                self.assertEqual(self.api.writes, [])

    def test_storage_drift_blocks_resume_without_modifying_datastores(self):
        self.guard.run(self.capture)
        self.api.storage["valkey"]["pvc"]["uid"] = "synthetic-replaced-pvc"
        self.assertEqual(self.guard.resume().state, "MANUAL_RECOVERY")
        self.assertEqual(len(self.api.writes), 2)
        self.assertTrue(all(name in w.TARGETS for name, _ in self.api.writes))

    def test_no_run_or_resume_retry(self):
        self.guard.run(self.capture)
        with self.assertRaises(w.Refused):
            self.guard.run(self.capture)
        self.guard.resume()
        with self.assertRaises(w.Refused):
            self.guard.resume()

    def test_journal_failure_before_intent_means_no_write(self):
        real = self.journal.append
        def fail(event):
            if event["event"] == "mutation_intent":
                raise OSError("synthetic disk full")
            real(event)
        self.journal.append = fail
        self.assertEqual(self.guard.run(self.capture).state, "INCOMPLETE")
        self.assertEqual(self.api.writes, [])

    def test_journal_failure_after_applied_write_means_manual_recovery(self):
        real = self.journal.append
        def fail(event):
            if event["event"] == "mutation_verified":
                raise OSError("synthetic disk full")
            real(event)
        self.journal.append = fail
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.uncertain, ("langfuse-web",))
        self.assertEqual(self.records()[-2]["event"], "mutation_intent")

    def test_total_journal_failure_refuses_all_writes(self):
        self.journal.close()
        self.assertEqual(self.guard.run(self.capture).state, "MANUAL_RECOVERY")
        self.assertEqual(self.api.writes, [])

    def test_fsync_failure_refuses_writes(self):
        with patch.object(w.os, "fsync", side_effect=OSError("synthetic fsync failure")):
            self.assertEqual(self.guard.run(self.capture).state, "MANUAL_RECOVERY")
        self.assertEqual(self.api.writes, [])

    def test_exclusive_no_overwrite_symlink_and_public_directory_rejection(self):
        with self.assertRaises(FileExistsError):
            w.Journal(self.directory / "operation.jsonl")
        (self.directory / "link").symlink_to(self.directory / "operation.jsonl")
        with self.assertRaises(FileExistsError):
            w.Journal(self.directory / "link")
        public = self.directory / "public"
        public.mkdir(mode=0o755)
        # Earlier capture tests can deliberately tighten the process umask.
        # This negative fixture must actually be public under either umask.
        public.chmod(0o755)
        with self.assertRaises(w.Refused):
            w.Journal(public / "journal")
        (self.directory / "linked-directory").symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(w.Refused):
            w.Journal(self.directory / "linked-directory" / "journal")

    def test_wrong_resource_scope_refuses(self):
        for change in ({"name": "langfuse-postgresql"}, {"kind": "StatefulSet"},
                       {"namespace": "other"}):
            with self.subTest(change=change), self.assertRaises(w.Refused):
                w.WriterGuard(self.api, self.journal, self.approval,
                              (replace(self.expected[0], **change), self.expected[1]))

    def test_malformed_write_readback_never_accepted(self):
        original_scale = self.api.scale
        def wrong(before, replicas, deadline):
            written = original_scale(before, replicas, deadline)
            spec = copy.deepcopy(written.spec)
            spec["template"]["metadata"] = {"annotations": {"synthetic": "unexpected"}}
            written = replace(written, spec=spec)
            self.api.objects[before.name] = written
            return written
        self.api.scale = wrong
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(result.reason, "mutation_readback_failed")
        self.assertFalse(result.capture_complete)

    def test_resume_journal_records_manual_state_on_drift(self):
        self.guard.run(self.capture)
        self.api.objects["langfuse-web"] = replace(self.api.objects["langfuse-web"], version="99", generation=4)
        self.assertEqual(self.guard.resume().state, "MANUAL_RECOVERY")
        self.assertEqual(self.records()[-1]["state"], "MANUAL_RECOVERY")

    def test_actual_later_boundary_reproduction_and_correction(self):
        for strict in (True, False):
            with self.subTest(previous_exact_comparison=strict):
                self.api = SyntheticAPI(self.clock)
                web = replace(self.api.objects[w.TARGETS[0]].scaled(1),
                    uid="8ff8744e-9dec-4c8f-bd7a-80fe04e49612", version="20869432", generation=4)
                self.api.objects[web.name] = web
                self.expected = tuple(copy.deepcopy(self.api.objects[n]) for n in w.TARGETS)
                guard = self.make_guard()
                def terminated(name, deadline):
                    if name == web.name:
                        # No immediate ack race: the pause was already verified
                        # at RV20869433/gen5 before this later controller update.
                        self.assertEqual(guard.current[name].version, "20869433")
                        self.assertEqual(guard.current[name].generation, 5)
                        self.api.objects[name] = replace(self.api.objects[name], version="20869453")
                    return True
                self.api.stopped = terminated
                comparison = w.Resource.same_revision
                with patch.object(w.Resource, "same_revision",
                                  (lambda old, new: old == new) if strict else comparison):
                    result = guard.run(self.capture)
                if strict:
                    self.assertEqual(result.reason, "concurrent_resource_change")
                    self.assertEqual(result.paused, (web.name,))
                    self.assertEqual(self.api.writes, [(web.name, 0)])
                else:
                    self.assertEqual(result.state, "CAPTURED", result)
                    self.assertEqual(guard.current[web.name].version, "20869453")
                    self.assertEqual(guard.resume().state, "RESUMED")

    def test_later_drift_after_verified_pause_never_stops_worker(self):
        changes = [dict(version=v) for v in ("1", "0", "opaque", "３", None)]
        changes += [dict(version="23", **{field: value}) for field, value in (
            ("generation", 4), ("generation", None), ("uid", "replacement"),
            ("name", "langfuse-worker"), ("namespace", "other"), ("kind", "StatefulSet"))]
        changes += [dict(version="23", spec=self.expected[0].scaled(7).spec)]
        for change in changes:
            with self.subTest(change=change):
                self.api = SyntheticAPI(self.clock)
                guard = self.make_guard()
                def terminated(name, deadline):
                    self.api.objects[name] = replace(self.api.objects[name], **change)
                    return True
                self.api.stopped = terminated
                result = guard.run(self.capture)
                self.assertEqual(result.state, "INCOMPLETE")
                self.assertEqual(self.api.writes, [(w.TARGETS[0], 0)])
                self.assertFalse(result.capture_complete)

    def test_later_snapshot_refresh_rejects_drift_and_aba(self):
        original = replace(self.expected[0], version="20")
        changes = [dict(version=v) for v in ("19", "0", "", "opaque", "２１", 21, None, "020")]
        changes += [dict(version="21", **{field: value}) for field, value in (
            ("uid", "replacement"), ("name", "langfuse-worker"),
            ("namespace", "other"), ("kind", "StatefulSet"),
            ("generation", 3), ("generation", None), ("generation", True),
            ("spec", original.scaled(0).spec),
            ("spec", dict(original.spec, strategy={"type": "Recreate"})))]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(original.same_revision(replace(original, **change)))
        self.assertTrue(original.same_revision(original))
        self.assertTrue(original.same_revision(replace(original, version="27")))

    def test_evidence_is_not_rebound_to_newer_status_snapshot(self):
        def rebind(e):
            current = self.api.objects[w.TARGETS[0]]
            newer = replace(current, version=str(int(current.version) + 1))
            self.api.objects[current.name] = newer
            return replace(e, resources=(newer, e.resources[1]))
        self.api.evidence_transform = rebind
        result = self.guard.run(self.capture)
        self.assertEqual(result.reason, "fresh_exact_safety_evidence_required")
        self.assertEqual(self.api.writes, [])

    def test_spec_aba_during_evidence_blocks_next_write(self):
        def aba(e):
            current = self.api.objects[w.TARGETS[0]]
            self.api.objects[current.name] = replace(current,
                version=str(int(current.version) + 2), generation=current.generation + 2)
            return e
        self.api.evidence_transform = aba
        self.assertEqual(self.guard.run(self.capture).reason, "concurrent_resource_change")
        self.assertEqual(self.api.writes, [])

    def test_evidence_cannot_reuse_baseline_with_fresh_challenge(self):
        def cached(e):
            self.clock.sleep(0.5)
            return replace(e, observed_at=99.9)
        self.api.evidence_transform = cached
        self.assertEqual(self.guard.run(self.capture).state, "INCOMPLETE")
        self.assertEqual(self.api.writes, [])

    def test_replayed_evidence_challenge_fails_before_first_pause(self):
        cached = []
        def replay(e):
            if not cached:
                cached.append(e)
            return cached[0]
        self.api.evidence_transform = replay
        self.assertEqual(self.guard.run(self.capture).state, "INCOMPLETE")
        self.assertEqual(self.api.writes, [])

    def test_invalid_volume_identity_is_not_general_metadata_acceptance(self):
        self.api.storage["valkey"]["pvc"] = {"uid": "synthetic-only-uid"}
        self.assertEqual(self.guard.run(self.capture).state, "INCOMPLETE")
        self.assertEqual(self.api.writes, [])

    def test_expired_approval_refuses_and_cannot_auto_renew(self):
        self.approval = replace(self.approval, expires_at=99)
        self.assertEqual(self.make_guard().run(self.capture).state, "INCOMPLETE")
        self.assertEqual(self.api.writes, [])

    def test_provider_controlled_refusal_detail_is_redacted(self):
        def fail(name, deadline):
            raise w.Refused("SENSITIVE PROVIDER ERROR")
        self.api.read = fail
        result = self.guard.run(self.capture)
        self.assertEqual(result.reason, "operation_failed")
        self.assertNotIn("SENSITIVE", (self.directory / "operation.jsonl").read_text())

    def test_journal_permission_drift_refuses_next_mutation(self):
        def chmod_after_pause():
            os.chmod(self.directory / "operation.jsonl", 0o640)
        self.api.after_scale = chmod_after_pause
        result = self.guard.run(self.capture)
        self.assertEqual(result.state, "MANUAL_RECOVERY")
        self.assertEqual(self.api.writes, [("langfuse-web", 0)])

    def test_unlinked_journal_refuses_writes(self):
        (self.directory / "operation.jsonl").unlink()
        self.assertEqual(self.guard.run(self.capture).state, "MANUAL_RECOVERY")
        self.assertEqual(self.api.writes, [])

    def test_journal_short_writes_are_completed_before_mutation(self):
        real_write = os.write
        def short_write(fd, view):
            return real_write(fd, view[:17])
        with patch.object(w.os, "write", side_effect=short_write):
            self.assertEqual(self.guard.run(self.capture).state, "CAPTURED")
        self.assertEqual(self.records()[-1]["event"], "capture_completed")

    def test_journal_zero_write_is_failure_not_infinite_retry(self):
        with patch.object(w.os, "write", return_value=0):
            self.assertEqual(self.guard.run(self.capture).state, "MANUAL_RECOVERY")
        self.assertEqual(self.api.writes, [])


if __name__ == "__main__":
    unittest.main()
