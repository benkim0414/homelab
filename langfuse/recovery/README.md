# Langfuse recovery tooling

These tools support the bounded recovery procedure in
[RECOVERY-FIRST.md](../RECOVERY-FIRST.md) and the acceptance criteria in
[BACKUP.md](../BACKUP.md). Publishing source is not operational authorization.
Some modules are read-only inspectors or generated-data fixtures; capture and
restore modules can export confidential data and mutate scoped live resources
when invoked by an authorized caller. Do not treat all files here as diagnostics.

## Historical scope and current limits

The first coordinated capture and isolated restore completed, followed by the
three reviewed datastore rollouts. The
[chronological report](../../reports/2026-11-21-langfuse-recovery-preparation.md)
separates generated tests, actual native execution, operator UI confirmation,
failed attempts and accepted outcomes. Private receipts, ciphertexts, keys,
one-time execution drivers and operation inputs remain in ignored storage;
they are not shipped by this source publication.

Original capture pins/identities intentionally remain fixed. The metadata
preflight and native inspectors below describe that baseline, not a current
post-upgrade health command. Do not auto-update them, replay a consumed operation
or reconstruct an executable mutation from an old receipt. No schedule,
retention deletion, generic framework or extra storage coverage is authorized.

**Live capture is disabled in the publication copy.** The post-execution watch
correction requires validated shared Pod/Deployment storage revision ordering;
numeric resourceVersion strings alone do not establish that contract. The live
adapter refuses pause with `pause-watch-ordering-unproven` before journal intent
or replica writes (WriterGuard currently reports the sanitized
`operation_failed`). There is no operational opt-out. Generated shared-revision
tests exercise conditional CAS-bound admission only; they are not K3s ordering
evidence. Do not patch out the refusal or relabel historical receipts as proof
for the corrected bytes. Separately reviewed future reuse is not part of this
publication.

### Staging capacity is not a hard quota

Capture byte budgets are archive admission checks, not enforced filesystem
ceilings. PostgreSQL finishes its dump before the size check and has no local
free-space admission in that fragment. ClickHouse and SeaweedFS check available
space first, but can still exceed their supplied budgets before final refusal.
SeaweedFS stages native copies and their outer archive on its original data
filesystem. Capacity analysis must therefore include transient coexistence and
source-serving headroom, not just final ciphertext size. Do not claim timeout or
post-write size checks prevent disk exhaustion. Any separately authorized reuse
needs independently established staging capacity or reviewed enforcement; this
publication does not replay or retrofit the historical operation.

## Metadata-only baseline

From the assigned task worktree:

```sh
mkdir -p verification/cache/langfuse-recovery
chmod 700 verification/cache/langfuse-recovery
python3 langfuse/recovery/preflight.py \
  --output "$PWD/verification/cache/langfuse-recovery/preflight-UNIQUE.json"
```

The output parent must already exist under this worktree's ignored cache. The
receipt is created exclusively with mode 0600; an existing file is never replaced.
The script uses configured kubectl and strict-host-checking SSH authentication,
and the fixed private HTTPS readiness endpoint with ordinary TLS verification.
It does not query Secret objects, logs, Pod environment or database contents.

Exit codes:

- `0`: the narrow metadata baseline passed.
- `2`: metadata was collected but one or more baseline checks failed.
- `1`: collection or receipt publication failed; no acceptance is established.

The baseline checks six Ready, initialized, non-deleting Pods with zero restarts,
current image/index identities, four original claim/volume bindings and sizes,
manual Synced/Healthy Application state without an active operation, the captured
server version, absence of namespace Jobs/CronJobs, and an unused proposed NAS
archive path. Unresolved platform-specific image IDs fail for explicit index
resolution rather than being assumed equal to a manifest-index digest.

The original-claim and captured-image baselines are intentionally fixed to the
first recovery plan. A legitimate future expansion, image change or additional
workload requires review, not automatic rewriting to match observed state.

Even exit 0 always records `recovery_accepted: false`. It does not establish
writer exclusion, queue/migration state, native backup integrity, encryption/key
custody, source/client idleness, placement/capacity reservation, stable-secret
recovery or a successful restore. Do not use it as a capture/rollout command.

Run its credential-free unit tests with:

```sh
python3 -m unittest discover -s verification/tests \
  -p test_langfuse_recovery_preflight.py -v
```

## Read-only production-native metadata and transport

```sh
python3 -B langfuse/recovery/inspect-native.py \
  --output "$PWD/verification/cache/langfuse-recovery/production-inventory/native-UNIQUE.json"
python3 -m unittest discover -s verification/tests \
  -p test_langfuse_recovery_native_inventory.py -v
```

Create the owner-only output parent first. This inspector launches bounded
read-only native clients inside the existing pinned workloads. PostgreSQL uses
its configured in-container environment with read-only SQL, statement/lock
timeouts and no local psql startup files. The exact ClickHouse client natively
consumes `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD`; no password is transferred to
the host or put in command arguments. The pinned source for that behavior is
[Client.cpp](https://github.com/ClickHouse/ClickHouse/blob/b47359294fe0f498ee19c5e31f18a9155b6dedae/programs/client/Client.cpp#L328-L334).

The Valkey server container has no configured client-credential environment.
The probe first requires an unauthenticated PING to be rejected. It then uses
the worker image's existing ioredis dependency and configured connection/password
internally, admitting only the known in-namespace destination. It issues PING,
INFO persistence, a narrow CONFIG GET and DBSIZE. No ACL/password file is opened,
no key names/contents are queried, and credentials/arbitrary errors are never
printed. A zero exit status or unauthenticated PONG is not authentication proof.

The inspector also streams generated bytes through configured strict-host-key
SSH to NAS `sha256sum`. This verifies an authenticated stream/hash round trip,
not filesystem permissions, encrypted archive publication, receiver isolation
or production restore. No NAS file is created.

Receipts contain only allowlisted scalar state and workload/code identities.
Exit 0 means collection/receipt publication succeeded, not that every component
passed: inspect each result. `capture_ready` and `recovery_accepted` remain false.
Workload drift, unexpected schemas/responses and unsupported authentication
paths fail closed. Counts are live observations, not a writer-quiescent snapshot.

## Read-only SeaweedFS topology admission

```sh
python3 -B langfuse/recovery/inspect-seaweed.py
python3 -m unittest discover -s verification/tests \
  -p test_langfuse_recovery_seaweed_inventory.py -v
```

This uses only pinned-source-backed read-only loopback master/volume status
endpoints through the configured pod's BusyBox wget. It cross-checks two stable
topology samples and refuses unknown/missing schema, inconsistent volume IDs and
unsupported EC/remote/replication/TTL/collection/disk/delete/compaction state.
Private exclusive receipts contain allowlisted counts, workload identity and a
policy hash, not raw topology, collection names or errors. A topology pass is not
an object inventory, writer-exclusion, IAM/system-identity or capture-readiness
pass. Preserve that boundary when adapting generated fixtures to production.

## Generated native datastore fixtures

```sh
python3 -B langfuse/recovery/fixture-pg-valkey.py
python3 -B langfuse/recovery/pg-valkey-tests.py
python3 -B langfuse/recovery/fixture-clickhouse.py
python3 -B langfuse/recovery/clickhouse-fixture-tests.py
python3 -B langfuse/recovery/fixture-seaweed.py
python3 -B langfuse/recovery/test_fixture_seaweed.py
```

Review each helper's supported platform, pinned images, resource limits and
CLI before execution. These native fixtures use generated data, anonymous public
OCI downloads and isolated rootless runtime state. They do not export production
data, consume existing credentials or mount production volumes. Preserve attempt
receipts, including failures. Acceptance is tied to the exact helper/shared-code
hashes and retained image/runtime artifacts, not an exit code alone.

The hardened SeaweedFS fixture keeps its metadata-loader stdin open while bounded
inventory, chunk and object readbacks are reconciled. It rejects corrupt/partial
exports and final-entry loss. Its generated local replication000 topology is not
a production topology adapter. Internal post-capture log volumes are explicitly
inventoried and excluded, not claimed recovered. Production topology/identity,
EC/remote storage, richer S3 policy and writer exclusion require additional proof.

## Generated encryption/archive fixture

```sh
python3 -B langfuse/recovery/fixture-encryption.py
python3 -m unittest discover -s verification/tests \
  -p test_langfuse_recovery_encryption.py -v
```

This generated-only Linux AMD64 fixture downloads checksum-pinned official age
1.3.2 binaries and runs them in private, network-isolated bubblewrap namespaces.
It has no external input/key/recipient arguments. It creates disposable synthetic
identities only in new ignored owner-only cache directories; it never reads an
existing operator identity or selects a production recipient. Do not reuse its
keys for production or treat them as a custody mechanism.

It verifies encryption/decryption, byte-identical archive recovery, complete
member inventory and rejects wrong identities, truncated/corrupted ciphertext,
incomplete plaintext archives and output overwrite. Failed decryption can emit
partial plaintext: fixture output stays explicitly incomplete and is never
published as accepted. Archive validation also rejects hidden trailing archives,
unexpected/duplicate members, links and oversized inputs. The helper does not
claim release-signature verification, production-key custody or full coordinated
recovery. Receipts bind the current fixture and downloaded executable hashes.

## PostgreSQL export command adapter

[postgres_exports.py](postgres_exports.py) constructs fixed database/custom-format
and globals/no-role-password stream commands bound to the original pinned Pod,
container, image and source UID. It never executes kubectl on import or build.
The guarded runner must separately verify source UID before/after exec (kubectl
exec has no UID precondition), writer exclusion, complete encrypted streaming,
private identity recovery and restore acceptance. Full DB exports contain
confidential application authentication/project records even when role passwords
are omitted from the separate globals stream. Do not run them as preflight probes.

The exact inner commands are exercised against generated SCRAM-authenticated
native PostgreSQL in a private rootless namespace, including complete custom
archive parsing, role restore, cold database restore and amcheck:

```sh
python3 -B langfuse/recovery/fixture-postgres-export.py
python3 -m unittest discover -s verification/tests \
  -p test_langfuse_postgres_exports.py -v
```

Missing native password configuration, wrong database and truncated archive are
negative cases. The generated plaintext fixture artifacts are not production
archives. Datastore role password/original identity recovery is deliberately
separate, not claimed by `--no-role-passwords`. A builder plus fixture is not a
production capture coordinator or proof that other stores' exports are ready.

## Capture primitives and writer-guard model

[capture_stream.py](capture_stream.py) implements encrypted local streaming and
exclusive FD-pinned publication, not a NAS receiver. It checks producer, encrypt,
decrypt and optional sink exits plus complete decrypted byte/hash equality before
publishing a `.complete.json` marker. Failed or interrupted attempts remain
explicitly incomplete. The caller must supply an independently trusted expected
native stream identity; a hash observed only after host ingestion is not an
independent source proof. Native archive parse/restore acceptance is separate.

Descriptor allowlists are per process (`producer_pass_fds`, `age_pass_fds`,
`decrypt_pass_fds`, `sink_pass_fds`); identity descriptors belong only in the
decrypt allowlist. Trusted argv must not contain credential literals. No common
descriptor allowlist may expose private custody inputs to producers or sinks.
Filesystem write/fsync calls need an external supervisor for hard IO deadlines.
An optional sink exit/hash does not prove remote durability or exclusive publish.

[writer_guard.py](writer_guard.py) implements an adapter-only state machine with
durable pre-mutation journal intents, exact resource/spec/UID/version binding,
write readbacks, fresh evidence challenges and a continuous writer-fence contract.
It pauses web before drain and worker, and resumes only explicitly after fresh
clean-migration evidence. Unknown outcomes/concurrent drift require manual
recovery, never automatic retry/rollback. The state machine itself has no CLI;
the separately reviewed one-time operational callers are described below.
Sampled metadata cannot stand in for the required gap-free fence or client-idle
evidence. `RESUMED` means replica restoration, not application readiness.

```sh
python3 -B -m unittest discover -s verification/tests -p test_langfuse_capture_stream.py -v
python3 -B -m unittest discover -s verification/tests -p test_langfuse_writer_guard.py -v
```

## One-time operational modules

- [first_live_adapter.py](first_live_adapter.py) supplies the fixed Kubernetes/NAS
  adapter and writer-watch machinery for the original capture. These are live
  operations, not generated fixtures or an automatically safe health command.
- [first_capture.py](first_capture.py),
  [first_object_capture.py](first_object_capture.py) and
  [first_valkey_capture.py](first_valkey_capture.py) compose guarded native exports,
  private staging, encrypted streams and separate final NAS publication/readback.
  Keep primitive local-completion receipts distinct from later coordinator remote
  durability evidence; never rewrite historical flags to match a later stage.
- [first_restore.py](first_restore.py) validates the original isolated resource
  bundle, identities, authenticated archives, native state and startup gates.
  Its primitive native result deliberately leaves application-level
  `recovery_accepted` false. Operator login/old-trace evidence and actual new
  application ingestion/readback are additional acceptance, not implied by Pod
  readiness, an archive hash or a native restore return code.

The one-time execution drivers and private operation inputs are not a reusable
public CLI. New execution is not authorized by importing these modules or by
the historical accepted operation. Post-execution publication fixes have only
their stated local regression proof; do not attach old live receipts to new
helper hashes. Native opt-in tests depend on retained historical cache artifacts
and are not clean-checkout native CI. Preserve missing/failed evidence as such.

The generated native-age streaming class additionally requires Linux AMD64,
`/usr/bin/bwrap` and memfd support. It explicitly skips before tool downloads or
key generation when those prerequisites are absent, rather than dropping its
sandbox. A clean CI run with such skips is not native-age execution proof; retain
the separate local generated-native results and actual skip reasons.

## Read-only queue/transaction drain sample

```sh
python3 -B langfuse/recovery/inspect-drain.py
python3 -B -m unittest discover -s verification/tests -p test_langfuse_recovery_drain.py -v
```

The installed queue registry/BullMQ code and dependency trees are hash-checked.
The probe uses aggregate-only `EVAL_RO`, not BullMQ's `getCounts` API: the pinned
getCounts Lua can remove legacy markers. No job payloads or queue/key names are
emitted. Future delayed and repeat/scheduler work conservatively block the sampled
queue-empty predicate. Do not clear jobs, disable schedules or silently exempt
recurring work to obtain a pass. The completed first capture/restore instead
preserved the source-verified registry, all eleven canonical counts and scoped
scheduler/job-content fingerprint, then reconciled them before target app startup.
That approved policy is implemented by the one-time modules above, not by
filtering delayed work out of this older queue-empty inspector.
An empty PostgreSQL or queue sample never proves client idleness/writer exclusion.

## Confidentiality prerequisite

Before any real confidential export, an operator-selected public encryption
recipient and private restore-key custody mechanism must be available. Neither a
new disposable fixture key nor an existing unencrypted backup establishes that
prerequisite. Do not search private credential stores, generate a production key
without an agreed custody path, or fall back to plaintext to complete a run.

The operator's historical direction to proceed and the original private inputs
do not authorize a fresh capture/restore today or turn failed/unexecuted tests
into passing evidence. Keep production running and stop a proposed new attempt
when its actual prerequisites or permission cannot be verified.
