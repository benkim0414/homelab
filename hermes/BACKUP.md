# Hermes backups

The declared nightly job runs at **04:00 Australia/Melbourne**, including daylight
saving changes. It retains the latest **seven successful nightly backups** on the
existing Longhorn target, `nfs://192.168.0.40:/longhorn-backups`. The source is
`hermes/hermes-data`, volume `pvc-d4c53ad4-a9a2-4d28-91a9-0c4e3c884383`.
Changing that identity requires reviewing the job environment and Longhorn Role;
the controller refuses to back up a replacement PVC silently.

This is a NAS copy, not an offsite copy. The existing volume and backup target
are not encrypted by this configuration. The archive includes personal history,
workspace files and rotating OAuth credentials. Restrict NAS/export and backup
administration access, and remove restored credentials before starting Hermes.
No new NAS credentials, export changes, or cluster-wide backup settings are used.

## Consistency and availability

`hermes-backup` acquires an expiring Kubernetes Lease before it:

1. Verifies the bound PVC identity, healthy volume, available NAS target, and one
   ready Hermes replica.
2. Records its maintenance marker in the Lease, scales only `hermes` to zero,
   and waits for all its pods to terminate and its volume to detach.
3. Creates a Longhorn Snapshot CR. Longhorn 1.13's snapshot controller attaches
   detached volumes as needed; no helper pod or manual attachment is required.
4. Creates a Backup CR and waits for `Completed` with the expected source and NAS
   URL. The source remains quiesced for this operation.
5. Requests one Hermes replica in a `finally` block, then applies retention only
   after the new NAS backup succeeded. Only backups labeled with this volume,
   target and `backup.homelab/policy=hermes-nightly` are eligible. Failed, pending,
   manually created or unrelated backups are preserved. Old local snapshots are
   removed only when they belong to pruned completed backups in the same policy.

Expect a brief chat outage during a successful nightly backup. The controller
has a 15-minute run budget and handles SIGTERM by attempting resume. Its Job has
a 20-minute deadline and no automatic retries that could pause Hermes again.
Manual ArgoCD sync must remain enabled: syncing Hermes while intentionally
quiesced can restart writers before the snapshot is captured.

The separate `hermes-backup-recovery` CronJob runs every five minutes. If a runner
or its node crashes, it can take over only after the 120-second Lease plus a
30-second grace expires. It resumes only a pause recorded by this controller,
preserves an operator's positive replica count, and retains the maintenance
marker when resume fails so a later recovery run can retry. Recovery may take
about eight minutes after the last heartbeat, plus pod/volume startup time.
Kubernetes or Longhorn failures can require operator intervention; this does not
force detach, replace, salvage or delete the production volume.

The backup runner has a dedicated service account: it can read the source PVC,
list Hermes-namespace pods, read this one volume and backup target, manage
Longhorn Snapshot/Backup objects in `longhorn-system`, and patch only the scale
subresource of the Hermes Deployment. Kubernetes RBAC cannot constrain CR
creation or list/delete permissions by label; the script also checks source and
policy before retention. The recovery account has no Longhorn permissions.
Neither account can patch the Deployment template, read Secrets, or exec into
pods. Neither runner mounts the Hermes disk or receives dashboard/OAuth values.
Their NetworkPolicy allows only the Kubernetes API Service and the observed K3s
API endpoints; node-traffic exceptions still apply.

## Operation

The monitoring Application declares two Hermes-specific alerts:

- `HermesBackupJobFailed`: any failed `hermes-backup-*` Job in namespace `hermes`,
  including the recovery watchdog and manual runs, for five minutes.
- `HermesBackupStale`: the nightly CronJob records no success within 36 hours, with
  a one-hour pending period. A never-successful CronJob gets the same 36-hour
  grace from creation; a missing CronJob alerts after one hour. Watchdog successes
  do not reset backup age. The window tolerates the Melbourne daylight-saving
  transition and a delayed run, while detecting a missed nightly backup.

These depend on kube-state-metrics and on manually syncing the monitoring
Application; committing the rules does not activate them. CronJob success is an
operational signal, not independent proof of a new backup or successful restore.
A runner that acquires the lease waits for NAS completion and requests Hermes
resumption; it does not wait for the new pod to become ready. A lock-contended
runner can also exit successfully without creating a backup. Continue checking
Longhorn completion and Hermes readiness, and periodically repeat an isolated
restore. A manual Job's success does not update the nightly CronJob's success
timestamp.

These commands describe separately authorized operations; they do not authorize
running them. First finish the repository's verification and manual-sync review.
Review the Hermes Application include glob and the default AppProject's access
to `longhorn-system` before syncing the backup Roles and their bindings.

Inspect the schedule and latest execution:

```sh
kubectl -n hermes get cronjob hermes-backup hermes-backup-recovery
kubectl -n hermes get jobs --sort-by=.metadata.creationTimestamp
kubectl -n hermes get lease hermes-backup
kubectl -n longhorn-system get backups.longhorn.io -l backup.homelab/policy=hermes-nightly
```

For an approved immediate backup, use a unique Job name:

```sh
kubectl -n hermes create job --from=cronjob/hermes-backup hermes-backup-manual-YYYYMMDD-HHMMSS
kubectl -n hermes logs job/hermes-backup-manual-YYYYMMDD-HHMMSS
```

Confirm the Job succeeded, the Backup's status is `Completed`, its error is empty,
and its URL and volume match the intended target/source. Record its name, URL,
completion timestamp, image digest and selected model. A scheduled Job, snapshot,
or submitted Backup CR alone is not proof of a successful backup. Verify Hermes
has one ready replica and the original claim/volume identity remains unchanged.

If a backup fails, inspect its Job and Longhorn CR status without printing data
files or credentials. Do not remove the Lease to force concurrency. If Hermes is
paused, inspect the Lease marker and wait for/review the recovery job. If the
underlying APIs remain unavailable, restore service after they recover; do not
force a volume attachment or delete the original claim. Failed backup/snapshot
CRs may need separately reviewed cleanup; they are not silently discarded.

## Restore exercise

Use an approved successful backup and unique test resource names. Preserve the
working Deployment, PVC and volume throughout the exercise:

1. Create a **new** Longhorn Volume with `spec.fromBackup` set to the recorded NAS
   backup URL, matching the 10 GiB size, V1 data engine and two replicas. Do not
   change `spec.fromBackup` on the production volume or restore into its claim.
2. Bind a separate static CSI PV/PVC to that new volume handle. Use reclaim policy
   **Retain**, an explicit claim reference and volume name, and no dynamic storage
   class, so the exercise cannot bind to the production volume accidentally.
3. Run an isolated inspection Job using the reviewed Hermes image's Python
   binary directly. Bypass its s6/Hermes entrypoint, mount only the restored
   claim, disable its service-account token and all network ingress/egress, and
   run as UID/GID 10000 with dropped capabilities and no privilege escalation.
4. Remove the **restored** `auth.json` and `.env` without printing their contents;
   remove profile grants too if profiles exist. Do not launch Hermes against the
   clone. Check SQLite integrity, expected session/message counts, selected model
   and a known workspace file/hash. Keep logs limited to integrity results and
   counts. This establishes data recovery without reusing a rotating OAuth grant.
5. Confirm the working instance is still healthy and uses the original volume.
   Remove only the named test Job, policy, claim, retained PV and cloned Longhorn
   volume after separate cleanup approval. Preserve the successful NAS backup.

The initial exercise reserves these names:

| Resource | Name |
| --- | --- |
| Longhorn Volume / static PV | `hermes-restore-test-20261019` |
| PVC in namespace `hermes` | `hermes-restore-test-20261019` |
| Job in namespace `hermes` | `hermes-restore-check-20261019` |
| NetworkPolicy in namespace `hermes` | `hermes-restore-test-20261019` |

For actual disaster recovery, follow the same isolation and credential removal,
then review the new production claim identity in Git. Keep the original volume
and start just one Hermes instance on the approved replacement. Perform a fresh
device login, verify a small model request, and recheck history and workspace
data before declaring recovery complete. An offline restore exercise does not
verify future account entitlement or guarantee unlimited subscription quota.

## Verification record: 20 October 2026

The configuration in `ecc266d147ab2d36c1b791019a5e0a0ae8a6321c` passed
[CI verification](https://github.com/benkim0414/homelab/actions/runs/39333926540)
and was manually synced without pruning. Both `apps` and `hermes` were
Synced/Healthy. The nightly and recovery CronJobs were enabled with the declared
Melbourne schedules. The Deployment template, ingress and PVC were unchanged by
the sync.

The first immediate run exercised the nightly CronJob's template:

| Evidence | Observed result |
| --- | --- |
| Job | `hermes-backup-manual-20261019-221959`, succeeded |
| Job interval (UTC) | `2026-10-19T22:19:59Z` to `2026-10-19T22:20:34Z` (35 seconds) |
| NAS Backup | `hermes-20261019-222000-6802fb67`, `Completed`, progress 100, no error |
| Backup completion | `2026-10-19T22:20:28Z` / 20 October, 09:20:28 Melbourne |
| Source volume | `pvc-d4c53ad4-a9a2-4d28-91a9-0c4e3c884383`, 10 GiB, V1, two replicas |
| Backup data size | 320,864,256 bytes; Longhorn reported 8,109,303 bytes newly uploaded |
| Resume | One ready replica at `2026-10-19T22:21:12Z`; original volume healthy on `k3s-03` |
| Concurrent recovery run | Observed the active Lease and skipped without resuming Hermes early |
| Application check | HTTPS status required authentication; a fresh Codex model request returned `HERMES_BACKUP_OK` |

The completed backup URL was:

```text
nfs://192.168.0.40:/longhorn-backups?backup=hermes-20261019-222000-6802fb67&volume=pvc-d4c53ad4-a9a2-4d28-91a9-0c4e3c884383
```

An isolated restore used the reserved resources above, a new Longhorn volume,
a static PV with reclaim policy `Retain`, and the same reviewed image:

```text
nousresearch/hermes-agent:v0.22.2@sha256:36099926da316742423544e055d4734777105ffe6341873af5459b957d0c2919
```

The inspection Job succeeded between `2026-10-19T22:21:17Z` and
`2026-10-19T22:22:29Z`. Its container bypassed the Hermes entrypoint, had no
service-account token, and was selected by a deny-all ingress/egress policy.
It removed two cloned credential files without reading their contents and never
started Hermes or reused the copied OAuth grant. Its results matched the
pre-backup baseline:

- SQLite `integrity_check`: `ok`.
- Seven sessions, 32 messages, including all six acceptance-session messages.
- Provider `openai-codex`, model `gpt-6.1-sol`.
- Workspace acceptance-file SHA-256:
  `a07941bf4f885dad4671242c57867497a20a743b6bfbd78426213ab66bbe3127`.
- Restored volume healthy with two replicas before cleanup.

After explicit cleanup approval, only the named test Job, NetworkPolicy, PVC,
retained PV and cloned Longhorn volume were removed. The successful NAS backup
was preserved, and production remained ready on its original claim and volume.
Transient attachment errors during restore settled without forced detach or
storage changes.

Live RBAC checks confirmed the backup account could patch only the Deployment's
scale subresource and could not patch its template or read Secrets. The recovery
account could not create Longhorn Backups. Failure recovery and seven-copy
retention passed the controller tests; a node-crash recovery and live deletion
of an eighth successful backup were not exercised. This first execution does not
establish that future scheduled runs have succeeded; inspect their Job and
Backup results before upgrades.

Implementation references, pinned to the installed Longhorn release:

- [Snapshot controller and detached-volume attachment](https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/snapshot_controller.go)
- [Backup controller and completion/deletion behavior](https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/backup_controller.go)
