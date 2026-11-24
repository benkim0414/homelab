# Langfuse recovery preparation — 2026-11-21

Status: **incomplete; generated native fixtures passed for all four stores;
confidential production capture and upgrades remain blocked**.
The operator directed completion of remaining Langfuse work without further
approval. This is task authorization, not evidence that the unselected encryption
recipient/private restore-key custody or recovery acceptance prerequisites exist.
No confidential export, production pause, credential retrieval/rotation, new
production volume, upgrade merge or live sync occurred in this preparation.

Source baseline: `260444e18662cf5519842fb1bb53ba7c1b8b771e`.
Task worktree: `.worktrees/homelab-scientist-complete-langfuse`.
Changes are local and uncommitted.

## Live baseline

The metadata-only [preflight helper](../langfuse/recovery/preflight.py) was actually
executed against configured Kubernetes/SSH authentication and the fixed HTTPS
readiness endpoint. Its final receipt is under the task worktree's ignored cache:
`verification/cache/langfuse-recovery/preflight-20261121-images-verified.json`.

- Application Synced/Healthy; manual sync policy; no active Application operation.
- All six Pods Running, Initialized and Ready; zero restarts; captured-version
  image/index identities matched.
- All four original claim UIDs, PV/CSI handles and sizes matched the
  [first-recovery plan](../langfuse/RECOVERY-FIRST.md). Claims had no owner references
  or deletion timestamps. Both StatefulSets reported Retain-on-scale/delete.
- All four production Longhorn volumes attached/healthy with two replicas.
- All six SealedSecrets reported Synced. Secret values were not queried.
- HTTPS readiness returned `OK`, version `4.77.0`; no namespace Jobs/CronJobs.
- All five nodes Ready with Memory/Disk/PIDPressure false at the sampled check.
- NAS configured writer UID/GID 1000/1000; `storage/k3s` mounted; available bytes
  188788805632. Existing dataset owner/group/mode remained `0:100:2755`.
  The proposed first-recovery destination was absent; no directory was provisioned.

An initial helper run rejected an incorrect expected Redis container name. The
expectation was corrected to the observed `langfuse-redis`, and subsequent
baseline/image checks passed. The initial failed receipt remains preserved.
This is not writer-exclusion, migration/queue, reserved-capacity or recovery proof.
Grafana alerts/Loki and an all-namespace cluster-health audit were not performed.

## Actually executed synthetic native recovery

The [fixture helper](../langfuse/recovery/fixture-pg-valkey.py) uses anonymous public
image downloads with index/platform/config/layer/diffID verification, private
rootless bubblewrap namespaces, a read-only normalized image tree and bounded
systemd user resource scopes. It does not start Langfuse or use production data,
credentials or entrypoints. See its docstring for runtime/ownership deviations.

Latest receipts matching the current helper's SHA-256 were independently read
back and their receipt hashes checked against their `verified.json` records:

- PostgreSQL 18: PASS, native fixture 11.622 seconds.
  `verification/cache/langfuse-recovery/pg-valkey/postgres/run-6e08bf7403484f71a1a293b4325d5424/receipt.json`
- Valkey 8.0: PASS, native fixture 0.466 seconds.
  `verification/cache/langfuse-recovery/pg-valkey/valkey/run-d39595a90b74441a95a3b4df9da3a4c4/receipt.json`

PostgreSQL covers a synthetic custom dump, globals/role ownership, full archive
parse, truncated-archive rejection, restore, schema/row/content reconciliation,
sequence continuation and `pg_amcheck`. Valkey covers a generated multipart AOF
checkpoint including base/incremental dependencies, native integrity checks,
corrupt-copy rejection and restored typed values/queue order/TTL.

Earlier attempts/receipts are preserved. These passes do not prove actual
Langfuse schema recovery, original authentication, encryption/decryption,
production-platform behavior, four-store consistency or owner login. Neither
ClickHouse nor SeaweedFS recovery acceptance is established by these receipts.

### Late worker evidence, independently checked

The separate PostgreSQL/Valkey fixture-safety suite was rerun by the parent:
8 tests passed, including archive traversal/link confinement, whiteout ordering,
cached digest corruption and symlink-cache rejection. These are additional to
the main unit suite, not part of its 204-test count. A worker-reported additional
invalid-scope execution probe did not execute because the approval gateway blocked
it; no result is claimed for that probe.

The ClickHouse/SeaweedFS worker was interrupted before task completion. It left
a source review at `verification/cache/langfuse-recovery/ch-seaweed-review.md`.
The parent read its diagnostic verifier and executed it against the retained
SeaweedFS receipt. Current verified state is
`ch-seaweed/run-1795234054546316295/`, not the earlier run named in that review.
Its seven source topology volume IDs matched seven exported volume pairs; a
38-byte object and a 3145739-byte, four-chunk object matched restored bytes, and
the chunk metadata matched. Six false-success error cases and metadata-only
restore failure were also asserted by that diagnostic verifier.

This is limited synthetic native SeaweedFS evidence, not complete service/S3
identity recovery or a production-ready importer. The review identifies a
metadata-loader final-entry completion hazard; a sleep-based fixture workaround
must not become a production completion protocol. The interrupted review and
diagnostic files remain ignored cache artifacts, not production capture tooling.
ClickHouse native runtime/backup/restore remains unexecuted.

## Local validation

- Metadata preflight unit tests: 10 passed.
- Full unit suite with checksum-verified public Langfuse delegate source:
  204 tests run, 6 skipped (promtool unavailable, four browser-image aiohttp cases,
  and already-committed Immich cutover).
- Conftest: 5 passed.
- Full verifier: 21 Applications, 520 resources passed.
- `git diff --check` passed.

An earlier full scan rejected a bare public OCI digest in the fixture helper as
`generic-api-key`. The helper now uses full public image references; the complete
verifier then passed. No scanner exception or policy weakening was introduced.

## Concrete remaining blocker and dependent work

### Resumed independent preparation

The operator subsequently directed continuation of the standing goal. The missing
production encryption inputs block confidential capture, not independent native
fixture/tooling work. ClickHouse and hardened SeaweedFS preparation were resumed
as separate bounded workstreams; their results require independent verification
before this report can claim those gates passed.

The generated-only [age encryption fixture](../langfuse/recovery/fixture-encryption.py)
was implemented and actually executed using official age v1.3.2 binaries verified
against the public release-asset SHA-256. It passed an offline synthetic round
trip with byte-identical archive recovery and rejected wrong identity, truncated
and corrupted ciphertext, incomplete plaintext archive and existing-output
overwrite. Eight dedicated unit tests also passed, including hidden trailing
archive/member/link and private-publication rejection.

Receipt:
`verification/cache/langfuse-recovery/encryption/run-a2bc802632944006900947e2f4a507f0/receipt.json`.
The parent independently compared its helper hash and source/restored archive
hashes. These are disposable fixture keys, not a selected production recipient
or proof of private production-key custody. No existing key store was read.

A fresh metadata baseline receipt also passed:
`verification/cache/langfuse-recovery/preflight-resumed-20261121.json`.

Resumed full validation after adding the encryption fixture passed: 212 unit
tests run, the same 6 skips, 5 conftest tests, and 21 Applications / 520 resources
through the complete verifier. `git diff --check` passed. These results precede
the final ClickHouse/SeaweedFS workstream changes and must be rerun afterward.

### Completed resumed native fixtures

The later completed work supersedes the earlier source-only ClickHouse and
sleep-based SeaweedFS diagnostic status above. Both remain AMD64 generated-only
fixtures, not production recovery adapters or full Langfuse acceptance.

- ClickHouse 26.8.36.3: native `BACKUP_CREATED` followed by cold `RESTORED` into
  fresh state with only the native archive mounted read-only. Atomic engine,
  table/view DDL, 1000 rows, 1000 view results, two migration-shaped records and
  latest `42/dirty=0` matched. Relative allowed-path resolution, disallowed relative
  and absolute paths, disallowed Disk, existing destination and truncated archive
  errors were exercised. Receipt:
  `verification/cache/langfuse-recovery/clickhouse/run-32bc69bb38ea49f59a0386de6582be21/receipt.json`.
- SeaweedFS 4.23 hardened fixture: loader stdin remains open until bounded,
  independent metadata/chunk/object reconciliation succeeds, without relying on
  a fixed sleep. Both generated objects and four-chunk content survived restore
  and cold restart. Seven capture-point volumes / 21 volume files and five indexed
  needles were reconciled. Truncated metadata, corrupt metadata, missing volume,
  native rc0 failed export, partial export and valid-gzip final-entry loss all
  failed closed. Receipt:
  `verification/cache/langfuse-recovery/seaweed-hardened/run-1795250788733476819/receipt.json`.

The parent independently rehashed every retained artifact: 136 for ClickHouse,
644 for SeaweedFS, and checked current helper/shared-code hashes against the
receipts. The separate five ClickHouse and seven SeaweedFS unit tests passed.
Post-workstream full validation passed again: 212 main-suite tests run / 6 skips,
5 conftest tests, full verifier 21 Applications / 520 resources, diff whitespace.
The 12 separate fixture tests are not part of the 212-test count.

SeaweedFS's source shutdown created internal log volume 8 after the capture point;
it is recorded and excluded explicitly, not silently treated as restored. System
log identity recovery is unproven. General production topology/collections,
EC/remote/chunk manifests, TTL/deletes/compaction, S3 versioning/IAM/policy,
authenticated transport and full identity restoration remain outside this
fixture. Unsupported state must cause refusal, not a broadened production claim.
No production-platform ARM64 execution or writer-exclusion proof was added.

### Production-native read-only adapter preparation

Implemented and executed [inspect-native.py](../langfuse/recovery/inspect-native.py)
and its [worker client probe](../langfuse/recovery/inspect-valkey.js). The current
receipt is `verification/cache/langfuse-recovery/production-inventory/native-and-transport-20261121.json`.
Its Python/JavaScript helper hashes were independently compared with current
files. Native clients consumed already configured credentials internally; no
Secret value, ACL/password file, key name/content or arbitrary raw error was
read out or saved.

- PostgreSQL configured loopback native authentication passed with read-only SQL,
  statement/lock timeouts and startup files disabled. Observed version_num 180007,
  expected application DB, not in recovery, 470 migration records and zero
  unfinished/unrolled-back migrations. This does not compare the image migration
  file inventory or prove database backup/restore authentication.
- ClickHouse's pinned Client.cpp was inspected to verify native configured
  `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` consumption before invocation. Read-only
  native authentication passed as the expected user, version 26.8.36.3, latest
  migration 56 / dirty 0. Historical dirty transitions were not treated as current.
- Valkey's server-container client has no configured credential environment;
  unauthenticated PING correctly returned NOAUTH. No credential was extracted
  from ACL/Secret files to work around that. Instead the pinned worker's existing
  ioredis dependency consumed its configured Redis destination/password internally.
  Fixed-destination validation, authenticated PING, narrow INFO/CONFIG GET and
  DBSIZE passed. AOF was enabled, native layout matched, no loading/rewrite was
  active, last rewrite/write statuses were good, and 234 DB keys were observed.
  This is not queue emptiness or a writer-quiescent checkpoint.
- A generated 1048576-byte stream traversed configured strict-host-key SSH to NAS
  sha256sum and matched locally. No NAS file was created. This proves the sampled
  authenticated stream, not private receiver permissions, archive publication,
  encrypted transfer acceptance or restore.

Nine dedicated native-inspection tests passed, including destination/auth/schema
refusals, duplicate/unknown output rejection and private diagnostics. Full local
validation at this point passed 239 main-suite tests / 6 skips, 5 conftest tests,
and 21 Applications / 520 resources. The concurrent SeaweedFS topology-inspector
workstream still requires its final independent receipt review.

The completed [SeaweedFS topology inspector](../langfuse/recovery/inspect-seaweed.py)
was subsequently independently reviewed. All 18 dedicated tests passed again;
the parent read the final private receipt, checked mode 0600 and matched its
helper hash with the current script. The actual read-only loopback master and
volume endpoints cross-checked two stable samples: 14 normal volumes, 2 supported
collections, 1 node, zero EC shards and remote volumes. Narrow pinned-schema
topology admission passed. Receipt:
`verification/cache/langfuse-recovery/production-inventory/seaweed-topology-d3824b2347b7498c84f6dc515f4d4c82.json`.

Unknown/missing schema, contradictory inventories and unsupported policy/state
are refused. A corrected intermediate HTTP-version-format rejection remains
historical; it is not the current result. Raw topology/collection names/errors
were not persisted. The 14 production volumes are not assumed equivalent to the
synthetic fixture's 7-volume inventory. This verifies neither object/chunk
inventory nor system-log/S3 identity, capture quiescence or recovery readiness.
Production export/encrypted-publish/stop-resume implementations remain separate
work; these read-only inspectors do not implement those operations.

### Capture implementation in progress

The operator directed continuation of the full capture implementation. The
[PostgreSQL producer adapter](../langfuse/recovery/postgres_exports.py) now builds
fixed, source-bound native custom-dump and globals/no-role-password commands.
It performs no production exec on import/build. Source UID must be rechecked by
the eventual runner because kubectl exec itself has no UID precondition.

The exact native inner commands passed a new generated SCRAM-authenticated
[export/restore fixture](../langfuse/recovery/fixture-postgres-export.py), including
complete custom archive parse, globals restore, cold database restore of 1000
rows and content digest, and native amcheck. Missing configured authentication,
wrong DB and truncated custom archive were rejected. The initial generated
attempt failed because amcheck was not installed in the fresh restored fixture;
the positive fixture explicitly installs it in generated restored state only.
That failed attempt remains preserved. No production mutation was performed.

Current verified native receipt:
`verification/cache/langfuse-recovery/postgres-export/run-503d1e2f504f47c2b74c956a30ae678c/verified.json`.
The parent independently rehashed all 2582 retained artifacts and current
producer/helper/shared-code hashes. Native duration was 13.318 seconds, excluding
image preparation. Five producer-admission unit tests passed. Role passwords are
not included; the full DB stream still contains confidential application auth
and project records and must never be treated as nonsecret.

Encrypted stream/publication, bounded writer guards and a source-grounded queue
drain inspector are separate active workstreams. They require final integration
and independent evidence review before any production-capture readiness claim.
Interim full local validation passed 324 main-suite tests / 6 skips, 5 conftest
tests, 21 Applications / 520 resources and diff whitespace; rerun after the active
workstreams finalize. No production capture command was executed.

### Completed primitive work and new live drain blocker

The three bounded component workstreams completed; they are not a complete
production runner:

- Encrypted local stream/publication primitive implemented, with full producer,
  encrypt/decrypt/sink result checks, no-overwrite FD publication and retained
  incomplete receipts. Parent review found a shared descriptor allowlist could
  expose an identity FD to unrelated children; it was replaced by per-process
  descriptor policies. Zero-progress writes now fail closed and directory privacy
  is rechecked before publication. All 29 native generated age tests passed,
  including new FD isolation and zero-progress/privacy-drift tests. Current
  standalone suite receipt:
  `verification/cache/langfuse-recovery/encryption/capture-tests-a78cb07bdb5f482e958fe60a2a92cecc/suite-receipt.json`.
  No NAS receiver, remote durable publication, independent native producer stream
  identity adapter or production key-custody integration was established.
- Writer guard state machine implemented and independently rerun: 40 synthetic
  tests passed. It journals before mutations, requires fresh bound evidence and
  CAS/readback contracts, and treats unknown outcomes/concurrent drift as manual
  recovery. Production Kubernetes adapter, cross-process authorization replay
  protection and gap-free actual writer fence are not implemented by its model.
  No production mutation occurred, and no automatic resume/retry was enabled.
- Source-grounded queue/transaction probe implemented and rerun against live
  configured native authentication. The parent inspected the code first. At
  `2026-11-21T09:51:34.282347+00:00`, 46 queues had 6 delayed jobs, 6 repeat/scheduler
  entries and 23 retained failures. Other reported pending/active states were
  zero. The queue-empty prerequisite **failed**, not passed. PostgreSQL had zero
  non-probe in-flight/active/idle/unknown/prepared transactions at that sample,
  with statistics visibility verified. No job payloads were inspected or jobs
  cleared; source hashes and only aggregate counts were reported.

The pinned BullMQ getCounts Lua can RPOP legacy markers; the probe instead uses
aggregate-only EVAL_RO and rejects unknown namespaces/types/configuration. Fifteen
drain-probe tests passed. Recurring work needs an explicitly reviewed disposition
or preserved-and-reconciled checkpoint policy; do not disable schedules, clear
queues or silently relax the empty predicate. A sample never proves ongoing
writer exclusion or desktop/cluster client idleness.

Final local validation after parent fixes passed: 328 main-suite tests run,
6 skipped, 5 conftest tests, full verifier 21 Applications / 520 resources and
`git diff --check`. Production capture remains blocked by missing recipient /
custody / private original-identity restore inputs, the unresolved scheduled-work
disposition, and the production integration still listed above.

### Five-step scope: key, destination and one-time NAS method verification

After the operator explicitly requested key generation, a new private local age
identity was created with exclusive no-overwrite semantics and verified mode0600
inside an owner-only directory. Its private contents were not displayed, stored
in Git/memory, or uploaded. Public recipient:
`age143mh4l8ex4k8nqplyhdltsy5zwwvk9agpd7vmv0j4h488k8gwghqk7wft6`.
Native age was verified against the pinned official archive before use. The
public-recipient input is now resolved. Subsequently the operator reported the
private identity saved in Vaultwarden, following instructions for secure note
`Homelab — Langfuse recovery key`. Treat this as operator-confirmed custody, not
an agent readback of the note or proof of independent vault retrieval. No vault
credential or private-key contents were requested/read out. The original-Langfuse
identity restoration mechanism was selected explicitly in the subsequent
six-Secret authorization and verified snapshot below.

Within the existing destination step, created only the previously absent
`langfuse/recovery/first-20261120` components beneath `/storage/k3s` on NAS.
Each new directory is UID/GID1000/1000, mode0700. Separate readback as the configured
writer confirmed ownership, permissions and accessibility. Existing dataset
owner/group/mode remained0:100:2755; no export/dataset permissions were changed.

Executed one generated-data transport/recovery check using the new recipient.
Encrypted bytes were published exclusively via a held file descriptor and fsynced
on NAS, read back through a separate strict-host-key SSH request, decrypted
locally using the new identity, and fully parsed/reconciled against generated
archive contents. The remote completion receipt was separately read back. No
production data or private key was sent to NAS. The retained remote test directory
is `/storage/k3s/langfuse/recovery/first-20261120/transport-check-630d894601914471a599cf8fa5f1d08c`.
Local receipt:
`verification/cache/langfuse-recovery/transport-check-630d894601914471a599cf8fa5f1d08c/nas-method-verified.json`.
The private NAS directory now exists and contains this explicitly generated test;
the old preflight's absent-destination expectation is historical and must not be
reported as passing unchanged. No production-set completion marker was created.

Completed the planned native CPU/version compatibility proof for proposed restore
target k3s-02: Job `langfuse-recovery-cpu-check-20261121`, UID
`c06f4b51-c5c0-4004-a2a7-73dd6ce5aa29`, ran the exact pinned ClickHouse26.8.36.3
ARM64 image as UID/GID101, tokenless, with no data/Secret volumes and bounded
CPU/memory/runtime. Independent Job/Pod readback confirmed Succeeded, exit0,
zero restarts and version26.8.36.3 on k3s-02. This is binary CPU compatibility,
not server/restore readiness or a capacity reservation. The completed helper is
retained; no cleanup was performed. It is an expected additional completed Job,
not proof the old no-Jobs preflight expectation still passes.

Post-operation verification: Langfuse remained manual Synced/Healthy, readiness
OK/version4.77.0, all six original workload Pod UIDs unchanged and zero restarts,
and all four original claim UIDs/PV bindings unchanged and Bound. No writers were
paused, Secrets exported, jobs cleared, schedules altered or upgrades merged.

All remaining work stays within the operator's five steps: establish outstanding
original-identity inputs; finish the one-time capture procedure; preserve
or reconcile scheduled work; execute one coordinated backup/isolated restore;
then exact-image review, eligible PR merges and verified manual rollouts.

### Authorized original-identity snapshot: step 1 complete

After reporting the Vaultwarden key backup saved, the operator explicitly chose
`Authorize encrypted capture of only those six Secrets` through the clarification
form. Scope: namespace langfuse; langfuse-app-credentials, langfuse-bootstrap,
langfuse-clickhouse-auth, langfuse-postgresql-auth, langfuse-redis-auth and
langfuse-s3-auth. No unrelated Secret/controller key, rotation or plaintext output
was authorized or performed.

First exercised the exact private stream/validation path with generated values
and a missing-entry rejection. Then native kubectl output for exactly the six
named Secrets was piped directly into age encryption. No plaintext file/log/tool
output was created. Decryption and exact name/namespace/type/declared-key/base64
validation ran in bounded memory; source UID/resourceVersion metadata matched
before and after NAS publication. Only ciphertext went to the private NAS path.
After exclusive publication, ciphertext and its nonsecret receipt were fetched
through separate SSH readbacks and private native decryption/schema validation
passed again. The private encryption identity stayed on the workstation.

Remote component directory:
`/storage/k3s/langfuse/recovery/first-20261120/identity-20261121-bb5b26c1e5c64dd9be271473f8be74be`.
Local verified receipt:
`verification/cache/langfuse-recovery/identity-20261121-bb5b26c1e5c64dd9be271473f8be74be/verified.json`.
Generated-flow receipt:
`verification/cache/langfuse-recovery/identity-fixture-07e6c1163eba46f2ad87cea2c001ed21/verified.json`.

This establishes the private original-identity recovery source for step1; the
isolated restore will reconstruct only the required Opaque Secret type/data,
not replay production UID/resourceVersion/controller owner references. Actual
application/owner-login restoration remains step4 acceptance, not a claim from
private JSON validation. This is an identity-only snapshot, not a coordinated
four-store backup. Its identity versions must be revalidated at the coordinated
capture point. No workload was paused, job cleared or schedule changed.

Step1 is complete: public recipient and private NAS destination/writer verified,
Vaultwarden key custody operator-confirmed, and the explicitly authorized private
identity bundle encrypted/published/read back and validated. Steps2–5 remain the
same bounded capture procedure, scheduled-work preservation/reconciliation,
coordinated backup/isolated restore, then eligible PR merges/manual rollouts.
Never put private keys/passwords in chat. Production capture-adapter
coverage, measured capture timing, writer/client quieting, encrypted coordinated
capture, complete isolated restore and acceptance still must pass; generated
native fixtures alone do not close those gates.

PRs #106 (Valkey), #107 (PostgreSQL) and #111 (ClickHouse) remain held. Their green
CI and the four synthetic native passes are not a waiver of the recovery gates.
No backup schedule, retention policy or destructive cleanup has been enabled.

### Step 2: fixed first-capture preparation checked

The operator directed the next steps without scope expansion. The fixed
`langfuse/recovery/first_capture.py --prepare` phase was executed against the real
source, without pausing workloads or exporting database/object state. It verified
all six pinned workload identities, original claims/PVs, healthy two-replica
Longhorn volumes, retained StatefulSet claims, manual healthy Application and
absence of unreviewed namespace workloads. The exact retained CPU-probe Job/Pod
is explicitly identified, not broadly exempted.

Fresh checks compared the complete literal set of 470 Prisma migration directory
names in the running web image against applied DB records; all matched, with zero
unfinished migrations and zero rows affected by the startup cleanup. Literal
delivered names include spaces/mixed case/hyphens/.sql suffixes and were preserved,
not normalized into an assumed naming convention. All 56 delivered unclustered
ClickHouse migrations matched latest version56/dirty0.

Both exact web/worker pause patches passed API-server dry-run using UID,
resourceVersion and replica-count tests. Dry-run responses changed only replicas;
separate reads proved the real resources/versions/specs unchanged. This is not an
actual pause or a writer fence. Current private receipt:
`verification/cache/langfuse-recovery/first-prepare-eb35a86c3e3644feb61c6258c1c070ee/prepared.json`.
Failed initial preparation attempts are retained. Local full verifier passed
21 Applications / 520 resources and diff whitespace. Capture execution is still
disabled pending reviewed native sections and the bounded client-idle window;
there is no production execution entrypoint or readiness claim yet.

### Step 2: live nonroot Valkey access verified

After renewed operator execution approval, the fixed read-only helper was
admitted on `k3s-03` using the pinned Valkey image, UID/GID1000, no fsGroup,
no service-account token, dropped capabilities and a read-only root filesystem.
The original Valkey claim was mounted read-only at `/data`; private scratch was
created by the nonroot process at `/scratch/capture`, mode0700. No source ownership
or permissions were changed. Authentication used only the reviewed SecretKeyRef
`langfuse-redis-auth/default` through native `REDISCLI_AUTH`.

Initial single-shot checks failed. The classified diagnostic identified
`connection_refused`, not a demonstrated password error. The existing worker's
configured authenticated read-only probe separately passed. A bounded readiness
check then observed one connection refusal, waited three seconds, and succeeded
on its second PING. It subsequently verified native server 8.0.12 and enabled AOF,
and emitted `VALKEY_HELPER_READONLY_OK`. This establishes transient initial
connectivity and successful later native access; it does not identify the exact
CNI/proxy cause. Establish helper connectivity before any production writer pause;
do not retry authentication/ACL failures or weaken policies.

Retained Job/Pod identities (all on `k3s-03`, zero Pod restarts):

| Job | Job UID | Pod UID | Outcome |
| --- | --- | --- | --- |
| `langfuse-first-valkey-access-20261121` | `4119e51f-e5eb-44db-b885-6c2a62ca0a45` | `43b9f5b2-85a1-45d7-8b89-7a7a3a15b540` | Failed, exit1 |
| `langfuse-valkey-access-diagnostic-20261121` | `2a21f125-b298-4d4c-9522-da63fba0417b` | `4f8d3dee-ab25-4754-aad8-00f6f6a0f2ff` | Failed, exit1 at PING |
| `langfuse-valkey-ping-reason-20261121` | `8b4c1e1e-bb30-4ef3-ba45-d417173a38fd` | `47c018df-cc34-40b9-8e40-a4282a0b5d45` | Failed, exit1, connection refused |
| `langfuse-valkey-network-ready-20261121` | `38847381-59fa-4f35-9578-4145007174d8` | `a3fc7f72-0868-46e2-b9d0-923938e2d25b` | Succeeded, exit0 |

These are explicit retained diagnostic artifacts, not a broad exemption for
additional namespace workloads. The old CPU-probe-only preparation inventory
requires an exact-identity update before reuse. No Job or failed artifact was
deleted, and no schedule or retention policy was enabled.

After the successful helper, separate live readback verified all six original
production Pod UIDs unchanged, Running/Ready with zero restarts; all four original
PVC/PV bindings remained unchanged and Bound. The Application was Synced/Healthy;
HTTPS readiness returned OK/version4.77.0. No production writer was paused, no
coordinated datastore export was performed, and no isolated restore was deployed.

The completed generated SeaweedFS application/S3 proof supersedes the blanket
internal-log-history concern: its current-code archive validator independently
accepted 14 volumes, all 42 native volume files and 10 application metadata entries
in an 80,896-byte generated archive. The scoped single-LevelDB2-filer recovery does
not claim historical change-log replay. All source volumes and real application
metadata/identity remain mandatory. This remains generated recovery evidence,
not acceptance of production capture or a full Langfuse restore.

### Steps 2–4 continuation: coordinator, transport and live admission evidence

The parent independently reran the fixed coordinator suite (16 tests), fixed
restore suite (20 tests) and existing writer-guard suite (40 tests); all passed.
The full local verifier also passed 21 Applications / 520 resources and
`git diff --check`. Coordinator tests exercise actual age encryption and local
receiver publication, but use synthetic native-validation/fence adapters; they
do not authorize a production pause. Production adapter and full native-parser
integration remain under implementation. The restore bundle is preparation,
not an executed restore; regenerate from final code rather than using the
earlier cached bundle that predates identity-schema corrections.

Normal configured kubectl authentication was actually exercised in a child with
only the normal HOME and fixed `/usr/bin:/bin` PATH, returning the exact original
Valkey Pod UID. No kubeconfig/credential contents were inspected. This verifies
the proposed explicit environment wrapper for capture_stream's empty-env child;
an empty environment alone is not assumed to retain configured authentication.

The coordinator's actual NAS receiver and separate SSH-readback path were tested
against the approved NAS destination using only generated data encrypted to the
already selected public recipient. Official age package/executable checks passed.
Exclusive publication, file/directory fsync and independently authenticated
readback matched all 606552 ciphertext bytes and SHA-256. Retained remote probe:
`/storage/k3s/langfuse/recovery/first-20261120/method-probe-fc05a47000f04618b0724a89277a83be.age`.
Local receipt:
`verification/cache/langfuse-recovery/nas-coordinator-check-fc05a47000f04618b0724a89277a83be/verified.json`.
No production data or private decryption key was used in this method test.
No coordinated-capture or recovery-acceptance marker was created.

Fresh request accounting included regular containers, ordered restartable init
sidecars, init peaks, Pod-level requests and overhead. Observed headroom:

| Node | CPU request headroom | Memory request headroom | Live memory usage |
| --- | --- | --- | --- |
| k3s-01 | 2980m | 5856.3125Mi | 4566Mi / 62% |
| k3s-02 | 3025m | 5538.3125Mi | 5887Mi / 80% |
| k3s-03 | 2702m | 4649.3125Mi | 6076Mi / 83% |
| k3s-04 | 2330m | 3052.3125Mi | 4239Mi / 58% |
| k3s-05 | 920m | 5485.24609375Mi | 7608Mi / 49% |

All Longhorn disks reported Ready/Schedulable with scheduling enabled; no space
was reserved. Requests fitting is not live RAM/capture/restore acceptance:
the proposed k3s-02 ClickHouse placement requires review against its current
runtime headroom. No unrelated workload was moved/resized and no restore limits
were reduced to force admission. Current original store working sets were
ClickHouse 622Mi, PostgreSQL 64Mi, Valkey 14Mi and SeaweedFS 44Mi; web 759Mi and
worker 483Mi. These samples are not startup peak bounds.

The read-only queue/transaction probe at `2026-11-22T00:16:14.712673+00:00`
admitted 46 source-verified queues. Active/wait/prioritized/paused/stalled/
waiting-children and paused-queue counts were zero; delayed 6, repeat 6 and
failed 23 remained. PostgreSQL active/inflight/idle-in-transaction/unknown/prepared
counts were zero. Preserve and reconcile the scheduled/retained state; do not
clear jobs or require delayed/repeat/failed counts to become zero. This is sampled
prerequisite evidence, not a continuous writer fence or client-idle confirmation.
No production writer pause, coordinated export, or isolated restore has occurred.

### Step 4: final generated native startup/transport evidence verified

The completed fixed restore runtime now includes authenticated private decryption
before upload, exact target UID/image/new-volume checks, independent uploaded
size/hash verification, native startup, migration/queue reconciliation, and
Seaweed application metadata plus authenticated S3-byte reconciliation while the
loader is held and again after cold restart. This is implementation evidence,
not a production restore acceptance claim.

The parent reran the current restore suite: 31 tests discovered, five explicitly
native cases skipped in that default invocation, no failures. The five native
cases were separately executed by the worker in bounded generated-only fixtures.
The parent independently found each PASS receipt, confirmed synthetic-only scope
and matched its restore-code SHA-256 to the current helper:

- PostgreSQL: `first-restore-native-postgres-8d6053b3a2cc45adb0f03371790b025f/verified.json`
- Valkey: `first-restore-native-valkey-ecddd93243454e4bb2823c290e5b2edf/verified.json`
- ClickHouse: `first-restore-native-clickhouse-7e3b4fedf9374c278587faee29c6c18b/verified.json`
- SeaweedFS/S3: `first-restore-native-seaweedfs-f6cd40fabf764455a05423d7b800c5b5/verified.json`
- Authenticated age transport: `first-restore-native-transport-2dcc54ba964f4d2d8cd4dcddba04e04f/verified.json`

All receipt paths above are relative to `verification/cache/langfuse-recovery/`.
Generated PostgreSQL testing includes actual restore/startup, correct-password
connection, wrong-password rejection and HBA parsing. The fixed original
langfuse-role/database SCRAM rule permits only the web/worker node Pod CIDR;
the parent independently verified live `k3s-05` still declares `10.42.4.0/24`.
Application PostgreSQL/Redis URL construction is encoding-tested with generated
credentials, not a literal redaction placeholder or exposed operator credentials.

The corrected bundle is
`verification/cache/langfuse-recovery/first-restore-reviewed-20261122-r2.json`.
The parent checked its current helper/dependency hashes and exactly 25 resources;
the worker's strict Kubeconform check accepted all 25. Do not use the stale earlier
bundle. Deployed and recovery-accepted remain false.

Fresh live memory samples still do not accept the proposed restore placement:
k3s-02 used 5761Mi / 78%, and k3s-03 used 6375Mi / 87%. Capacity remains explicitly
unaccepted; request fit and generated AMD64 native passes are not full ARM64
startup/capture/restore capacity proof. All six original production Pod UIDs
remained unchanged, Running/Ready with zero restarts. No target namespace/claim
was created, no production writer was paused and no upgrade was performed.

### Step 2: real list/watch admission fault corrected before any pause

The final fixed live adapter/coordinator wiring passed parent reruns of the
capture, writer-guard and restore suites. A fresh actual `--prepare` admitted
source/storage identities and clean migrations, including 470 PostgreSQL image
migrations, zero unfinished migrations/startup-cleanup rows, and ClickHouse
migration 56/not dirty. Both replica-patch server dry runs passed without changing
replicas. Its receipt is
`verification/cache/langfuse-recovery/first-prepare-8fb70b9162b941ed81bca8fe0145d010/prepared.json`;
it predates the following code correction and is not a reusable execution approval.

Actual read-only watch admission then correctly refused before any writer pause.
The approved classified diagnostic established that its first event was ADDED
for an already-listed Pod, not an authentication failure or a bookmark timeout.
The ordinary kubectl list projection had an empty list resourceVersion: the
generic CLI List printer had discarded the server PodList RV, so the watch was
unintentionally requesting an initial snapshot instead of the exact earlier RV.

`first_capture.get('pods','')` now reads the fixed raw namespaced PodList API and
requires a complete PodList with a positive numeric RV. Missing/empty/zero RVs,
generic Lists and continuation pages refuse before a watch. ADDED-event rejection
was not weakened. Two focused regression tests cover the real boundary; all
40 current capture tests passed.

The actual corrected PodWatch transport was then exercised read-only against the
live API, including a later list/progress barrier. It passed with two progress
events: initial bookmark 61.023 seconds, total observation 121.075 seconds, unchanged
source UIDs and zero replica mutations. This verifies actual API transport/progress,
not a completed production writer fence or confidential capture.

The prepared one-shot helper manifest is
`verification/cache/langfuse-recovery/first-live-helper-4e244d4883544258b33b4ca708edf34c.json`.
It passed shell syntax and server-side dry-run admission but was NOT created.
Its bounded Job lease of 2100 seconds covers preparation/watch progress plus the
unchanged maximum 1800-second capture limit; the old 175-second sleep
would not cover the observed watch overhead. UID/GID1000, no fsGroup/token/init,
native SecretKeyRef, original PVC read-only, dropped capabilities, read-only root
filesystem and bounded private scratch are unchanged. Native Valkey checkpoint
pause/copy bounds were not extended. No operator quiet-window confirmation has
yet been consumed and no production pause has occurred.

The whole-repository verifier against newly advanced `origin/main` refused an
unrelated career-advisor PVC removal: this task checkout is still at 260444e,
while origin/main advanced to b6a3107 outside this task. Langfuse manifests and its
Application have no tracked differences between those revisions. Verification
against the task's explicit base 260444e passed 21 Applications/520 resources;
`git diff --check` passed. No unrelated app, storage policy, branch or worktree was
changed to suppress the newer-base failure.

### Existing step 4 placement revised; production eviction independently confirmed

Read-only capacity review found a sampled fit by changing only isolated restore
placement: ClickHouse on k3s-04 and SeaweedFS on k3s-01, retaining PostgreSQL01,
Valkey03 and web/worker05. Every original resource request/limit remains unchanged;
no production placement or unrelated workload was changed. Parent independently
recomputed scheduler requests (including init peaks and allocated-resource status),
runtime margins and ephemeral budgets from the retained measurements. The curated
receipt is `verification/cache/langfuse-recovery/placement-reviewed-20261122-r3.json`.
After added requests and an additional 512Mi runtime cushion, sampled margins were
1153.25Mi/980.96875Mi/122.21875Mi/293.15625Mi/5070.359375Mi on nodes01–05.
This is observational request-fit evidence, not reserved capacity, proof that all
limits can be consumed simultaneously, or acceptance of actual replica bindings.
The proposed two-replica disk allocation remains a feasibility witness; actual
four-new-claim/PV/Longhorn identities and two healthy replicas must be read back
before native restore startup. No target resources have been created.

During this discovery Kubernetes evicted original ClickHouse Pod
`9bccf7f8-48bd-4559-abb4-367acabe48b7`: the event states
`Usage of EmptyDir volume "logs" exceeds the limit "512Mi".` The parent independently
read back that event and the Ready replacement UID
`42d6c841-e51c-4dd3-a08d-f3bd44a3b157`. The original ClickHouse claim/PV and all four
claim identities remained unchanged/Bound; readiness returned OK/version4.77.0,
and Argo reported Synced/Healthy. Zero replacement-container restarts did not mean
unchanged Pod identity. No capture was running and no eviction/restart/log cleanup
was initiated by this task. Replacement log-directory usage was sampled at1636KiB;
no logging fix, limit increase or production rollout was applied.

The old Pod snapshot is invalid. A new read-only preparation on the replacement
passed exact source/storage/migration checks and both replica-patch server dry
runs, with no replica changes:
`verification/cache/langfuse-recovery/first-prepare-a0fdfac78f8e4a6894361ff635cc47f5/prepared.json`.
Any execution must refresh against that new identity rather than reuse an old
writer-fence snapshot. This is no claim of historical-data/application recovery.

Current native restore code, including the placement-only revision, was exercised
again using the existing generated fixtures. Initial mixed-scope execution
retained two failures: ClickHouse correctly refused the inappropriate1Gi scope,
and Seaweed's generated shell operation failed in that96-task scope. No guard was
weakened. Rerunning each affected case under its existing reviewed engine scope
(ClickHouse4Gi/2CPU/256tasks; Seaweed1Gi/1CPU/128tasks) passed. PostgreSQL, Valkey and
authenticated age transport passed in their existing1Gi/1CPU/96task scope.
All five PASS receipts were independently matched to the current restore hash:

- `first-restore-native-postgres-36fefcbe40ea495bb0adc4b206bbf7df/verified.json`
- `first-restore-native-valkey-f4ea88a9f0d04a8b92d5adb745b1ca09/verified.json`
- `first-restore-native-clickhouse-933c63e603c84437a442846ff13acc27/verified.json`
- `first-restore-native-seaweedfs-86742f6c296c4f2f8e520736f1a4e16d/verified.json`
- `first-restore-native-transport-285ad97a37a0494bb19e913810f0485e/verified.json`

Paths above are relative to `verification/cache/langfuse-recovery/`. These remain
AMD64 generated native-method evidence, not full live ARM64 Langfuse acceptance.
The regenerated bundle
`verification/cache/langfuse-recovery/first-restore-reviewed-20261122-r3.json`
matches current code and all25 resources passed the repository's strict schema
validator. r2 is now stale. A new regression protects the revised restore-only
placement and unchanged production-equivalent resource budgets.

The operator quiet-window and private owner-login availability questions timed
out unanswered. That is not consent or client-idle evidence. Production remains
running; the prepared capture helper was not created, no writer was paused, no
coordinated production backup was attempted and no isolated restore was deployed.

### Operator-confirmed window: capture refused before writer changes

The operator confirmed item1 (other clients idle) at the window starting
`2026-11-22T16:42:11+11:00`, bounded until17:12:11. Owner-login availability was
not confirmed. Fresh preparation passed. The reviewed read-only helper was created:
Job `langfuse-first-capture-4e244d488354`, UID`4a7a54bd-b89d-42cb-bcd0-4d6a5a2b4747`;
Pod `langfuse-first-capture-4e244d488354-4wdfn`, UID`affb9358-21f1-4797-98d5-fe2fb6a77e9e`.
It has the bounded lease, original claim read-only and private scratch; it is
retained rather than deleted. No source data/permissions/authentication changed.

The first launch refused an incorrectly shaped request before reserving an
operation. Correcting inputs exposed two builder/live-manifest mismatches:
the reviewed helper's actual name/container differed from the original builder's
fixed form, and PostgreSQL's actual `docker.io/postgres` reference differed from
the unqualified fixture reference despite the identical pinned digest. The builder
now admits only the two explicit reviewed helper forms, retaining all UID/image/
Job/auth/mount checks and actual names. PostgreSQL explicitly admits the observed
fully qualified pinned reference and preserves it in source evidence; no source
identifier was rewritten. All40 capture tests and five PostgreSQL builder tests
passed, including the live-shaped input regressions.

The corrected request is
`verification/cache/langfuse-recovery/first-window-inputs-4e244d4883544258b33b4ca708edf34c/request-r2.json`.
The next launch reserved operation
`verification/cache/langfuse-recovery/first-live-first-4e244d4883544258b33b4ca708edf34c/`
but exited during admission, before writing a reviewed plan or any writer-guard
journal event. Only an empty operation.jsonl was present. No guarded confidential
capture/export occurred and no coordinated marker was published. Do not replay
that reserved operation or infer its admission error from a generic CLI message.

The follow-up read-only admission diagnostic was blocked by a five-minute tool
approval timeout and did not run. No bypass/retry was attempted. Final independent
live readback at17:05:37 verified web/worker desired1/Ready1, Synced/Healthy and
HTTPS readiness OK/version4.77.0. Neither workload had been paused, so no resume
was necessary. The unused remainder of this client-idle window is released;
another capture requires a new explicit window and reviewed operation, not the
remaining expiry on these failed inputs. Steps2–4 remain incomplete.

### Approved read-only diagnosis: retained PVC-reference accounting corrected

After explicit renewed diagnostic approval, the actual Kubernetes metadata probe
confirmed four exact retained terminal diagnostic Pods still reference the
original Valkey claim. `diagnostic_pod()` correctly recognizes their pinned
UID/Job/phase/exit identities, but `volume_proofs()` tried to map those same Pods
through `_source()`, which correctly refused `unreviewed-pod`. The helper's
immutable security/auth-reference/read-only-mount admission passed independently.
Diagnostic receipt:
`verification/cache/langfuse-recovery/first-window-inputs-4e244d4883544258b33b4ca708edf34c/claim-reference-diagnostic.json`.
No private-key or Secret values were read, and no capture was retried.

A realistic low-level fixture retaining diagnostic PVC references reproduced
the exact `volume_proofs -> _source -> unreviewed-pod` failure before the fix.
Volume accounting now excludes only exact terminal artifacts validated by the
existing diagnostic classifier. Unknown terminal Pods, changed UID/Job/outcome
and unknown volume consumers still fail closed. Nothing is deleted or exempted
by label. The old completed capture helper's exact Job/Pod identities and exit0
were separately verified and recorded as a retained terminal artifact; it cannot
be reused as a new active capture helper.

Verification after the fix:43 capture tests and40 writer-guard tests passed;
the restore suite ran32 tests with its five explicit native cases skipped in
that default invocation, no failures. Full local verification passed21
Applications/520 resources against task base260444e, plus `git diff --check`.
The prior newer-origin/main comparison caveat remains; no unrelated PVC/policy
was altered. Fresh live read-only `--prepare` passed with clean migration checks
and both replica-patch server dry runs, without changing replicas:
`verification/cache/langfuse-recovery/first-prepare-77ee16a778b941968b03d28386faa12b/prepared.json`.
Web and worker were each desired1/Ready1, and HTTPS readiness returned OK/version4.77.0.

This fixes a confirmed admission bug, not a completed production backup. Full
live admission with a fresh bounded helper is still unproved. Do that read-only
before requesting another quiet window; the expired/released window and reserved
failed operation must not be reused. No new helper, pause, confidential capture,
restore deployment, commit or push occurred during this diagnostic/fix.

### Fresh bounded helper: actual read-only admission data path passed

The next operator-approved read-only check completed against real Kubernetes and
native configured clients, without requesting a quiet window. No WriterGuard or
capture approval was instantiated; replica mutation, capture-fence and evidence
entrypoints were explicitly disabled. The existing pre-mutation data checks were
run directly, without mocked Kubernetes responses or a fictitious client-idle
authorization. Receipt:
`verification/cache/langfuse-recovery/readonly-admission-47d6711e2ff94a4abed9cdca5dcc347e/result.json`.

READ_ONLY_ADMISSION_PASSED in 76.788 seconds: actual watch/progress, manual policy,
retained-artifact checks, original volume proofs, helper authentication, verified
queue registry/fingerprints, native idle interfaces, writer-controller ownership
and migration-image equality. Current consumers were PostgreSQL1/ClickHouse1/
SeaweedFS1/Valkey2 (the original Valkey plus the reviewed read-only helper).
Scheduled/retained counts stayed delayed6/repeat6/failed23; active/wait and other
executable-work counts were zero in the sample. This is no continuous writer
fence, confidential export, coordinated-backup marker or restore acceptance.

Node03 was at95% of allocatable memory. Full capture/restore capacity was not
admitted from that sample. For this short metadata-only diagnostic, the unchanged
256Mi helper limit was checked against actual kubelet available memory while
preserving the existing512Mi available-memory soft threshold. Available bytes
were1085505536 before and1022066688 after; pressure conditions were false.
No limit was reduced and no unrelated workload was moved/resized.

Job `langfuse-recovery-valkey-47d6711e2ff9`, UID`77d128e2-4fae-4931-9555-1f9c411657c8`,
and Pod UID`efc31ff5-3788-49ce-bb48-9a03dc39503e` used the original Valkey claim
read-only, native SecretKeyRef and the reviewed nonroot/no-token/no-fsGroup
security settings. Independent readback verified normal completion/exit0 at
`2026-11-22T07:50:46Z`. The artifact was retained and its exact terminal identity
recorded for later preflight; no deletion or automatic retry occurred.

After completion,43 capture tests passed and full verification passed21
Applications/520 resources against task base260444e, plus `git diff --check`.
Fresh read-only preparation also passed:
`verification/cache/langfuse-recovery/first-prepare-a743c5cf3a784b19945408e473e79a9e/prepared.json`.
Web/worker remained desired1/Ready1, Argo Synced/Healthy and HTTPS readiness
OK/version4.77.0. No new production capture or isolated restore was attempted.

### Full-operation capacity refresh and restore-only Valkey correction

Read-only capacity assessment completed at `2026-11-22T08:18:28Z`:
`verification/cache/langfuse-recovery/full-capacity-3833933b37014c3dafc37bebe6a5b77b/assessment.json`.
The refresh includes allocated/requested resources, init/sidecar peaks, overhead,
Pod status aggregate requests, two actual kubelet memory/filesystem samples,
Longhorn scheduling settings/disks, source staging space/data-size aggregates,
and strict-host-key SSH destination metadata/free space. It does not reserve
capacity or establish simultaneous memory-limit safety or actual restore peaks.

The previous target placement fails the sampled runtime model on `k3s-03`:
after the additional256Mi Valkey request and512Mi cushion, its margin is
negative510.12Mi. Change only the isolated restore Valkey placement to `k3s-01`;
production Valkey stays on `k3s-03`. All requests, limits, images, users, original
volume identities and manual sync policies remain unchanged. This supersedes
the Valkey-on03 entry in earlier placement evidence; ClickHouse stays04,
PostgreSQL/SeaweedFS stay01, and web/worker stay05.

With that correction, sampled margins after added target memory requests and
the512Mi cushion are1020.88Mi on01,372.25Mi on04 and5091.56Mi on05. Scheduler
requests and declared ephemeral storage budgets fit those target nodes. Node03
still has a negative allocatable-based cushion without any restore Pod there;
that existing tightness remains a warning, not spare restore capacity.

The separate source capture helper budget uses actual kubelet available memory:
the lower sample is1025.88Mi, leaving257.88Mi beyond its unchanged256Mi limit
and the512Mi available-memory threshold. Source Valkey AOF apparent size is
63.64Mi. PostgreSQL database size is14522047bytes; ClickHouse active application
parts total462962bytes; SeaweedFS apparent data size is1910402bytes. These are
source sizing observations, not native archive sizes or a successful capture.
Source staging space fits the bounded exports. The private NAS destination is
still mode0700 and has175.62Gi available, exceeding two sets of the bounded
component budgets. No directory or permission was changed by this check.

A non-reserving two-distinct-node Longhorn witness fits all65Gi claims/130Gi
replicas while retaining the measured filesystem minimum/ephemeral budgets:
ClickHouse01+02, SeaweedFS01+03, PostgreSQL03+04, Valkey01+03. No new replicas
are assigned to the more constrained05 in that witness. Actual PVC/PV/volume
identities, allocation and two healthy replicas must still be independently
read back before any restored native startup; this calculation is not binding.

Local validation after the one-line placement change:

- Restore suite:32 discovered,27 passed and five explicitly skipped generated
  native cases; all five were then independently exercised successfully.
- Current-code generated native proofs: PostgreSQL, Valkey and age transport in
  the reviewed1Gi/1CPU/96-task scope; ClickHouse4Gi/2CPU/256tasks; SeaweedFS
  held-loader/cold restart1Gi/1CPU/128tasks. All passed and all five receipt
  hashes match current `first_restore.py` SHA-256
  `09c96f58326e77ab9e153308d2224cdb38061ca2827a10c2bde6d26f19297dbb`.
- Reviewed target bundle:
  `verification/cache/langfuse-recovery/first-restore-reviewed-20261122-r4.json`;
  all25 resources passed strict schemas with zero invalid/errors/skips. The r3
  bundle and its older current-code receipt bindings are superseded.
- Full verifier passed21 Applications/520 resources against task base260444e.

Live verification remains separate: all six original application Pods were
Running/Ready with zero restarts and unchanged current UIDs; all four original
PVC/PV bindings remained Bound/unchanged. ArgoCD reports Synced/Healthy and HTTPS
readiness reports OK/version4.77.0. No production workload was changed, helper
created, writer paused, archive captured or restore deployed by this refresh.
No commit/push or datastore PR merge/rollout occurred. A fresh explicit bounded
client-idle window is still required; do not reuse the expired window or failed
reserved operation. Capacity must be checked again at actual execution time.

### First actual writer pause refused; separate manual web recovery verified

After fresh operator client-idle confirmation, actual capture operation
`first-d079828f7d5f4d0987e8c4fe5b64b838` passed live pre-pause admission and
attempted its first web replica CAS. The guard returned `MANUAL_RECOVERY`, reason
`mutation_readback_failed`, with web uncertain and no verified paused resources.
No native export ran, no components were published, and no coordinated capture
or isolated restore succeeded. Worker remained at its original1 replica.

The actual web Deployment UID remained `8ff8744e-9dec-4c8f-bd7a-80fe04e49612`,
but a fresh read confirmed replicas0 and no remaining web Pod. Its complete spec
matched the prepared original except replicas. The failed guard was not replayed,
cleared or automatically resumed. Separate reviewed manual recovery verified the
unchanged worker, clean original-image-bound migration state, original datastore
Pod identities and original PVC/PV specs, plus attached/healthy/two-replica
Longhorn state. One UID/resourceVersion/full-spec-tested JSON patch restored
only web replicas0→1; exact original-spec readback then passed.

Deployment rollout and HTTPS readiness subsequently passed. Web has the expected
new Pod UID `ed8cfb13-6f87-4ec3-b8f6-d80656228361`; worker retains
`b2017102-41d5-4903-a8c6-e7b94e976c48`. Both are Ready1/1, ArgoCD is
Synced/Healthy, and readiness is OK/version4.77.0. The operator was explicitly
released from the idle window; no capture retry ran.

The additional read-only post-recovery preparation was initially blocked by a
tool-approval timeout and did not execute at that point. Following the operator's
subsequent instruction to proceed, the approved check actually passed at
`2026-11-22T09:19:59Z`:470 matching PostgreSQL image/applied migrations,
unfinished0/startup-cleanup0; ClickHouse56/latest56/dirtyfalse; all four original
claim/volume identities, retention and healthy two-replica checks unchanged.
Receipts are under
`verification/cache/langfuse-recovery/first-live-first-d079828f7d5f4d0987e8c4fe5b64b838/`:
`manual-web-recovery-review.json`, `manual-web-recovery-readback.json`,
`post-manual-recovery-prepared.json` and `post-manual-recovery-summary.json`.
The original journal/outcome remains incomplete, not retrospectively successful.

The guard compares the patch response and subsequent GET including their
resourceVersions. Status-only controller churn is a leading reproducible code
hypothesis, not a proven forensic cause of this particular incident: the failed
path did not retain both mutation snapshots. A focused correction/regression
review is required before another explicitly bounded operation; UID/spec drift
and conflicting writes must remain rejected. No datastore upgrade was performed.

### Later version-only boundary refused; service recovered again

The focused immediate-acknowledgement correction was independently exercised:
44 writer-guard tests and46 capture tests passed;32 restore tests passed with
five explicit native-fixture skips. Full verification passed21 Applications/
520 resources. The correction carried Deployment generation through preparation
and snapshots, permitting forward supported resourceVersions only with matching
identity/full desired spec and exactly the intended generation transition.
Spec ABA, stale/regressed versions and missing generation remained rejected.

Following an approved helper-preparation retry and a fresh client-idle
confirmation, operation `first-914466344c5e49098d296c050157f27a` passed the
corrected initial web mutation verification: web UID
`8ff8744e-9dec-4c8f-bd7a-80fe04e49612`, resourceVersion20869433, generation5.
It then refused at a later exact-read boundary with `concurrent_resource_change`.
A fresh API read showed version20869453, the same generation5/UID, and the exact
prepared spec except the intended replicas0. Worker remained1. The recorded
old web exit was143; the initial queue sample retained delayed6/repeat6/failed23
with executable work0. This is not a completed queue-preservation checkpoint.
No datastore exports or coordinated marker were produced.

The interactive guard resume was explicitly declined rather than using stale
state. Separate manual recovery rechecked UID/full paused spec, unchanged worker,
fresh migration state, original datastore Pods and original healthy two-replica
storage. Its first command was blocked by tool-approval timeout and did not run;
after explicit operator retry, one reviewed CAS restored web replicas1 and exact
original-spec readback passed. Rollout then passed, web/worker were Ready1/1,
ArgoCD became Synced/Healthy, and HTTPS readiness was OK/version4.77.0.

Actual read-only post-recovery preparation passed at
`2026-11-22T10:42:07Z`, including470 matching PostgreSQL migrations,
unfinished0/startup-cleanup0 and ClickHouse56/latest56/dirtyfalse, unchanged
original storage identities and healthy two-replica state. Web's new Pod UID is
`747355f8-80d2-4eed-92cc-d791b0693f0a`; worker remains
`b2017102-41d5-4903-a8c6-e7b94e976c48`. Recovery review/readback and subsequent
preparation/summary receipts are retained under
`verification/cache/langfuse-recovery/first-live-first-914466344c5e49098d296c050157f27a/`.
The client-idle window was released, no capture retry ran, and the operation
remains incomplete. The remaining local correction must cover later exact-read,
evidence and pre-CAS boundaries without accepting identity/spec/generation drift,
replaying failed journals, or adding automatic mutation retries.

### Later resourceVersion-only handling corrected and independently tested

The local correction now covers subsequent exact-read/evidence boundaries and
the adapter's final pre-CAS GET, not only the immediate mutation acknowledgement.
Current and paused snapshots can advance to a supported positive decimal RV only
with unchanged UID/name/kind/namespace/full spec/generation. Generation remains
mandatory and rejects changed-then-restored specs. Evidence is validated against
its original exact resource tuple and challenge, never relabeled with a later RV.
The adapter patches the newer pre-CAS GET using atomic UID/RV/full-spec tests;
there is still no mutation retry, journal replay or automatic resume.

Parent review inspected the actual implementation and independently reran:
49 writer-guard tests,49 capture tests, and32 restore tests with five explicit
native-fixture skips; all passed. The regressions include repeated later version
updates through termination, evidence collection, pre-CAS, capture checkpoints
and explicit resume, plus UID/spec/generation drift, spec ABA, unsupported or
backward versions and atomic conflict refusal. Full verification again passed21
Applications/520 resources against task base260444e; whitespace checks passed.
The native restore implementation was unchanged; the five default-suite skips
are not new native execution evidence.

This is local validation, not successful live capture. A write after the final
GET may still conflict atomically and stop; multi-object evidence is not a
cluster-wide transaction. Production web/worker remained Ready1/1 during this
work. No live capture/recovery/deployment, commit or push was performed by this
correction. Both failed operations remain incomplete and must not be reused.

### Frozen capture reached; inherited staging mode blocks first component

After the approved next-helper retry and a fresh explicit client-idle window,
operation `first-72c99b7e2a514b918297c0c0246a56c6` passed both writer pauses and
the frozen capture admission. Web's verified paused generation was7 and worker's
was2. The retained exit evidence was web143/worker0. The sampled preserved queue
state remained delayed6/repeat6/failed23 with executable work0. The capture then
returned `INCOMPLETE`/`operation_failed`, with no accepted/published component and
no coordinated marker. This is not backup or restore acceptance.

Unlike the previous attempts, one separately reviewed explicit guard resume
succeeded: both original replica specifications were restored, with no unknown
or paused resources remaining. Review is retained as `explicit-resume-review.json`
under `verification/cache/langfuse-recovery/first-live-first-72c99b7e2a514b918297c0c0246a56c6/`.
Actual web and worker rollout checks passed, ArgoCD became Synced/Healthy, and
HTTPS readiness returned OK/version4.77.0. The operator was released from the
idle window; no capture retry ran. The process exit1 represents incomplete
capture, not failed explicit resume.

Read-only source metadata subsequently identified a concrete first-component
validation blocker: the newly created PostgreSQL staging directory
`/tmp/first-7c447276d57944138989a7a1287b291f-postgres-database` is UID999/mode2700,
while its staged native archive is UID999/mode0600/578842bytes. No archive
contents were read or printed; the partial confidential artifact is retained.
The existing `_private_path_checks` requires directory mode exactly700, so this
directory necessarily fails validation. Do not describe this attempt as having
performed no native export: PostgreSQL did stage a dump, but none was accepted,
encrypted/published as a completed component, or marked coordinated.

A local generated-empty-directory reproduction confirmed that mkdir(mode0700)
under a setgid parent produces mode2700; explicit chmod0700 on only the new
task-owned child produces0700 without altering its parent. Production ownership
and permissions were not changed. The next narrow correction must account for
inherited setgid when creating new private staging directories, retain strict
private-path validation, and leave original mounts/PVC permissions untouched.
No plaintext fallback, cleanup, restore, upgrade, commit or push occurred.

### Staging-fix work: current live verification reachability limitation

On `2026-11-23` AEDT, the next local staging-fix task began without a production
pause. Kubernetes Deployment/Application inspection from the workstation failed:
`192.168.0.11:6443` returned `no route to host`. The separate HTTPS readiness
check still returned OK/version4.77.0. Do not infer current Pod replica status,
ArgoCD health or storage health from that HTTPS response or an aggregate shell
exit code. No host routes, authentication or other profiles were changed to work
around the failure. Local implementation/regression validation can continue;
another live capture requires restored configured API connectivity and fresh
execution gates, not historical readiness observations.

### New-stage mode normalization implemented and locally validated

The narrow correction creates only fresh task-owned staging directories using
exclusive mkdir, then runs shell `chmod 00700` before confidential output and
retains the existing exact owner/mode/no-symlink checks. The five-digit numeric
mode matters: GNU chmod700 can preserve directory setgid, whereas00700 clears it.
Covered paths are both PostgreSQL export stages, ClickHouse's new stage,
SeaweedFS's new stage/volumes and Valkey's new checkpoint/appendonlydir. Existing
parents, original mounts/PVCs, `/scratch/capture` and failed artifacts are not
repaired. ClickHouse's existing backup-parent exact0700 prerequisite remains
strict and must be checked before another writer pause.

Focused regressions execute actual generated filesystem creation/proof/producer
logic with synthetic native output, including setgid inheritance, unchanged
parent inode/mode/UID/GID, children0700/files0600, and occupied/symlink refusal.
They are not actual native datastore export/restore execution. Parent review
inspected the generated shell paths and independently reran the56-test capture
suite,49-test writer guard suite and32-test restore suite (five native skips).

Combined discovery also exposed an existing negative fixture whose intended
public0755 directory became0700 under a prior test's restrictive process umask.
That test fixture now explicitly sets its intended0755 mode; production privacy
validation and production umask behavior were not relaxed. The final combined
Langfuse run passed329 tests with25 explicit skips (20 desktop-source and five
native-startup cases). Generated transport receipt:
`verification/cache/langfuse-recovery/encryption/capture-tests-3e5b058d1f9b4a00ba7a6218e6a51b6c/suite-receipt.json`.
Full verification passed21 Applications/520 resources against task base260444e;
whitespace checks passed.

Live verification remains blocked: a bounded API `/readyz` recheck still returned
`no route to host`; HTTPS Langfuse readiness separately returned OK/version4.77.0.
No production pause, permission change, native export, helper creation, capture
retry, deployment, commit or push occurred during this local correction. Native
capture and isolated restore acceptance remain incomplete.

### Operator temporary route restored API access; backup parent prerequisite missing

The operator explicitly approved the temporary API-host route and applied it in
a private terminal after noninteractive sudo was unavailable. Readback verified
`192.168.0.11` via `192.168.86.1` on `wlp192s0`, and the normally authenticated
Kubernetes `/readyz` returned ok without kubeconfig/TLS/authentication changes.
This supersedes the workstation API reachability blocker above; no persistent
network or Docker route change was performed by the agent.

Read-only live checks then verified web/worker Ready1/1, ArgoCD Synced/Healthy,
all four original claim UIDs unchanged/Bound, and HTTPS readiness OK/version4.77.0.
PostgreSQL `/tmp` is root:999/mode2777, consistent with the inherited-setgid
staging reproduction. A targeted metadata-only check found ClickHouse's required
`/var/lib/clickhouse/backups` parent absent. The current producer requires this
existing owner-only source prerequisite, so another writer pause must not begin
until that specific prerequisite is resolved and independently verified.
No directory was created or repaired, no writers were paused, and no capture,
restore or upgrade ran during these connectivity/prerequisite checks.

### Missing ClickHouse backup parent explicitly provisioned and verified

Following the operator's instruction to proceed, the unchanged pinned Ready
ClickHouse Pod `42d6c841-e51c-4dd3-a08d-f3bd44a3b157` was checked as service
UID/GID101. Native config still reported path `/var/lib/clickhouse/` and relative
allowed backup path `backups`. Absence/no-symlink checks passed for the required
new backup parent before an exclusive mkdir and explicit chmod00700, executed
as the existing service user without root or chown.

Independent readback verified `/var/lib/clickhouse/backups` as a directory owned
101:101/mode0700. Existing `/var/lib/clickhouse` retained device2112/inode2,
owner0:101/mode2775; only the new directory was created and normalized. No existing
volume-root permissions or ownership were changed. Web/worker remained Ready1/1,
ArgoCD Synced/Healthy and HTTPS readiness OK/version4.77.0.

Read-only PostgreSQL and SeaweedFS staging-parent/tool checks passed. The previous
helper `langfuse-recovery-valkey-72c99b7e2a51` was independently verified terminal:
Job UID`10cd5881-9751-456c-bb8d-e0190d4c2b33`, Pod
UID`0157bc7c-e483-48dc-9bf2-2f29c0e25bc5`, Succeeded/exit0. Its exact retained
identity was added to admission; no broad terminal-helper exemption or deletion.

Fresh actual preparation passed with470 matching PostgreSQL migrations,
unfinished0/startup-cleanup0, ClickHouse56/latest56/dirtyfalse, original storage
checks and two replica-pause server dry runs:
`verification/cache/langfuse-recovery/first-prepare-11f9f9a5c3d34adfa442bad24abaa6be/prepared.json`.
The updated56-test capture suite and whitespace checks passed. Preparation still
reports `capture_ready:false`: a fresh bounded helper, execution-time capacity/
watch/queue admission and a newly confirmed client-idle window remain required.
No writer was paused, native export rerun, backup marker published, restore
started or datastore upgraded by this prerequisite-provisioning step.

### Coordinated production capture completed; expired-window manual resume verified

Operation `first-9267a093154a4926ab44c618a23b410a` completed actual coordinated
capture after a fresh helper, current capacity/NAS checks and explicit client-idle
confirmation. Both writer pauses, continuous fence completion and native archive
validation passed. All five components (PostgreSQL database/globals, ClickHouse,
SeaweedFS and Valkey) were encrypted and published with complete receipts and
authenticated independent NAS readbacks. The final coordinated marker is:
`/storage/k3s/langfuse/recovery/first-20261120/first-9267a093154a4926ab44c618a23b410a-capture.json`.
Its receipt reports4941bytes and SHA-256
`4a869adc6830794c08eafd4bd30a00611cbfae5e097bf1a9d0d9f6aab48fbfdd`.
The captured queue checkpoint preserved delayed6/repeat6/failed23 with executable
work0; no queues were cleared or schedules disabled.

The separate parent marker/resume review first encountered tool-approval timeout.
Its subsequent verification incorrectly compared the NAS reader's JSON digest
receipt with raw marker bytes; that caller error was corrected after inspecting
the actual reader contract, without changing the backup or re-running capture.
The final approved review verified the exact NAS marker size/hash/exclusive/
durable receipt, all five component identities, unchanged complete paused specs
and clean current migrations. `explicit-resume-review.json` retains the result.

Approval delays exceeded the original bounded window. The one explicit guarded
resume therefore refused `deadline` and recorded `MANUAL_RECOVERY`; it did not
restore replicas automatically or invalidate the already completed backup.
Separate manual recovery was initially tool-blocked and did not execute then.
Following explicit retry, fresh deployment UID/spec/generation, migration and
original PVC/PV/healthy-two-replica checks passed. Atomic UID/RV/generation/full-
spec patches restored only the original replica counts, each with independent
exact-spec readback: web generation10/replicas1 and worker generation5/replicas1.
No failed journal was replayed and no capture was rerun.

Both real Deployment rollouts passed; web and worker are Ready1/1, ArgoCD is
Synced/Healthy, and HTTPS readiness is OK/version4.77.0. The operator was released
from the idle window. Manual review and per-resource/combined readback receipts
are retained under
`verification/cache/langfuse-recovery/first-live-first-9267a093154a4926ab44c618a23b410a/`.
This establishes production backup capture and separate verified service
recovery, not isolated restore or application acceptance. Four-new-volume
restore, restored data/queue reconciliation, owner login, target-only ingestion,
and eligible datastore upgrade merges/manual rollouts remain incomplete.

### Isolated restore input compatibility and identity continuity verified locally

The actual capture marker uses the canonical queue fingerprint schema, not the
older drain-probe schema. The restore checker now compares the exact captured
registry hash, all11 counts, scheduler/job-content fingerprint and scope. It
derives the registry statically from the held target worker's pinned source,
verifies source trees independently and executes the unchanged hash-pinned
capture Lua through EVAL_RO only against recovery-valkey DB0. Legacy fields are
not invented or relabeled as captured evidence. Count-equal fingerprint drift,
registry/shard drift, malformed types and wrong scopes remain rejected.

SeaweedFS before/after admission is now derived, boundedly in RAM, from the six
JSON metadata members inside the authenticated native archive, followed by the
complete existing archive validator. This is archive-bound recovery-point
evidence, not a reconstruction of the external observations formerly held only
in capture-process memory. Resumed production is not sampled as the baseline.

The parent authenticated the original encrypted six-Secret List privately and
verified its schema without plaintext files or displayed values. Every original
UID/resourceVersion exactly matched the current source metadata projection,
establishing unchanged identity across the earlier coordinated capture:
`verification/cache/langfuse-recovery/first-restore-identity-continuity-fc3d68b49fab437d8cb0085d2010aabc.json`.
No target Secrets were created by this check.

Independent local validation passed336 combined Langfuse tests with25 explicit
skips. All five generated native cases were subsequently actually executed under
their reviewed separate resource scopes: PostgreSQL, Valkey, ClickHouse,
SeaweedFS held-loader/cold restart and authenticated age transport. Their receipts
were independently checked against current restore SHA-256
`9dce70c86139ab599906566a4077033695fb2c9a6054b2551f94c38336155c2b`.
Reviewed bundle `verification/cache/langfuse-recovery/first-restore-reviewed-20261123-r5.json`
passed all25 strict schemas with zero errors/skips. Full verification passed21
Applications/520 resources against task base260444e. Historical capture and older
native receipts were retained unchanged, not rewritten to the new helper hash.

Live capacity/admission inspection found the target namespace absent and sampled
budgets feasible, but these observations do not reserve capacity or prove actual
replica bindings. The command to create only the fresh namespace, isolation
policies and four empty claims hit a tool-approval timeout and did not run.
No recovery namespace, claims, Pods or target identities were created; no native
restore ran. Resource creation remains blocked pending explicit operator retry
and tool approval, with fresh execution-time checks. Production was not paused.

### Target bootstrap completed; held-Pod preparation blocked on actual replicas

After explicit operator retry, the namespace and both reviewed policies were
created and read back. All four new claims bound to distinct new PV/CSI/Longhorn
identities; namespace UID is `d39bc842-da60-47b5-a923-a1cb22247154`.
Bootstrap receipt:
`verification/cache/langfuse-recovery/first-restore-bootstrap-40dcdb9287d748318b19745009cd629c.json`.
Binding/provenance receipt:
`verification/cache/langfuse-recovery/first-restore-storage-bindings-c2828fb62a034d03809944a167d333a5.json`.
The new PV reclaim policies remain their provisioned `Delete` defaults; no
cleanup, retention-policy changes or deletion were performed.

The next execution-time capacity refresh passed Pod requests/runtime checks but
the pre-provisioning allocator could no longer allocate another full replica set.
That allocator does not credit this task's already-reserved replicas: its false
result alone is not proof that the existing set cannot run. Independent readback
found exactly two scheduled, distinct-node replicas for each new volume, with no
failed timestamps. These detached/stopped replicas are not healthy-running proof.

Actual placement nevertheless fails the reviewed conservative physical gate:
Longhorn placed the new 30Gi ClickHouse replica on `k3s-05`, although the earlier
unreserved witness excluded that node. After the15% physical-free floor and the
two restored application Pods' staging limits, sampled node05 margin is13.87Gi;
budgeting the full30Gi replica leaves -16.13Gi. Other actual replica nodes pass.
The controller's thin-provisioned scheduling acceptance does not establish this
full-size physical/staging budget. No safety margin was lowered to accept it.

Evidence:
`verification/cache/langfuse-recovery/full-capacity-0d6c4260a05c43a3979539c0c8576b87/assessment.json`
and
`verification/cache/langfuse-recovery/first-restore-placement-blocker-eda52ef29e5945a7bd05c198510a18d9.json`.
Stopped before private identity reconstruction, held-Pod creation or archive
upload/start. No replicas were moved/deleted and no scheduling constraints or
production resources were changed. Both production Deployments remained1/1.
The four target claims and completed encrypted backup remain intact. Review a
target-only replica-placement correction before continuing; existing volume
identities and the two-replica requirement must be preserved.

### Longhorn v1.13.0 scoped eviction review — no live correction executed

Version-pinned manager source review ruled out directly patching the individual
replica's `spec.evictionRequested` as a durable, target-only operation. The node
controller's `syncReplicaEvictionRequested` recomputes that field from node/disk
eviction settings or cordon/drain policy, and cancels it on an ordinary healthy,
uncordoned node. Repeated patches would race reconciliation, not implement a
supported per-replica eviction intent. No such patch was attempted.

The volume controller also requires a running engine and healthy RW replicas
before its eviction/replenishment path can create a temporary replacement and
retire an evicting replica. The current pair has never started. Supported manual
frontend-disabled API attachment could initialize the storage engine without a
Pod, filesystem mount or application startup, but it cannot repair the missing
durable eviction intent and was therefore not performed solely for this purpose.
Eviction alone additionally does not guarantee exclusion of the source node.

Sources independently checked against deployed manager version v1.13.0:
- https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/node_controller.go#L2067-L2127
- https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/node_controller.go#L2208-L2250
- https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/volume_controller.go#L704-L739
- https://github.com/longhorn/longhorn-manager/blob/v1.13.0/manager/volume.go#L274-L381

Fresh capacity receipt:
`verification/cache/langfuse-recovery/full-capacity-031f40a955b745c78980b96bf06c8e09/assessment.json`.
All original volumes were attached/healthy with two replicas; original web/worker
Deployment UIDs and1/1 readiness were unchanged. Target claim/PV identities,
volume UID `855f8e84-5c34-4b25-b040-5686f87800e4`, detached actualSize0 state,
empty attachment-ticket map, and absence of target Pods were read back.

No end-to-end correction satisfying the reviewed no-global-eviction/no-direct-
deletion constraints was established. Broad node/disk eviction or cordoning would
affect unrelated volumes/workloads and is not an acceptable substitute. A bounded
replacement of only the unused target replica would require a separately reviewed
placement constraint and explicit deletion authorization; this is a proposal,
not an approved or executed action. Do not delete or recreate the target PVC/PV
or volume to work around this blocker, and do not claim relocation or recovery
acceptance from this source review.

### Approved unused target replica replacement completed and verified

After the operator proceeded with the explicitly described unused-replica
replacement, the one-time driver server-dry-ran the placement patches and
revalidated the empty, detached volume, no target Pods, no attachment tickets,
and both replicas' never-started/never-healthy identities. It confirmed that
`allow-empty-node-selector-volume=true` and strict distinct-node replica
scheduling remain unchanged. No global setting or node/disk eviction was enabled.

Added the unique Longhorn scheduling tag `langfuse-first-ch-recovery` only to
Longhorn nodes01 and03, preserving all other node spec fields. The target
ClickHouse volume alone now selects that tag, excluding node05 for future
replacement scheduling. These are Longhorn node tags, not Kubernetes cordons or
workload node-selector changes. Existing unselected volumes remain eligible.

Only unused replica `pvc-fb654ae0-3639-4887-a3cf-973156008aa6-r-153530ed`, UID
`285cb598-d8cc-4849-8098-41e1382bbcf4`, was removed with atomic UID/RV delete
preconditions after a server-side deletion dry run. The PVC, PV, CSI handle and
Longhorn volume UID `855f8e84-5c34-4b25-b040-5686f87800e4` were preserved; desired
replica count stayed2. No production replica was removed.

A supported manual API attachment to node01 used `disableFrontend=true` and the
unique ticket `longhorn-api-langfuse-empty-target-placement`. No filesystem was
mounted/formatted and no application process or native restore was started.
Storage-engine initialization did write internal Longhorn metadata. The retained
node03 replica UID `63fba9e0-ac3f-42a9-8ec6-7ec243284cae` and replacement node01
replica UID `f92bda32-5923-4323-a1d6-6e90fc1d37ea` both became healthy engine-RW
replicas before the driver released only its own ticket with forceDetach=false.
Final readback shows detached/stopped replicas and an empty ticket map. The
two-RW proof is attached-state evidence, not a claim of currently running engines.

Execution receipts share prefix
`verification/cache/langfuse-recovery/first-restore-replica-replacement-23482f40276f4c2b888d12f70ab4a787`.
`-05-two-healthy-RW-replicas-verified.json` retains the actual engine/replica proof;
`-06-complete.json` establishes successful scoped detach and unchanged original
volume specs/UIDs plus web/worker1/1 readiness. No target Secrets or Pods exist.

Independent post-operation readback and a fresh capacity refresh verified every
actual two-node target replica pair against the full-size physical budget,
preserving the15% floor and planned Pod staging limits. Remaining margins on
nodes01/02/03/04 were58.91/111.74/102.30/245.99Gi respectively. No target replica
remains on node05. Evidence:
`verification/cache/langfuse-recovery/first-restore-placement-corrected-e7ecce6197a24972aeebe8d09a9c0c2b.json`
and
`verification/cache/langfuse-recovery/full-capacity-8b2d089b541640f49014d123d4d03baf/assessment.json`.
The operation driver SHA-256 is
`08a5e70b96c3d0174f3345f27f81bae44c1694c2d6b973aaab8278e21f703af3`.

Earlier preflight-only attempts encountered intermittent Service-proxy503
responses and a local receipt-path contract error, all before live mutations.
The driver now uses the verified Ready owner-manager Pod UID through normal
authenticated Kubernetes Pod proxy, without changing authentication/network
settings. Actual private no-overwrite receipt publication was locally exercised
before the successful run. Historical failed artifacts were retained; no failed
live journal was replayed. The physical-placement blocker is resolved, but
original-identity reconstruction, held-Pod isolation/attachment checks, native
four-store restore and application acceptance still remain.

### Original identity reconstructed; six held Pods and sampled CNI checks passed

The operator proceeded with original-identity reconstruction and held-Pod
preparation. Fresh pre-creation capacity passed:
`verification/cache/langfuse-recovery/full-capacity-6df2e39377aa4ec8b1ce5af2dae41a53/assessment.json`.
The approved encrypted identity snapshot was hash/FD checked, authenticated by
age with only the private key FD inherited by that child, and validated in RAM.
All six original Secret UID/resourceVersions still exactly matched the current
source metadata projection. The original six identities were reconstructed only
in the existing UID-bound recovery namespace; exact target Secret-data equality
was privately read back and source metadata rechecked afterward. No private
values were displayed, no plaintext host files were written, no credentials were
regenerated and no bootstrap/reseeding variables were enabled.

Reviewed ConfigMaps/ClusterIP Services and all six held Pods were created, then
read back against the reviewed specs. Each Pod was Running/Ready on its fixed
node/image with zero restarts. No `/restore/start` or native-restored marker
existed. Readiness here means a healthy held shell, not database/application
readiness. Receipt:
`verification/cache/langfuse-recovery/first-restore-held-5b4c96b60b2b445293d3fa3b121de564-06-held-ready.json`.

All four claims mounted their previously verified new PV/CSI/Longhorn identities.
Each target volume was attached/healthy with exactly two running replicas on
distinct nodes, and each engine independently reported both exact replica IDs
as RW. No target replica was on node05. Evidence:
`verification/cache/langfuse-recovery/first-restore-held-isolation-1d82136238894eec8ab8591f4f33cc4c-storage.json`.

Actual bounded TCP probes, not policy-render inspection alone, established two
allowed worker-to-held-web paths (Service DNS and Pod IP), seven denied target
egress paths (production web, PostgreSQL, both ClickHouse ports, Valkey,
SeaweedFS S3 and Kubernetes API), and two denied production-web-observer ingress
paths (target web Pod IP and ClusterIP). The temporary bare target TCP listener
exited cleanly; it never started Langfuse. No authentication/protocol payload was
sent to production dependencies. These are sampled CNI path results, not proof
of every possible network path or application-level acceptance. Receipt:
`verification/cache/langfuse-recovery/first-restore-held-isolation-1d82136238894eec8ab8591f4f33cc4c-verified.json`.

All six startup markers remained absent after the probes. Production web/worker
remained1/1 and all four original volumes remained attached/healthy with two
replicas. No archive upload, native restore or application startup occurred.
The conservative earliest held-shell deadline is2026-11-23T04:36:00Z; recheck
Pod UID/restart/hold continuity and remaining time before continuation. Do not
silently extend deadlines or recreate a terminated Pod. Native four-store
restore, data/queue reconciliation and owner/trace/ingestion acceptance remain
uncompleted, and datastore upgrades remain recovery-gated.

### Actual NAS-backed four-store native restore gate passed

The operator proceeded with authenticated staging and native restore. Fresh
post-Pod capacity used the reviewed scheduler accounting without adding the six
already-declared target Pod requests a second time. Runtime modeling retained
the full target memory requests in addition to held-shell RSS and the512Mi
cushion. Actual allocated replicas, full-size physical/staging budgets and all
original volume health were checked independently; no new-set feasibility
witness was substituted for the allocated set.

All five ciphertext streams and exact COMPLETE receipts were read back from NAS
with strict configured SSH authentication, directory/file owner/mode/type/link
checks and byte/hash equality. The primitive COMPLETE receipts retain
`remote_durability_verified=false` because they precede coordinator NAS
publication; they were not rewritten. Final coordinator publications, their
separate durable readbacks and this fresh NAS readback establish remote evidence.
Ciphertexts were authenticated again with age through the private key FD, with
all decrypted data confined to RAM and the authorized isolated target volumes.

The first staging attempt independently verified PostgreSQL DB/globals and
ClickHouse target bytes, then correctly refused an empty SeaweedFS target file.
No native process had started. Generated2117632-byte tests reproduced truncated
SeaweedFS exec-stdin transfers despite rc0: cat, fullblock dd, direct dd and a
SPDY variant yielded zero/32768 bytes, whereas other target images received the
full stream. This narrows the failure to that observed receiver path; it does
not establish a definitive kubelet/containerd/BusyBox root cause.

A full-size generated bounded worker-to-SeaweedFS HTTP transfer passed exact
size/hash and exited cleanly. The actual continuation used the same one-shot
path/source-Pod-IP restriction wholly inside the isolated namespace. This is
private in-cluster HTTP, not TLS. It retained the failed empty input via a
verified no-clobber rename, reused only independently authenticated exact-hash
staged files, and transferred the missing SeaweedFS and Valkey inputs. Nothing
was deleted, overwritten, cleared or replayed from a failed live journal.
All five target plaintext stream sizes/hashes and PostgreSQL full archive parse
then passed before any native startup gate was released:
`verification/cache/langfuse-recovery/first-restore-native-continuation-b84478cb4ec74747ac10cc3635a6c2fc-08-complete-staging-verified.json`.

All four actual native restore markers were subsequently observed. The runtime
performed SeaweedFS full live-loader metadata/authenticated-object comparison
before EOF, then a cold restart and comparison, followed by PostgreSQL checks.
It stopped at a ClickHouse checker-format error, not demonstrated data corruption.
Pinned26.8.36.3 defaults `check_query_single_value_result=0`: empty tables return
zero rows and populated tables return per-part `is_passed`, rather than `result`.
Live queries proved explicit summary mode returns `{"result":1}` for both empty
and populated restored tables. The checker now explicitly requests that mode
and accepts exactly one integer-success summary, rejecting empty/per-part,
failure/bool/duplicate/unexpected-field responses. Focused regressions exercise
that contract. No restore was rerun to fix this read-only checker.

After the read-only reconciliation approval timed out, no command ran; explicit
operator approval authorized its later successful execution. Current evidence:
- PostgreSQL exact applied migration-set hash, no unfinished migrations and
  native pg_amcheck passed.
- All14 ClickHouse native tables passed explicit summary integrity checks and
  the latest migration state matched the captured proof on26.8.36.3.
- Captured canonical queue registry, all11 counts and scheduler/job-content
  fingerprint matched exactly before worker startup, including delayed6,
  repeat6 and failed23. No queues were cleared or schedules disabled.
- Full retained SeaweedFS live/cold application metadata matched the authenticated
  archive. Actual files were `live-metadata-0.gz` and `cold-metadata-18.gz`;
  cold readiness polling need not create export0. The original pre-EOF marker
  and pinned control flow retain the live-loader gate evidence. A fresh separate
  authenticated readback reverified all231 object byte counts/hashes.

Native read-only receipt:
`verification/cache/langfuse-recovery/first-restore-readonly-native-reconciled-0213787fe6404c1b898eb63a901d3e0f.json`.
SeaweedFS read-only receipt:
`verification/cache/langfuse-recovery/first-restore-seaweed-readonly-reconciled-1c646830fd304812baeb4266c099b7ec.json`.
Combined native gate:
`verification/cache/langfuse-recovery/first-restore-native-gate-passed-2e9a3312ee91485381bf47747474b1e0.json`.
The current read-only checker helper hash is
`212d98dc65f31ae635595bb3561ab114da4f1e490f64557c4714b9a493b44aaf`.
Earlier execution/capture/helper hashes remain historical, unchanged receipts.

Local validation separately passed336 Langfuse tests with25 explicit skips,
then all five generated native cases were actually rerun under their reviewed
separate resource scopes. Full repository verification passed21 Applications/
520 resources. These local proofs are not the actual restore or application
acceptance; the live receipts above establish the native restore gate.

Final native-gate readback found all four original and four target volumes
attached/healthy with two replicas and production web/worker still1/1. Web and
worker remain behind their original unmodified startup gates, whose conservative
deadline is2026-11-23T04:36:00Z. Original owner login, old trace/observation API/UI
readback and new target-only ingestion remain pending. Recovery acceptance is
stillfalse; no datastore PR merge or rollout has been cleared by this milestone.

### Approved acceptance-only application replacement started successfully

The original web/worker held shells exited1 at2026-11-23T04:36:03Z as their
original hold leases expired. All four datastores continued running and retained
their restored healthy two-replica volumes. Nothing was silently restarted.
After the replacement decision timed out, the operator explicitly approved a
new application-only pair while retaining both expired Pods.

Created `recovery-web-acceptance` (UID
`2ad26deb-4c07-4cca-bea6-0c3f16b0d7e7`) and `recovery-worker-acceptance` (UID
`bdb11c99-6796-4d9e-a65d-a062c0939f26`). They reuse the unchanged reviewed app
images, resources, scripts, namespace policies and original Secret references;
neither mounts a datastore PVC. No native store or credential was recreated.
Capacity counted the four running native Pods once, excluded the two terminal
expired Pods, and added only the two new applications. Current native working
sets were credited once against their remaining request budgets, retaining the
512Mi cushion rather than double-counting existing requests or dropping reserves.

Before application startup, the exact migration/integrity and canonical queue
fingerprint gates passed again through the fixed-name/UID-bound new held worker.
The authenticated archive metadata and all231 S3 object byte/hash checks also
passed through that new worker. Only after those checks did the driver release
the two new application startup gates. The four native identities and helper
source remained unchanged. The new Pod routing adapter was confined to this
one-time process and the two explicitly approved names; no general target
override or core-helper relaxation was introduced.

Application receipt:
`verification/cache/langfuse-recovery/first-restore-acceptance-apps-87172cc03e0f4b24a4deb28bc0414779-05-application-ready.json`.
Both new Pods were Running with zero restarts, and target web health plus public
readiness returned HTTP200/statusOK/version4.77.0. Retained expired Pod UIDs and
production Deployment UIDs/1/1 readiness were independently rechecked. Starting
the new application processes exits their hold loops; the old15:36 deadline does
not impose a new running-application expiry.

The existing recovery-web Service's Ready endpoint was independently bound to
the new web UID. A loopback-only port-forward was started as owned process
`proc_cc4905e79a08`, listening at `http://127.0.0.1:3300`. Actual workstation HTTP
health/readiness both returned200/statusOK/version4.77.0; unauthenticated v2
observations returned401. This loopback HTTP is not a public/Tailscale exposure
or an end-to-end TLS claim. Receipt:
`verification/cache/langfuse-recovery/first-restore-acceptance-loopback-528cd3ef774c4ed995e3c4524ab31053.json`.

Actual running-application network samples then passed four worker-to-target
datastore paths, seven denied production/API egress paths, and two denied
production-to-acceptance-web ingress paths. No credentials or protocol payloads
were sent to production dependencies:
`verification/cache/langfuse-recovery/first-restore-active-app-isolation-e9dc81dbf8db456abd7c943662703241.json`.

Original-owner private login, old trace/observation UI/API readback and one new
target-only ingestion remain unverified. No owner reset, bootstrap reseed,
client enrollment, provider/authentication change or datastore upgrade occurred.
Recovery acceptance remainsfalse pending those application checks. The operator
must enter any owner credentials privately in the loopback UI, never in chat.

### Original application recovery acceptance completed

The operator privately confirmed original-owner login, then confirmed an existing
project's pre-backup trace detail and associated observations/spans loaded
correctly through the isolated loopback UI. These are operator-confirmed UI
results, not an agent-inspected authenticated browser session. Metadata-only
receipts preserve that distinction:
`verification/cache/langfuse-recovery/first-restore-owner-login-operator-report-d8fe087184c7406abcd1e590b557079b.json`
and
`verification/cache/langfuse-recovery/first-restore-old-trace-operator-report-d26c28583ff54b08964cb8d5e117ffea.json`.

After the credential-choice prompt timed out without action, the operator
explicitly authorized only this homelab-scientist profile's existing project
keys through its normal credential provider for the isolated test. The standalone
process asserted the exact active profile home, hydrated normal sources, bound
only the existing two Langfuse auth names to that home, and used native get_secret
without cross-profile or missing-key environment fallback. No credential files,
profile/plugin settings, production endpoint, guard allowlists or providers were
changed. Provider output was suppressed and no key values were displayed or
persisted by the test. The explicit credential-use authorization was one-time,
not standing authorization for later credential operations.

The endpoint was atomically fixed at `http://127.0.0.1:3300`, with the Ready
Service endpoint bound to the acceptance web UID, redirects refused and all
environment proxies disabled. Read-only project authentication returned only
`hermes-desktop` before the write. Public SDK4.15.2 API/source inspection confirmed
Langfuse v4 uses supported OTLP ingestion and v2 observations, not removed legacy
trace/ingestion endpoints. No SDK exporter/client with a possible Cloud default
was constructed and the existing production tracing guard was not weakened.

Exactly one OTLP request generated a synthetic no-model trace with two SPAN
observations, fixed metadata-only flags and no input/output attributes. Trace ID:
`9b2d92d61a874e19b01e536674433158`. The initial response decoder rejected a
non-protobuf response body after the request, so it did not infer success or
resend. Separate bounded read-only v2 observations queries then proved the actual
stored result: both exact observation IDs, the expected single project/trace,
root-child linkage, names/environment/type, null/absent IO and the complete
allowlisted metadata map. This was actual application ingestion/readback, not a
synthetic API response or a model/tool tracing acceptance claim. A one-shot
completion latch now refuses another producer execution before credential/network
use; no POST was retried.

Verified readback:
`verification/cache/langfuse-recovery/first-restore-target-ingestion-readback-91d25ec071a2489186c9660726f675da.json`.
Independent production native read-only queries found zero matches for that exact
trace ID in events_core, events_full, observations and traces. The authorized
project keys were never used against production; these aggregate checks used the
source container's normal native CLI authentication:
`verification/cache/langfuse-recovery/first-restore-fixture-production-absence-8a99d7f26fb548bb9828d3d83e0b53a9.json`.

Final readback found both new application Pods Running with zero restarts,
production web/worker1/1 and all four original plus four target volumes
attached/healthy with two replicas. Coordinated backup plus native and
application-level isolated restore acceptance is now passed, with operator versus
machine evidence explicitly separated:
`verification/cache/langfuse-recovery/first-restore-recovery-accepted-08aa277346a048a0bfaafa2e59f576f9.json`.
The separate Vaultwarden key-copy custody remains operator-reported; successful
use of the local decryption FD does not prove that secondary copy's readback.
Exact candidate-image reviews and eligible #106/#107/#111 merges/manual rollouts
remain uncompleted. No upgrade, commit, push, cleanup or schedule/integration
change was performed as part of this acceptance test.

### Remaining datastore PRs merged and manually rolled out (2026-11-24)

This supersedes the preceding pending-upgrade status. The operator requested
proceeding with the remaining original step5. Exact public image reviews found:

- #106 is Valkey8.0.12 to8.0.13, including upstream security and AOF/Lua fixes,
  not just a base-image rebuild. AMD64/ARM64 support and launch contract are
  preserved; both source RDB format constants are11.
- #107 keeps server18.7, changing PGDG packaging +2 to+5, libpq18.7 to19.0,
  postgres-common and gosu. This does not upgrade the server/PGDATA to19.
  The `/run/postgresql` entrypoint adjustment retains `/var/run` compatibility.
- #111 is ClickHouse26.8.36.3 to26.8.42.13 within the26.8 LTS branch. An exact
  no-secret/no-token/no-volume, nonroot version Job exited0 on actual k3s-04
  before rollout. Keep that ARM64 placement; compat CI builds do not make the
  official image suitable for the Xeon. The projection-repair caveat was checked:
  the sole projection belongs to empty topic_facet_summaries; no active parts
  had lightweight deletes and there were no unfinished mutations. No repair ran.

An independent candidate worktree at current main02efa4ec99e4ff7df22107aad3c6e20a0b67168d
validated only these three image substitutions. Full local verification passed
23 Applications/561 resources, separately from live results. Recovery work and
ignored private evidence remain in the original task worktree.

Each PR was merged with its exact reviewed head precondition, independently read
back, then held for successful main Verify at its own merge SHA:

| PR | Merge SHA | Successful main Verify |
| --- | --- | --- |
| [#106](https://github.com/benkim0414/homelab/pull/106) | `bcfbca02f642dc1caaee414fe6412e9e0c1d804d` | [45316405398](https://github.com/benkim0414/homelab/actions/runs/45316405398) |
| [#107](https://github.com/benkim0414/homelab/pull/107) | `110d4992202c20ca0f433bc47b73201d298b2a87` | [45317529143](https://github.com/benkim0414/homelab/actions/runs/45317529143) |
| [#111](https://github.com/benkim0414/homelab/pull/111) | `e8584fce6e81a842abb0d27812fee24a28c933d5` | [45318395016](https://github.com/benkim0414/homelab/actions/runs/45318395016) |

Normal ArgoCD MCP authentication worked. At each exact revision the full resource
status inventory had only the selected workload OutOfSync. Its normalized/live
diff changed only server/init images for Valkey/PostgreSQL and only server image
for ClickHouse. Reviewed scripts preserve AOF/PGDATA; existing Secret references,
claims, retention, resources, exposure and placement are unchanged. UID/RV/spec
CAS operations selected only that Deployment/StatefulSet, with exact ordered
chart/Git revisions, retry0, prunefalse, forcefalse and replacefalse. No hook,
root sync, migration replay, claim replacement or schedule change occurred.
Exact old-container termination watches observed exit0 for all three datastores.

Live verification passed after each rollout before the next merge/rollout:

- Valkey reports8.0.13 and authenticated PING/AOF checks pass, with233 keys and
  canonical counts delayed6/repeat6/failed23 preserved; other counts zero.
  Writers stayed active. Scheduler content fingerprints advanced naturally;
  this is not frozen fingerprint equality or continuous queue-drain proof.
- PostgreSQL reports18.7 PGDG+5,470 finished/zero unfinished migrations, with
  owner/project/API-key row counts1/2/2 preserved and no reseeding.
- ClickHouse reports26.8.42.13, latest schema migration56 clean, and all14
  MergeTree CHECK TABLE summaries return exact integer1. Existing events_core
  aggregate counts remain515 rows/515 unique span IDs/92 unique trace IDs.
  A first read-only aggregate assertion used the wrong column assumption and
  was corrected from actual system.columns before any ClickHouse merge.
  Query-level summary SETTINGS was then correctly refused164 READONLY; putting
  that output-shape option in client initialization preserved verified readonly1
  and passed all checks. Neither refusal indicated corruption or changed policy.

The worker had one clean exit0/restart at03:13:53Z during the PostgreSQL gap;
bounded previous-log classification found57P01/P1001 and no OOM. It recovered
Ready without intervention; its restart count stayed1. This is recorded rather
than claiming zero dependent-workload disruption. Final repeated samples over
62.71 seconds found all six source workloads Ready with stable restart counts,
all four original volumes healthy/two replicas and unchanged claim bindings.
Private HTTPS health/ready returned200/statusOK/version4.77.0; the Application
is Synced/Healthy at the final reviewed revision and still uses manual sync.

Consolidated immutable evidence:
`verification/cache/langfuse-recovery/first-restore-three-upgrades-complete-62ecb69345514c8f839c89bed2c0218a.json`.
It links separate per-datastore native/live receipts. Recovery resources and
failed/accepted evidence were retained. No fresh production-ingestion test was
performed: the explicit profile-key test authorization was isolated-only, and
that earlier successful recovery ingestion is not relabelled as a production
post-upgrade test. Secondary Vaultwarden custody remains operator-reported.
Existing PRs were merged; local recovery implementation/report changes have not
been committed or pushed, and candidate-worktree edits have not been discarded.

### Close-out production smoke attempt and publication review (2026-11-24)

The operator requested the recommended close-out. Only this task's public source,
focused tests and report were copied into a dedicated current-main close-out
worktree. The original task and candidate worktrees, private receipts, archives,
age identities, operation inputs and failed attempts were preserved; no private
cache was copied into the publication candidate. This is documentation/source
publication, not permission to replay the historical mutating helpers.

An ordinary new `homelab-scientist` CLI turn used the existing repository desktop
launcher with explicitly selected openai-codex/gpt-6.1-sol. Native settings
inspection confirmed no configured inference fallback or custom shell hooks.
The first invocation was rejected before session creation because the CLI's
advertised optional run-budget setting was unsupported by its initialization
path. The next invocation omitted only that option, retaining an external
owned-process-group timeout and the same provider/model. It exited0, produced
the exact requested benign reply and reported no provider fallback. No manual
project-key access, tracing reconfiguration, enrollment or provider change was
performed.

**Production tracing acceptance did not pass.** Bounded read-only native queries
found zero matching observations in both events_core and events_full for the
new session, and zero new core rows since the successful turn started. Enabled
plugin metadata is not proof of registered hooks/export. No alternate ingestion
was submitted, no key-only scope or default-Cloud client was constructed, and
no guard or configuration was weakened to manufacture a trace. Before the
ClickHouse rollout, the latest core event's created_at was already2026-11-22;
the absence does not establish that the datastore upgrades caused this gap.
Further client-tracing repair is outside this frozen close-out unless separately
approved. The successful isolated restore ingestion remains separate evidence.

Private attempt/readback metadata remains in the original task cache:
`verification/cache/langfuse-recovery/production-smoke-c3027503dcf94d4782be0dba3aca4d8f-execution.json`
and
`verification/cache/langfuse-recovery/production-smoke-423623d6656f4521b03e7a65eac2b779-readback.json`.
The failed pre-session attempt was retained too. Secondary Vaultwarden custody
still requires the operator's private retrieval check; no private key or master
password was requested or read. Publication review and local/CI validation must
not be described as passing this outstanding production trace or custody gate.

### Publication safety review — post-execution source corrections

Independent read-only reviews identified two publication blockers in the original
helper bytes: watch events could be classified against a later allowed-exit set,
and malformed OCI whiteout basenames could select the extraction root/parent for
deletion. Generated reproductions used mocked/synthetic I/O only. Neither review
examined confidential archives or establishes that the historical capture was
affected. Original executed sources and immutable receipts remain preserved in
the first task worktree; publication corrections must not be relabelled as the
bytes used by that accepted operation.

The publication copy now rejects empty/dot/dot-dot whiteout targets before any
deletion, confines the target lexically without following its final symlink,
and tests valid replacement/opaque behavior and outside-sentinel preservation.
All12 offline extraction safety tests passed. Restoring the pre-fix branch only
in a generated in-memory function made all six reserved-target regression
subcases fail as expected, with deletion mocked throughout. The existing offline
suite was added to the existing Verify job; no native engine or live operation
is run by that addition.

The publication watch correction now processes a fresh watch progress barrier
before mutation intent and replaces decode-time exit permission with committed
CAS-RV boundaries, serializing acknowledgement against event decoding. Delayed
pre-intent/pre-CAS contradictions, equal or opaque boundaries, missing progress
and genuine later shutdown were tested with the real reader/guard and generated
I/O.89 focused non-native tests passed repeatedly in the implementation review.

Crucially, shared Pod/Deployment revision ordering is not established merely by
numeric RV syntax or the existing operation inputs. **The publication live
adapter therefore refuses pause before journal intent or mutation**, with
`pause-watch-ordering-unproven` (sanitized to `operation_failed` by WriterGuard).
No operational bypass was added. Positive algorithm cases explicitly substitute
a shared-revision generated fixture; they are not live server evidence. This
closes unsafe publication admission by refusal, not by claiming a working,
newly live-verified capture path. No original capture or restore was replayed.

The reviews also confirmed an execution limitation rather than another code
expansion: capture staging byte budgets are post-write admission checks, not
enforced filesystem ceilings. PostgreSQL lacks a fragment-level free-space
precheck; ClickHouse/SeaweedFS can exceed their prechecked budgets, and SeaweedFS
stages copies plus an outer archive on the source filesystem. The helper README
now makes this explicit. Any future separately authorized reuse needs independent
capacity/enforcement review; no new backup, quota, schedule or replay was added.

Final local publication validation exercised646 discovered tests with91 explicit
skips and no failures/errors, plus12 offline OCI/extraction safety tests and9
policy tests. The pinned public desktop delegate source was downloaded and its
expected hash verified, so its guard tests were not silently skipped for a
missing workstation checkout. One unrelated Herdr Unix-socket test initially
hit the host's long scratch pathname limit; it was subsequently run unchanged
through a short held-FD alias to the approved scratch directory, including its
real positive/negative peer checks. Every other discovered test used the normal
scratch path. No health guard, assertion or repository test was weakened.

Full render/schema/policy/secret-scan validation passed23 Applications/561
resources against the publication base; actionlint, relative documentation links
and whitespace checks also passed. These are local/source results, not another
native engine rehearsal or a production trace acceptance result. Backup-looking
messages emitted by repository unit fixtures were mocked test output, not new
NAS backup executions. Remote PR publication and exact-head CI remain separate
steps and must be read back before being reported as completed.

Draft publication PR [#125](https://github.com/benkim0414/homelab/pull/125) was
created from reviewed commit `0d1022bdd459a585c7d3c7ac3b0137eade05a82f` and its
remote branch/head/file scope was read back. Initial exact-head
[Verify run45324424126](https://github.com/benkim0414/homelab/actions/runs/45324424126)
failed because the clean CI runner lacks `bwrap` for the generated native-age
class setup. That failure is retained, not a passing native result. The class
now explicitly skips unsupported Linux/architecture/bubblewrap/memfd hosts before
downloads or generated-key setup, without any unsandboxed fallback or changes to
production guards. Local native execution and clean-CI skips remain distinct.

The follow-up Verify run45325174540 then exposed an implicit test-order dependency:
the mandatory coordinator round trips expected the public age tools to have been
prepared by the now-skipped bubblewrap class. CI now prepares only those existing
checksum-pinned public executables explicitly before discovery. The coordinator
tests still fail if real age/age-keygen are missing; they are not skipped or
replaced with simulated encryption. No key generation occurs in the preparation
step, and no production authentication or datastore execution is involved.
