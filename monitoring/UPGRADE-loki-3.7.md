# Loki 3.6.11 → 3.7.10: image-only upgrade

**Deployed and live-verified on 19 November 2026 UTC.** Keep chart **7.3.0** and
manual sync. This was not a community-chart migration or a production tuning change.

## Verified production rollout

The reviewed Loki-only operation pinned chart 7.3.0 and Git revision
`5031b2358064cbfd2aa333422758e31a5d5bb81b`, after exact-revision Verify run
44409989931 passed. The complete 12-resource generated/live diff contained only
the Loki image and version labels: no runtime-config, storage, selector, service,
RBAC or hook changes. Prune/force/replace remained disabled.

Fresh cold full NAS backup `upgrade-loki-20261119031623-8e8429` completed after
observed exit 0 and ordinary detach; the original 3.6.11 writer resumed before
rollout. This final archive was verified, not separately restored. Recovery,
target replay, representative historical data and acknowledged-write restart
durability were exercised on the earlier whole-volume checkpoint described below.
All checkpoints, original/copy volumes and failed evidence were preserved.

Production API buildinfo reports **3.7.10 / c792f585**. The live historical sample
matches all ten independently checked namespace controls, totaling **1,478**,
including monitoring **983**. Post-upgrade count-only queries confirm recent logs
from all five nodes. Over 305 seconds/21 samples the Pod remained Ready with zero
restarts/no observed OOM; maximum sampled working set was **82Mi** of unchanged
512Mi. This is not worst-case capacity proof; the default 4GB replay ceiling
remains a separately reviewed capacity risk.

ArgoCD reports Synced/Healthy/Succeeded. Its operation completed before Pod startup
finished, so the first verifier assertion failed; that record was preserved and
verification continued without resubmitting the sync. Original StatefulSet,
PVC/PV/CSI identities, reclaim/retention policies and all three ConfigMap data
hashes are unchanged. No loopback/query-lookback rehearsal override was deployed.

The optional per-node version-probe creation request returned nonzero before any
matching probe Pod existed; it was not retried. Ingestion acceptance used actual
existing-collector logs in a window wholly after target startup, not those probes.
The cohort report separately records a recurring Prometheus rule timeout and
k3s-03 resource warnings; this is not an all-clear cluster-health claim.

## Historical preparation and recovery-test record

The dated holds below are preserved as history and superseded by the verified
rollout above. A failed test or timed-out approval never authorized its own retry.

On 18 November 2026 UTC, approved maintenance produced cold full NAS backup
`upgrade-loki-20261118212931-22c862` after observed normal exit 0; the original
3.6.11 writer resumed Ready on its unchanged claim. Two independent restored
test copies, old 3.6.11 and target 3.7.10, both exited 1 before readiness. Neither
showed OOMKilled, but replay/restore acceptance was not established. Further
startup diagnosis was tool-denied; its explicit reauthorization prompt timed out.
Do not infer approval to retry from the earlier general rollout approval or
deploy to bypass the failed gate. Production remains 3.6.11, Healthy/OutOfSync.
Preserve all original/clone volumes and failed evidence. See the
[cohort rollout record](../reports/2026-11-19-remaining-application-upgrades.md).

### Authorized follow-up: corrected test still inconclusive

The operator subsequently approved redacted diagnosis and one corrected batch.
The original failure was memberlist's separate advertise-address auto-detection
rejecting the isolated loopback interface. Explicit fixture-only memberlist
bind/advertise addresses resolved that error; persistent configuration and the
512Mi Loki limit were unchanged.

The batch stopped at baseline readiness; target startup was not attempted. The
baseline later exited normally at its Pod deadline, with zero restarts/no observed
OOM. Read-only event classification then identified a missing executable in the
shell-based readiness probe. Final logs contain a full WAL-recovery marker and
`Loki started`; the timeout therefore does **not** establish failed WAL recovery.
HTTP readiness, historical queries and target durability are still unproved.

That single-use attempt is consumed. The subsequent request for one helper-based
isolated batch timed out unanswered. Do not retry, deploy, increase Loki's memory
limit or relax networking implicitly. A further authorized test must avoid shell/
wget assumptions in the service image, retaining loopback/deny-all isolation and
the unchanged Loki budget. Preserve `corrected-receipt.json`,
`corrected-final-evidence.json` and `corrected-readiness-diagnosis.json` alongside
the original evidence in the ignored rehearsal cache. Production remains 3.6.11.

### Helper-based batch — 19 November 2026 UTC

The operator then explicitly approved one helper-based batch. Both pinned
versions completed full WAL recovery and sustained loopback HTTP/Pod readiness
for over 25 seconds at the unchanged 512Mi limit. Both Loki/helper pairs stopped
normally with exit 0, zero restarts and no observed OOM. The helper resolved the
missing-executable problem without changing production or network isolation.

Acceptance nevertheless failed: the historical aggregate at
`2026-11-18T21:29:10+00:00` returned **1,144** on the baseline copy and **699** on
the target copy. The batch stopped there; synthetic/collision/restart-durability
checks and production rollout were not attempted. The cause is undiagnosed;
this is not proof of data loss and is not upgrade acceptance. Saved evidence is
being compared offline without another application start or restore. Preserve
`helper-receipt.json` and `helper-final-readback.json`; no retry is authorized by
that consumed batch. Production remains Ready on 3.6.11 with unchanged data.

Offline review verified the same instant query, five-minute interval, timestamp,
tenant behavior and byte-identical main/runtime configs. Both restores came from
the same completed backup, but the baseline copy had already run its engine for
583 seconds in the earlier probe-broken attempt; the target had no equivalent
successful preconditioning. This is a proven comparison confound, not proof that
it caused the count difference. WAL recovery metrics count replay/checkpoint work,
not the logical population of that historical query. No data-loss conclusion or
upgrade acceptance follows from them.

One clean comparison on two fresh, equivalently conditioned restores was proposed;
its authorization prompt timed out unanswered. It has not run. Before a future
authorized comparison, control query age/ingester eligibility across both runs,
not just the shared timestamp; do not cross a time-based query cutoff unnoticed.

### Authorized fresh comparison: native checks passed, historical coverage held

The operator approved one new fresh-pair comparison. Two new independent Retain
10Gi restores used identical first-start conditioning and the documented
test-only `querier.query_ingesters_within: 0s` override. Both completed WAL
recovery/readiness at unchanged 512Mi. The target acknowledged one synthetic
write and preserved it and the expected metadata-collision behavior across a
normal restart. All test containers stopped with exit 0, zero restarts/no observed
OOM; both restore volumes are retained/detached and production remains unchanged.

The batch's internal positive/equal-count gate passed **1 / 1 / 1**, but this is
not sufficient historical-preservation acceptance. At the same timestamp/window,
the original producer returned **983 for monitoring alone**, while these restored
copies returned only 1 across all nonempty namespaces. Parent readback verified
the exact successful Pod/Retain-volume identities and explicitly held acceptance
in `fresh-parent-review.json`. No production rollout was performed. Read-only
analysis of saved/public query/config/restore evidence is active; no new native
attempt is authorized by the consumed fresh batch. Preserve all fresh evidence.

### Coverage correction and independently checked baseline

Saved query statistics established zero ingester requests in the 1/1/1 test.
Both pinned single-binary module implementations derive an ingester/store
lookback and copy it into a querier field that takes precedence over
`query_ingesters_within`. Parse-time config validation does not expose that later
module mutation. Thus the earlier 0s override did not establish WAL query coverage.

The operator approved a focused check with test-only
`ingester.query_store_max_look_back_period: 24h`. Baseline reached the ingester
and returned 1,478 globally, including monitoring 983. The script stopped before
the target because its old 1,144 control was cutoff-affected and invalid. Parent
then independently queried the producer for all ten returned namespaces: every
per-namespace count matched the restored baseline exactly, totaling 1,478. This
validates that representative baseline sample, not all stored log contents.

The baseline stopped normally; production remains unchanged. Preserve the failed
control assertion and its successor `coverage-producer-control.json`; do not edit
the failed receipt to claim success. The target-only approval prompt timed out.
No target coverage attempt or production upgrade has run. A further approved
target-only check must match the independently verified namespace counts and
demonstrate actual ingester participation, at unchanged 512Mi/deny-all isolation.

## Reviewed target and upstream changes

The [3.7.10 release](https://github.com/grafana/loki/releases/tag/v3.7.10)
was published 2026-11-13T07:51:25Z. The
[3.7.9…3.7.10 source comparison](https://github.com/grafana/loki/compare/v3.7.9...v3.7.10)
and release notes add configurable TLS curve preferences, fix internal-server
shutdown deadlock and ingester autoforget goroutine shutdown, and fix accepting
new Logs Drilldown series after its limit trips. Dependency updates include
`golang.org/x/net` and `golang.org/x/crypto` security updates. The Multipath TCP
default-disable change is explicitly **reverted** in the same release; do not
present it as an effective protection. No TLS/auth/listener settings are changed
by this candidate. The canary query API fix does not enable our disabled canary.

Relative to **3.6.11**, review the full
[3.7 release notes](https://github.com/grafana/loki/blob/v3.7.10/docs/sources/release-notes/v3-7.md)
and [upgrade guide](https://grafana.com/docs/loki/latest/setup/upgrade/):

- Parsed labels no longer override structured metadata: check representative
  LogQL extraction/collision queries and dashboards, not only readiness.
- New query-engine scheduler changes are not an engine migration here; effective
  `query_engine.enable` and `dataobj.enabled` remain false. Promtail removal in
  3.7.3 does not require changing the existing Alloy collector.
- Included WAL fixes address replay hangs (3.7.3), an ingester flush race (3.7.5)
  and concurrent WAL append ordering that could create irrecoverable state
  (3.7.9). They do not establish repair of an already-corrupt WAL.
- WAL disk throttling defaults to usage threshold **0.9** in the target. Preserve
  this protection and check disk/inode headroom. Do not opt into Thanos objstore,
  object-store deletion markers, or missing-chunk deletion suppression.

Anonymous Docker Hub pull-token/manifest requests verified the public
`docker.io/grafana/loki:3.7.10` multi-platform index. SHA-256 of the returned bytes
matched the registry's content-digest header:

```text
sha256:b43c257ccfc925d4a50b8717cac61a3b51df8c48d01847936057e5c4075a24a7
```

The index covers **linux/amd64, linux/arm/v7, linux/arm64**. Values explicitly set
registry, repository, tag and this **index**, not a platform child digest. Chart
7.3.0 gives digest precedence, rendering `docker.io/grafana/loki@sha256:…`.

## Local evidence

Exact chart 7.3.0 renders before/after the values edit have identical resource
identities and byte-identical Loki runtime configuration. Only the Loki container
image and `app.kubernetes.io/version` resource metadata labels differ. No change
to claim templates, selectors, retention, resource limits, gateway pod template,
RBAC rules, hooks, storage paths, schema, exposure or auth was rendered.

Official GitHub `loki-linux-amd64.zip` matched the release API's asset SHA-256:
`200e74f7e631969bd0f2a066a2e1d33cdea9b3c0801aaaa7d78947c4ac29bddb`.
Its binary reported **3.7.10 / c792f585** and accepted the chart-generated config
with `-target=all -verify-config=true` (**exit 0**, `config is valid`). This checks
parsing/defaults, not startup, image-binary equivalence, persisted-data recovery
or production capacity. No full rehearsal was run in this preparation scope.
Ignored local evidence/reproducer is under
`verification/reports/loki-3.7.10/` in the preparation worktree; it is not a
published backup or a substitute for CI.

## Backup-first remaining gates

1. **Before stopping the writer:** refresh live Retain/Retain policy, absence of
   StatefulSet/Pod claim owner references, Bound PVC/PV/CSI identities and healthy
   Longhorn replicas/capacity. Preserve StatefulSet `loki`, claim template
   `storage` and PVC `storage-loki-0`. PV reclaim policy remains **Delete**;
   retention is not protection from explicit PVC/namespace deletion. See the
   [retention safeguard](README.md#loki-retention-safeguard-before-recovery-maintenance).
2. Parent must obtain and verify a fresh durable **whole `/var/loki`** checkpoint
   outside the source-volume failure domain, with a tested isolated restore.
   Include WAL/checkpoints, chunks, active/cache TSDB indexes, compactor markers,
   delete requests and existing ownership/permissions. No current backup was
   established by this work. Coordinate single-replica downtime, collector retries,
   rotation and RPO; a live snapshot alone is not proven recoverability.
3. Establish target WAL replay, historical queryability and memory/load headroom
   from an isolated restored copy at the actual **512Mi** Loki-container limit;
   compare old-version recovery on an independent copy. Check acknowledged writes
   across restart and representative LogQL collision semantics. Do not delete WAL
   or weaken probes to force success.
4. Require full repository verification, successful exact-published-SHA Verify CI,
   complete generated-to-live diff/hook/storage review and separate maintenance
   approval. Follow the [pre-sync checklist](../argocd/README.md#verification-before-manual-sync).
   Sync only the reviewed Loki Application without prune/force/replace. Check the
   desired template digest before rollout status, then actual image/buildinfo,
   restart/OOM history, replay completion and recent Alloy logs by node/workload.

### Memory/WAL risk is deliberately unresolved

Both [3.6.11 WAL source](https://github.com/grafana/loki/blob/v3.6.11/pkg/ingester/wal.go)
and [3.7.10 WAL source](https://github.com/grafana/loki/blob/v3.7.10/pkg/ingester/wal.go)
default replay memory ceiling to **4GB**, versus the unchanged **512Mi** container
limit. The target's effective config confirms WAL enabled, 5m checkpoints,
`flush_on_shutdown: false`, ceiling 4GB, querier concurrency 4 and compactor
retention deletion workers 150. A replay ceiling is not reserved memory or a
whole-process RSS bound; small idle usage does not prove recovery safety.

Source supports `loki.ingester.wal.replay_memory_ceiling` (runtime YAML:
`ingester.wal.replay_memory_ceiling`) to flush during replay at a lower threshold.
**256MB is a separate test hypothesis, not an approved production setting.**
It still needs heap/cache/query/compaction headroom measurements. This patch
changes neither that knob nor concurrency/resources. Hold deployment if recovery
or load evidence fails; review a bounded configuration/resource change separately.

Recovery must restore the **entire matching pre-upgrade checkpoint with the old
3.6.11 image/config**, preserving failed candidate data for diagnosis. Retention
and compaction mutate persisted state; image-only downgrade is not a proven
rollback. Account for records accepted after the checkpoint and during downtime.
