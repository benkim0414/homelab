# K3s HA Cluster - Ansible Configuration

Inventory and scripts for deploying a high-availability K3s cluster on Raspberry Pi and Proxmox VM nodes using [k3s-ansible](https://github.com/k3s-io/k3s-ansible).

## Architecture

```
                  +-------------------------+
                  |   VIP: 192.168.0.10     |  (kube-vip, ARP mode)
                  |   K8s API endpoint      |
                  +------------+------------+
     +-------------------------+-------------------------+
     v                         v                         v
+------------------+  +------------------+  +------------------+
| rpi5-8gb-crucial |  | rpi5-8gb-crucial |  |   rpi5-8gb-rpi   |  Control Plane
| -p3-plus-500gb   |  | -bx500-500gb     |  |    -512gb        |  (etcd + server)
|    .0.11         |  |    .0.12         |  |    .0.13         |
+------------------+  +------------------+  +------------------+
                      +------------------+
                      |  rpi5-8gb-rpi    |  Worker
                      |    -256gb        |
                      |    .0.14         |
                      +------------------+
                      +------------------+
                      | macpro-vm-16gb   |  Worker
                      | samsung-980-120gb|  (Proxmox VM, compute-only)
                      |    .0.21         |
                      +------------------+

   MetalLB Pool: 192.168.0.200 - 192.168.0.250 (L2 mode)
   Traefik: LoadBalancer service -> gets IP from MetalLB
```

### Nodes

| Hostname                       | IP           | Role                 | Storage       |
| ------------------------------ | ------------ | -------------------- | ------------- |
| rpi5-8gb-crucial-p3-plus-500gb | 192.168.0.11 | Control plane / etcd | NVMe (fast)   |
| rpi5-8gb-crucial-bx500-500gb   | 192.168.0.12 | Control plane / etcd | SATA          |
| rpi5-8gb-rpi-512gb             | 192.168.0.13 | Control plane / etcd | NVMe (fast)   |
| rpi5-8gb-rpi-256gb             | 192.168.0.14 | Worker / agent       | NVMe (medium) |
| macpro-vm-16gb-samsung-980-120gb | 192.168.0.21 | Worker / agent       | Proxmox VM, compute-only |

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

The Mac Pro worker is created manually in Proxmox, then joined through this
inventory as a K3s agent.

Recommended VM settings:

| Setting | Value |
| ------- | ----- |
| VM hostname | `macpro-vm-16gb-samsung-980-120gb` |
| VM IP | `192.168.0.21` |
| OS | Debian 12 Bookworm |
| vCPU | 4 |
| RAM | 16 GiB |
| Disk | 120 GiB |
| Network | Proxmox `vmbr0` |
| K3s role | Agent only |
| Longhorn role | Compute-only; no default disk label |

Create the `benkim0414` user on the VM with passwordless or promptable sudo
for Ansible, then install the homelab SSH key used by
`~/.ssh/codex_homelab_config`.

To create the VM from a Debian 12 cloud image with cloud-init instead of doing
a manual installer flow, run:

```bash
~/workspace/homelab/scripts/provision-macpro-k3s-vm.sh
```

## Inventory Configuration

All configuration lives in `inventory.yml`. Key decisions:

- **`api_endpoint`** is set to `192.168.0.11` (the first server's real IP) for bootstrap. kube-vip doesn't exist yet during initial install, so the VIP (192.168.0.10) is unreachable. Switch kubeconfig to the VIP after kube-vip is deployed.
- **`cluster-init`** is NOT in `server_config_yaml`. The k3s-ansible role handles `--cluster-init` (first server) vs `--server` (join, others) automatically via its systemd service template. Putting it in `server_config_yaml` writes it to every server node's `/etc/rancher/k3s/config.yaml`, causing each to initialize its own cluster.
- **`servicelb` is disabled** because MetalLB handles LoadBalancer services instead.
- **`tls-san`** includes the VIP and all server IPs so the API server cert is valid regardless of which endpoint is used.
- **`cluster_context`** is set to `k3s` so the kubeconfig context, cluster, and user are named `k3s` instead of the default `k3s-ansible`.

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
ansible-playbook playbooks/site.yml -i ~/workspace/homelab/k3s-ansible/inventory.yml
```

To join only the Mac Pro worker VM to an existing cluster, limit the playbook to
`.21`:

```bash
cd ~/workspace/k3s-ansible
ansible-playbook playbooks/site.yml \
  -i ~/workspace/homelab/k3s-ansible/inventory.yml \
  --limit 192.168.0.21
```

### 3. Configure kubectl

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
kubectl label node rpi5-8gb-crucial-p3-plus-500gb storage-tier=nvme-fast
kubectl label node rpi5-8gb-rpi-512gb storage-tier=nvme-fast
kubectl label node rpi5-8gb-rpi-256gb storage-tier=nvme-medium
kubectl label node rpi5-8gb-crucial-bx500-500gb storage-tier=sata
```

The Mac Pro VM receives opt-in scheduling labels through `extra_agent_args`:

```bash
kubectl get node macpro-vm-16gb-samsung-980-120gb \
  -L homelab/host,homelab/node-class,homelab/workload-tier
```

Expected labels:

```text
homelab/host=macpro
homelab/node-class=vm
homelab/workload-tier=heavy
```

Do not add `node.longhorn.io/create-default-disk=true` to this VM during the
first rollout.

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
ssh benkim0414@192.168.0.21 sudo systemctl restart k3s-agent
```

### 9. Verify

```bash
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
| Longhorn Mac Pro disk                       | No schedulable default disk or replicas on the Mac Pro VM |

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
