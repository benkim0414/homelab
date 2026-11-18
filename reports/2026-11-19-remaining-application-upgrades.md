# Remaining application upgrades — 19 November 2026 AEDT

Verified on 18 November 2026 UTC / 19 November AEDT. This is a partial-completion
record: three target upgrades deployed; Loki held on its original healthy runtime.
It does not declare the original upgrade-all objective complete.

## Authorization and publication

The operator requested upgrading Hermes, monitoring, Loki and Hindsight until
healthy. Explicit approval covered the formerly denied isolated Hindsight database
rehearsal, app-scoped commits/push/PR/merge after CI, then bounded backup maintenance
and the protected named admission Secret migration/RBAC effects.

[PR101](https://github.com/benkim0414/homelab/pull/101) published the candidates as
four app-scoped commits. Main `dfdb91d69f013db62b35e3aefa13e80ee21dfe6e` passed
[Verify44286251169](https://github.com/benkim0414/homelab/actions/runs/44286251169).
That exact revision was used for deployments; manual sync and disabled features
were preserved. No root-wide sync, prune, force/replace, claim recreation,
credential rotation or new schedule was used.

## Live outcome

| Track | Actual runtime | Observed state |
| --- | --- | --- |
| Hermes | Gateway/browser 0.23.2; matching init/backup runners | Synced / Healthy / Succeeded |
| Monitoring | Chart 93.4.0; operator/reloader 0.95.2; Prometheus 3.16.0; Alertmanager 0.35.0; Grafana 13.3.1 | Synced / Healthy / Succeeded |
| Hindsight | Chart/API/UI 1.2.1, API/UI index-pinned | Synced / Healthy / Succeeded |
| Loki | Original 3.6.11/chart 7.3.0; candidate 3.7.10 not deployed | Healthy / OutOfSync; diagnosis held |

Programmatic comparison of the fixed four-app cohort against the original
inventory verified three target-image cohorts, all original claim/volume identities
unchanged, all selected workloads Ready, and manual sync preserved. Five nodes were
Ready without memory/disk/PID pressure; all 34 cluster PVCs were Bound. Prometheus
reported 32/32 scrape targets up and zero critical firing alerts. The earlier
API-server recording-rule timeout and KubeJobFailed alerts were no longer firing;
Watchdog intentionally fires and OffsiteBackupMissing remains a separate warning.
No alert was disabled or silenced to obtain this result. Grafana reported database
OK and version 13.3.1 through external HTTPS; authenticated datasource queries worked.
This is app-scoped live verification, not a full security/private-error-log audit.

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
| Loki 10Gi | `upgrade-loki-20261118212931-22c862` |

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

## Loki blocker — do not bypass

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
Continuation needs explicit isolated Loki diagnosis reauthorization, a verified
fixture fix if warranted, successful replay/recovery evidence, then the reviewed
Loki-only rollout and actual ingestion checks. Do not silently waive those gates.

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
