---
title: Provisioning Proxmox Debian Cloud-Image VMs as K3s Workers
date: 2026-08-20
category: integration-issues
module: homelab GitOps infrastructure
problem_type: integration_issue
component: infrastructure
symptoms:
  - "Debian cloud-image VM booted on Proxmox but did not become reachable through the expected SSH identity and static network path."
  - "Cloud-init VM provisioning alone was insufficient, requiring offline guest disk mutation to inject SSH, sudo, networkd, hostname, and package state."
  - "The guest root filesystem did not automatically consume the resized Proxmox disk until growpart and filesystem resize were run in the guest."
  - "Cluster preflight and post-deploy verification had Raspberry Pi assumptions and old node-count expectations after adding the compute-only Mac Pro VM."
root_cause: incomplete_setup
resolution_type: workflow_improvement
severity: medium
tags: [proxmox, debian-cloud-image, k3s, ansible, ssh, vm-provisioning, macpro]
---

# Provisioning Proxmox Debian Cloud-Image VMs as K3s Workers

## October 2026 update

The sections below record the original Debian 12 rollout. The rebuilt VM is
`k3s-05`, VMID `210`, at `192.168.0.21`, running Debian 13.7 with 4 vCPUs,
16 GiB RAM, a 128 GiB disk and Longhorn replica storage. It uses
`~/.ssh/pi_ed25519` through `~/.ssh/homelab_config`. All five nodes joined
successfully. See [current setup](../../../k3s-ansible/README.md) and the
[rebuild record](../../superpowers/plans/2026-10-14-cluster-rebuild.md).

This rebuild completed through cloud-init without offline mutation. The guest
root filesystem grew automatically. `.15` resolved to a different MAC, so the
user selected `.21` after checking router allocation. A TCP refusal differs from
a host-key mismatch: preserve SSH error output rather than treating both as an
unreachable guest. After reusing an address, verify the replacement host key
through Proxmox before replacing the old trusted entry.

The cloud image had no console password or running guest agent initially. To
read the public host key through the trusted Proxmox host, use:

```bash
ssh -t -F ~/.ssh/homelab_config pve-macpro \
  'sudo virt-cat -a /dev/pve/vm-210-disk-0 /etc/ssh/ssh_host_ed25519_key.pub | ssh-keygen -lf -'
```

`virt-cat` inspects the guest automatically; it does not accept `-i`. Compare
the fingerprint with the SSH-presented key before trusting it. The preparation
playbook now installs the guest agent and Longhorn packages/modules; the worker
join playbook reads the existing token in memory with logging disabled.

## Original rollout record


## Problem

Provisioning the Mac Pro as a Debian 12 Proxmox cloud-image VM for a
compute-only k3s worker was not a single create-and-join operation. The target
VM is encoded as VMID `210`, hostname
`macpro-vm-16gb-samsung-980-120gb`, IP `192.168.0.21`, 4 vCPU,
16384 MiB RAM, and a 120G disk on `local-lvm` in
[scripts/provision-macpro-k3s-vm.sh](../../../scripts/provision-macpro-k3s-vm.sh).

The intended cluster role is agent-only. The inventory keeps
`192.168.0.21` under `agent`, while the Raspberry Pi control-plane nodes stay
under `server` in
[k3s-ansible/inventory.yml](../../../k3s-ansible/inventory.yml).

## Symptoms

- The VM was created, but the guest did not converge to the intended first-boot
  state; during this rollout, the Proxmox console showed a generic `localhost`
  login (session history).
- SSH did not become usable until the homelab key identity was forced. The
  scripts and host vars use `~/.ssh/codex_homelab_ed25519` and
  `IdentitiesOnly=yes` rather than relying on whatever keys an SSH agent offers.
- During this rollout, Proxmox expanded the virtual disk to 120G, but the guest
  root partition and filesystem stayed small until an in-guest resize ran
  (session history).
- During this rollout, a resize attempt that depended on an unavailable `lsblk`
  column failed with `lsblk: unknown column: PARTN`; the repair path now derives
  the partition number from the root block device name (session history).
- During this rollout, the limited k3s-ansible join run also depended on
  controller-side Ansible dependencies, a valid k3s token extra-vars file, and
  a usable remote temp directory before the node could join (session history).

## What Didn't Work

Relying on Proxmox cloud-init alone was insufficient for this cloud image in
this environment. The provisioner sets the NoCloud drive, cloud-init user, SSH
keys, static IP, nameserver, and boot settings, but the guest still needed
offline mutation when those settings did not fully materialize.

Letting SSH choose identities automatically was fragile. Direct SSH and Ansible
both need the same explicit key path for this VM; otherwise authentication can
fall back to password prompts or fail with `Permission denied`.

Assuming Proxmox disk resize means the guest filesystem is resized was also
wrong. `qm resize` changes the virtual disk size, but the guest-side root
partition and filesystem still need `growpart` plus `resize2fs` or
`xfs_growfs`.

Session history also showed earlier false starts around this work: initial
design placeholders used a different VMID, hostname, and IP before the final
identity settled on VMID `210` and `192.168.0.21` (session history). Treat the
current scripts and inventory as the source of truth for the final identity.

## Solution

Keep a normal Proxmox creation path, but pair it with an explicit offline repair
path for failed guest bootstrap. The repair script confirms the VMID before
mutation, resolves the Proxmox disk path from `scsi0`, shuts down the VM if it
is running, and uses `virt-customize` against the guest disk in
[scripts/repair-macpro-k3s-vm-offline.sh](../../../scripts/repair-macpro-k3s-vm-offline.sh).

The offline repair injects the intended hostname, static systemd-networkd
config keyed to the VM MAC address, `/etc/hosts`, SSH `authorized_keys`,
sudoers, and service state. It also disables cloud-init so the direct repair
remains authoritative on the next boot.

When SSH support is absent from the guest image, install the missing packages
offline:

```bash
virt-customize --network -a "$disk_path" \
  --run-command "apt-get update" \
  --run-command "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server sudo qemu-guest-agent"
```

Force the SSH identity everywhere this node is accessed:

```yaml
ansible_user: benkim0414
ansible_ssh_private_key_file: ~/.ssh/codex_homelab_ed25519
ansible_ssh_common_args: "-o IdentitiesOnly=yes"
```

Those host vars are scoped to `192.168.0.21` in
[k3s-ansible/host_vars/192.168.0.21.yml](../../../k3s-ansible/host_vars/192.168.0.21.yml),
preserving the default Raspberry Pi SSH user in inventory.

Resize the guest root filesystem after SSH comes up, and derive the partition
number from the actual root block device name:

```bash
root_source=$(findmnt -n -o SOURCE /)
disk_name=$(lsblk -no PKNAME "$root_source" | head -n1)
part_name=$(lsblk -no NAME "$root_source" | head -n1)
part_num="${part_name##*[!0-9]}"
sudo growpart "/dev/$disk_name" "$part_num" || true
```

The provision and repair scripts both follow that resize pattern and then grow
the mounted filesystem according to its type.

Keep the node compute-only in k3s. Inventory places the Mac Pro VM under the
`agent` group, and the node-specific k3s args add workload labels without
adding a Longhorn default-disk label.

Update verification to encode the intended end state. The verifier expects
5 nodes, 3 control planes, 5 MetalLB speakers, the Mac Pro node name, the
Mac Pro labels, and absence of any Longhorn node object for the Mac Pro VM in
[k3s-ansible/scripts/verify-cluster.sh](../../../k3s-ansible/scripts/verify-cluster.sh).
It also uses `mktemp` for the VIP health response body, treats any unhealthy
etcd endpoint as failure, and keeps display-only `kubectl` calls from silently
terminating the script under `set -e`.

## Why This Works

The offline repair bypasses the unreliable first-boot cloud-init path by editing
the guest root disk directly before boot. Hostname, network, SSH, sudo, and
required services are present before the VM needs to be contacted over the
network.

The explicit SSH identity fixes both direct shell access and Ansible access.
Direct scripts pass the private key derived from `SSH_KEY_PATH`, and Ansible
receives the same identity through host vars. Access no longer depends on SSH
agent ordering or unrelated keys.

The guest resize step closes the gap between Proxmox's virtual disk size and
Linux's mounted root filesystem. Deriving the partition number from
`lsblk -no NAME` avoids the unavailable `PARTN` column and works with root
devices whose partition suffix ends in digits.

The verifier prevents accidental promotion of the VM into the wrong role. It
checks that the Mac Pro is Ready, is not labeled control-plane, carries the
expected workload labels, is absent from Longhorn storage nodes, and can serve
traffic through the Traefik smoke test when live cluster access is available.

## Prevention

For future Proxmox cloud-image workers, treat provisioning as three gates:
VM creation, guest accessibility, and cluster join.

First, confirm cloud-init actually applied hostname, network, SSH, sudo, and
qemu guest agent. If it did not, use offline repair rather than iterating on
Ansible against an unreachable guest.

Second, force the intended SSH identity in both ad hoc SSH and Ansible host
vars. This is especially important on hosts where several keys are loaded.

Third, run preflight and post-deploy verification before considering the node
added. Preflight knows this Mac Pro node uses user `benkim0414`, interface
`eth0`, and skips Raspberry Pi cgroup checks; post-deploy verification encodes
the compute-only success criteria.

Keep smoke tests explicit about mutation. The verifier currently applies and
deletes the whoami workload as part of its Traefik check, so live runs need
cluster write permission. In restricted agent environments, use syntax checks
and read-only probes locally, then run the full verifier from a shell that can
reach and mutate the cluster.

## Related Issues

- [Codex Session Hook Health Checks](../developer-experience/codex-session-hook-health-checks.md)
  covers the adjacent principle of bounded, honest cluster health checks.
