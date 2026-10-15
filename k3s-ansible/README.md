# K3s HA Cluster - Ansible Configuration

Inventory and scripts for deploying a high-availability K3s cluster on Raspberry Pi and Proxmox VM nodes using [k3s-ansible](https://github.com/k3s-io/k3s-ansible).

## Architecture

```text
API VIP 192.168.0.10 (kube-vip)
  k3s-01 (.11) -- control plane / etcd
  k3s-02 (.12) -- control plane / etcd
  k3s-03 (.13) -- control plane / etcd
  k3s-04 (.14) -- Raspberry Pi worker
  k3s-05 (.22) -- Mac Pro VM worker, Longhorn storage

MetalLB: 192.168.0.200 - 192.168.0.250
```

### Nodes

| Hostname                       | IP           | Role                 | Storage       |
| ------------------------------ | ------------ | -------------------- | ------------- |
| k3s-01 | 192.168.0.11 | Control plane / etcd | 256 GB NVMe   |
| k3s-02   | 192.168.0.12 | Control plane / etcd | 256 GB NVMe|
| k3s-03             | 192.168.0.13 | Control plane / etcd | 256 GB NVMe   |
| k3s-04             | 192.168.0.14 | Worker / agent       | 512 GB NVMe |
| k3s-05 | 192.168.0.22 | Worker / agent       | Proxmox VM, Longhorn storage |

### Networking

| Component | Address / Range               |
| --------- | ----------------------------- |
| VIP       | 192.168.0.10 (kube-vip, ARP)  |
| MetalLB   | 192.168.0.200 - 192.168.0.250 |
| K3s API   | port 6443                     |

## Files

```
homelab/
|-- k3s-ansible/
|   |-- README.md
|   |-- inventory.yml               # Cluster inventory + all vars
|   |-- host_vars/                  # Node names, addresses and VM overrides
|   |-- prepare-nodes.yml           # Host packages, modules, Pi boot setup
|   |-- join-workers.yml            # Join existing cluster without server changes
|   `-- scripts/
|       |-- preflight-check.sh      # Pre-flight node validation
|       `-- verify-cluster.sh       # Post-deploy verification
|-- kube-vip/
|   `-- values.yaml                 # Helm chart values
|-- metallb/
|   |-- values.yaml                 # Helm chart values
|   |-- ipaddresspool.yaml          # Post-install CR
|   `-- l2advertisement.yaml        # Post-install CR
`-- traefik/
    |-- helmchartconfig.yaml         # K3s HelmChartConfig CRD
    `-- examples/
        |-- example-ingressroute.yaml
        `-- whoami-test.yaml
```

## Prerequisites

- [k3s-ansible](https://github.com/k3s-io/k3s-ansible) cloned to `~/workspace/k3s-ansible`
- Ansible with required galaxy collections
- SSH access to Raspberry Pi nodes as `pi` and the Mac Pro VM as `benkim0414`
  (key-based, passwordless or promptable sudo)

Install galaxy collections:

```bash
ansible-galaxy collection install community.general ansible.posix
```

Add Helm chart repos:

```bash
helm repo add kube-vip https://kube-vip.github.io/helm-charts
helm repo add metallb https://metallb.github.io/metallb
helm repo update
```

## Mac Pro Worker VM

VM 210 is Ready as `k3s-05` at `.22` after migration from the conflicting `.21`
address. It was recreated from Debian's
generic cloud image and joined through this inventory as a K3s agent.

Recommended VM settings:

| Setting | Value |
| ------- | ----- |
| VM hostname | `k3s-05` |
| VM IP | `192.168.0.22` |
| OS | Debian 13 Trixie |
| vCPU | 4 |
| RAM | 16 GiB |
| Disk | 128 GiB |
| Network | Proxmox `vmbr0` |
| K3s role | Agent only |
| Longhorn role | Replica storage; default disk label enabled |

Create the `benkim0414` user on the VM with passwordless or promptable sudo
for Ansible, then install the homelab SSH key used by
`~/.ssh/homelab_config`.

To create the VM from a Debian 13 generic cloud image with cloud-init instead of doing
a manual installer flow, run:

```bash
./scripts/provision-macpro-k3s-vm.sh
```

Run from the checkout containing the reviewed script. Replacing existing VM 210
requires `RECREATE_EXISTING=1` and the interactive `DESTROY-210` confirmation.
The script downloads/verifies Debian's SHA512 checksum before deleting the VM.
Proxmox sudo currently requires the user's password in their own terminal.
The default guest login key is `~/.ssh/pi_ed25519.pub`. Verify the new guest's
ED25519 host fingerprint through the Proxmox console and add it to local known
hosts before SSH verification; the script deliberately requires a trusted key.

## Inventory Configuration

All configuration lives in `inventory.yml`. Key decisions:

- **`api_endpoint`** is set to `192.168.0.11` (the first server's real IP) for bootstrap. kube-vip doesn't exist yet during initial install, so the VIP (192.168.0.10) is unreachable. Switch kubeconfig to the VIP after kube-vip is deployed.
- **`cluster-init`** is NOT in `server_config_yaml`. The k3s-ansible role handles `--cluster-init` (first server) vs `--server` (join, others) automatically via its systemd service template. Putting it in `server_config_yaml` writes it to every server node's `/etc/rancher/k3s/config.yaml`, causing each to initialize its own cluster.
- **`servicelb` is disabled** because MetalLB handles LoadBalancer services instead.
- **`tls-san`** includes the VIP and all server IPs so the API server cert is valid regardless of which endpoint is used.
- **`cluster_context`** is set to `k3s` so the kubeconfig context, cluster, and user are named `k3s` instead of the default `k3s-ansible`.

## Fresh node preparation

Set OS hostnames to `k3s-01` through `k3s-04` and preserve the `.11` through `.14`
addresses when imaging Raspberry Pi OS 64-bit Lite. Enable SSH and passwordless
sudo for `pi`, and verify each new host key before trusting it.

The Pis use `~/.ssh/pi_ed25519`; local aliases are in `~/.ssh/homelab_config`.
K3s is pinned to `v1.36.5+k3s1`, with wired `eth0` for Flannel and explicit node
IPs. The VM also uses `eth0`; it is joined at `.22`.

Apply the reviewed prerequisites and reboot fresh Pis:

```bash
ANSIBLE_LOCAL_TEMP=/tmp/homelab-ansible \
ANSIBLE_SSH_CONTROL_PATH_DIR=/tmp/homelab-ansible-cp \
ansible-playbook -i k3s-ansible/inventory.yml k3s-ansible/prepare-nodes.yml \
  --limit '192.168.0.11,192.168.0.12,192.168.0.13,192.168.0.14' \
  -e prepare_reboot=true
```

The playbook installs iSCSI/NFS tools, enables `iscsid`, loads `iscsi_tcp` and
`dm_crypt` persistently, enables
memory cgroups, and disables Pi swap with an rpi-swap drop-in. It preserves the
original boot command line at `/var/backups/cmdline.txt.before-k3s`; keeping that
backup off the FAT boot partition avoids unsupported timestamp characters.

## Deployment

### 1. Pre-flight checks

Validates SSH connectivity, RAM, disk, and each node's required network
interface. Raspberry Pi nodes also get cgroup boot-parameter checks.

```bash
bash ~/workspace/homelab/k3s-ansible/scripts/preflight-check.sh
```

Raspberry Pi 5 firmware injects `cgroup_disable=memory` into the kernel command line. The `cmdline.txt` must contain `cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory` to override this. If the script adds missing params, **reboot the affected nodes** before proceeding.

### 2. Deploy K3s

Run from the k3s-ansible repo root (required for `ansible.cfg` to resolve `roles_path = ./roles`):

```bash
cd ~/workspace/k3s-ansible
ansible-playbook playbooks/site.yml -i ~/workspace/homelab/k3s-ansible/inventory.yml \
  --limit '192.168.0.11,192.168.0.12,192.168.0.13,192.168.0.14' --forks=1 \
  -e kubeconfig=/tmp/homelab-k3s-rebuild.yaml
```

To join only the Mac Pro worker VM to an existing cluster, use the worker playbook
and limit it to `.22`. It retrieves the existing token from the first server with
logging disabled, without rerunning the server role:

```bash
cd ~/workspace/k3s-ansible
ANSIBLE_ROLES_PATH="$PWD/roles" ansible-playbook \
  ~/workspace/homelab/k3s-ansible/join-workers.yml \
  -i ~/workspace/homelab/k3s-ansible/inventory.yml \
  --limit 192.168.0.22
```

Verify the replacement VM's SSH fingerprint through Proxmox before joining. The
replacement VM key was verified through Proxmox and installed in the user's
persistent known-hosts file with approval on 15 October 2026. Run
`prepare-nodes.yml` for the VM first; its host variables enable the
QEMU guest agent along with the Longhorn prerequisites.

After provisioning, restrict files that contain join credentials to root:

```bash
# Run on each node. The worker uses k3s-agent.service.env.
sudo chmod 0600 /etc/rancher/k3s/config.yaml /etc/systemd/system/k3s.service.env
# On a worker instead:
sudo chmod 0600 /etc/rancher/k3s/config.yaml /etc/systemd/system/k3s-agent.service.env
```

### 3. Configure kubectl

For the rebuild, use the separate kubeconfig fetched by Ansible:

```bash
kubectl --kubeconfig /tmp/homelab-k3s-rebuild.yaml get nodes
```

The following commands replace the default local kubeconfig; use them only when
ready to switch local tools to the rebuilt cluster.

```bash
mkdir -p ~/.kube
scp pi@192.168.0.11:/etc/rancher/k3s/k3s.yaml ~/.kube/config
sed -i 's|https://127.0.0.1:6443|https://192.168.0.11:6443|' ~/.kube/config
kubectl get nodes
```

### 4. Deploy kube-vip

```bash
helm install kube-vip kube-vip/kube-vip \
  --namespace kube-system \
  --values ~/workspace/homelab/kube-vip/values.yaml
kubectl -n kube-system wait --for=condition=ready pod -l app.kubernetes.io/name=kube-vip --timeout=120s
curl -k https://192.168.0.10:6443/healthz
```

### 5. Switch kubeconfig to VIP

```bash
sed -i 's|https://192.168.0.11:6443|https://192.168.0.10:6443|' ~/.kube/config
kubectl get nodes
```

### 6. Deploy MetalLB

```bash
helm install metallb metallb/metallb \
  --namespace metallb-system \
  --create-namespace \
  --values ~/workspace/homelab/metallb/values.yaml
kubectl -n metallb-system wait --for=condition=ready pod -l app.kubernetes.io/name=metallb --timeout=180s
kubectl apply -f ~/workspace/homelab/metallb/ipaddresspool.yaml
kubectl apply -f ~/workspace/homelab/metallb/l2advertisement.yaml
```

### 7. Configure Traefik

```bash
kubectl apply -f ~/workspace/homelab/traefik/helmchartconfig.yaml
kubectl -n kube-system rollout status deployment traefik --timeout=120s
```

### 8. Label nodes

```bash
kubectl label node k3s-01 storage-tier=nvme
kubectl label node k3s-03 storage-tier=nvme
kubectl label node k3s-04 storage-tier=nvme
kubectl label node k3s-02 storage-tier=nvme
```

The Mac Pro VM receives opt-in scheduling labels through `extra_agent_args`:

```bash
kubectl get node k3s-05 \
  -L homelab/host,homelab/node-class,homelab/workload-tier
```

Expected labels:

```text
homelab/host=macpro
homelab/node-class=vm
homelab/workload-tier=heavy
```

The VM host variables enable `node.longhorn.io/create-default-disk=true`.
Set each OS hostname to its `k3s-01` through `k3s-05` name before provisioning;
host variables also explicitly set the matching K3s node name.

The kubelet eviction thresholds in `inventory.yml` (`eviction-hard`, `eviction-soft`,
`kube-reserved`) are written to `/etc/rancher/k3s/config.yaml` on each server node by
the k3s-ansible playbook, but do **not** take effect until k3s is restarted. After
running the playbook, restart k3s one node at a time to preserve etcd quorum:

```bash
ssh pi@192.168.0.11 sudo systemctl restart k3s
ssh pi@192.168.0.12 sudo systemctl restart k3s
ssh pi@192.168.0.13 sudo systemctl restart k3s
```

The same thresholds are applied to worker nodes via `agent_config_yaml`. After
changing those settings on an already joined worker, restart that worker's agent
to pick up the new config:

```bash
ssh pi@192.168.0.14 sudo systemctl restart k3s-agent
ssh -F ~/.ssh/homelab_config \
  -i ~/.ssh/pi_ed25519 \
  -o IdentitiesOnly=yes \
  benkim0414@192.168.0.22 sudo systemctl restart k3s-agent
```

### 9. Verify

The verification script creates and deletes a temporary whoami workload; obtain
approval for those cluster mutations before running it. Use the rebuild
kubeconfig explicitly:

```bash
KUBECONFIG=/tmp/homelab-k3s-rebuild.yaml \
  bash ~/workspace/homelab/k3s-ansible/scripts/verify-cluster.sh
```

## Verification Checklist

| Check                                       | Expected                                  |
| ------------------------------------------- | ----------------------------------------- |
| `kubectl get nodes`                         | 5 nodes Ready (3 control-plane, 2 workers) |
| `curl -k https://192.168.0.10:6443/healthz` | `ok`                                      |
| kube-vip pods                               | 3 running (one per control-plane node)    |
| MetalLB pods                                | 1 controller + 5 speakers                 |
| `kubectl -n kube-system get svc traefik`    | EXTERNAL-IP in 192.168.0.200-250          |
| Node labels                                 | `storage-tier` set on Raspberry Pi nodes; opt-in labels set on Mac Pro VM |
| Longhorn Mac Pro disk                       | Ready, schedulable Longhorn disk on the Mac Pro VM |

## Resetting

To tear down k3s and start over:

```bash
cd ~/workspace/k3s-ansible
ansible-playbook playbooks/reset.yml -i ~/workspace/homelab/k3s-ansible/inventory.yml
```

## Troubleshooting

### `failed to find memory cgroup (v2)`

Raspberry Pi 5 firmware adds `cgroup_disable=memory` to the kernel command line. Ensure `/boot/firmware/cmdline.txt` ends with:

```
cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory
```

Reboot after modifying. Verify with `cat /proc/cmdline | grep cgroup_enable`.

### Secondary servers fail to join

- Ensure `api_endpoint` points to the first server's IP (not the VIP).
- Do NOT put `cluster-init: true` in `server_config_yaml` - the role handles this.
- Check that the first server's k3s is running: `ssh pi@192.168.0.11 sudo systemctl status k3s`.

### Role not found errors

Run `ansible-playbook` from the `~/workspace/k3s-ansible` directory so `ansible.cfg` can resolve `roles_path = ./roles`.

### VM DNS and IP migration

VM 210 now uses 192.168.0.22; .21 was observed answering with a different MAC.
The K3s agent service's explicit node-ip is .22, matching inventory and host vars.
After the service restart, the Node status converged to .22 and all five nodes
reported Ready. No Node deletion or disk reformat was needed.

The approved host DNS override uses 1.1.1.1 with the default DNS routing domain
`~.` in `/etc/systemd/resolved.conf.d/60-homelab-dns.conf`. It is managed by
`prepare-nodes.yml` only where `host_dns_server` is set. Provisioning/repair
scripts default to the same resolver for future runs. The existing Proxmox
cloud-init DNS metadata still contains .1; the guest override takes precedence.
A direct containerd pull of tailscale/tailscale:v1.104.1 succeeded afterward.
