# Immich rollout evidence — 2026-11-11

Status: isolated restore and v3 startup verified; authenticated functional
checks and rollback testing remain pending. Production remains PostgreSQL 14.19
and Immich v2.7.5. No database cutover or application upgrade has occurred.
The merged declaration is `18c627f8b41f8d49e4dd3c1b578af015ac9523eb`.
Do not full-sync Immich until the migration gates pass.

## Confirmed prerequisites

The operator confirmed compatible mobile clients and no third-party API
integrations. The operator also explicitly approved a new temporary database
credential for the isolated rehearsal. It was generated in memory and injected
through Kubernetes; production credentials were not copied or changed.

Production aggregate counts: 22,809 assets, 2 users, 26 albums. No invalid indexes.
Extensions include vector 0.8.1 and vchord 0.4.3, with no pgvecto.rs extension.
The original database PVC `data-immich-postgres-0` remains intact; its PV
`pvc-27d1548e-ee2f-40f6-98b7-2786280dd7ae` has reclaim policy **Delete**.

The NAS pool reported healthy. Its latest daily snapshot was
`storage/k3s@homelab-daily-20261110T164501Z`.
The snapshot contains `immich-20261110T160000718049647Z.dump` (27,163,578 bytes),
SHA256 `b6aece4cddda4802709755598523f649d2dccab581481fba2e6d9cb2746dc085`.
This is a rehearsal archive, not the final write-frozen migration backup.

## Rehearsal resources

- Namespace `immich-rehearsal-20261111`, with a deny-all ingress/egress policy.
  A pre-start TCP probe to production was denied; no external access was opened.
- Pod `rehearsal` on k3s-05, with separate PostgreSQL 16, Valkey and gated Immich
  containers. No Service or ingress was created. Server startup was held until
  restore validation. It uses a fresh cache and separate writable media.
- PVC `rehearsal-postgres`, PV `pvc-903584d2-a414-4674-9d74-890045da8c98`, 20 GiB
  Longhorn. No production database PVC is mounted.
- NAS dataset clone `storage/immich-rehearsal-20261111`, originating from the
  recorded daily snapshot, mounted at
  `/export/k3s-storage/immich-rehearsal-20261111`. NFS mounting this child returned
  stale-file-handle errors. The clone is retained, not used by the updated pod.
- Alternative media copy `/storage/k3s/immich/rehearsal-20261111/library`, created
  with mandatory `cp --reflink=always` from the live library. This is not a
  write-frozen media checkpoint. Its backup subdirectory contains a copy of the
  verified archive with matching checksum; mounted read-only by the pod.

The restore and migration results appear below. Authenticated rehearsal login
and media functional checks remain pending. Task manifests are in the worktree's ignored
`verification/cache/rollout/` directory and contain only Secret references.

## Storage issue and recovery

Cross-snapshot reflink copying failed with EXDEV. Same-dataset reflink copying
succeeded and saved roughly 153 GiB of physical blocks, but duplicate references
counted against the dataset quota. At 02:09 UTC, `storage/k3s` reported
330,573,389,824 used bytes against a 322,122,547,200-byte quota and zero available
bytes. The pool had 661,717,884,928 physical free bytes. The copy process ended.
Production pods remained Ready, but this does not prove new media writes succeed.

An attempted temporary increase from 300 GiB to 500 GiB was rejected by automatic
approval review as an unapproved shared storage-policy change. The user was
immediately asked to approve that increase or deletion of only the new rehearsal
copy. No workaround or quota change was performed before explicit approval.

Future rehearsals must account for ZFS quota charging of cloned block references,
not only pool allocation or `bclonesaved`. Validate both during a bounded sample
before copying a full library. Do not delete any production data, snapshot or PVC
as part of recovering rehearsal space. Retain the original PG14 database and
migration recovery artifacts until explicitly approved cleanup.

## Approved quota recovery

The operator explicitly approved the temporary quota increase. It was applied
to `storage/k3s`: quota 500 GiB, used 308 GiB, available 192 GiB; pool free
616 GiB. Restore the original 300 GiB quota after approved rehearsal cleanup and
a fresh capacity check prove sufficient headroom. Do not lower it while the
rehearsal copies still consume the quota.

The corrected rehearsal pod reached Running (3/3, zero restarts). A TCP connection
to the production Immich endpoint was denied from the rehearsal container.
The isolated database restore was then started with the verified archive.

## PostgreSQL 16 restore and old-server verification

The production archive restored successfully in 32 seconds. The restored database
was 190 MB, with 22,809 assets, 2 users, 26 albums, and zero invalid indexes.
`vector` remained 0.8.1 and `vchord` remained 0.4.3. `earthdistance` is 1.2 on the
target (1.1 on the source); the other listed extension versions matched.

Immich v2.7.5 started successfully on the isolated PG16 database and returned
`{"res":"pong"}`. Startup logs reported no error lines. Both media trees
contained 63,363 files; every one of the 22,809 original asset paths existed
within the isolated `/data` mount. No filenames or personal rows were logged.

A rehearsal pre-v3 dump was saved inside the separate database volume as
`/var/lib/postgresql/data/rehearsal-pre-v3.dump`, SHA256
`62bffdfe72f2c908736c98759c21b14b9719fd69846077d02b1bfd65f0540215`.
It restored successfully into a separate `immich_rollback` database. This is
restore evidence only; application rollback still needs testing.

Snapshot `storage/k3s@immich-rehearsal-prev3-20261111` was taken during shutdown
preparation. Subsequent checks showed the old server still had DB connections,
so do not treat that snapshot as a proven write-frozen checkpoint. The startup
gate was closed before requesting the isolated v3.2.0 image transition.

## Frozen checkpoint and v3 rehearsal

After the old server stopped, a query confirmed zero other connections to the
rehearsal database. A second dump,
`/var/lib/postgresql/data/rehearsal-frozen-pre-v3.dump`, had SHA256
`ae4e3ded222b46f759df1edfc61a3f2ecf63829de3af52ef70f508c72a7c8cd0`.
It restored into `immich_rollback_frozen`. Snapshot
`storage/k3s@immich-rehearsal-frozen-prev3-20261111` followed while startup was
gated. Only the rehearsal subtree is a write-frozen media checkpoint; production
remained active. Never roll back this shared dataset wholesale.

The isolated v3.2.0 server initially returned ping after 14 seconds, but the
PostgreSQL container then hit its rehearsal-only 1 GiB memory limit (OOMKilled).
PostgreSQL recovered its WAL; application retries occurred during recovery.
After checking k3s-05 memory headroom, an in-place Kubernetes resize increased
the isolated database limit to 3 GiB and request to 512 MiB. Production database
resource settings were not changed.

The server then started successfully, with version endpoint reporting 3.2.0,
22,809 assets, 2 users, 26 albums, zero invalid indexes, and 96 migration records
versus 68 in the frozen v2 rollback database. Startup logs after recovery showed
no error lines. Sample working memory was PostgreSQL 647 MiB, server 1,202 MiB,
and Valkey 10 MiB; these are samples, not peak measurements. The first ping
duration is not a clean migration benchmark because of the subsequent OOM.

A localhost-only port-forward exposes the rehearsal at `http://127.0.0.1:2284`.
A task-owned file write/delete probe on the isolated NAS mount passed after
quota recovery. The operator was asked to verify login, timeline, albums, photo download, video,
search and a controlled upload. No production Service or ingress was changed.

## Remaining gates and retained resources

- Complete authenticated functional checks and application rollback testing.
- Repeat the migration from a fresh checkpoint with the adequate memory budget
  to obtain a clean runtime and stability result. The combined rehearsal Pod
  tests the pinned server/database/cache images; it does not establish that the
  production Helm chart has rolled out successfully.
- Review production scheduling/headroom, full ArgoCD diff and exact revision;
  take a final write-frozen production dump and matching media snapshot before
  any database cutover. No production downtime has begun.
- Retain all original production PVCs, media and recovery archives.
- The rehearsal namespace/PVC, unused NAS dataset clone, media copy, and two
  rehearsal snapshots remain. Cleanup needs explicit approval. Snapshots retain
  the copied files too: deleting only the working directory may not free the
  quota. Check `usedbysnapshots`, `usedbydataset`, pool free space and dataset
  availability before restoring the approved temporary quota to 300 GiB.

## Rehearsal browser hang

The operator could load the homepage but reported a hang. At diagnosis the
server responded internally in 69 ms, database sessions were idle, container
restart counts were unchanged, and recent application logs had no error lines.
The localhost port-forward timed out and reported stream-creation timeouts.
Replacing only that tunnel restored access: 24 homepage/ping/version requests
with concurrency eight all returned HTTP 200, with a maximum duration of 75 ms.
The replacement tunnel writes diagnostics to the ignored task-local
`verification/cache/rollout/port-forward.log`. This verifies tunnel recovery,
not authenticated media functionality; the operator must retry those checks.

### Repeated hang on Albums navigation

The operator reproduced the hang by clicking Albums. The replacement tunnel
again timed out even for ping and logged stream-creation timeouts; the internal
server still returned HTTP 200, database sessions were idle, and recent server
logs had no error lines. The earlier 24-request test was insufficient to establish
browser-session stability. Authenticated Albums behavior remains unverified.

The task-local tunnel was replaced using `KUBECTL_PORT_FORWARD_WEBSOCKETS=false`
to select the supported alternative transport; this changes only the client
process, not cluster security settings or the rehearsal NetworkPolicy. See the
[Kubernetes transport design](https://www.kubernetes.dev/resources/keps/4006/).
Diagnostics are in ignored `verification/cache/rollout/port-forward-spdy.log`.

A larger test fetched Albums page assets plus health/version endpoints with
concurrency 12: 176 requests passed, transferring 22,005,992 bytes, with a maximum
request duration of 3.158 seconds. Unauthenticated Albums API requests returned
the expected 401; these are not authenticated album-query tests. Ping afterward
completed in 38 ms. The operator was asked to retry Albums before acceptance.
