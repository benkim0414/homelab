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

Implementation references, pinned to the installed Longhorn release:

- [Snapshot controller and detached-volume attachment](https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/snapshot_controller.go)
- [Backup controller and completion/deletion behavior](https://github.com/longhorn/longhorn-manager/blob/v1.13.0/controller/backup_controller.go)
