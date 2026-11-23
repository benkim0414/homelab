# Specialist scheduled backup and Career advisor restore result

Verified at `2026-11-23T00:12:10.383547+00:00`.
Operational task 1 passed after correcting the initial resume failure described
below. Repository publication and GitOps adoption remain pending. Task 2 memory
integration is not included in this record.

## Deployed configuration

Exactly 24 new resources were created from the reviewed local backup manifests.
The deployment added only dedicated service accounts, Roles/RoleBindings,
controller ConfigMaps, NetworkPolicies, and nightly/recovery CronJobs. No
production Deployment template, namespace, PVC or volume was replaced.

| Runtime | Nightly schedule | Recovery schedule | Zone | Retention |
| --- | --- | --- | --- | --- |
| Learning coach | `15 4 * * *` | `*/5 * * * *` | Australia/Melbourne | 7 successful policy-owned backups |
| Career advisor | `30 4 * * *` | `*/5 * * * *` | Australia/Melbourne | 7 successful policy-owned backups |

The CronJobs are not suspended. Both recovery CronJobs recorded a successful run
at `2026-11-23T00:10:05Z`. The nightly CronJobs have not yet reached their first
scheduled execution. Immediate Jobs exercised their templates; those successes
do not populate the nightly CronJobs' last-success timestamps. Lease markers
were clear at final readback. No production failure was injected to test the
watchdog live; expired-Lease/failure paths were exercised by synthetic tests.

## Successful immediate backup checks

| Field | Learning coach | Career advisor |
| --- | --- | --- |
| Job | `learning-coach-backup-check-20261123-000805` | `career-advisor-backup-check-20261123-000913` |
| Job UID | `71ff27d7-5ffa-44f1-a2c0-8d4f0f4c00a0` | `767c8ffa-f299-4a6f-a384-9f9f50dc63ba` |
| Job start UTC | `2026-11-23T00:08:05Z` | `2026-11-23T00:09:13Z` |
| Job completion UTC | `2026-11-23T00:08:43Z` | `2026-11-23T00:09:53Z` |
| Backup | `learning-coach-20261123-000806-6740df06` | `career-advisor-20261123-000914-24e26373` |
| Backup UID | `db3babb3-7fec-4688-854c-a748117ed2c6` | `aa6efc7e-c3db-4de7-a39f-c7e337020ac9` |
| Backup state / progress / error | Completed / 100 / empty | Completed / 100 / empty |
| Source PVC UID | `6fae088c-2245-47aa-82ba-cf48ce7dc8f6` | `f4805c89-7cfe-4592-a413-b0ea7f1715af` |
| Source Longhorn volume | `pvc-6fae088c-2245-47aa-82ba-cf48ce7dc8f6` | `pvc-f4805c89-7cfe-4592-a413-b0ea7f1715af` |

Both backups use the existing target
`nfs://192.168.0.40:/longhorn-backups`. Both sources returned Ready on their
original claim/volume identities. Their intentional quiescence created new pods.
House manager retained its original Pod UID and restart count.

## Initial failures and correction

Deployment first stopped at a readback assertion after Kubernetes omitted the
empty NetworkPolicy `ingress` array. The comparison was corrected to accept that
serialization only for empty ingress/egress lists. The created policy retained
explicit Ingress/Egress isolation and the exact API-only egress allowlist. The
17 already-created exact-UID resources were checked before creation continued.
No source had been paused and no backup had run at that point.

The first Learning coach backup completed as
`learning-coach-20261123-000447-84a8c62c`, but its Job failed during resume with
`KeyError: 'replicas'`. Kubernetes omits the zero-valued replicas field from the
Scale API. The source remained paused until an immediate operator recovery
requested one replica using the original Deployment UID and current Scale
resourceVersion. Readback confirmed Learning coach Ready again on its original
claim. No force detach, reset or credential operation was used.

A new regression test reproduced the missing-zero-field error for both copied
controllers. Both controllers now interpret an omitted Scale replica field as
zero. Tests then passed, both exact controller ConfigMaps were updated and read
back, and fresh verification Jobs passed as recorded above. The failed Job and
its completed backup remain preserved. No Job automatic retry was enabled.

## Isolated Career advisor restore

The restore source was `career-advisor-20261123-000914-24e26373`, validated by UID,
Completed state, original source volume, and backup URL. A new test namespace,
Longhorn volume, static Retain PV/PVC, ConfigMap, deny-all NetworkPolicy and
inspection Job use the name `ca-restore-20261123-001022` (the Job and ConfigMap
are named `inspect-clone`, and the policy is named `deny-all`).

The Job invoked the pinned image's Python directly, not s6/Hermes. It had no
service-account token, host network, init containers, Secret/projected mounts,
privilege escalation or additional containers. It mounted only the cloned PVC
and public inspection script. The sole NetworkPolicy denied all ingress and
egress before the Job started.

Observed result:

- SQLite integrity: `ok`.
- Approved root credential files removed from the clone: 2.
- Hermes started: false.
- Clone Longhorn robustness: healthy.
- All original workloads: Ready on original claims and volumes.

Only `auth.json`, `.env`, and `auth.json.corrupt` were eligible for unlinking.
Their values were not opened or printed. The inspector refused native named
profiles and symlinked database files. It made no application-row queries.
The clone is not declared comprehensively sanitized. It remains private and
quarantined, pending separately approved exact-resource cleanup. Do not start
Hermes against it, reuse copied OAuth, or infer full disaster recovery from this
SQLite-integrity result. No login or model request was made.

## Preservation, authority and local checks

All three Deployment UIDs, PVC UIDs, volume identities and runtime image pins
match the preflight baseline. The original manual Learning coach backup
`lc-restore-20261122-092311` remains Completed with its original UID. No backup
was pruned during this exercise; synthetic tests verified seven-successful-copy
retention and exclusions for manual, failed, foreign-policy and foreign-volume
records.

Live authorization checks denied each backup account Secret reads, pod exec, and
cross-specialist scale access. Each recovery account was denied Longhorn volume
reads. Standard Kubernetes RBAC cannot label-scope the backup account's Longhorn
Snapshot/Backup CRUD. The runner's source/target/policy checks remain essential.

Local verification passed:

- Repository suite: 276 tests, 26 skipped.
- Backup tests: 63 passed, including zero-valued Scale and failure-path tests.
- Policy tests: 9 passed.
- Full render/schema/policy/secret verifier: 23 Applications, 561 resources.
- Inspector synthetic tests: 3 passed with warnings treated as errors.

Direct deployment used only the reviewed new backup manifests. The Application
include changes remain local and uncommitted. No ArgoCD Application was patched
or synced against unpublished files, and manual sync remains preserved. Publish
and adopt these additions through the existing Applications only after separate
publication authorization. No broad parent sync or pruning is required.

Public operational evidence is retained in this worktree's ignored
`verification/cache/specialist-{baseline,deployment}.json`,
`career-restore-{state,resources}.json`, and the reviewed one-time operational
scripts. These are not credential stores, backup schedules, or permission to
repeat a restore. Preserve the worktree until its local deliverables are published.
