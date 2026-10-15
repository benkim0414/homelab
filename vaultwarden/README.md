# Vaultwarden

The rebuilt deployment uses chart `0.46.3` and server `1.37.1`, with a 2 GiB
Longhorn volume and two replicas. The configured URL is
`https://vaultwarden.tailbd291c.ts.net`; the dedicated MetalLB address is `.205`.

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
