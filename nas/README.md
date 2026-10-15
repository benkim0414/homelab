# NAS snapshots

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

## Installation (requires approval)

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
