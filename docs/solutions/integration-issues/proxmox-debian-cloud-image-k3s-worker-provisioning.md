# Proxmox Debian cloud-image worker recovery

## Current configuration and recorded outcome

VM 210 is `k3s-05` at `192.168.0.22`: Debian 13 Trixie, 4 vCPUs, 16 GiB RAM,
128 GiB disk, `vmbr0`, and Longhorn replica storage. Use
[current setup](../../../k3s-ansible/README.md),
[host variables](../../../k3s-ansible/host_vars/192.168.0.22.yml) and the
[rebuild record](../../superpowers/plans/2026-10-14-cluster-rebuild.md).
The login is `benkim0414` using `~/.ssh/pi_ed25519` through
`~/.ssh/homelab_config`, with strict host-key verification.

The original Debian 12 rollout needed offline repair and manual guest growth.
The October rebuild completed through cloud-init without offline mutation; the
filesystem grew to the full disk size. The former compute-only role, `.21`
address and old SSH identity are superseded.

## Diagnose in three stages

1. **VM creation:** inspect VM identity, disk, bridge, MAC and cloud-init settings
   through Proxmox. The [provisioner](../../../scripts/provision-macpro-k3s-vm.sh)
   verifies the downloaded Debian image checksum before approved replacement.
   Recreating an existing VM requires its explicit destruction confirmation;
   never recreate a working VM merely to change its address.
2. **Guest accessibility:** verify cloud-init applied hostname, network, SSH user
   and key. Preserve SSH error output: connection refusal, routing failure,
   authentication failure and host-key mismatch need different investigations.
   Check disk and root filesystem sizes independently; resizing a virtual disk
   does not itself establish guest filesystem growth.
3. **Cluster join:** run the preparation and worker-only join workflows in the
   K3s runbook. Preserve no-log, in-memory server-token handling. Verify Ready
   state, agent role, intended labels, Longhorn disk schedulability and volumes.

## SSH trust and offline repair

Verify a replacement guest's public SSH fingerprint independently through the
trusted Proxmox console before changing trust. The recorded fallback when no
console password/guest agent was available used `virt-cat` to inspect
`/etc/ssh/ssh_host_ed25519_key.pub` and `ssh-keygen -lf -`; `virt-cat` does not
accept the `-i` inspection option. Resolve the actual guest disk first instead
of assuming a historical disk path. Do not inspect private host keys.

The [offline repair script](../../../scripts/repair-macpro-k3s-vm-offline.sh)
is a separately approved fallback for failed bootstrap. It stops the VM,
resolves its `scsi0` disk and MAC, injects hostname/network/SSH/sudo state,
disables cloud-init, starts the VM and attempts guest filesystem growth.
It may install packages on Proxmox and in the guest. Review its effects before
running it; disabling cloud-init changes which configuration remains authoritative.

The scripts derive partition numbers from root device names rather than the
unavailable `lsblk PARTN` column encountered in the original rollout. Inspect
`findmnt` and `lsblk` output before interpreting resize success, especially for
layouts other than the configured simple root partition.

## Address and DNS lessons

The October VM first joined at `.21`; that address later answered with another
MAC. Migration to `.22` preserved node name and disks, updated the agent's
explicit node-ip, and converged without deleting the Kubernetes Node. Check
router/DHCP allocation before selecting an address; absent ping/ARP responses
do not reserve it. Reverify host trust if cloud-init regenerates SSH keys.

Image pulls still failed despite successful DNS probes. An approved
systemd-resolved override to `1.1.1.1` restored direct containerd pulls.
`host_dns_server` now manages that override for the VM; provisioning and repair
use the same resolver by default. Verify the runtime's actual pull path rather
than relying only on a workstation or guest DNS query.

## Verification boundaries

The preflight script can modify Pi boot parameters. The full cluster verifier
creates and deletes a whoami workload. Neither is a read-only local test.
Use syntax checks for local script review and obtain approval for operational
runs. Check all five nodes, three control planes, MetalLB speakers and a Ready,
schedulable Longhorn disk on the VM; do not restore old checks requiring the VM
to be absent from Longhorn.
