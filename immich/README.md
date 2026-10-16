# Immich on K3s

The restored deployment uses Helm chart `0.12.0` with server `v2.7.5`, matching
its pre-rebuild version. The cluster has four Raspberry Pis and one amd64
Proxmox worker. Both architectures are available for scheduling.

## Storage and access

| Component | Storage / configuration |
| --- | --- |
| Photo and video library | NAS `.40`, `/storage/k3s/immich/library`, NFSv4 `/k3s-storage/immich/library` |
| PostgreSQL | 20 GiB Longhorn PVC `data-immich-postgres-0`, two replicas |
| Database backup destination | NAS `/storage/k3s/immich/backups`, NFSv4 `/k3s-storage/immich/backups` |
| Valkey | Ephemeral cache/queue |
| Machine learning | Disabled |
| LAN | `http://192.168.0.201:2283` |
| Tailscale | `https://immich.tailbd291c.ts.net` |

The library and backup NFS PVs use `Retain`; their declared capacities are not
NAS quotas. PostgreSQL uses the image pinned in `postgresql.yaml`, including the
required vector extensions. Do not substitute a generic PostgreSQL image during
restore. The server mounts the library at `/data`.

## Recovery and deployment

The October rebuild restored 22,784 assets, 2 users and 26 albums. All original
media paths were verified, and the user confirmed the application works. See the
[rebuild record](../docs/superpowers/plans/2026-10-14-cluster-rebuild.md) for the
verified archives, hashes and recovery sequence.

For a fresh recovery, restore the Sealed Secrets controller key first, then apply
the existing database SealedSecret, namespace and storage manifests. Restore the
database and confirm media access before starting the pinned server version.
Keep the existing database credentials when restoring; generating a replacement
password is a separate rotation operation.

The chart installation command, once data and credentials are ready, is:

```bash
helm install immich oci://ghcr.io/immich-app/immich-charts/immich \
  --namespace immich -f immich/values.yaml --version 0.12.0
```

The current deployment is restored and manual ArgoCD adoption is complete.
Review the full diff before future syncs. The raw manifest include list in
`argocd/apps/immich.yaml` must cover storage, PostgreSQL, backups,
SealedSecret and the Tailscale ingress.

## Scheduled backups

`immich-pg-backup` runs at **03:00 Australia/Melbourne**, retaining the latest
seven successful dumps in `/storage/k3s/immich/backups/scheduled`. It publishes
only a nonempty custom-format dump whose `pg_restore --list` check passes.
Retention affects only this dedicated directory, preserving older dump archives
and the verified rebuild backups at `/storage/rebuild-backups/2026-10-14`.
A listing check validates archive structure; periodic isolated restore testing
is still needed to verify full recoverability.

The NAS snapshots `storage/k3s` at **03:45 Melbourne time**, retaining seven
managed snapshots. This covers media and stored database dumps, not the live
Longhorn database volume. See [NAS snapshots](../nas/README.md). Both snapshots
and archives are on the same NAS; S3 backups remain disabled pending replacement
credentials.

To run the configured database job manually, choose a unique job name:

```bash
kubectl --kubeconfig /tmp/homelab-k3s-rebuild.yaml create job \
  --from=cronjob/immich-pg-backup immich-backup-check-<date> -n immich
```

## Verification and upgrades

```bash
kubectl --kubeconfig /tmp/homelab-k3s-rebuild.yaml get pods,pvc,cronjobs -n immich
curl --fail http://192.168.0.201:2283/api/server/ping
curl --fail https://immich.tailbd291c.ts.net/api/server/ping
```

Both ping endpoints return `{"res":"pong"}`. Use the restored account; no new
admin account is needed. Before upgrading, verify a fresh database backup,
review the release's migration requirements, and update both the chart pin in
`argocd/apps/immich.yaml` and compatible image tag in `values.yaml`.

Before removing workloads or claims, review the actual PV reclaim policies and
PVC retention behavior. NFS `Retain` does not imply Longhorn volumes will survive
claim deletion. Removal is a separate operation requiring approval.
