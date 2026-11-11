# Immich v3.2.0 / chart 0.13.4 upgrade

Replacement for stale [PR #77](https://github.com/benkim0414/homelab/pull/77).
The pre-upgrade recovery baseline is chart 0.12.0, server v2.7.5. This change
declares chart 0.13.4 and explicitly pins server v3.2.0; chart and image version
numbers have different meanings. It is not a record of a completed deployment.

## Compatibility review

- [Chart 0.13.4](https://github.com/immich-app/immich-charts/blob/immich-0.13.4/charts/immich/Chart.yaml)
  declares appVersion v3.2.0 and common library 5.2.1. The upgrade crosses the
  breaking 0.13.0 release. Validate the packaged chart, including values schema,
  actual images, Service selectors and volume mounts; the PR's old patch label
  no longer describes the upgrade from the restored 0.12.0 baseline.
- [Immich v3 migration](https://immich.app/blog/v3-migration) removes pgvecto.rs
  support, deprecated environment variables, legacy mobile timeline support and
  API fields/endpoints. The inspected database has VectorChord 0.4.3 and pgvector
  0.8.1; retain them and verify the actual indexes and extension selection before
  rollout. Do not infer extension selection merely from the container tag.
- The removed environment variables listed upstream are absent from repository
  values. Inspect any live overrides and external API consumers without
  exporting credentials. Upgrade affected consumers before reopening access.
  Check OAuth issuer/configuration if enabled; do not enable insecure OAuth.
- Upgrade mobile clients to versions compatible with v3 first. This needs user
  confirmation at the maintenance gate because client state is not in Git.
- Machine learning stays disabled. Its changed x86 baseline does not justify
  enabling it. Preserve current external access, library and credentials.
- Server strategy is `Recreate` to prevent overlapping server versions during
  schema changes. This intentionally incurs downtime; it does not by itself stop
  external writers or replace the maintenance procedure.

## Dependencies and rollout gates

Complete the separately reviewed PostgreSQL 16 migration replacing
[PR #75](https://github.com/benkim0414/homelab/pull/75) first. Refresh this branch
against main after that migration's Git changes land and rerun verification.
Do not merge/sync this upgrade while the database cutover is in progress. Although
upstream v3.2.0 also ships a PostgreSQL 14 example, this project's chosen sequence
validates the old server on PG16 before changing the application schema.

Require an isolated rehearsal of the complete v2.7.5-to-v3.2.0 path on a restored
database with a separate writable media copy and cache. Disable outgoing
integrations there. Never mount the production library writable in rehearsal.
Record restore/migration durations, extension/index results and aggregate counts.
Do not infer recoverability from `pg_restore --list` alone.

Before the approved window:

1. Run full [verification](../verification/README.md) against current main and
   review the entire [pre-sync checklist](../argocd/README.md#verification-before-manual-sync).
   Check the pinned image architectures against eligible nodes and available RAM.
2. Record current database/volume identities, versions, asset/user/album counts,
   successful backup Job and a fresh verified archive outside scheduled retention.
   Record a matching NAS media snapshot while writers are stopped. Do not revert
   the shared NAS dataset to recover one application's media.
3. Confirm mobile client readiness and external API integration compatibility.
   Prevent uploads/integration writes, drain background jobs and stop all old
   server/worker pods before replacing the ephemeral Valkey queue. Confirm no
   active backup Job; suspend scheduled backups for the transition.
4. Inspect the complete ArgoCD diff, especially Valkey's actual image, memory
   limit, service discovery, emptyDir queue and any unexpected resource removal.
   Do not prune, force/replace or modify storage to make the sync pass.

Deploy only the reviewed revision, without pruning. Keep writes blocked until
the server finishes migrations and passes readiness. Inspect migration errors,
index validity and job processing; the startup probe allows ten minutes, but a
restart loop is a failure requiring investigation, not permission to erase data.
If migrations exceed that budget in rehearsal, adjust the probe before rollout.

Verify LAN and Tailscale ping, authenticated login, timeline, albums, existing
photo download, video playback and non-ML search. Compare aggregate counts to
the frozen baseline; test a controlled upload before admitting general traffic.
Ensure no unexpected ML workload exists and external database references still
resolve to the migrated PG16 Service. Resume scheduled backups, run a fresh
PG16 backup and verify an isolated restore. Record the deployed commit, ArgoCD
health, smoke-test results and backup evidence in a committed rollout report.

## Rollback

Immich does not support downgrading a migrated database. A Git revert or old
container image alone is insufficient. Before reopening writes, stop v3, restore
the pre-v3 database checkpoint into a separate recovery destination and pair it
with the corresponding media checkpoint. Then restore the reviewed old chart and
server pin and redirect database traffic only after the restored data is checked.
Preserve the failed PG16 database for investigation. Never start v2.7.5 against
the v3-migrated schema.

If choosing the retained PG14 fallback from the earlier migration instead, first
prove that no user writes occurred between its final dump and the v3 checkpoint;
otherwise it is stale. After reopening writes, stop and preserve the new database
and media, then plan reconciliation before any rollback. Obtain explicit approval
for data loss, cleanup or claim deletion. Keep manual ArgoCD sync throughout.

## Validation record

Local full verification passed on 2026-11-11 (19 Applications, 469 resources);
73 unit/render tests passed with five existing skips, and five policy tests passed.
The target renders Valkey `9.1.2-alpine` with its chart-provided digest and
`emptyDir`, a 128 MiB limit, and the existing `immich-valkey` Service. The server
and database target image manifests both advertise Linux amd64 and arm64.
Local rendering and tests are also recorded on the replacement PR. Live rehearsal,
client confirmation, maintenance approval, migration success and post-upgrade
backup/restore evidence remain required before deployment is accepted.

References: [v3.2.0 release](https://github.com/immich-app/immich/releases/tag/v3.2.0),
[upgrade and downgrade policy](https://docs.immich.app/install/upgrading/).
