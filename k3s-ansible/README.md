# K3s HA Cluster - Ansible Configuration

Inventory and scripts for deploying a high-availability K3s cluster on Raspberry Pi 5 nodes using [k3s-ansible](https://github.com/k3s-io/k3s-ansible).

## Architecture

```
                  ┌─────────────────────────┐
                  │   VIP: 192.168.0.10     │  (kube-vip, ARP mode)
                  │   K8s API endpoint      │
                  └─────────────┬───────────┘
     ┌──────────────────────────┼──────────────────────────┐
     ▼                          ▼                          ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ rpi5-8gb-crucial │  │ rpi5-8gb-samsung │  │  rpi5-8gb-rpi    │  Control Plane
│ -p3-plus-500gb   │  │ -980-500gb       │  │  -256gb          │  (etcd + server)
│    .0.11         │  │    .0.13         │  │    .0.14         │
└──────────────────┘  └──────────────────┘  └──────────────────┘
                      ┌──────────────────┐
                      │ rpi5-8gb-crucial │  Worker
                      │ -bx500-500gb     │
                      │    .0.12         │
                      └──────────────────┘

   MetalLB Pool: 192.168.0.200 - 192.168.0.250 (L2 mode)
   Traefik: LoadBalancer service → gets IP from MetalLB
```

### Nodes

| Hostname                       | IP           | Role          | Storage       |
| ------------------------------ | ------------ | ------------- | ------------- |
| rpi5-8gb-crucial-p3-plus-500gb | 192.168.0.11 | Control plane | NVMe (fast)   |
| rpi5-8gb-crucial-bx500-500gb   | 192.168.0.12 | Worker        | SATA          |
| rpi5-8gb-samsung-980-500gb     | 192.168.0.13 | Control plane | NVMe (fast)   |
| rpi5-8gb-rpi-256gb             | 192.168.0.14 | Control plane | NVMe (medium) |

### Networking

| Component | Address / Range               |
| --------- | ----------------------------- |
| VIP       | 192.168.0.10 (kube-vip, ARP)  |
| MetalLB   | 192.168.0.200 - 192.168.0.250 |
| K3s API   | port 6443                     |

## Files

```
homelab/
├── k3s-ansible/
│   ├── README.md
│   ├── inventory.yml               # Cluster inventory + all vars
│   └── scripts/
│       ├── preflight-check.sh      # Pre-flight node validation
│       └── verify-cluster.sh       # Post-deploy verification
├── kube-vip/
│   └── values.yaml                 # Helm chart values
├── metallb/
│   ├── values.yaml                 # Helm chart values
│   ├── ipaddresspool.yaml          # Post-install CR
│   └── l2advertisement.yaml        # Post-install CR
└── traefik/
    ├── helmchartconfig.yaml         # K3s HelmChartConfig CRD
    └── examples/
        ├── example-ingressroute.yaml
        └── whoami-test.yaml
```

## Prerequisites

- [k3s-ansible](https://github.com/k3s-io/k3s-ansible) cloned to `~/workspace/k3s-ansible`
- Ansible with required galaxy collections
- SSH access to all nodes as the `pi` user (key-based, passwordless sudo)

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

## Inventory Configuration

All configuration lives in `inventory.yml`. Key decisions:

- **`api_endpoint`** is set to `192.168.0.11` (the first server's real IP) for bootstrap. kube-vip doesn't exist yet during initial install, so the VIP (192.168.0.10) is unreachable. Switch kubeconfig to the VIP after kube-vip is deployed.
- **`cluster-init`** is NOT in `server_config_yaml`. The k3s-ansible role handles `--cluster-init` (first server) vs `--server` (join, others) automatically via its systemd service template. Putting it in `server_config_yaml` writes it to every server node's `/etc/rancher/k3s/config.yaml`, causing each to initialize its own cluster.
- **`servicelb` is disabled** because MetalLB handles LoadBalancer services instead.
- **`tls-san`** includes the VIP and all server IPs so the API server cert is valid regardless of which endpoint is used.
- **`cluster_context`** is set to `k3s` so the kubeconfig context, cluster, and user are named `k3s` instead of the default `k3s-ansible`.

## Deployment

### 1. Pre-flight checks

Validates SSH connectivity, cgroup parameters, RAM, disk, and `eth0` on all nodes.

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

### 8. Label nodes and apply .14 taint

```bash
kubectl label node rpi5-8gb-crucial-p3-plus-500gb storage-tier=nvme-fast
kubectl label node rpi5-8gb-samsung-980-500gb storage-tier=nvme-fast
kubectl label node rpi5-8gb-rpi-256gb storage-tier=nvme-medium
kubectl label node rpi5-8gb-crucial-bx500-500gb storage-tier=sata
```

Node `.14` (`rpi5-8gb-rpi-256gb`) has a `NoSchedule` taint to prevent Deployments
and StatefulSets from scheduling there. It is managed via `host_vars/192.168.0.14.yml`
(persisted through k3s-ansible re-runs), but must also be applied manually after a fresh
cluster deploy before ArgoCD syncs workloads:

```bash
kubectl taint node rpi5-8gb-rpi-256gb node-role.kubernetes.io/control-plane:NoSchedule
kubectl drain rpi5-8gb-rpi-256gb --ignore-daemonsets --delete-emptydir-data
```

**Why:** `.14` is the smallest node (256 GB NVMe, "nvme-medium"). Running etcd I/O and
workload containerization I/O on the same drive caused repeated kubelet crashes, which
led to force-deleted pods, stale Flannel IPAM leases, and full IPAM exhaustion. DaemonSets
with `tolerations: [{operator: Exists}]` still run on `.14` (kube-vip, MetalLB,
Alloy, node-exporter, Longhorn manager/driver, flannel-ipam-cleanup).

### 9. Verify

```bash
bash ~/workspace/homelab/k3s-ansible/scripts/verify-cluster.sh
```

## Verification Checklist

| Check                                       | Expected                                  |
| ------------------------------------------- | ----------------------------------------- |
| `kubectl get nodes`                         | 4 nodes Ready (3 control-plane, 1 worker) |
| `curl -k https://192.168.0.10:6443/healthz` | `ok`                                      |
| kube-vip pods                               | 3 running (one per control-plane node)    |
| MetalLB pods                                | 1 controller + 4 speakers                 |
| `kubectl -n kube-system get svc traefik`    | EXTERNAL-IP in 192.168.0.200-250          |
| Node labels                                 | `storage-tier` set on all 4 nodes         |

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
- Do NOT put `cluster-init: true` in `server_config_yaml` — the role handles this.
- Check that the first server's k3s is running: `ssh pi@192.168.0.11 sudo systemctl status k3s`.

### Role not found errors

Run `ansible-playbook` from the `~/workspace/k3s-ansible` directory so `ansible.cfg` can resolve `roles_path = ./roles`.
