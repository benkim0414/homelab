# Remaining application upgrades — 19 November 2026 AEDT

Updated through 19 November 2026 UTC / AEDT. All four requested target runtimes
are deployed and app-scoped live verification passed. Broader health closeout is
not all-clear: recurring Prometheus rule timeouts and k3s-03 resource warnings
remain. This does not close the original all-application inventory/owner-acceptance
work or assert that the entire cluster is warning-free.

## Authorization and publication

The operator requested upgrading Hermes, monitoring, Loki and Hindsight until
healthy. Explicit approval covered the formerly denied isolated Hindsight database
rehearsal, app-scoped commits/push/PR/merge after CI, then bounded backup maintenance
and the protected named admission Secret migration/RBAC effects.

[PR101](https://github.com/benkim0414/homelab/pull/101) published the candidates as
four app-scoped commits. Main `dfdb91d69f013db62b35e3aefa13e80ee21dfe6e` passed
[Verify44286251169](https://github.com/benkim0414/homelab/actions/runs/44286251169).
That revision was used for the first three deployments. Loki subsequently used
documentation-only successor `5031b2358064cbfd2aa333422758e31a5d5bb81b`, after exact
Verify run 44409989931 passed. Manual sync and disabled features were preserved.
No root-wide sync, prune, force/replace, claim recreation,
credential rotation or new schedule was used.

## Live outcome

| Track | Actual runtime | Observed state |
| --- | --- | --- |
| Hermes | Gateway/browser 0.23.2; matching init/backup runners | Synced / Healthy / Succeeded |
| Monitoring | Chart 93.4.0; operator/reloader 0.95.2; Prometheus 3.16.0; Alertmanager 0.35.0; Grafana 13.3.1 | Synced / Healthy / Succeeded |
| Hindsight | Chart/API/UI 1.2.1, API/UI index-pinned | Synced / Healthy / Succeeded |
| Loki | Runtime 3.7.10 / c792f585, index-pinned; chart 7.3.0 unchanged | Synced / Healthy / Succeeded |

Programmatic comparison of the fixed four-app cohort against the original
inventory verified all four target-image cohorts, all original claim/volume
identities unchanged, all selected workloads Ready, and manual sync preserved.
Five nodes were Ready without Kubernetes memory/disk/PID pressure conditions;
all 36 cluster PVCs were Bound, including retained recovery-test claims. Those
conditions do not negate the utilization warnings below. Prometheus reported
32/32 scrape targets up. Grafana reported database OK/version 13.3.1 and normal
authenticated datasource queries worked. Loki's observed live behavior is below.

At the initial post-Loki alert inspection, **PrometheusRuleFailures was firing critically**:
30-day API-server recording rules timed out expanding series on the Ready,
zero-restart Prometheus Pod. The same group had failed before the stack upgrade,
cleared temporarily, then recurred. k3s-03 was at 92% memory with disk-I/O/load
warnings. No causal relationship to the Loki rollout is established. Read-only
capacity diagnosis found Prometheus using 1,405Mi against a 512Mi request and
1,536Mi limit. The rule group took 282.79s against its 180s interval. These facts
support capacity/placement contention, not a proven regression or proven device
attribution. k3s-04 was at 37% memory versus k3s-03 at 92%; a placement/resource
correction is the recommended separate scope, subject to destination scheduling,
Longhorn/device mapping, replica health and backup/recovery preflight. Moving the
single-replica RWO workload requires a planned monitoring interruption; no such
move, restart, rule/timeout/resource change was performed. KubeJobFailed refers to preserved
old recovery-openclaw integrity-check evidence; it was not deleted to clear the
warning. OffsiteBackupMissing remains and Watchdog is intentionally firing.
This is not a clean global-health, full security or private-error-log audit.

The subsequent placement preflight found one recovered Prometheus OOMKilled/137
at 05:00:20Z. Earlier zero-restart samples above do not describe that later event.
The operator requested proceeding; a selector/resource correction was prepared,
then published and applied after explicit approval. Its
[separate maintenance plan](2026-11-19-prometheus-placement.md)
records confirmed sde attribution, destination capacity, unchanged volume identity
and the publication/checkpoint/selective-sync gates.

### Prometheus capacity correction — deployed, sustained acceptance pending

PR103/main b8c07ea9 passed exact-main CI. After a preserved wrapper error before
any pause and a separately authorized corrected attempt, fresh cold full backup
`upgrade-prometheus-20261119095749-1536cc` completed; both containers stopped
normally with exit 0 and the original resumed. One selective Prometheus-CR apply
then moved its writer to k3s-04 with 500m/1536Mi requests and a 2Gi memory limit.
Image digest, all original CR/StatefulSet/PVC/PV/CSI identities, rules, timeouts,
retention and manual sync remained unchanged. No admission hook or other
monitoring workload was restarted. Argo reports Synced/Healthy/Succeeded and the
new Pod is Ready with zero restarts. Fifteen-minute performance/memory/rule/target
observation is in progress; this is not yet a completed sustained-health verdict.

## Recovery points and checks

Cold whole-volume backups were taken after observed normal container shutdown,
zero remaining claim consumers and ordinary detach, then the same originals were
resumed Ready. All backups completed without retention deletion:

| Application | Verified NAS backup |
| --- | --- |
| Hermes 20Gi | `hermes-20261118-210359-82e28aee` |
| Grafana 2Gi | `upgrade-grafana-20261118211504-444b7b` |
| Prometheus 20Gi | `upgrade-prometheus-20261118211558-76eae9` |
| Alertmanager 2Gi | `upgrade-alertmanager-20261118212130-dee9ed` |
| Loki 10Gi, recovery-tested representative checkpoint | `upgrade-loki-20261118212931-22c862` |
| Loki 10Gi, final verified cutover checkpoint (not separately restored) | `upgrade-loki-20261119031623-8e8429` |

Prometheus/Alertmanager pauses used their owning CR replica fields; reconciliation
was not bypassed by scaling operator-managed StatefulSets. Retain/Retain and empty
claim owner references were checked before cold maintenance; backing production
PVs still have Delete reclaim. Never delete claims/namespaces as recovery cleanup.

Grafana's fresh independent restore passed read-only SQLite integrity and schema
checks (92 tables), not full application/encrypted-setting acceptance. Alertmanager
0.35.0 loaded its fresh restore with inert routing/no peers, passed HTTP readiness
for 25 seconds, and stopped normally with zero restarts. Prometheus 3.16.0 opened
restored blocks and replayed WAL at the production 1536Mi budget, but restore/CSI
attachment consumed its first Pod deadline. The failed test was preserved. One
corrected readiness check on the already-restored target copy passed for 25 seconds,
zero restarts and normal exit 0; production limits were not increased to pass it.

Hindsight's real opaque PG17.8/pgvector 0.8.1 rehearsal migrated the target twice
and independently restored the old version, preserving 24 original-table counts.
The final cutover separately stopped the sole API/worker with observed exit 0,
excluded database clients, fully parsed a new dump and verified its workstation
copy against producer byte count/hash and independent remote hash readback.
Final dump Job: `hindsight-upgrade-20261118t213530z-607173cd`. The original DB/grant
claims were retained. Live migration `c8e2f4a6b1d3`→`05867433a58c` preserved 3 banks,
2 aliases and 8 memory units, with no invalid/unready indexes. Health, REST 401 for
absent credentials, and normal project-bank recall/reflect passed. No test memories
were retained. No grant clone, reauthentication, model/provider change or paid
fallback was introduced; expiry-driven refresh and new-retain acceptance were not
exercised. A database recovery requires the matching original checkpoint, not an
image downgrade against the migrated schema.

## Admission migration and orchestration lesson

Only `monitoring/kube-prometheus-stack-admission` was read through the approved
protected pipeline. SAN/CA-chain/key-pair and webhook-CA consistency passed. The
original Secret and public webhook configuration were strictly sealed outside app
raw-manifest globs. NAS ciphertext copy/readback hashes and controller decryptability
were verified. No plaintext private key was written/displayed; controller private
keys or external disaster-recovery custody were not inspected or claimed.

Packaged 0.95.2 CRDs were applied/Established before the operator. The approved hook
converted Opaque→TLS, retaining legacy entries with matching standard aliases.
The initial hook-enabled sync was marked Failed during transient Prometheus/
Alertmanager init-container health; actual workloads subsequently reached the
reviewed target images, Synced/Healthy and Available/Reconciled=True. Failed history
was saved before any follow-up. One reviewed completion sync ran the PostSync CA
hook with unchanged TLS Secret UID/data, matching webhook CA, unchanged original
claims, and no workload replacement/restart. This is not permission to automatically
retry migrations or weaken health checks. First distinguish a transient orchestration
race from an actual application/configuration failure.

Grafana was explicitly paused before that full rollout: its declared RollingUpdate
strategy otherwise allows old/new processes to overlap on the same SQLite claim.
The old writer's normal shutdown was observed before the new version started.

## Historical Loki holds and validation corrections

Two independent whole-volume test restores for old 3.6.11 and target 3.7.10 exited 1
before readiness, with zero restarts and no observed OOMKilled status. Restore/
replay acceptance, historical queries and synthetic-ingest/restart acceptance were
not established. Further startup diagnosis was tool-denied. The scoped prompt to
reauthorize redacted diagnosis plus one corrected isolated test timed out unanswered.
Earlier general rollout approval is not authorization to retry that denied step
or deploy to avoid it. Production remains Ready on 3.6.11 with the full NAS backup
preserved; the 512Mi limit, WAL/config and original volumes were not changed.

The failed target/baseline test namespaces, fresh Retain clone volumes, failed
monitoring test and all backup evidence remain preserved. No cleanup was performed.
The operator subsequently approved redacted diagnosis and one corrected batch.
Memberlist's separate advertise-address auto-detection was rejecting loopback;
explicit fixture-only bind/advertise addresses removed that error. The batch
stopped at baseline readiness, without starting the target. The baseline later
exited normally at its Pod deadline with zero restarts/no observed OOM.

Read-only post-test diagnosis found a missing executable in the shell-based
readiness probe. Final logs contain a full WAL-recovery marker and `Loki started`.
This corrects the initial incomplete-recovery interpretation: a broken probe is
not evidence of WAL corruption or failed recovery, but it supplies no HTTP/query
acceptance either. The target startup/count/durability checks were not executed.

The approved single-use attempt is consumed. A subsequent scoped request for one
helper-based isolated batch timed out unanswered. Continuation requires that
fresh test authorization, valid runtime-native readiness/query/recovery evidence,
then the reviewed Loki-only rollout and live ingestion checks. Do not silently
waive those gates, retry, or change the 512Mi budget/network isolation. All three
completed Applications were rechecked Synced/Healthy/Succeeded; Loki remains
Healthy/OutOfSync on 3.6.11. Follow-up receipts remain protected in
`loki-restore-verify/{corrected-receipt,corrected-final-evidence,corrected-readiness-diagnosis}.json`.

The operator next explicitly approved one helper-based batch. Both old/target
versions completed full WAL recovery and real HTTP/Pod readiness for over
25 seconds at unchanged 512Mi, then stopped normally; Loki and helper containers
all exited 0, with zero restarts/no observed OOM. The historical aggregate at
`2026-11-18T21:29:10+00:00` differed: baseline 1,144 versus target 699. The batch
stopped at that gate. Synthetic writes, collision queries, durability restart and
production rollout were not attempted. Both clone Pods were independently read
back as Succeeded with matching UID handles. Production remains unchanged/Ready.

Count-mismatch cause is undiagnosed; do not infer data loss or accept the upgrade.
Only offline comparison of saved requests, metadata and public source is active;
no new native test/restore is authorized by the consumed batch. Preserve
`loki-restore-verify/helper-receipt.json` and `helper-final-readback.json`.

Offline comparison verified identical instant query, five-minute window and
timestamp, matching tenant behavior and byte-identical configs, with a common
backup origin. The clones were not equivalently conditioned: baseline had a
previous 583-second engine run; target did not. This is a confound, not an
established explanation or data-loss proof. WAL recovery counters describe replay
work, not unique stored-log totals. A fresh-pair comparison was proposed but its
approval prompt timed out; no new native experiment was started. Local-only
numeric/empty-vector checks passed three tests; those are not native Loki tests
or upgrade acceptance. The consumed helper/evidence hashes remain unchanged.

The operator subsequently approved one clean fresh-restore batch. Two new Retain
10Gi copies had matched virgin engine histories and both-test-only
`querier.query_ingesters_within: 0s`. Native WAL/HTTP readiness, acknowledged target
write, metadata-collision counts and normal-restart durability passed at 512Mi;
all containers exited 0 without restarts/observed OOM. Historical counts matched
at 1/1/1, passing the script's internal gate, **not** the broader data-preservation
acceptance. The original producer's monitoring-only count was 983 at that same
window, so equal restored counts of 1 remain suspiciously incomplete.

Parent live readback verified four unique completed Pods and two independent
Retain/detached restore volumes, plus unchanged Ready production. This is recorded
as `HISTORICAL_COVERAGE_NOT_ACCEPTED` in `fresh-parent-review.json`; the reported
native successes are retained, not discarded or promoted to full acceptance.
Only offline analysis continues. No additional application start, restore or
production rollout was made after the batch, and no new attempt is authorized.

Subsequent offline source/query-stat review proved that the 1/1/1 requests never
reached ingesters: single-binary module initialization derives another lookback
that overrides the zero querier setting. After a separately approved focused
24h test-only ingester/store-lookback check, baseline returned 1,478 with actual
ingester participation, monitoring 983. Its old 1,144 assertion failed and stopped
the batch before target startup. Parent independently queried the producer's ten
corresponding namespaces: all counts matched baseline, totaling 1,478. The old
cutoff-affected control was invalid; this is not evidence of baseline data loss.

The preserved failure receipt is supplemented, not overwritten, by
`coverage-producer-control.json`. Parent read back baseline Pod
`58c8bdaa-4048-4800-ae6a-1d518815c7f9` as Succeeded, both containers exit 0 and zero
restarts. The target-only coverage authorization prompt timed out; no target test
or production rollout followed. The three upgraded apps remain Synced/Healthy,
while Loki remains Healthy/OutOfSync on its original runtime. The next gate is
target agreement with this independently checked historical sample and actual
ingester participation; no new restores or synthetic writes are needed.

## Final Loki rollout and live checks — 19 November UTC

The separately approved target-only coverage check passed all ten independently
checked namespace controls: 1,478 total/monitoring 983, with positive ingester
participation. Both containers exited 0 without restarts/OOM. This completed the
representative historical recovery gate alongside earlier target replay,
collision-semantics and acknowledged-write normal-restart checks at 512Mi.
It does not establish equivalence of every stored log record.

Fresh full NAS checkpoint `upgrade-loki-20261119031623-8e8429` then completed;
the old writer stopped/resumed normally and all prior backups remained intact.
One reviewed Loki-only operation applied chart 7.3.0 plus Git5031b235..., with no
prune/force/replace. Argo sync succeeded before the new Pod was Ready; the early
verification assertion was preserved, then rollout/behavior verification continued
without resubmitting the operation. StatefulSet UID, original claim/PV/CSI volume,
Delete reclaim/Retain retention and all ConfigMap data hashes stayed unchanged.

Production buildinfo is 3.7.10/c792f585. The same ten live historical namespace
counts matched 1,478/983. All five nodes supplied recent logs in a window wholly
after target startup. Over 305.3 seconds and 21 samples, readiness held with zero
restarts/no observed OOM; maximum sampled working set was 82Mi of 512Mi. The
test-only 24h query lookback and loopback/ring overrides were not deployed.

An optional version-only probe-Pod creation request failed with nonzero API exit;
no matching probe resources existed on independent readback, and no retry occurred.
The precise API cause was not retained/classified. Actual existing-collector
count-only queries, not synthetic probe claims, established five-node ingestion.
Collector drop counters were unavailable even after broader metric discovery, so
zero dropped entries is not claimed. No old tests, volumes or jobs were cleaned up.

Workspace proofs include `target-only-count-evidence.json` (under the rehearsal
directory), `loki-production-verification.json`, `loki-live-behavior.json` and
`live-final-four-20261119.json`. The first rollout-verifier failure remains intact.
The unchanged 4GB WAL replay ceiling is not a whole-process bound and remains a
capacity risk beyond this measured checkpoint/workload. The separate monitoring
critical alert and node-capacity follow-up remain open.

## Evidence and acceptance limits

Workspace-only receipts are under
`verification/cache/four-upgrades/` in the assigned task worktree, including
`hermes-rollout.json`, `hindsight-final-cutover.json`,
`monitoring-initial-transient-health-failure.json`,
`monitoring-completion-receipt.json`, `live-verification-20261118T2206Z.json`,
`loki-restore-verify/receipt.json` and the retained restore-test receipt directory.
They contain sanitized structural metadata; private full logs and opaque dumps
remain ignored/protected and are not publication artifacts.

Local manifest validation passed 21 Applications/520 resources; the final unit run
passed 192 tests with 6 optional/historical skips. Those and exact-SHA CI are separate
from the live results above. Owner-level Hermes chat/browser/tracing privacy,
Hindsight expiry refresh/new-retain and interactive Grafana login acceptance were
not all exercised. No result here claims full private-row equivalence, universal
network confinement, offsite resilience or completion of all four upgrades.
