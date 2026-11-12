# Vaultwarden

The declared upgrade target is chart `0.46.4` and explicit server `1.37.5`.
The rebuilt deployment used server `1.37.1`; a desired pin does not prove rollout.
The deployment uses a 2 GiB Longhorn volume with two storage replicas. The configured URL is
`https://vaultwarden.tailbd291c.ts.net`; the dedicated MetalLB address is `.205`.

## Upgrade review: server 1.37.1 to 1.37.5

The repository's previous explicit image was `1.37.4`, but the supplied live
baseline is `1.37.1`; review the complete live-to-target path. Chart `0.46.4`
changes appVersion/default Alpine tag, not workload or storage templates. Our
explicit `1.37.5` override keeps the existing non-Alpine image variant.

Reviewed releases [1.37.2](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.2),
[1.37.3](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.3),
[1.37.4](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.4),
[1.37.5](https://github.com/dani-garcia/vaultwarden/releases/tag/1.37.5) and
[chart 0.46.4](https://github.com/guerzon/vaultwarden/releases/tag/v0.46.4).

- 1.37.2 supports newer 2026.8+ clients; 1.37.4 and 1.37.5 include security
  fixes, notably organization revocation, 2FA, attachments, icons and emergency
  access. 1.37.5 bundles web vault 2026.10.1 and fixes newer 2FA/emergency-access
  payloads. No custom web vault is declared here.
- 1.37.4 changes forwarded-IP selection to the rightmost untrusted address,
  removes legacy registration/prelogin endpoints and deprecated feature flags,
  and drops old CLI Send receive support. Check actual client/proxy compatibility
  before rollout; no proxy trust or authentication changes are included.
- 1.37.5 rejects invalid numeric settings and purge cron expressions at startup.
  Declared values do not set the affected numeric/cron options, but persisted
  admin configuration and runtime overrides still need owner validation without
  exporting credentials. Do not remediate by silently removing saved settings.
- Before separately authorized sync, verify a recent successful backup Job and a
  fresh recovery checkpoint, plus an isolated full-data restore/integrity and
  attachment test. Review the generated-to-live diff and target architectures.
  Preserve the existing PVC, signups-disabled policy, Secret references, service
  exposure and manual sync. No PostgreSQL change is involved (SQLite).
- Test existing clients, login/2FA, vault sync, attachment download and an approved
  controlled write. Do not rotate organization/API credentials as part of this
  change; upstream's conditional rotation advice requires separate approval.
- Treat schema changes as forward-only operationally. For rollback, stop the
  application and restore the entire pre-upgrade data archive to a fresh volume
  with the matching old image. An image revert alone is not a recovery plan.

This is a local proposal; no deployment, archive inspection or restore test was
performed. Job success does not prove a complete restore or a consistent snapshot
of concurrently changing attachments.

## NAS backups

`vaultwarden-backup` runs daily at 03:30 in `Australia/Melbourne` and retains
seven successful archives. It runs on the same node as the application so the
ReadWriteOnce data volume can be mounted read-only. SQLite's online backup API
produces a separate database snapshot. The archive includes the remaining data
directory, including attachments, configuration and the RSA signing key; live
SQLite WAL/shared-memory files and temporary directories are excluded.

Before publishing an archive, the job checks SQLite integrity and verifies that
every attachment referenced by the database has an archive member. It writes a
temporary filename, then renames the verified result. Application writes can
continue during the SQLite backup, but the filesystem and database are not one
transaction: concurrent attachment deletion can cause a backup run to fail.
The previous successful archives remain available if that happens.

Archives live at `/storage/k3s/vaultwarden/backups` on the NAS through the NFSv4
export `/k3s-storage/vaultwarden/backups`. They are **not encrypted**, contain
sensitive material and use mode `0600` within a root-owned `0700` directory.
The Retain PV's 10 GiB capacity is a Kubernetes declaration, not an NFS quota.
Only `vaultwarden-*.tar.gz` in this dedicated directory participates in retention;
the verified rebuild backup is separate and remains untouched.

The NAS also snapshots `storage/k3s` at 03:45 Australia/Melbourne, retaining seven
managed snapshots. Those snapshots include the published archives, not the live
Longhorn database. See [NAS snapshot policy](../nas/README.md). Both are on the
same NAS and do not provide recovery from NAS pool loss.

To test the configured job:

```bash
kubectl --kubeconfig /tmp/homelab-k3s-rebuild.yaml create job \
  --from=cronjob/vaultwarden-backup vaultwarden-backup-check-<date> -n vaultwarden
```

Restore with the application stopped and a fresh volume. Extract the complete
archive, check SQLite integrity and attachment presence, then start the pinned
server version. See the [rebuild record](../docs/superpowers/plans/2026-10-14-cluster-rebuild.md)
for the completed restoration and acceptance checks.
