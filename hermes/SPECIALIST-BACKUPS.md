# Scheduled specialist backups

## Approved scope

The user approved nightly full-volume backups to the existing unencrypted NAS,
brief nightly outages, seven-successful-backup retention per specialist, and one
isolated Career advisor restore test without authentication or inference.
Specialist memory is the next task, not part of this implementation.

| Runtime | Schedule, Australia/Melbourne | Source volume | Retention policy label |
| --- | --- | --- | --- |
| Learning coach | `15 4 * * *` | `pvc-6fae088c-2245-47aa-82ba-cf48ce7dc8f6` | `learning-coach-nightly` |
| Career advisor | `30 4 * * *` | `pvc-f4805c89-7cfe-4592-a413-b0ea7f1715af` | `career-advisor-nightly` |

Both use `nfs://192.168.0.40:/longhorn-backups`. The backups contain private
conversation state and OAuth credentials. This configuration does not encrypt
them or provide offsite protection. Never inspect their credential values or
start Hermes from a restore containing copied OAuth credentials.

## Operation and safety

Each profile has its own backup and recovery service accounts, Lease, controller
ConfigMap, NetworkPolicy, and namespace-scoped Roles. The implementation adapts
the existing [House manager pattern](profiles/house-manager/BACKUP.md). It does not
change House manager, production PVCs, image pins, provider/model routing, or the
manual ArgoCD sync posture.

The source PVC UID, volume identity, and Deployment UID are fixed. A replacement
claim or Deployment requires review, not silent adoption. The backup controller
checks target availability and source health before pausing its own Deployment.
It acquires an expiring Lease, stops writers, waits for detachment, and creates
one Longhorn Snapshot and Backup. It requests resumption in a finally path.
The recovery job handles abandoned maintenance markers after Lease expiry.
Neither runner mounts the production PVC, reads OAuth files, executes Hermes,
or makes provider requests. Recovery is not an automatic backup retry.

The backup runner has a 15-minute run budget and a 20-minute Job deadline.
The separate recovery job runs every five minutes. Infrastructure failures can
still require operator intervention. Never force detach or salvage the source
volume to obtain a passing backup.

Retention starts only after a new backup completes. Only successful backups with
the exact source, target, and specialist policy labels qualify. Failed, pending,
foreign-policy and manual backups remain excluded. Keep the manual Learning
coach backup `lc-restore-20261122-092311`; do not relabel it as scheduled policy
state. Deletions use UID preconditions. Each policy retains seven successful
backups, not seven arbitrary Backup CRs.

Kubernetes RBAC cannot constrain Longhorn create/list/delete permissions by label.
The source/policy checks in the runner are therefore part of the safety boundary.
The recovery account has no Longhorn permissions. No account receives Secret-read
or pod-exec permissions. Review namespace-specific permissions before deployment.

## Verification and current status

Both policies are deployed and enabled. Fresh immediate Jobs from their corrected
nightly templates completed their NAS backups and resumed both specialists.
The isolated Career advisor restore passed SQLite integrity checking without
starting Hermes. See the [execution record](SPECIALIST-BACKUP-RESULT.md), including
the initial resume failure, operator recovery, regression test and correction.
Both recovery CronJobs recorded successful executions. The nightly schedules
have not yet reached their first scheduled execution.

The final repository suite passed (276 tests, 26 skipped), all nine policy tests
passed, and the full verifier passed (23 Applications, 561 resources). The
Career advisor inspector passed three synthetic safety tests with warnings
treated as errors. All three production workloads were Ready at final readback
on their original PVCs/volumes. The original manual Learning coach backup remains
Completed. Its earlier test remains in its separate review worktree; do not copy
or discard that unfinished worktree's changes.

The backup manifests and Application includes were published by
[PR 120](https://github.com/benkim0414/homelab/pull/120), merged as
`5430aa6ee52d5c0122956ceca3d0b2f40b8f762e`. Both specialist Applications adopted
the existing resources without pruning and were Synced/Healthy at that revision.
Manual sync, production pods, templates, claims and volume identities remained
unchanged. The Career advisor restore resources were subsequently removed with
exact-UID cleanup and absence verification. All successful backups were preserved.
See the execution record for timestamps and the deliberately untouched parent
Application drift. Memory integration remains a separate task.

Acceptance requires:

1. Passing regression tests and the full repository render/policy/schema check.
2. Reviewed server-side admission checks and exact-resource deployment readback.
3. A successful Job from each specialist's nightly template, a matching Completed
   NAS backup, and each original workload Ready on its original claim and volume.
4. One network-isolated Career advisor restore using a new Longhorn volume and
   static Retain PV/PVC. Use the pinned image's Python directly, never its Hermes
   entrypoint. Disable the service-account token and all ingress/egress.
5. Removal of the explicitly reviewed root credential files from the clone without
   reading them. Run only SQLite integrity verification, not conversation queries,
   login, inference, or a full runtime recovery claim.
6. A final readback proving original claims, volumes, image pins and manual sync
   are preserved. Preserve all unrelated House manager and manual-backup state.

Close interactive specialist CLI sessions before an immediate backup test.
Nightly backups intentionally terminate writers during the approved outage.
A successful backup Job does not establish SQLite integrity or OAuth validity.
A restore integrity pass does not establish full disaster recovery.

## Publication and cleanup boundaries

Do not sync Applications against unpublished local include changes. Source
Applications continue to track `main` with manual sync. Publication requires
separate authorization. Record any pre-publication direct deployment explicitly
and reconcile it after approved publication without pruning.

Retain isolated restore resources until separate exact-resource cleanup approval.
Always preserve the successful NAS backup. Never delete a production namespace,
claim, volume or credential as test cleanup. No alerting subsystem, storage
expansion, encryption rollout, new backup target, inference test, or memory
integration is included in task 1.
