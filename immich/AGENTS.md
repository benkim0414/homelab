# Immich instructions

Read [the runbook](README.md) for storage, recovery, backup verification, and
upgrade procedures. These rules also apply to `argocd/apps/immich.yaml`.

## Data and upgrade constraints

- Keep the Helm chart pin and server image compatible; they use different version
  schemes and need not be numerically equal. Review release/migration requirements
  before changing either. Preserve restored versions unless upgrading is in scope.
- Before an upgrade rollout, verify a recent successful PostgreSQL backup Job.
  A CronJob schedule alone is not evidence of success or a pre-upgrade gate.
- Preserve the PostgreSQL image's required vector extensions, database credentials,
  library mount, and existing volume identities during recovery. Restore controller
  keys and database/media prerequisites before starting the server.
- Check actual PV reclaim and PVC retention policies before proposing removal.
  NFS Retain does not imply Longhorn database storage survives PVC deletion.
- Keep backup retention confined to its dedicated scheduled-backup directory;
  preserve verified rebuild archives. NAS snapshots do not replace database dumps
  or protect against loss of the NAS itself.
- Keep offsite backup and S3 secret manifests excluded until replacement credentials
  and activation are explicitly authorized. Do not refresh credentials for checks.

## Verification

- Follow [ArgoCD instructions](../argocd/AGENTS.md) when changing Application
  sources, pins, raw-manifest inclusion, or sync behavior.
- Check values, PostgreSQL/storage references, and backup configuration together.
  An archive listing validates structure; it does not prove a successful restore.
- Report local validation separately from any authorized backup, restore test,
  application health check, or upgrade rollout.

## Code Review Rules

- Flag chart/server version changes without compatibility and migration review.
  Use compatible versions, not numerical equality between chart and image tags.
- Flag upgrade rollout plans without a verified recent successful database backup;
  a scheduled CronJob or successful archive listing is not proof of recovery.
- Flag restore changes that replace required PostgreSQL vector extensions,
  credentials, or volume identities. Preserve them unless a separately reviewed
  migration or rotation is explicitly requested.
