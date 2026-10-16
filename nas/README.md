# NAS storage and recovery

The NAS at `192.168.0.40` was preserved during the October cluster rebuild.
This runbook consolidates useful material from the original OpenMediaVault
guide. Hardware/bootstrap details below are historical setup records, not a
fresh inspection. Operational changes require separate authorization.

## Storage identities

| Purpose | NAS path or identity |
| --- | --- |
| ZFS pool | `storage`, originally two mirrored pairs of Crucial BX500 500GB SSDs |
| Cluster dataset | `storage/k3s`, mounted at `/storage/k3s` |
| NFSv4 cluster export | `192.168.0.40:/k3s-storage` through `/export/k3s-storage` |
| Immich media | `/storage/k3s/immich/library` |
| Immich scheduled dumps | `/storage/k3s/immich/backups/scheduled`, 03:00 Melbourne, retain 7 |
| Vaultwarden archives | `/storage/k3s/vaultwarden/backups`, 03:30 Melbourne, retain 7 |
| Longhorn backup target | `nfs://192.168.0.40:/longhorn-backups` |
| Independent rebuild recovery set | `/storage/rebuild-backups/2026-10-14`, excluded from retention |

Live application databases use Longhorn volumes on cluster SSDs, with two
replicas. NFS Retain policies do not protect those database PVCs from deletion.
Use the current [Immich](../immich/README.md) and
[Vaultwarden](../vaultwarden/README.md) manifests/runbooks for volume identities,
ownership and restoration. Do not recreate the old generic NFS StorageClasses,
shared PVs, local-path database examples or unused media-stack directories.

## Hardware and pool recovery

The original NAS build used a Raspberry Pi 5 with 16 GiB RAM, Radxa Penta SATA
HAT, four SATA SSDs, a Radxa DC12 60W supply and a separate OS SD card.
Its `/boot/firmware/config.txt` enabled PCIe with `dtparam=pciex1` and used
`dtparam=pciex1_gen=3`. Preserve these recorded boot settings during OS recovery;
inspect `lspci` and `lsblk` to confirm the controller and all drives appear.

Inspect existing storage before considering any replacement or import:

```sh
sudo zpool status -P storage
sudo zpool list storage
sudo zpool import
sudo zfs list -r storage
sudo zfs get mountpoint,compression,recordsize,quota,reservation storage/k3s
ls -l /dev/disk/by-id/
```

`zpool import` without a pool argument lists import candidates. If the existing
pool is missing after OS replacement, identify its member disks and pool GUID,
then arrange an approved import and OMV ZFS-plugin registration. Do not create a
new pool, force an import or overwrite signatures as a discovery step. Historical
layout was two mirror vdevs; inspect actual membership with stable by-id paths
before replacing a disk. After an approved replacement, monitor resilvering with
`zpool status` and verify the exported data before resuming workloads.

Pool health and OMV UI registration are distinct. If ZFS sees an imported pool
but OMV does not, inspect its ZFS plugin and registration before proposing
`omv-salt deploy run zfs` or an engine restart. The old guide's quota and
reservation examples were not a record of verified current capacity. Inspect
actual free space and snapshot growth rather than reapplying them.

## NFS export recovery and troubleshooting

The recorded bind mapping is `/storage/k3s` to `/export/k3s-storage`.
An additional historical media dataset mapped `/storage/media` to
`/export/media-storage`; preserve it if present, but current cluster application
manifests do not establish its use. Inspect before changing mounts or exports:

```sh
findmnt /storage/k3s
findmnt /export/k3s-storage
sudo exportfs -v
systemctl status nfs-kernel-server
```

The recorded persistent bind entry is:

```fstab
/storage/k3s /export/k3s-storage none bind 0 0
```

Check existing OMV-managed mounts and `/etc/fstab` before restoring a missing
entry. Configure shares and client access through OMV rather than overwriting
its generated `/etc/exports`. Mount/export changes and service restarts require
approval; do not unmount active application storage as a test.

This NAS's NFSv4 client paths use `/k3s-storage/...`, omitting the NAS-side
`/export` prefix. A missing-path error can mean either a missing backing bind
mount or an incorrect client path. Confirm the exported directory has the
expected files. Permission failures require checking numeric UID/GID, directory
modes, export mapping and workload security context together; do not recursively
change all datasets to the old guide's example UID `1000`.

For SMB recovery, retain OMV-managed shares and user mappings; the original
media share was named `media-storage`. Verify its actual backing dataset and
access requirements before re-enabling it. Do not reset users or authentication
as part of storage discovery.

## Maintenance

Inspect `zpool status`, `zpool iostat storage`, dataset space, SMART results and
OMV notifications regularly. The original setup called for monthly ZFS scrubs;
verify the actual scheduled task instead of assuming it survived OS changes.
Snapshots consume the same pool's capacity, so leave headroom for changed data.
For any recovery, preserve the independent rebuild archives until replacement
backups have been restored and checked. Rollback, disk replacement, pool import
and configuration changes require an operation-specific recovery plan.

## Daily snapshots

`homelab-k3s-snapshots.timer` snapshots `storage/k3s` daily at 03:45
Australia/Melbourne, after the scheduled 03:00 Immich database and 03:30
Vaultwarden backups. These schedules do not guarantee the backup jobs completed;
check their Kubernetes Job status separately.

The dataset contains live Immich media, Immich database dumps and Vaultwarden
backup archives. Database volumes remain on Longhorn: a ZFS snapshot cannot
replace the application backup jobs. Snapshots are filesystem-consistent, and
their recovery point depends on the latest successful application backup.

Only the latest seven snapshots named exactly
`storage/k3s@homelab-daily-YYYYMMDDTHHMMSSZ` are retained. Other snapshots, child
datasets, existing archives and `/storage/rebuild-backups/2026-10-14` are excluded
from pruning. Snapshot creation must succeed before pruning starts. Failed
creation or deletion makes the service fail; inspect `journalctl -u
homelab-k3s-snapshots.service` and `systemctl --failed`.

Snapshots share the NAS pool and consume additional space as files change. They
protect against accidental changes but do not survive NAS/pool loss. No automatic
rollback is configured.

### Snapshot installation (requires approval)

Install `k3s-snapshots.py` as root-owned mode 0755 at
`/usr/local/sbin/homelab-k3s-snapshots.py`, and the service/timer as root-owned
mode 0644 under `/etc/systemd/system/`. Then run:

```sh
sudo systemctl daemon-reload
sudo systemctl start homelab-k3s-snapshots.service
sudo systemctl enable --now homelab-k3s-snapshots.timer
sudo systemctl list-timers homelab-k3s-snapshots.timer
sudo zfs list -t snapshot -r storage/k3s
```

Installed and enabled on 15 October 2026 with user approval. The first run
succeeded, creating `storage/k3s@homelab-daily-20261014T232502Z`.
The timer's next run was verified as 16 October 2026 at 03:45 AEDT.
Inspect free pool space and service logs regularly.
