# Immich PostgreSQL 16 migration

This replaces the image-only proposal in [PR #75](https://github.com/benkim0414/homelab/pull/75).
The production PostgreSQL 16 restore and cutover completed on 2026-11-11. The
active claim is `data-immich-postgres16-0`; PostgreSQL 14 is stopped with its
original claim retained. [Rollout evidence](../../reports/2026-11-11-immich-rollout.md)
records archives, checksums, snapshots and application rollout status.

The procedure below documents the gated transition. Its preparation commands
and cutover generator describe the original PG14 state and must not be rerun
against the already migrated database.

## Gates and evidence

On 2026-11-11 read-only inspection found PostgreSQL 14.19, a 190 MB database,
`vchord` 0.4.3 and `vector` 0.8.1, and a recent completed scheduled backup Job.
These observations are not proof of restore or permission to deploy. Refresh
them at execution. PostgreSQL 16 must never mount `data-immich-postgres-0`.

Before rollout, attach the following evidence to the replacement PR:

- Passing full [verification](../../verification/README.md) and complete reviewed
  [ArgoCD diff](../../argocd/README.md#verification-before-manual-sync), exact main
  commit, image manifests supporting the scheduled node architectures, and no
  pruning, force/replace, or unexpected hooks.
- Actual Longhorn free capacity for a new 20 GiB claim with two replicas plus
  rehearsal storage; current PV reclaim and StatefulSet PVC retention policies.
  Do not delete or recreate the existing claim. Default StatefulSet retention is
  Retain, but the actual backing PV can still use Delete.
- Completed backup Job, archive path and SHA256, isolated restore results,
  baseline asset/user/album counts, extension/index checks, and measured runtime.
- Successful rehearsal of v2.7.5 against PostgreSQL 16 and the subsequent v3.2.0
  upgrade, with separate writable media and cache. Never point rehearsal at the
  production media or database. Disable outbound integrations in the rehearsal.
- An approved maintenance window based on rehearsal time plus recovery margin.
  Record the operator, archive, media snapshot, commits, times and results here
  or in a linked committed report. Do not record credentials or personal rows.

The original preparation commit did not perform a live cutover. Use the linked
rollout evidence for completed gates; an archive listing or render alone does
not establish restore success.

## Prepare and rehearse

1. Merge and manually sync preparation only after approval. The PG16 StatefulSet
   has zero replicas, so it does not yet allocate its claim. The client Service
   and scheduled backup remain on PostgreSQL 14.
2. For rehearsal use an isolated namespace, fresh database and media copy, and
   isolated cache. Supply credentials through an approved injection workflow;
   do not export/copy the production Secret. Adapt names in a local manifest
   copy. Allow the helper's fixed hostname `immich-postgres16` in that namespace.
3. Restore a verified archive and compare aggregate data and extension/index
   validity. Start v2.7.5, then v3.2.0 with chart 0.13.4 against the isolated
   library copy. Validate login, timeline, albums, downloads, video, search and
   controlled upload. Measure database restore, index work and application
   migrations independently. Test rollback before reopening writes.
4. The production target must be fresh for the final restore. Do not rehearse on
   it and then bypass the nonempty check. A failed restore investigation may
   require a new disposable destination; deletion needs separate approval.

## Final backup and restore (approved window only)

Keep the chart/server upgrade unmerged or unsynced throughout the database stage.
Prevent clients and integrations from writing, let background jobs finish, then
scale all Immich server/worker deployments to zero. Record original replicas and
wait for their pods to terminate. Confirm there are no other database writers.
Suspend `immich-pg-backup` and wait for active backup Jobs to complete. Do not run
a full ArgoCD sync while these temporary maintenance changes are in effect.

Create a unique manual backup Job from the existing CronJob in a local manifest
copy. Change its image to the pinned PostgreSQL 16 image, set `BACKUP_KEEP=0`, and
replace `/backups/scheduled` with `/backups/migrations` in its command. This uses
the existing secret reference and NAS claim without extracting credentials.
Its `pg_dump` must still target the stable Service, currently PostgreSQL 14.
Review the generated manifest, create it, require completion, and record the
published archive path and SHA256. Preserve it outside scheduled retention.

While writers remain stopped, take and record a named NAS snapshot of
`storage/k3s` (see [NAS runbook](../../nas/README.md)); the snapshot must include
the media and the completed dump. Do not roll back the whole shared dataset to
recover Immich: other applications also live there. Restore only Immich data
from the recorded snapshot if needed.

Start the target explicitly and wait for readiness:

```sh
kubectl -n immich scale statefulset/immich-postgres16 --replicas=1
kubectl -n immich rollout status statefulset/immich-postgres16 --timeout=10m
```

Check the new claim is `data-immich-postgres16-0`, distinct from the old claim,
and that only the new target pod mounts it. Keep the old database running for
comparison, with no application writers. Use the production namespace only
after the rehearsal and backup gates are satisfied.

Create the restore script ConfigMap (no secrets), then a unique Job from the
template. Run these commands from the reviewed worktree:

```sh
kubectl -n immich create configmap immich-pg16-restore-script \
  --from-file=restore.sh=immich/migration/restore.sh --dry-run=client -o yaml \
  | kubectl apply -f -
```

Copy `restore-job.yaml` to an ignored local validation directory and set
`RESTORE_CONFIRM=immich-postgres16-empty`, `RESTORE_FILE` to the final dump's
absolute `/backups/migrations/...dump` path, and `RESTORE_SHA256` to its verified
hash. Use `kubectl create -f <reviewed-job-copy>`; do not apply the placeholder
template. Record the generated Job name and wait for Complete. A failed Job is
not retried automatically; inspect the cause before creating another Job.

The helper checks the version, checksum and destination emptiness, serializes
concurrent helper attempts with an advisory lock, and restores in one transaction
with errors fatal. It never drops objects, cleans a destination or reads the old
PVC. Ownership becomes the existing database user; ACLs are not replayed because
this is the dedicated single-user Immich database. Confirm this assumption during
rehearsal. Restore SQL diagnostics remain inside the pod rather than public logs.

Check `pg_extension`, invalid indexes (`pg_index.indisvalid`), database size and
aggregate asset/user/album counts against the frozen source. Investigate every
unexplained mismatch. The target must contain VectorChord 0.4.3 and pgvector 0.8.1.

## Prepare and apply the cutover

After successful final restore, run in a clean dedicated task worktree:

```sh
python3 immich/migration/prepare-cutover.py --restore-verified
git diff --check
git diff
verification/venv/bin/python scripts/verify.py --all --base origin/main
```

This only edits Git files: PG14 replicas become zero, PG16 replicas become one,
the stable `immich-postgres` Service selects PG16, the backup image changes to 16,
and Renovate freezes PG14 while allowing the reviewed PG16 variant. It refuses
unexpected source content or a dirty worktree. It does not verify a live restore.
Update this runbook and the parent README to record completed cutover state and
the new active claim after success. Commit, review and obtain merge approval.

Once the reviewed cutover commit is on main, refresh the ArgoCD Application and
review the full diff. With application writers still stopped, sync **only** the
two PostgreSQL StatefulSets and the stable Service, without pruning. Keep backup
suspension in effect. Check Service endpoints resolve solely to PG16 and confirm
the old pod stops while its PVC remains Bound. Full sync is forbidden until
this routing/readiness gate passes because it could restart the server early.

Resume v2.7.5 at its recorded replica count, with external writes still blocked.
Check readiness, login, aggregate counts and media reads; then sync the reviewed
backup CronJob (PG16 client, unsuspended). Verify its effective image and suspend
state. Run a manual backup and isolated restore test. Finish/reconcile the full
Application sync after these checks. The separate chart/server upgrade can now
proceed; record a fresh database/media checkpoint before its schema migrations.

## Rollback and retention

Before reopening user writes, stop the new application, restore the reviewed
v2.7.5/chart 0.12.0 configuration, start PG14 on its untouched claim and switch the
stable Service back to its original selector. Restore the PG14 backup image and
Renovate rule in Git as well. Review/sync those resources in the same gated order.
Do not start v2.7.5 against a database already migrated by v3. Matching media must
be recovered from the checkpoint if application processing changed it.

Once user writes resume, PG14 is stale. A switch back would lose new database
changes. Stop writers and preserve a fresh dump and media snapshot before
planning reconciliation or restore; obtain approval for any data loss. A Git
revert alone cannot undo application schema/data migrations.

Keep PG14 scaled to zero, its PVC, final migration dumps and media snapshots until
separate cleanup approval. Do not add pruning, deletion jobs or blanket policy
exceptions. Scheduled retention remains confined to `/backups/scheduled`.

## References

- [PostgreSQL 16 major upgrades](https://www.postgresql.org/docs/16/upgrading.html)
- [Immich upgrade guidance](https://docs.immich.app/install/upgrading/)
- [Immich v3 migration](https://immich.app/blog/v3-migration)

## Local test evidence (2026-11-11)

Full repository rendering/schema/policy verification passed for preparation.
The cutover generator has tests for routing, replicas, backup image, policy and
unexpected-input refusal. A disposable network-isolated PostgreSQL 16 container
successfully restored synthetic data with vector and vchord extensions and
rejected a wrong checksum, populated public and non-public schemas, and a failed
restore subprocess. This is helper validation, not a production restore rehearsal.
The smoke test uses the image's actual startup wrapper and PostgreSQL config so
VectorChord is preloaded. Reproduce with worktree-local Podman storage:

```sh
TASK_ROOT=$(pwd)
podman --root "$TASK_ROOT/verification/cache/containers" \
  --runroot "$TASK_ROOT/verification/cache/container-run" --storage-driver vfs \
  run --rm --network none --hostname immich-postgres16 \
  --tmpfs /var/lib/postgresql/data --tmpfs /backups \
  -v "$TASK_ROOT/immich/migration:/migration:ro,Z" \
  -v "$TASK_ROOT/verification/tests/immich_restore_smoke.sh:/test.sh:ro,Z" \
  --entrypoint /bin/bash \
  ghcr.io/immich-app/postgres:16-vectorchord0.4.3-pgvectors0.2.0 /test.sh
```
