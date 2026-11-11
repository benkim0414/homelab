# Immich rollout evidence — 2026-11-11

Status: production migration and rollout complete; operator acceptance confirmed.
Immich v3.2.0 runs on PostgreSQL 16.10. LAN and Tailscale access are restored,
ArgoCD is Healthy / Synced, and scheduled PG16 backups are enabled. Pre-v3 and
post-v3 backups both restored successfully in isolated databases.
Cutover PR #92 merged as `fe300996579942d6976c56ac5b1b425f1f8202b9`.
Original PRs #75 and #77 are closed as superseded. Recovery resources remain
retained; destructive cleanup and reducing the temporary NAS quota are separate.
Earlier sections below preserve the chronological evidence.

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
and media functional checks were subsequently accepted; see the final section. Task manifests are in the worktree's ignored
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

- Complete the outstanding authenticated functional checks. Rollback startup
  and the clean migration retry passed as recorded below. The combined rehearsal
  Pod tests the pinned server/database/cache images; it does not establish that
  the production Helm chart has rolled out successfully.
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

## Confirmed Albums, rollback and clean migration

The operator confirmed Albums works after the alternative tunnel transport was
selected. Photo download, video playback, search and a test upload were asked
about separately and remain unconfirmed. Production remains untouched.

Before rollback, the rehearsal v3 database was preserved as
`/var/lib/postgresql/data/rehearsal-v3-before-rollback.dump`, SHA256
`4d9e70017c3904a76bdb508ffab8917aae77a67d872e6c1ae91fef871fb46a23`.
The disposable Pod was recreated, retaining the same database PVC and using
`immich_rollback_frozen` as the server database, with a fresh Valkey cache.

A media dry-run comparison against the frozen snapshot found six changed
`.immich` marker files (78 bytes total) and one directory timestamp; no other
files differed by size/mtime or inventory. Checksums confirmed the six marker
contents differed. Their v3 versions were preserved under
`/storage/k3s/immich/rehearsal-20261111/media-v3-before-rollback/` before restoring
only those six files from the checkpoint. No production media was modified and
no data was deleted. This comparison did not checksum all 154 GiB of media.

The restored v2.7.5 application started successfully, with 22,809 assets, 2 users,
26 albums, 68 migration records, zero invalid indexes and no startup error lines.
This verifies rollback startup and database integrity; it is not a separate
operator-authenticated rollback browser test.

The Pod was then recreated for v3.2.0 with a fresh cache and the same pre-v3
database, retaining the corrected 3 GiB PostgreSQL memory limit. It became ready
in 16 seconds. Counts remained 22,809 / 2 / 26, migration records increased from
68 to 96, and invalid indexes remained zero. All three containers had zero
restarts. Twenty-four health probes over approximately 46 seconds passed, with
a maximum latency of 73 ms, and startup logs had no error lines. PostgreSQL's
reported cgroup peak was 852,799,488 bytes for this clean Pod lifetime.

`immich_rollback_frozen` now contains the clean v3 rehearsal result; its name no
longer indicates a pre-v3 schema. The frozen pre-v3 dump remains the recovery
source. The original first-run v3 database `immich` is also retained. The current
localhost-only alternative tunnel writes to ignored
`verification/cache/rollout/port-forward-clean-v3.log`.

## Post-download tunnel failure and direct SSH access

The operator confirmed a photo download worked, then reported another hang.
The alternative Kubernetes port-forward also logged stream-creation timeouts,
and localhost ping timed out. Inside the Pod, ping still returned HTTP 200 in
70 ms; the clean rehearsal remained Running with zero restarts. Short concurrent
request tests had not established sustained Kubernetes tunnel reliability.

Using the existing VM login documented in the K3s runbook
(`benkim0414@192.168.0.22`, configured `pi_ed25519` identity), a same-node request
to the rehearsal Pod returned ping in 3 ms. The failed task-local port-forward
was replaced with an SSH local forward bound to `127.0.0.1:2284`, targeting only
`10.42.4.64:2283`. Host key verification remains enabled. No Service, ingress,
firewall rule, authentication setting or NetworkPolicy was changed. The
rehearsal's outbound production connection was rechecked and remained denied.

The temporary tunnel log is ignored at
`verification/cache/rollout/ssh-tunnel.log`. The target Pod IP must be reverified
if the rehearsal Pod is recreated. This is temporary rehearsal access, not a
production exposure mechanism. Video, search and test upload remain unconfirmed.

Direct-tunnel validation passed 176 concurrent page/asset requests (22,005,992
bytes; maximum request duration 2.547 seconds), followed by eight deliberately
slow concurrent downloads of a public 4,845,504-byte application asset
(38,764,032 bytes total). Fifteen interleaved health probes all passed, with a
maximum latency of 1.039 seconds. These tests do not prove sustained browser
session stability; the operator was asked to retry download and Albums.

## Rehearsal acceptance and production preflight

The operator confirmed "All works and tested" after the direct SSH tunnel fix.
This completes acceptance of the requested login, timeline, Albums, download,
video, search and test-upload checks. Earlier pending-check statements above
record the sequence of testing and are superseded by this confirmation.

Full local verification passed again: 19 Applications and 471 resources, against
`origin/main` at `18c627f8b41f8d49e4dd3c1b578af015ac9523eb`. The merged revision's
GitHub Verify workflow also passed. These are configuration checks, not evidence
of a production migration.

The live Application descriptor was aligned with the merged declaration (chart
0.13.4 and inclusion of the inactive PG16 manifests), without a workload sync.
Manual sync remains enabled; status is OutOfSync / Healthy. The ArgoCD API
credential failed signature validation, so the configured Kubernetes access was
used for resource inspection; credentials were not changed. The local render
was compared with live resources, including individual container fields. The
18-resource inventory has no prune candidates and the render has no sync hooks.
The chart changes the server to v3.2.0, Valkey to the rehearsed pinned 9.1.2 image,
and server strategy to Recreate. Secret references, environment configuration,
media mounts and declared storage identities remain unchanged.

Production database cutover and application upgrade have not started. The next
gate is an approved maintenance window for blocking writers, obtaining a final
database dump and matching media snapshot, restoring and verifying production
PG16, and applying the reviewed cutover before the v3 rollout. The old PG14 PVC
and recovery archives remain retained. Rehearsal cleanup and restoration of the
temporary NAS quota remain separate, pending explicit cleanup approval.

## Approved production maintenance and final restore

The operator approved the maintenance window, publication/merge of the reviewed
cutover, and v3 rollout. External Service routing was blocked and the server
scaled from one replica to zero at approximately 03:10 UTC. Scheduled backups
were suspended; no active backup or queue work remained. Source connections were
zero after shutdown. Frozen counts were 22,809 assets, 2 users and 26 albums,
with zero invalid indexes.

Final Job `immich-final-pg14-20261111031007` completed in 24 seconds using the PG16
client, retention disabled, and the existing credential reference. Its archive is
`/backups/migrations/immich-20261111T031024424414710Z.dump`, SHA256
`2c693626ec38df2d3a8fa8b7c065e62ac1dab8de01ec74a3522565804b27ef6c`.
Matching media/archive checkpoint: `storage/k3s@immich-final-pg14-20261111T0310Z`.
The NAS pool was healthy.

The new production claim `data-immich-postgres16-0` is Bound to
`pvc-82e50c89-0c5f-40bf-a70b-41d6f475e80a`; only the new target mounts it.
Guarded restore Job `immich-pg16-restore-srlv7` completed successfully. PG16.10
contains the matching aggregate counts, zero invalid indexes, a 190 MB database,
vector 0.8.1 and vchord 0.4.3. Earthdistance is 1.2 instead of PG14's 1.1, matching
the successful rehearsal. The old PG14 claim remains intact.

The generated cutover changes are now ready for publication. Production routing
and application upgrade remain gated until the cutover commit is merged.

## Production database cutover and v3 rollout

PR #92 passed GitHub Verify and merged as
`fe300996579942d6976c56ac5b1b425f1f8202b9`. Local verification passed for
19 Applications and 471 resources; 78 unit tests completed with six skips
(including the already-applied cutover generator), and five policy tests passed.

A selected ArgoCD sync applied only the two database StatefulSets and database
Services, with no pruning or force. The stable Service endpoint resolved only to
`immich-postgres16-0` at `10.42.2.81`. PG14 stopped and its original PVC remained
Bound. The new Longhorn volume was healthy, attached and configured for two
replicas. The final production restore Job took 34 seconds.

Immich v2.7.5 started on PG16 with zero startup error lines. Ping and version
returned HTTP 200. All 22,809 original media paths were readable, aggregate
counts matched and invalid indexes remained zero. This operational check did
not include a separate operator-authenticated v2 production login.

The PG16 backup CronJob was synced and its image and unsuspended state verified.
The v2 server was then stopped again, backups suspended for schema transition,
and zero other database connections confirmed. Frozen pre-v3 Job
`immich-pg16-prev3-20261111031652` published
`/backups/migrations/immich-20261111T031653006541328Z.dump`, SHA256
`7553ffc3a435c1ef79354e8707f2052547091331edce2d07c59630925a91eea4`.
Matching NAS snapshot: `storage/k3s@immich-production-prev3-20261111T0317Z`.
The guarded helper restored this into isolated database
`production_pg16_prev3_check`, with 22,809 assets, 2 users, 26 albums and zero
invalid indexes. No production media or credentials were copied into rehearsal.

The reviewed server, Valkey, ServiceAccounts and Valkey Service were synced at
the merged revision, without pruning. The server image pull took 28.84 seconds.
V3.2.0 reached readiness with no startup error lines and zero container restarts.
Ping/version passed; counts and vector/vchord versions remained unchanged, and
invalid indexes remained zero. All 22,809 original media paths were readable.

Post-v3 Job `immich-pg16-postv3-20261111031909` published
`/backups/migrations/immich-20261111T031910607560138Z.dump`, SHA256
`cdb04edb9f980a375d01747783ba48c02bf67163dfee57ac41c2d10bb3c2e74f`.
It restored through the guarded helper into isolated database
`production_pg16_postv3_check`, with matching counts and zero invalid indexes.

A localhost-only SSH forward on port 2285 targets production Pod
`10.42.2.85:2283` through its node k3s-03. The rehearsal remains on port 2284.
Production concurrent testing passed 176 page/static-asset/API requests
(22,005,992 bytes, maximum 1.958 seconds). Authenticated album requests were not
part of that automated test; unauthorized API responses were checked as 401.
The operator has been asked for final production functional checks and a small
test upload before general traffic is reopened.

Twelve further health probes over approximately 24 seconds passed with a maximum
latency of 20 ms. The database has 96 migration records. Production server,
Valkey and PostgreSQL have zero restarts. Measured memory was approximately
683 MiB / 8 MiB / 417 MiB respectively. ArgoCD is Healthy; the only OutOfSync
resource is the deliberately blocked server Service.

Original PRs #75 and #77 were closed as superseded by merged PRs #90, #91 and
#92. Their closing comments record the replacements and the pending final
production functional acceptance.

Scheduled PG16 backups were explicitly resumed after successful post-v3 restore
verification while operator testing remained pending. The remaining maintenance
change is external server routing; the final guarded reconciliation script is
prepared but has not been executed.

## Final production acceptance and reopened access

The operator confirmed "Works okay" in response to the production functional
check. On 2026-11-11T03:29:08.404913+00:00, the original server Service
selector was restored and the complete reviewed Application was synced at
`fe300996579942d6976c56ac5b1b425f1f8202b9`, without pruning or force. ArgoCD
reported Succeeded, Healthy and Synced. Both LAN
`http://192.168.0.201:2283/api/server/ping` and Tailscale
`https://immich.tailbd291c.ts.net/api/server/ping` returned `{"res":"pong"}`.

Production server, Valkey and PostgreSQL were Ready with zero restarts. PG14
remains at zero replicas and its original claim remains Bound. The PG16 backup
CronJob is unsuspended, with no active Job at this check. The temporary local
validation tunnels are no longer needed after normal access is restored.

User writes are now admitted. The retained PG14 database is stale from this
point: switching back would lose later changes. Preserve current database/media
before any recovery and do not downgrade the v3 schema in place.

The rehearsal namespace, media copies, database claims, archives and snapshots
remain retained. NAS quota remains at the explicitly approved temporary 500 GiB.
Cleanup requires separate approval; check actual usage before restoring 300 GiB.
