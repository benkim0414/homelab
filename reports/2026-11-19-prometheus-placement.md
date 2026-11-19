# Prometheus placement and memory correction — 19 November 2026

## Status and scope

**Deployed and Ready on k3s-04; sustained observation pending.** After “proceed next” and
the concrete preflight, the operator explicitly selected **“Approve publication,
fresh backup and Prometheus-only move”**. This covers scoped commit/push/PR/merge
after exact-commit CI, one fresh cold checkpoint and the reviewed selective move,
including the two monitoring interruptions. No automatic retry or cleanup was
approved. No change to chart 93.4.0, Prometheus 3.16.0,
retention, rules, query timeout/concurrency, authentication, exposure, storage
identity, automation or other workloads is proposed.

## Pre-correction evidence

- The critical API-server availability recording group exceeded its 180-second
  interval and its two 30-day rules timed out expanding series. Subsequent checks
  also found a firing failure alert for the API-server burn-rate group.
- Earlier zero-restart observations are historical: the same Prometheus Pod now
  records one **OOMKilled / exit 137 at 2026-11-19T05:00:20Z**, then recovered Ready.
  Six-hour working-set samples approached the existing 1536Mi limit. This proves
  a memory-limit failure, not that every rule timeout is caused by memory.
- k3s-03 sampled 93% memory; k3s-04 sampled 37%. Both are arm64, Ready,
  schedulable and untainted. No node policy/taint change is needed.
- Host device metadata for `/dev/longhorn/pvc-74b2467c-85d8-4704-bbe8-78a50bf6cd6e`
  and `sde` both identify block device hex `8:40`. `node_disk_info` independently
  maps sde's iSCSI path to that exact volume. The earlier busy-disk warning is
  therefore attributable to Prometheus's virtual Longhorn block device, not
  automatically a failing physical disk or a particular backing replica.

## Candidate and capacity

Change only the Prometheus CR's node selector and resources through Helm values:

- Keep `kubernetes.io/os: linux`; add hostname `k3s-04`.
- CPU request: 100m → 500m; no CPU limit introduced.
- Memory request: 512Mi → 1536Mi; limit: 1536Mi → 2Gi.

At preflight, k3s-04 requested approximately 970m CPU / 2706Mi memory, against
3800m / 7294Mi allocatable. The config-reloader has no explicit reservations.
The candidate adds 500m / 1536Mi: approximately **1470m / 4242Mi** total requests.
Its sampled 2759Mi actual node usage plus the entire 2048Mi Prometheus limit and
17Mi sampled reloader is 4824Mi, leaving about 2470Mi of allocatable headroom.
These are snapshot estimates, not bounds on concurrent bursts of other workloads.
Both healthy replicas already reside on k3s-04 and k3s-01; no replica relocation
is requested. Node/disk conditions and available Longhorn space passed preflight.

Hard hostname selection deliberately prevents the enlarged process returning to
the crowded node. It is not HA: if k3s-04 becomes unavailable, placement must be
reviewed/changed before rescheduling elsewhere. Do not remove taints, add broad
tolerations or force attachment as recovery shortcuts.

## Storage and recovery gates

Preserve the original 20Gi RWO claim, UID
`74b2467c-85d8-4704-bbe8-78a50bf6cd6e`, PV
`pvc-74b2467c-85d8-4704-bbe8-78a50bf6cd6e`, PV UID
`742fe1a2-81bd-431b-88e1-4b67d07e226f` and CSI handle. The PV has **Delete**
reclaim; do not delete/recreate the claim. StatefulSet retention is Retain/Retain,
claim owner references are empty, and no PV node affinity prevents attachment.
The attached volume is healthy with two running RW replicas; no rebuild/failure
was observed. The normal NAS backup target is available. The previous 20Gi backup
`upgrade-prometheus-20261118211558-76eae9` remains Completed, and earlier independent
Prometheus 3.16.0 restore/readiness checks passed; it is not a fresh move checkpoint.

Before moving, make one fresh cold full NAS checkpoint: pause through the owning
Prometheus CR, observe normal shutdown and writer exclusion, allow ordinary detach,
verify full backup completion and resume the original. Preserve all older backups,
test volumes and failed diagnostic artifacts. Do not run retention cleanup.
The existing Pod has 600-second termination grace; shutdown observation must cover
that budget rather than expiring early and asserting corruption. Never force-stop
or force-detach to meet an estimated interruption window.

## Reviewed deployment and acceptance procedure

1. Review/publish the candidate and associated records only with operator approval;
   require exact-commit CI. Local HEAD's tree equals deployed-main5031's tree,
   despite the merge commit not being present locally; no fetch/reset was used.
2. Recheck current capacity, replica health and original identities. Obtain the
   fresh checkpoint above. Backup maintenance and subsequent movement each cause
   a monitoring interruption, normally a few minutes; storage delays may extend it.
3. Review the complete generated/live diff at exact main. The pinned local Helm
   comparison changes **one of 120 chart objects**, only `nodeSelector/resources`
   on `monitoring.coreos.com/Prometheus/monitoring/kube-prometheus-stack-prometheus`.
   Image/storage/retention and every other object/hook are unchanged, apart from
   existing precisely ignored generated Grafana credential/checksum randomness.
   Kubernetes server dry-run accepted the candidate; readback proved no live change.
4. Sync **only that Prometheus CR**, with source-order revisions pinned and
   prune/force/replace disabled. Selective apply avoids rerunning completed
   admission certificate hooks, Grafana migrations or any other stack rollout.
   Let the operator/CSI perform normal shutdown and detach/attach; do not scale
   its owned StatefulSet, delete Pods manually or migrate volume contents.
5. Wait for actual template/Pod target configuration, not operation success alone.
   Verify Ready on k3s-04, same PVC/PV/CSI identity and healthy replicas, no new OOM
   or restarts, and observe memory/readiness for at least 15 minutes. Verify all
   targets, both failing rule groups completing healthy evaluations after the
   move, evaluation durations/intervals, alert state and destination node headroom.
6. Stop on a real failure. Do not increase timeouts, disable rules or silently
   resize again. Preserve evidence. A placement-only reversal retaining reviewed
   memory headroom may be considered after checking alternate-node capacity and
   ordinary CSI recovery; no automatic data restore, force attachment or image
   downgrade is authorized by this plan.

This is a measured correction, not proof that 2Gi suffices for every future load
or that placement alone fixes every expensive rule. The offsite-backup gap and
preserved failed recovery-job warning remain separate; do not silence them.

## Validation

- Pinned chart SHA-256 matched its reviewed 93.4.0 package.
- Old/candidate local render: unchanged resource identities; only the two intended
  Prometheus spec fields differ. Generated Secret payloads were not displayed.
- Kubernetes server-side dry-run accepted the intended selector/resources; actual
  CR resources remained unchanged on independent readback.
- Full repository verifier passed: **21 Applications / 520 resources**.
- Unit suite: 192 tests run, six skipped; five policy tests passed. Printed backup
  IDs in unit-test output are synthetic fixtures, not new live recovery points.
- This is local/admission/preflight validation, not deployed performance recovery.

## Historical publication and stopped checkpoint attempt

[PR103](https://github.com/benkim0414/homelab/pull/103) merged the reviewed candidate
as main `b8c07ea984e76911a42f42f633dd69e565bbe7c0`. Exact-main Verify run
44466265423 succeeded. Argo resolved all three sources at the reviewed revisions;
only Prometheus was OutOfSync among 112 tracked resources, and its filtered
generated/live diff changed only selector/resources. The first unfiltered MCP
response was truncated; it was not accepted as a complete diff.

The approved checkpoint wrapper failed **before any pause** with a constructor
TypeError: the existing observer accepts only namespace/name, not a `seconds`
keyword. That failed source code/reservation and the intent receipt
`upgrade-prometheus-20261119053915-31415c-receipt.json` remain unchanged.
Independent readback verified the same original Ready Pod/old resources,
replicas one, and no Snapshot/Backup with that intent name. No move was attempted.
The critical health issue is therefore not resolved by publication alone.

A separate UID-bound observer now explicitly supports the complete grace-period
budget. The corrected successor and the not-yet-executed move caller use it.
Nine local generated-fixture tests passed, including the original backup caller's
success and abnormal-stop/resume paths; these are not a live checkpoint. The
corrected single-use reservation does not exist. Its fresh approval request timed
out unanswered: **no corrected checkpoint or move is authorized by that timeout**.
Do not reuse/delete the failed reservation or silently retry. Production remains
on k3s-03 at 1536Mi; Argo is Healthy/OutOfSync against the published correction.

## Corrected checkpoint and reviewed move

The operator subsequently explicitly approved one corrected checkpoint followed
by the reviewed move. Fresh live preflight found the old Pod Ready but its
historical restart count had risen to three; k3s-03 was at 94% memory, k3s-04 at
37%. The pinned main/CI, manual policy, node scheduling and two RW replicas were
rechecked before spending the corrected single-use attempt.

Cold full NAS backup **`upgrade-prometheus-20261119095749-1536cc`** completed for
the unchanged 20Gi source. Config-reloader exited 0 at 09:57:51Z and Prometheus
exited 0 at 10:00:17Z; the UID-bound observer covered the existing 600-second
grace period. Backup completion was verified at 10:04:25Z and the original writer
resumed Ready. This is a verified fresh full backup, not a separate restore test.
The failed predecessor, old checkpoints and all recovery fixtures remain intact.

One selective Argo operation at **b8c07ea984e76911a42f42f633dd69e565bbe7c0**
then applied only the reviewed Prometheus CR. Both old containers again exited 0;
the replacement Pod started at 10:07:52Z, became Ready on k3s-04 with 500m/1536Mi
requests and 2Gi memory limit, and its image digest matched the original. The
CR/StatefulSet, PVC/PV/CSI identities and all other monitoring Pod identities are
unchanged. The same original volume is attached/healthy on k3s-04. Operation
Succeeded, Application Synced/Healthy; no admission hook or other resource ran.

The **15-minute readiness/memory/rule/target observation is in progress**. Initial
rule health can be unknown before the first evaluation completes; it is not
counted as proof of a failed evaluation. Acceptance requires three distinct
healthy reported evaluations of both previously failing groups, evaluation times
below their intervals, 32/32 active targets, no firing PrometheusRuleFailures,
same Ready zero-restart Pod and adequate node04 available memory. A historical
target-health sample (10 jobs/32 up targets) was captured before moving and will
be compared at the identical instant after observation. These are representative
checks, not complete stored-series equivalence or worst-case capacity proof.
