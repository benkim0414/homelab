"""Fail-closed, adapter-only web/worker writer guard. No production entrypoint.

Adapters are trusted safety boundaries, NOT implemented by the metadata probes.
All IO must honor the supplied monotonic deadline (including cancellation of
subprocesses). Python cannot forcibly interrupt an arbitrary blocking callback.
A writer fence must watch *all* writer paths without gaps, including terminating
pods, background jobs, external ingest and in-flight transactions; checking just
Deployment replicas at either end is insufficient. The fence remains active for
the entire capture callback and fails closed on watch disconnect/overflow.

A failed operation never automatically resumes, retries or rolls back. Call
resume() explicitly after review. Unknown mutation outcomes, journal failure or
concurrent edits require manual recovery; reopening a journal does not authorize
replay. A process crash leaves an exclusive durable intent for human inspection.
Receipts are nonsecret evidence references, not secret values or approval inferred
from healthy metadata. Production adapters and independent evidence review remain
unimplemented. Spec snapshots belong only in the private journal, never logs.
"""
from __future__ import annotations

import copy
import fcntl
import json
import math
import os
import stat
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Protocol


TARGETS = ("langfuse-web", "langfuse-worker")


class Refused(Exception):
    """Controlled refusal; no arbitrary provider exception text is published."""


class Cancelled(Refused):
    pass


@dataclass(frozen=True)
class Resource:
    name: str
    uid: str
    version: str
    spec: dict
    namespace: str = "langfuse"
    kind: str = "Deployment"
    generation: int | None = None

    def validate(self):
        if (self.name not in TARGETS or self.namespace != "langfuse"
                or self.kind != "Deployment" or not self.uid or not self.version):
            raise Refused("resource_scope")
        if type(self.generation) is not int or self.generation <= 0:
            raise Refused("resource_generation_required")
        replicas = self.spec.get("replicas")
        if type(replicas) is not int or replicas < 0:
            raise Refused("explicit_replicas_required")
        if not self.images():
            raise Refused("images_required")

    def images(self):
        pod = self.spec.get("template", {}).get("spec", {})
        containers = pod.get("containers", []) + pod.get("initContainers", [])
        images = tuple(c.get("image", "") for c in containers)
        if not images or any(not i or "@sha256:" not in i for i in images):
            raise Refused("pinned_images_required")
        return images

    def scaled(self, replicas):
        spec = copy.deepcopy(self.spec)
        spec["replicas"] = replicas
        return replace(self, spec=spec)

    def same_revision(self, newer):
        """Fixed K3s snapshot: only forward numeric RV churn, never spec ABA.

        Generation is required even for equal specs: a changed-and-restored spec
        is not a status update. Scope, UID and the entire spec remain exact.
        """
        versions = (self.version, newer.version)
        return (all(isinstance(v, str) and v.isascii() and v.isdecimal()
                    and int(v) > 0 for v in versions)
                and (newer.version == self.version or int(newer.version) > int(self.version))
                and type(self.generation) is int and self.generation > 0
                and type(newer.generation) is int
                and replace(newer, version=self.version) == self)


@dataclass(frozen=True)
class Approval:
    """Nonsecret references to reviewed, one-shot authorization and custody."""
    operation_id: str
    authorization_ref: str
    recipient_ref: str
    custody_ref: str
    destination_ref: str
    client_idle_ref: str
    expires_at: float  # monotonic clock in this process

    def validate(self, now):
        if (not all(isinstance(v, str) and v.strip() for v in (
                self.operation_id, self.authorization_ref, self.recipient_ref,
                self.custody_ref, self.destination_ref, self.client_idle_ref))
                or not math.isfinite(self.expires_at) or now >= self.expires_at):
            raise Refused("missing_or_expired_authorization")


@dataclass(frozen=True)
class Evidence:
    """Fresh independent evidence, bound to exact current objects, not aggregates.

    pvc_proofs maps each of the four store names to a complete nonsecret identity
    projection: PVC UID/version/spec, PV UID/version/spec/volume handle, consumers,
    retention/reclaim/owner references and health proof. The adapter independently
    rereads and compares it before each write and during the writer fence.
    """
    operation_id: str
    resources: tuple[Resource, ...]
    pvc_proofs: dict
    client_idle_ref: str
    migration_ref: str
    observed_at: float
    migration_images: tuple[tuple[str, tuple[str, ...]], ...]
    clean_migrations: bool
    manual_sync: bool
    no_concurrent_operation: bool
    safety_ref: str
    challenge: str

    def validate(self, approval, resources, now, freshness, challenge, requested_at):
        if (self.operation_id != approval.operation_id
                or self.challenge != challenge
                or self.resources != resources
                or self.client_idle_ref != approval.client_idle_ref
                or not self.migration_ref or not self.safety_ref
                or self.clean_migrations is not True
                or self.manual_sync is not True
                or self.no_concurrent_operation is not True
                or not math.isfinite(self.observed_at)
                or self.observed_at < requested_at
                or not 0 <= now - self.observed_at <= freshness
                or self.migration_images != tuple((r.name, r.images()) for r in resources)
                or set(self.pvc_proofs) != {"postgresql", "clickhouse", "valkey", "seaweedfs"}):
            raise Refused("fresh_exact_safety_evidence_required")
        required = {"pvc", "pv", "volume_handle", "consumers", "retention", "health_ref"}
        for proof in self.pvc_proofs.values():
            if not isinstance(proof, dict) or set(proof) != required:
                raise Refused("incomplete_pvc_proof")
            for key in ("pvc", "pv"):
                obj = proof[key]
                if (not isinstance(obj, dict) or not obj.get("uid")
                        or not obj.get("resourceVersion") or not isinstance(obj.get("spec"), dict)
                        or not obj["spec"]):
                    raise Refused("incomplete_volume_identity")
            if not all(proof[k] for k in ("volume_handle", "retention", "health_ref")):
                raise Refused("incomplete_volume_safety")
            if not isinstance(proof["consumers"], list):
                raise Refused("incomplete_consumer_inventory")


class Fence(Protocol):
    def check(self, deadline: float) -> bool:
        """Prove continuous exclusion since acquisition, not a point sample."""
        ...
    def finish(self, deadline: float) -> bool:
        """Close watch and attest uninterrupted exclusion through completion."""
        ...


class Adapter(Protocol):
    def read(self, name: str, deadline: float) -> Resource: ...
    def evidence(self, approval: Approval, resources: tuple[Resource, ...],
                 phase: str, challenge: str, deadline: float) -> Evidence:
        """Fresh independent checks, attested to this unique challenge.

        Verify the referenced authorization covers the exact resources, mutation,
        recipient/custody/destination, client-idle window and operation ID. Reject
        an operation ID used by any previous guard/process. An evidence request
        is not permission to invent approval, copy historical metadata or bypass
        missing operator decisions. Check migrations against actual image trees.
        """
        ...
    def scale(self, before: Resource, replicas: int, deadline: float) -> Resource:
        """Atomic UID AND resourceVersion compare-and-swap; ONLY /spec/replicas.

        Return the API write result; never fallback to unconditional scale, update,
        force, replace or retry. The guard independently rereads the exact target.
        """
        ...
    def drained(self, deadline: float) -> bool:
        """Real queue AND transaction/request-idle check after web termination."""
        ...
    def stopped(self, name: str, deadline: float) -> bool:
        """Normal graceful termination complete; no live/terminating owned pods."""
        ...
    def fence(self, deadline: float) -> Fence:
        """Acquire gap-free absence-of-all-writers watch, or refuse."""
        ...


class Journal:
    """New private O_EXCL journal in an existing private nonsymlink directory.

    Lock is held for object lifetime; no reopen/replay API. fsync each record and
    directory entry before any mutation. Files intentionally survive failure.
    """
    def __init__(self, path: str | Path):
        path = Path(path).absolute()
        self.fd = None
        self.dirfd = None
        self.name = path.name
        # Reject symlink ancestors, not merely the final directory.
        for parent in (path.parent, *path.parent.parents):
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise Refused("journal_directory_type")
        self.dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(self.dirfd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise Refused("journal_directory_not_private")
            self.fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                              | os.O_NOFOLLOW, 0o600, dir_fd=self.dirfd)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self.fd)
            os.fsync(self.dirfd)
        except BaseException:
            self.close()
            raise

    def append(self, event: dict):
        if self.fd is None or self.dirfd is None:
            raise Refused("journal_closed")
        info = os.fstat(self.fd)
        entry = os.stat(self.name, dir_fd=self.dirfd, follow_symlinks=False)
        directory = os.fstat(self.dirfd)
        if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (entry.st_dev, entry.st_ino) != (info.st_dev, info.st_ino)
                or directory.st_uid != os.getuid()
                or stat.S_IMODE(directory.st_mode) != 0o700):
            raise Refused("journal_identity_or_privacy_changed")
        payload = (json.dumps(event, sort_keys=True, allow_nan=False) + "\n").encode()
        view = memoryview(payload)
        while view:
            written = os.write(self.fd, view)
            if written <= 0:
                raise OSError("journal_short_write")
            view = view[written:]
        os.fsync(self.fd)
        os.fsync(self.dirfd)

    def close(self):
        for attr in ("fd", "dirfd"):
            fd = getattr(self, attr, None)
            if fd is not None:
                os.close(fd)
                setattr(self, attr, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@dataclass(frozen=True)
class Result:
    state: str
    capture_complete: bool
    paused: tuple[str, ...]
    uncertain: tuple[str, ...]
    reason: str = ""


class WriterGuard:
    def __init__(self, adapter: Adapter, journal: Journal, approval: Approval,
                 expected: tuple[Resource, Resource], *, timeout=1800.0,
                 drain_timeout=120.0, poll_interval=1.0, freshness=15.0,
                 clock=time.monotonic, sleep=time.sleep, cancelled=lambda: False):
        for value in (timeout, drain_timeout, poll_interval, freshness):
            if not math.isfinite(value) or value <= 0:
                raise Refused("invalid_bound")
        if tuple(r.name for r in expected) != TARGETS:
            raise Refused("exact_web_worker_order_required")
        for resource in expected:
            resource.validate()
        self.api, self.journal, self.approval = adapter, journal, approval
        self.original = copy.deepcopy(expected)
        self.current = {r.name: copy.deepcopy(r) for r in expected}
        self.paused = {}
        self.uncertain = set()
        self.clock, self.sleep, self.cancelled = clock, sleep, cancelled
        self.timeout, self.drain_timeout = timeout, drain_timeout
        self.poll_interval, self.freshness = poll_interval, freshness
        self.state, self.complete = "NEW", False
        self.deadline = 0.0
        self.storage = None

    def _check(self):
        if self.cancelled():
            raise Cancelled("cancelled")
        if self.clock() >= self.deadline:
            raise Refused("deadline")
        self.approval.validate(self.clock())

    def _record(self, event, **fields):
        self.journal.append({"event": event, "operation_id": self.approval.operation_id,
                             "at": self.clock(), **fields})

    def _read_exact(self):
        resources = []
        for name in TARGETS:
            self._check()
            actual = self.api.read(name, self.deadline)
            actual.validate()
            if not self.current[name].same_revision(actual):
                raise Refused("concurrent_resource_change")
            self.current[name] = copy.deepcopy(actual)
            if name in self.paused:
                self.paused[name] = copy.deepcopy(actual)
            resources.append(copy.deepcopy(actual))
        self._check()
        return tuple(resources)

    def _admit(self, phase):
        self._check()
        resources = self._read_exact()
        requested_at = self.clock()
        challenge = uuid.uuid4().hex
        evidence = self.api.evidence(self.approval, resources, phase, challenge, self.deadline)
        self._check()
        evidence.validate(self.approval, resources, self.clock(), self.freshness,
                          challenge, requested_at)
        # A migration proof is always freshly reissued; storage identities/specs
        # must stay identical across the entire one-shot operation.
        if self.storage is None:
            self.storage = copy.deepcopy(evidence.pvc_proofs)
        elif evidence.pvc_proofs != self.storage:
            raise Refused("concurrent_storage_change")
        self._record("admitted", phase=phase, safety_ref=evidence.safety_ref,
                     challenge=challenge,
                     migration_ref=evidence.migration_ref, resources=[r.__dict__ for r in resources],
                     pvc_proofs=evidence.pvc_proofs)
        # Evidence remains bound to the exact requested snapshot/challenge above;
        # never relabel it with a later RV. Recheck spec/generation after the call
        # and retain newer status-only snapshots for subsequent CAS operations.
        self._read_exact()

    def _mutate(self, name, replicas, phase):
        self._admit(phase)
        before = copy.deepcopy(self.current[name])
        wanted = before.scaled(replicas)
        self._record("mutation_intent", phase=phase, before=before.__dict__, replicas=replicas)
        self._check()
        # Once invoked, an exception may mean a committed but unobserved write.
        self.uncertain.add(name)
        written = self.api.scale(copy.deepcopy(before), replicas, self.deadline)
        readback = self.api.read(name, self.deadline)
        self._check()
        # This one-time K3s adapter supports positive decimal RVs only (as does
        # its Pod watch). Refuse unsupported/stale versions rather than treating
        # an arbitrary differing RV as proof that the CAS committed.
        versions = (before.version, written.version, readback.version)
        if (any(not isinstance(v, str) or not v.isascii() or not v.isdecimal()
                or int(v) <= 0 for v in versions)
                or not int(before.version) < int(written.version) <= int(readback.version)
                or type(before.generation) is not int or before.generation <= 0
                or type(written.generation) is not int
                or written.generation != before.generation + 1
                or type(readback.generation) is not int
                or readback.generation != written.generation
                or replace(written, version=before.version, generation=before.generation) != wanted
                or replace(readback, version=written.version) != written):
            raise Refused("mutation_readback_failed")
        # Keep the GET snapshot for the next CAS, not the older acknowledgement.
        # Later reads permit the same status-only churn via same_revision().
        readback.validate()
        self._record("mutation_verified", phase=phase, resource=readback.__dict__,
                     acknowledged_version=written.version)
        self.current[name] = copy.deepcopy(readback)
        if phase == "pause":
            self.paused[name] = copy.deepcopy(readback)
        else:
            self.paused.pop(name)
        self.uncertain.remove(name)

    def _wait(self, predicate, deadline):
        while True:
            self._check()
            if self.clock() >= deadline:
                raise Refused("drain_or_termination_timeout")
            done = predicate(min(deadline, self.deadline))
            self._check()
            if self.clock() >= deadline:
                raise Refused("drain_or_termination_timeout")
            if done is True:
                return
            self.sleep(min(self.poll_interval, deadline - self.clock()))

    def result(self, reason=""):
        return Result(self.state, self.complete, tuple(sorted(self.paused)),
                      tuple(sorted(self.uncertain)), reason)

    def _failed(self, exc, *, force_manual=False):
        # Never publish raw adapter/capture errors (they may contain secrets).
        codes = {"cancelled", "deadline", "missing_or_expired_authorization",
                 "concurrent_resource_change", "concurrent_storage_change",
                 "fresh_exact_safety_evidence_required", "incomplete_pvc_proof",
                 "incomplete_volume_identity", "incomplete_volume_safety",
                 "incomplete_consumer_inventory", "mutation_readback_failed",
                 "drain_or_termination_timeout", "writer_exclusion_lost",
                 "paused_identity_mismatch"}
        reason = str(exc) if type(exc) in (Refused, Cancelled) and str(exc) in codes else "operation_failed"
        self.state = "MANUAL_RECOVERY" if self.uncertain or force_manual else "INCOMPLETE"
        try:
            self._record("incomplete", state=self.state, reason=reason,
                         paused=sorted(self.paused), uncertain=sorted(self.uncertain))
        except BaseException:
            self.state = "MANUAL_RECOVERY"
            reason = "journal_failure"
        return self.result(reason)

    def run(self, capture: Callable[[Callable[[], None], float], None]) -> Result:
        """One shot. Capture must call checkpoint between bounded stream steps.

        Returning from capture means its own complete encrypted output validation
        succeeded; this library proves only writer coordination, not archive or
        restore acceptance. No implicit resume on success, exception or cancellation.
        """
        if self.state != "NEW":
            raise Refused("one_shot_only")
        self.deadline = min(self.clock() + self.timeout, self.approval.expires_at)
        fence = None
        try:
            self._admit("start")
            self.state = "PAUSING"
            for name in TARGETS:
                if self.current[name].spec["replicas"] > 0:
                    self._mutate(name, 0, "pause")
                self._wait(lambda d: self.api.stopped(name, d),
                           min(self.deadline, self.clock() + self.drain_timeout))
                if name == TARGETS[0]:
                    self._wait(self.api.drained,
                               min(self.deadline, self.clock() + self.drain_timeout))
            self.state = "PAUSED"
            self._admit("capture")
            fence = self.api.fence(self.deadline)
            active_fence = fence

            def checkpoint():
                self._check()
                self._read_exact()
                if active_fence.check(self.deadline) is not True:
                    raise Refused("writer_exclusion_lost")
                self._check()

            checkpoint()
            self._record("capture_started")
            self.state = "CAPTURING"
            capture(checkpoint, self.deadline)
            checkpoint()
            if fence.finish(self.deadline) is not True:
                raise Refused("writer_exclusion_lost")
            fence = None
            self._check()
            self._record("capture_completed")
            self.complete, self.state = True, "CAPTURED"
            return self.result()
        except BaseException as exc:
            self.complete = False
            return self._failed(exc)
        finally:
            if fence is not None:
                try:
                    fence.finish(self.deadline)
                except BaseException:
                    pass  # Failure already incomplete; never resumes writers.

    def resume(self) -> Result:
        """Explicit, single reviewed attempt, original resources only.

        Clean image-bound migration evidence is required before EACH replica
        restoration. No data restore, client change, datastore write or retry.
        Does not claim application readiness or fresh ingestion acceptance.
        """
        if self.state not in ("CAPTURED", "INCOMPLETE") or self.uncertain:
            raise Refused("manual_recovery_or_no_pause")
        self.deadline = min(self.clock() + self.timeout, self.approval.expires_at)
        self.state = "RESUMING"
        try:
            # Precheck both before any write, so known drift cannot partially resume.
            self._admit("resume")
            for original in self.original:
                name = original.name
                if name in self.paused:
                    if self.current[name] != self.paused[name]:
                        raise Refused("paused_identity_mismatch")
                    self._mutate(name, original.spec["replicas"], "resume")
            self._record("replicas_restored", capture_complete=self.complete)
            self.state = "RESUMED"
            return self.result()
        except BaseException as exc:
            # Resume is never automatically retried, including definite prewrite refusals.
            return self._failed(exc, force_manual=True)
