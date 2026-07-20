# Mac Pro K3s Worker VM Design

Date: 2026-07-20
Status: approved design

## Goal

Add a Debian VM on the 2013 Mac Pro Proxmox host and join it to the existing
homelab K3s cluster as a compute-only worker. The VM should provide amd64
capacity for selected heavier workloads while preserving the existing
Raspberry Pi control-plane quorum and avoiding storage topology changes in the
first rollout.

## Current Context

The K3s cluster is managed through `k3s-ansible/`. The current inventory has
three Raspberry Pi control-plane/etcd nodes and one Raspberry Pi worker:

- `192.168.0.11`: `rpi5-8gb-crucial-p3-plus-500gb`, control-plane/etcd
- `192.168.0.12`: `rpi5-8gb-crucial-bx500-500gb`, control-plane/etcd
- `192.168.0.13`: `rpi5-8gb-rpi-512gb`, control-plane/etcd
- `192.168.0.14`: `rpi5-8gb-rpi-256gb`, worker

Live metrics during design showed CPU headroom across all Pi nodes, but memory
pressure is the limiting factor. The Pi control-plane nodes were around
57-68% memory usage, with the total cluster pod footprint around 8 GiB. The
largest current pod consumers were Prometheus, Immich, Home Assistant, ArgoCD,
and Honcho components.

The Mac Pro has been reinstalled with Proxmox VE 9.2 on the Samsung 980 SSD.
It has 32 GiB RAM, LVM-thin local VM storage, and currently runs:

- LXC `100` `hermes`: restored, stopped, `onboot: 0`
- LXC `101` `openclaw`: running
- LXC `120` `arr-stack`: running, with `/data` backed by the NAS NFS mount

OpenClaw is not currently represented in this GitOps repo, so migrating it to
K3s requires packaging it declaratively before stopping LXC `101`.

## Decisions

### VM Role

The Mac Pro VM will join K3s as an agent-only worker. It must not join as an
etcd/control-plane node.

Rationale: the Pi control-plane set already has a three-node etcd quorum. The
Mac Pro should add workload capacity without making cluster quorum depend on
the Proxmox host.

### Storage Role

The first rollout is compute-only. The VM should not be labeled for Longhorn
default disk creation and should not participate in Longhorn replica placement
initially.

Rationale: this separates VM/k3s scheduling validation from storage topology
changes. Longhorn can be revisited after the worker is stable.

### Scheduling Policy

Workload placement onto the Mac Pro VM will be explicit opt-in through labels
and app-level `nodeSelector` or affinity. The VM will not be broadly tainted in
the first rollout, and existing workloads should not be moved automatically.

Recommended labels:

```text
homelab/host=macpro
homelab/node-class=vm
homelab/workload-tier=heavy
```

The standard `kubernetes.io/arch=amd64` label is expected to be assigned by
Kubernetes and should not be manually forced unless verification shows it is
missing.

### VM Sizing

Initial VM sizing:

```text
vCPU: 4
RAM: 16 GiB
Disk: 120 GiB
OS: Debian 12 Bookworm
Network: Proxmox vmbr0 on 192.168.0.0/24
Role: K3s agent
```

Rationale: this provides useful amd64 capacity while leaving room for the
Proxmox host and the currently running `arr-stack` LXC. If `arr-stack` later
migrates to K3s and LXC `120` is stopped, the VM can be resized upward.

### Provisioning Boundary

The Proxmox VM itself will be created manually for now. K3s cluster membership,
node labels, verification docs, and scheduling policy will be managed in this
repo.

Rationale: this avoids introducing Terraform/OpenTofu state and Proxmox
provider credentials during the first VM rollout, while keeping cluster state
repeatable through `k3s-ansible`.

## Target Architecture

```text
Mac Pro / Proxmox pve-macpro / 192.168.0.20
`-- VM: k3s worker, Debian 12, 4 vCPU, 16 GiB RAM, 120 GiB disk
    |-- Joins existing K3s API through current k3s-ansible flow
    |-- Runs selected opt-in amd64 workloads
    |-- Does not run etcd/control-plane services
    `-- Does not contribute Longhorn storage initially
```

The existing Raspberry Pi control-plane topology remains unchanged.

## Repo Scope

The implementation should update:

- `k3s-ansible/inventory.yml`
- `k3s-ansible/host_vars/<macpro-vm-ip>.yml`
- `k3s-ansible/README.md`
- `k3s-ansible/scripts/preflight-check.sh`, only if current checks assume Pi
  hardware, the `pi` SSH user, or `eth0`
- `k3s-ansible/scripts/verify-cluster.sh`, only if current verification needs
  the new node or label checks

The implementation should not:

- Change the Pi control-plane/etcd roles
- Add the Mac Pro VM to Longhorn storage scheduling
- Migrate `arr-stack`
- Start using Terraform/OpenTofu
- Remove the restored Proxmox LXC backups

## Rollout Flow

1. Create the Debian 12 VM manually in Proxmox with the agreed sizing.
2. Assign a stable LAN IP on `192.168.0.0/24`.
3. Create or configure the VM admin SSH user for Ansible access.
4. Add the VM to `k3s-ansible` as an agent node.
5. Add host vars that apply the Mac Pro VM scheduling labels and avoid the
   Longhorn default-disk label.
6. Run preflight checks.
7. Run the k3s-ansible playbook to join the VM.
8. Verify the node is `Ready`, labeled correctly, and absent from Longhorn
   storage nodes unless Longhorn creates a non-schedulable node object.
9. Package OpenClaw declaratively in GitOps.
10. Add node selection so OpenClaw lands on the Mac Pro VM.
11. Verify OpenClaw in K3s.
12. Stop Proxmox LXC `101` after K3s OpenClaw is healthy.

## Validation

Required validation after joining the VM:

- `kubectl get nodes -o wide` shows the Mac Pro VM `Ready`.
- `kubectl describe node <macpro-vm-node>` shows the expected labels.
- `kubectl top nodes` shows additional amd64 capacity.
- Longhorn does not schedule replicas to the Mac Pro VM in the first rollout.
- ArgoCD applications remain `Synced`.
- Existing services remain reachable through current Tailscale/Ingress paths.

Required validation after OpenClaw migration:

- OpenClaw manifests are committed to GitOps.
- OpenClaw pod lands on the Mac Pro VM through explicit node selection.
- OpenClaw service health is verified.
- LXC `101` can be stopped without service loss.

## Risks And Mitigations

- **Risk: wrong VM node role.** Mitigation: add it only under the `agent`
  inventory group and verify it does not receive control-plane labels.
- **Risk: accidental Longhorn scheduling.** Mitigation: omit
  `node.longhorn.io/create-default-disk=true` from Mac Pro VM host vars and
  verify Longhorn node state after join.
- **Risk: workload drift outside GitOps.** Mitigation: do not manually install
  OpenClaw into the cluster; package it in the repo before disabling the LXC.
- **Risk: Pi control-plane memory pressure remains.** Mitigation: use the VM
  first for OpenClaw, then move additional opt-in workloads such as monitoring
  only after the node is stable.
- **Risk: existing Alloy health issue masks rollout signals.** Mitigation:
  track Alloy `Progressing` as a known pre-existing issue and verify the new
  node independently through Kubernetes readiness and workload placement.

## Deferred Work

- Migrate `arr-stack` from Proxmox LXC to K3s.
- Add the Mac Pro VM as a Longhorn storage node.
- Manage Proxmox VM creation through Terraform/OpenTofu.
- Resize the VM above 16 GiB RAM after Proxmox LXC workload reduction.
