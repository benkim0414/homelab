# K3s cluster rebuild and data recovery

Rebuild the four Raspberry Pis and replace the Mac Pro worker VM, preserving
Immich and Vaultwarden data. Downtime was unrestricted and both applications
were stopped during backup and recovery. The NAS at `192.168.0.40` is excluded
from all disk erasure and VM replacement operations.

## Current status — 15 October 2026

- Four reimaged Pis and replacement VM 210 (`k3s-05`, `.21`) are Ready on
  `v1.36.5+k3s1`. Longhorn storage is enabled on all five nodes.
- Immich and Vaultwarden were restored, pass HTTPS health checks, and the user
  confirmed both applications work at their original Tailscale URLs.
- Daily Immich database backups (03:00), Vaultwarden archives (03:30), and NAS
  ZFS snapshots (03:45) are enabled in Australia/Melbourne time, each retaining
  seven successful backups or managed snapshots. Initial runs passed.
- The replacement VM's host key was verified through Proxmox, installed in
  persistent known-hosts with approval, and normal strict SSH login verified.
- GitOps activation remains pending review/publication of the matching config.
  S3 and Renovate need replacement credentials; Honcho and Nextcloud were not
  restored. Detailed entries below record the progression, including earlier
  pending states that have since been completed.

## Agreed node configuration

| Nodes | Role | Operating system | Storage |
| --- | --- | --- | --- |
| `192.168.0.11`, `.12`, `.13` | K3s control planes with embedded etcd | Latest Raspberry Pi OS 64-bit Lite | Reimage boot and attached data disks; retain Longhorn |
| `192.168.0.14` | K3s worker | Latest Raspberry Pi OS 64-bit Lite | Reimage boot and attached data disks; retain Longhorn |
| `192.168.0.21` | New Mac Pro VM worker | Debian 13.7 Trixie, minimal installation | 128 GiB virtual disk; enable Longhorn replicas |

The new VM has 4 vCPUs and 16 GiB RAM. It replaces VM 210 at
`192.168.0.21`; join it after rebuilding the Pis. Its existing Proxmox storage
is `local-lvm`, with bridge `vmbr0` and guest login `benkim0414`.
Debian 13.7 is the current stable release according to
[Debian release information](https://www.debian.org/releases/stable/).

The rebuilt Pis have 256 GB NVMe SSDs on `.11` through `.13`, and a 512 GB NVMe
SSD on `.14`; each boots from the same SSD used for local data.

Hostnames and K3s node names are `k3s-01` through `k3s-05`, mapping to
`.11`, `.12`, `.13`, `.14` and `.21` respectively. Set them before joining the fresh cluster.

## Backups and verification

Backups are stored at `/storage/rebuild-backups/2026-10-14` on the NAS.
The directory is restricted to its owner. Vaultwarden's archive contains
credentials and signing material and must remain private; it is not encrypted.
The fresh multi-key export was accidentally discarded. Recovery used the one
available February master key, which decrypted the required Immich database and
Vaultwarden secrets. A fresh export of the restored controller's available key
is gitignored at `sealed-secrets/sealed-secrets-master-keys.yaml`; external vault
backup should be maintained. Secrets encrypted with the lost keys require new
credentials.

| Data | Verification completed |
| --- | --- |
| Immich PostgreSQL custom dump | Restored into a separate database; 22,784 assets, 2 users, 26 albums and 225 public indexes match |
| Immich source media | All 22,784 original paths exist on the source NAS dataset |
| Vaultwarden full data archive | SQLite integrity passed; 1 user, 249 entries, 1 attachment present; isolated restored application health passed |

The independent 154 GiB Immich media copy completed successfully. A full rsync
checksum comparison found zero differing entries, and all 22,784 database
original paths exist in the copy. The verified directory is `immich-media`.
The user subsequently confirmed that both restored applications work; detailed
manual acceptance steps were not individually recorded.
The NAS verification report is `verification.json` in the backup directory.

## Rebuild sequence

1. Finish and verify the media copy. Record hashes for database archives and
   preserve the verified backups and Sealed Secrets keys outside rebuilt nodes.
2. Identify each Pi's exact boot and data devices and the existing Proxmox VM ID.
   Present the exact destructive operations for explicit approval before erasure.
   Keep the failed `.12` node powered off until reimaging; its etcd database is corrupt.
3. Reimage the Pis, install SSH access and updates, verify cgroups and disk mounts,
   and provision three K3s servers plus the `.14` worker. Select and pin compatible
   K3s, Longhorn and infrastructure versions before installation.
4. Bootstrap networking and ArgoCD with application deployment controlled.
   Restore the Sealed Secrets keys before allowing encrypted secrets to reconcile.
   Review kube-vip and MetalLB addresses with the user before changing them.
5. Install Longhorn with explicit persistent disk paths and replica placement.
   Correct the obsolete node affinity and reconcile the NAS backup target:
   the live NFSv4 target was `nfs://192.168.0.40:/longhorn-backups`.
6. Restore both databases and Vaultwarden's complete data directory onto fresh
   volumes. Restore Immich media paths and permissions. Start with compatible
   application/database images; review upgrades separately from data recovery.
7. Check photos, albums, videos, login, vault decryption and attachment download.
   Restore scheduled backups and verify a successful new backup before resuming use.
8. Delete and recreate the approved Mac Pro VM, provision it at `.21`, join it as
   a worker, and verify Longhorn disk scheduling, replica health and node failover.

## Repository preparation status

The inventory and VM host variables use `.21` and enable Longhorn.
Host variables explicitly set the approved node names, and provisioning and
verification scripts use the new VM specification. The Debian image checksum
was verified before replacing VM 210. Pi reimaging, infrastructure installation,
VM recreation and worker join are complete. GitOps activation remains pending.

## Installation verified on 14 October 2026

All four Pis are Ready on K3s `v1.36.5+k3s1`, pinned from the official stable
channel. `.11` through `.13` are control planes with etcd; `.14` is a worker.
Each control plane passed its local API readyz check, including etcd readiness.
CoreDNS, metrics-server and Traefik are Running and Ready. Flannel uses `eth0`
and the nodes advertise their wired `.11` through `.14` addresses.

The prerequisite playbook enabled memory cgroups, disabled zram swap and
installed the Longhorn host packages. The iSCSI daemon is active and enabled.
Join configuration and service environment files have root-only permissions.
The standalone kubeconfig is `/tmp/homelab-k3s-rebuild.yaml` with mode 0600;
the previous local kubeconfig was not replaced.

Infrastructure bootstrap completed using kube-vip chart `0.11.1`, MetalLB
`0.16.1`, Longhorn `1.13.0` and ArgoCD chart `10.10.3`. The API VIP `.10`
passed readyz; Traefik received `.200`, and ArgoCD received `.202` and served
HTTP 200. All four Longhorn nodes are Ready and schedulable; the CSI DaemonSet
rolled out on all four nodes. The default Longhorn storage class uses two replicas.
The NAS backup target reports available at `nfs://192.168.0.40:/longhorn-backups`.
Longhorn data resides at `/var/lib/longhorn/` on each Pi's new root SSD.
Two managers restarted during initial startup; all became Ready afterward.

ArgoCD has no Applications yet, so application recovery remains controlled.
Sealed Secrets key restoration and application data restoration remain pending.
A PVC write/read test has not yet been performed. The replacement VM has not been
recreated. The fresh nine-key export path and permission to import it have been
requested from the user.

## Sealed Secrets recovery check

The user reported accidentally discarding the fresh nine-key export in LazyGit.
The February backup survives at
`/home/benkim0414/workspace/homelab/sealed-secrets-master-keys.yaml` (mode 0600),
and contains one key record. With user approval, local `kubeseal --recovery-unseal`
tests passed for `immich-db-credentials`, `vaultwarden-secret` and
`home-assistant-prometheus-token`. No decrypted values were displayed or saved.
Tests failed for the Immich and Nextcloud S3 credentials, both Honcho secrets,
Nextcloud credentials and the Renovate token. Those require another original
key copy or replacement credentials before their Applications can reconcile.
The surviving key has not yet been imported into the rebuilt cluster.

The user subsequently approved importing the February key. It is now restored
in `kube-system`, and Sealed Secrets chart `2.20.0` is installed and Ready.
Both Immich database credentials and the Vaultwarden secret passed `kubeseal
--validate` against the running controller. A fresh, gitignored master-key export
is saved at `sealed-secrets/sealed-secrets-master-keys.yaml` with mode 0600;
it currently contains one key record and must be copied to the user's vault.
It does not recover the missing historical keys. The user plans to remove Honcho
and Nextcloud and reinstall Renovate. None are deployed on the fresh cluster;
Renovate and S3 backups still need replacement or recovered credentials.

## Application restoration verified

The NAS archive hashes were rechecked before restoration and matched the
pre-erasure records. Immich PostgreSQL was restored transactionally into a fresh
20 GiB Longhorn volume with the original PostgreSQL image. Counts match: 22,784
assets, 2 users and 26 albums. All 22,784 original paths resolve through the
configured NAS export. Database paths begin with `/data/`, matching the rendered
Immich chart mount; the temporary checker used a different mount and translated
that prefix for verification.

Immich chart `0.12.0` runs server `v2.7.5`, avoiding the repository's previously
configured v3 upgrade during recovery. Its ping and version endpoints pass on
`http://192.168.0.201:2283`. Vaultwarden's complete archive was extracted to a
fresh 2 GiB volume before starting image `1.37.1` via chart `0.46.3`. SQLite
integrity is `ok`; 1 user, 249 ciphers, 1 attachment and the RSA key are present.
Its web and alive endpoints return HTTP 200 at `http://192.168.0.205`.
Both Longhorn volumes are healthy, each with two running replicas on separate
nodes. The user approved deleting the temporary restore/check pods; both were
removed while retaining volumes and backups.

A fresh Immich custom-format dump was written to the existing NAS backup PVC
as `immich-post-restore-20261014.dump` and passed `pg_restore --list`. The one-off
Job is `immich-post-restore-backup-20261014`; scheduled backups and offsite S3
backups have not yet been enabled. Tailscale OAuth credentials are unavailable;
the user was given instructions to create a new client. Original HTTPS URLs,
user login/content checks, VM replacement and GitOps activation remain pending.

## Tailscale operator restored on 15 October 2026

With explicit approval, the operator chart `1.104.1` was installed using the
owner-only OAuth file at `~/homelab-secrets/tailscale-oauth.yaml`. Credential
contents were not displayed. The operator and both application proxies are Ready.
Immich ping returns HTTP 200 via `https://immich-1.tailbd291c.ts.net`, and
Vaultwarden alive returns HTTP 200 via `https://vaultwarden-1.tailbd291c.ts.net`.

Original names are still held by devices from the old cluster. Read-only SSH
confirmed VM 210 at `.21` continues running the old operator, application proxies,
ArgoCD and MetalLB components. It has not been shut down or recreated. Approval
was requested to shut it down (preserving disks), remove the three old application
and operator device registrations, and recover the original names for the new
devices. Until that is approved and verified, use the new `-1` URLs for health
checks; Vaultwarden's configured domain still points at its original URL.


## Original Tailscale names recovered

The user approved shutting down old VM 210 and recovering the three names.
The shutdown command succeeded over SSH; the Proxmox host subsequently reported
no `/run/qemu-server/210.pid` file. VM disks remain intact. The old registrations
for Immich (`100.112.17.2`), Vaultwarden (`100.90.218.31`) and the operator
(`100.78.7.58`) were identity-checked through the API and deleted. The new devices
were renamed to the originals: Immich `100.121.223.34`, Vaultwarden
`100.73.176.25` and operator `100.80.8.35`. MagicDNS resolves the original
application URLs to the new addresses. HTTPS certificate reissuance completed. Immich ping, Vaultwarden alive and
Vaultwarden web endpoints all return HTTP 200 at their original HTTPS URLs.
User login, photo/video browsing, vault decryption and attachment download remain
acceptance checks.

## Scheduled backups enabled and tested on 15 October 2026

The user confirmed both restored applications work. They approved daily Immich
database backups at 03:00 and Vaultwarden archives at 03:30 Australia/Melbourne,
retaining seven successful backups per application in dedicated directories.
The verified rebuild archives and old Immich dump directory remain untouched.

Immich uses `/storage/k3s/immich/backups/scheduled` on the NAS. Dumps are published
after a nonzero-size and `pg_restore --list` check. Vaultwarden uses SQLite's online
backup API, includes its data directory and verifies database integrity, signing
key and attachment members before publishing a tar archive to
`/storage/k3s/vaultwarden/backups`. Backups are not encrypted; files are root-owned
0600, with Vaultwarden's backup directory root-owned 0700. Failed runs are retained
in Kubernetes job history. Both CronJobs are active with the specified timezone.

Manual runs of the actual CronJob templates completed successfully. Independent
NAS hashing matched the job hashes:

- Immich: `immich-20261014T231232944379452Z.dump`, 27,165,870 bytes,
  SHA256 `55c99f641cf1636e3b767ff6ada55c4e05025309eabf295093d1137fe45b5e4a`.
- Vaultwarden: `vaultwarden-20261014T231233286895Z.tar.gz`, 883,969 bytes,
  SHA256 `f3bda2915917e492a0ff41be3e576cfab511146c6d61844e49e1ee19f3aad7f4`;
  archived database integrity passed with 1 user, 249 ciphers and 1 attachment.

Immich media remains on the NAS and its verified rebuild copy is preserved;
recurring media copies or snapshots require a separate policy decision. S3 remains
disabled pending credentials. The VM replacement script now uses the configured
homelab SSH aliases and Pi login public key, verifies Debian's SHA512 checksum
before deletion, and requires a known host key for the new guest. A simulated
checksum mismatch test confirmed it exits before VM shutdown/deletion. Proxmox
sudo still requires an interactive password, so VM recreation must run from the
user's terminal unless a separately approved access method is provided.

## NAS snapshot preparation

The user approved VM 210 replacement and preparation of daily NAS snapshots with
seven retained. `nas/` now contains the snapshot script, systemd service/timer and
installation notes. The proposed schedule is 03:45 Australia/Melbourne. It targets
only `storage/k3s`, checks the expected mountpoint, creates a snapshot before
pruning, and deletes only exact managed-prefix snapshots beyond the latest seven.
Mock verification confirmed retention excludes manual and child-dataset snapshots
and that failed creation never prunes. systemd accepted the timezone schedule;
`git diff --check` passed. NAS installation has not run. The user was given the
interactive VM replacement command; completion has not yet been confirmed.

## NAS snapshots enabled on 15 October 2026

With explicit user approval, installed the root-owned script and systemd units on
the NAS, started the service and enabled its persistent daily timer. The first run
returned `Result=success`, exit status 0, creating
`storage/k3s@homelab-daily-20261014T232502Z`. No existing snapshots were present
before installation, so nothing was pruned. The timer is enabled and active; its
next run is 16 October 2026 at 03:45 AEDT. Dataset free space before installation
was 146 GiB. Installed permissions are root:root 0755 for the script and 0644 for
both units. Unit verification succeeded with an unrelated pre-existing OMV
`KillMode=none` deprecation warning. VM recreation remains unconfirmed.

## VM address changed to .21

The user requested reusing `192.168.0.21` after `.15` resolved to a MAC
other than VM 210. Updated provisioning defaults, inventory, host variables,
preflight targets and README instructions. The VM already exists; change its
cloud-init network configuration and restart it rather than recreating its disk.
The live network change remains pending interactive Proxmox sudo.

## VM worker joined on 15 October 2026

The user recreated VM 210 and applied `.21` through Proxmox cloud-init. Its SSH
ED25519 fingerprint was independently read by the user from the VM disk through
Proxmox and matched `SHA256:jgg+1NRoD+uIVRCsZqqeAItjBlygmB9JQ+9vPY1xMMA`.
Access uses the verified key in `/tmp/homelab-rebuild-known-hosts`; the persistent
user known-hosts entry has not been changed.

Verified hostname `k3s-05`, Debian 13.7, eth0 at `192.168.0.21`, 16 GiB configured
RAM, full 128 GiB disk with grown root filesystem, cloud-init complete, memory
cgroup support and no swap. Installed and started the QEMU guest agent and
Longhorn prerequisites. Persisted `iscsi_tcp` and `dm_crypt` module loading.

Joined the worker using the upstream Ansible roles and the existing server token,
retrieved through a delegated no-log task and kept in memory. The reusable
`k3s-ansible/join-workers.yml` captures this workflow. Ansible completed with no
failures. Config and agent environment files are root-owned mode 0600.

All five Kubernetes nodes are Ready on `v1.36.5+k3s1`. All Longhorn and MetalLB
pods on the new worker became Ready; its default `/var/lib/longhorn/` disk is
Ready and Schedulable. Both restored database volumes remain healthy. Immich
HTTPS ping and Vaultwarden HTTPS alive checks passed after the join. YAML,
Ansible syntax and whitespace checks passed. GitOps activation and updating the
user's persistent SSH known-host entry remain pending.

## Persistent VM SSH trust updated

With user approval, backed up `~/.ssh/known_hosts` to
`~/.ssh/known_hosts.before-vm210-20261015`, removed only the old `.21` entries and
installed the independently verified ED25519 key. SSH with the normal known-hosts
file and strict host checking succeeds; the guest reports `k3s-05` with both K3s
agent and QEMU guest agent active.

## Repository review before committing

Reviewed all changed files and corrected provisioning name-collision handling,
preflight SSH addressing, explicit Ansible SSH configuration, Longhorn disk
schedulability verification and stale comments. Vaultwarden backup validation
now consumes the gzip trailer before publishing an archive. These final review
changes are repository changes; they have not been reconciled into the cluster.

All eight pinned charts rendered from locally cached packages. All changed YAML
parsed, both Ansible playbooks passed syntax checks, and changed shell scripts
passed Bash syntax and ShellCheck checks at warning severity. Kubernetes server
dry runs accepted the application backup manifests. Synthetic fixtures verified
Vaultwarden attachment preservation, archive permissions and retention, failed
backup cleanup without pruning, scoped ZFS retention and failure safety, and VM
checksum rejection before destructive operations. Candidate files contained no
private-key/token patterns; the master-key export and Python bytecode remain
ignored. No merge, push or ArgoCD activation was performed during this review.

## VM address migration to .22 — completed

During Longhorn Tailscale ingress adoption, VM image pulls repeatedly failed DNS
resolution through 192.168.0.1. SSH to .21 then became refused, and both Proxmox
and k3s-01 associated .21 with MAC 38:8c:50:e0:97:56 rather than VM 210's
bc:24:11:5a:9b:d4. The user selected 192.168.0.22. Proxmox probes found no ICMP
reply or resolved ARP entry for .22; this does not replace reserving it in DHCP.

Active inventory, host vars, provisioning/repair scripts and node tables now use
.22. Earlier entries in this record retain the historical addresses. Proxmox
required interactive sudo; the user updated cloud-init ipconfig0 to
192.168.0.22/24 (gateway .1), regenerated cloud-init and power-cycled the VM.
The agent node-ip was then updated while preserving node name k3s-05 and all disks.

Migration verification: SSH host key changed after cloud-init; the user confirmed
SHA256:cDRctZN2vO4ZI0nzhMb6HBSeZBv67QXfJvwcFvPrwNY through Proxmox. Strict SSH
verification uses a temporary known-hosts file; the user's persistent SSH files
were not changed. The agent service's explicit node-ip was changed to .22 with
its previous unit backed up. Initially the network policy controller saw stale
Node status at .21. A guarded status patch was rejected because the status had
already converged to .22; the next service restart succeeded. No Node was deleted.

Both LAN DNS and Cloudflare queries passed at .22, but image pulls still failed
DNS resolution. The approved persistent systemd-resolved Cloudflare override was
then installed and a direct containerd image pull succeeded. Ansible now records
this override. Longhorn is Synced/Healthy; its proxy is Running and advertises
https://longhorn-1.tailbd291c.ts.net initially, which passed HTTPS verification.
The user subsequently removed the stale device and renamed the new one. The
ingress now advertises https://longhorn.tailbd291c.ts.net and DNS resolves it to
100.104.134.122. A workstation HTTPS check after the rename timed out; renamed
HTTPS access is not yet verified. No old device was deleted by the agent. Both
application volumes remain healthy. Flag stale tailnet names before provisioning
future proxies and obtain approval before deleting any old devices.
