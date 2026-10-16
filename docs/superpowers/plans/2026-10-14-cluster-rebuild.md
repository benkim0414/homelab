# October 2026 cluster rebuild and recovery record

This records the 14–16 October rebuild of four Raspberry Pis and replacement of
Mac Pro VM 210. It is recovery evidence, not an executable plan. The NAS at
`192.168.0.40` was preserved throughout. Operational procedures live in the
[K3s runbook](../../../k3s-ansible/README.md) and application runbooks.

## Recorded outcome and remaining work

The five nodes run K3s `v1.36.5+k3s1`: `k3s-01` through `k3s-03` are control
planes at `.11`–`.13`; `k3s-04` is the worker at `.14`; VM 210 is `k3s-05`
at `.22`. The VM runs Debian 13 Trixie with 4 vCPUs, 16 GiB RAM, a 128 GiB
disk and Longhorn replica storage. All nodes use SSD storage and Longhorn's
default disk path `/var/lib/longhorn/`, with two replicas per application volume.

Immich and Vaultwarden were restored, passed LAN and original Tailscale HTTPS
checks, and the user confirmed both applications work. Scheduled application
backups and NAS snapshots passed initial runs. Subsequent GitOps adoption
completed: all 14 Applications reported Synced/Healthy, all five nodes Ready,
and seven Longhorn volumes healthy. See the
[adoption record](../../../argocd/README.md#rebuild-adoption-record--october-2026)
for monitoring corrections and verification limits.

Remaining checks recorded at handoff:

- Home Assistant needs user onboarding and a metrics token valid in the new instance.
- S3 backups and Renovate need replacement or recovered credentials and separate activation.
- Longhorn's renamed HTTPS URL resolved in DNS, but its post-rename workstation
  HTTPS check timed out; the earlier suffixed URL passed.
- After migration to `.22`, strict SSH verification used a temporary trusted-host
  file; persistent trust for that replacement key was not recorded as updated.
- Keep an external backup of the available Sealed Secrets controller key. The
  local export does not replace missing historical keys.

These are recorded results and outstanding items, not a new live health check.
Honcho and Nextcloud were not restored and their sources have since been removed.

## Preserved backup evidence

The owner-restricted NAS directory `/storage/rebuild-backups/2026-10-14` contains
the verified recovery set and `verification.json`. Preserve it separately from
scheduled retention. Vaultwarden archives contain credentials and signing
material and are not encrypted.

| Data | Verification before and during recovery |
| --- | --- |
| Immich PostgreSQL dump | Isolated restore matched 22,784 assets, 2 users, 26 albums and 225 public indexes |
| Immich source media | All 22,784 original paths existed on the source NAS dataset |
| Independent media copy | 154 GiB in `immich-media`; full rsync checksum comparison found no differences and all original paths existed |
| Vaultwarden full archive | SQLite integrity passed; 1 user, 249 ciphers, 1 attachment and signing material preserved; isolated application health passed |

Archive hashes were checked again before restoration. Immich restored
transactionally onto a fresh 20 GiB Longhorn volume using the original PostgreSQL
image, then chart `0.12.0` / server `v2.7.5`. Its database paths begin with
`/data/`, matching the chart mount. Vaultwarden's complete data archive was
restored before startup onto a fresh 2 GiB volume using chart `0.46.3` / server
`1.37.1`. Both volumes had two healthy replicas on separate nodes. Temporary
restore/check pods were removed with approval while retaining volumes and backups.
The user's application acceptance was confirmed, but individual manual
photo/video, vault decryption and attachment checks were not separately logged.

## Controller-key recovery

The fresh multi-key export was accidentally discarded. The surviving February
backup contained one key, which successfully recovered Immich database,
Vaultwarden and Home Assistant metrics SealedSecrets. No plaintext values were
printed or saved during recovery checks. With approval, the key was imported
and Sealed Secrets chart `2.20.0` installed; Immich and Vaultwarden credentials
validated against the running controller.

The key could not decrypt the old S3, Honcho, Nextcloud or Renovate secrets.
Successful recovery of one application therefore does not establish recovery of
all encrypted secrets. The fresh ignored export at
`sealed-secrets/sealed-secrets-master-keys.yaml` contains only the surviving key;
maintain an approved external copy. See
[Sealed Secrets operations](../../operations/sealed-secrets.md).

## Bootstrap and network recovery lessons

Pis were reimaged with memory cgroups enabled, zram swap disabled, and Longhorn
host packages/iSCSI installed. Bootstrap used the first server at `.11` before
kube-vip made `.10` available. Infrastructure pins were kube-vip `0.11.1`,
MetalLB `0.16.1`, Longhorn `1.13.0` and ArgoCD `10.10.3`. The NAS Longhorn backup
target was verified at `nfs://192.168.0.40:/longhorn-backups`.

The old VM still ran the former Tailscale operator/proxies and retained original
names. It was shut down with approval before the old registrations were
identity-checked and removed. New proxies recovered the original Immich and
Vaultwarden names; certificate reissuance and HTTPS checks succeeded. Resolve
stale tailnet registrations before creating replacements; deletion is a separate
approved operation.

VM 210 was recreated from a checksum-verified Debian cloud image and joined at
`.21` using cloud-init, without offline mutation. The guest filesystem grew to
128 GiB. The worker join kept the server token in memory with no-log handling.
The QEMU guest agent and persistent Longhorn modules were installed.

Later `.21` answered with a different MAC. The user selected `.22`, changed
cloud-init networking and restarted the VM. Agent node-ip and inventory were
updated while preserving node identity and disks; Node status converged without
Node deletion. The replacement SSH fingerprint was verified through Proxmox.
A clear ping/ARP probe is not a DHCP reservation.

Image pulls still failed DNS after migration. An approved persistent
systemd-resolved override to `1.1.1.1` restored containerd pulls; host variables
and preparation now record it. LAN DNS success alone did not prove runtime image
pulls worked. See the [VM troubleshooting record](../../solutions/integration-issues/proxmox-debian-cloud-image-k3s-worker-provisioning.md).

## Scheduled recovery protection

Daily jobs use Australia/Melbourne time: Immich database dumps at 03:00,
Vaultwarden complete archives at 03:30 and `storage/k3s` snapshots at 03:45.
Each retains seven successful backups or exact managed snapshots. Verified
rebuild copies and unrelated snapshots are excluded from retention.

Manual runs of the actual CronJob templates passed; independent NAS hashes
matched the job hashes:

| Published backup | Bytes | SHA256 |
| --- | --- | --- |
| `immich-20261014T231232944379452Z.dump` | 27,165,870 | `55c99f641cf1636e3b767ff6ada55c4e05025309eabf295093d1137fe45b5e4a` |
| `vaultwarden-20261014T231233286895Z.tar.gz` | 883,969 | `f3bda2915917e492a0ff41be3e576cfab511146c6d61844e49e1ee19f3aad7f4` |

The first NAS snapshot was `storage/k3s@homelab-daily-20261014T232502Z`.
Snapshot creation precedes scoped pruning. Backups and snapshots share the NAS
pool and do not protect against its loss. See the [NAS runbook](../../../nas/README.md).

Local verification during the rebuild included chart rendering, YAML/Ansible and
shell checks, backup/retention failure fixtures and a VM checksum-rejection
fixture. Authorized server dry runs accepted application backup manifests.
Those checks are historical evidence and were not rerun during documentation cleanup.
