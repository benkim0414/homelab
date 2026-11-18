# Loki 3.6.11 → 3.7.10: image-only candidate

**Prepared and locally validated; production upgrade held.**
Parent/operator owns backup, maintenance authorization and deployment. Keep chart
**7.3.0** and manual sync. This is not a community-chart migration.

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
