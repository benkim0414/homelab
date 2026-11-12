# Immich v3.2.0 to v3.4.1 proposal

This is a **local upgrade proposal**, not deployment evidence. Keep Helm chart
`0.13.4`; only the server override changes from `v3.2.0` to `v3.4.1`.
The chart's appVersion is v3.2.0, not a maximum supported image version. Local
rendering must confirm the explicit override and unchanged `/data`, database,
Valkey and Service wiring. No PostgreSQL engine, image, extension or PVC change
belongs to this upgrade. Machine learning remains disabled.

The [original v3 runbook](UPGRADE-v3.md) documents the earlier v2.7.5 transition;
use it for an old recovery set, not as instructions to repeat the PG16 cutover.
See the [earlier migration/recovery record](../reports/2026-11-11-immich-rollout.md)
for checkpoint evidence; its final entry still gates cutover publication. Reconfirm
the actual live server/database baseline before using this v3.2.0 upgrade path.

## Release and migration review

Reviewed [v3.3.0](https://github.com/immich-app/immich/releases/tag/v3.3.0),
[v3.4.0](https://github.com/immich-app/immich/releases/tag/v3.4.0) and
[v3.4.1](https://github.com/immich-app/immich/releases/tag/v3.4.1), plus the
[tagged migration source](https://github.com/immich-app/immich/tree/v3.4.1/server/src/schema/migrations)
against v3.2.0. Neither minor release instructs a PostgreSQL engine/extension
upgrade. That is not evidence of a tested database restore or production migration.

The target adds these migrations relative to v3.2.0:

- `1789419229196`: convert empty user OAuth IDs to NULL; relax nullability.
- `1790587508209`: rewrite stored country names in EXIF and workflow filters to
  GeoNames names. Its `down()` is intentionally unimplemented.
- `1790616293884` / `1790693088454`: person-sharing table, functions, triggers,
  indexes and a constraint forbidding self-sharing.
- `1792213725597`: backfill asset-face owner, visibility and deletion state,
  add triggers, build a timeline index and ANALYZE. Budget database time, WAL
  space and lock acquisition for the backfill even with ML disabled.
- `1792511451454`: passkey/auth-challenge tables. This proposal does not enroll
  passkeys or change the configured authentication method.
- `1792517020180` / `1792568637987`: update-ID indexes on stacks, faces,
  workflows and assets. Index builds are additional startup work.

These are schema/data changes, not a restart-only patch. Several historical
migration files also differ upstream; a normal existing database should not
re-run already-recorded migrations. Rehearse the actual checkpoint, including
its migration history, rather than validating an empty fresh install only.

v3.3 introduces person sharing, different thumbnail generation and optional ML
model revision v2. Do not enable ML or regenerate all thumbnails as part of this
upgrade. Review person-sharing behavior with both users. OAuth claim syncing
changes require checking the existing provider behavior if used, without changing
credentials. v3.4 removes the deprecated update-me password field and tightens
shared-link permissions, storage paths and symlink handling, plus CSP. Test
external integrations, existing media paths, shared links and browser login.
v3.4.1 fixes shared-link performance and queue status. The bundled backup feature
and futo-backup changes do not replace or authorize changes to our NAS dump jobs.
Confirm mobile/API consumers support the target before opening writes.

## Rollout gate (separate authorization required)

1. Run full repository verification and review the complete generated-to-live
   ArgoCD diff. Keep manual sync, `Recreate`, PVC identities, reclaim policies,
   external Secret references and the existing database image/extensions.
2. Check target image availability on eligible amd64/arm64 nodes. Reconfirm
   storage headroom, backup destination and no concurrent restore/cutover.
3. Require a recent successful `immich-pg-backup` Job, then a fresh pre-upgrade
   checkpoint outside scheduled retention during the approved maintenance
   window. A successful Job or `pg_restore --list` is not a restore test.
4. Rehearse the v3.2.0-to-v3.4.1 migration on an isolated restored database and
   separate writable media copy/cache, with outbound integrations disabled.
   Verify extension/index validity, aggregate counts and representative media.
   Record migration/restore duration; adjust the startup budget only if evidence
   requires it. Do not mount production media writable in the rehearsal.
5. Block uploads/integration writes, drain work and stop old server instances;
   pair the database checkpoint with a matching media snapshot. Do not roll back
   the shared NAS dataset to recover one app. Coordinate any temporary backup
   pause separately; no schedule/retention change is included in this proposal.
6. Sync only the reviewed revision without prune/force/replace. Keep writes
   blocked through startup migrations. Investigate migration failures or restart
   loops; never erase data or swap database images to make readiness pass.
7. Check LAN/Tailscale ping, login, timeline, albums, person access, shared links,
   downloads, video playback and non-ML search; compare frozen counts. Test a
   controlled upload, reopen traffic, and verify a new backup and isolated restore.

## Recovery

Follow the [upstream downgrade policy](https://docs.immich.app/install/upgrading/):
**do not run v3.2.0 against the migrated v3.4.1 database**. A Git/image revert is
not a data rollback, and the country-name rewrite is not reversibly encoded.
Stop writers, preserve the failed database/media, restore the pre-upgrade dump
into a fresh destination with the exact existing PostgreSQL image/extensions,
and pair it with the matching media checkpoint. Verify recovery before a
reviewed routing switch and restoration of server v3.2.0 / chart 0.13.4.
Do not reuse the retained, stale PG14 volume as a v3.2.0 checkpoint. Once writes
have reopened, reconciliation and any potential data loss need explicit approval.
No rehearsal, restore, rollout, schedule change or cleanup was executed here.
