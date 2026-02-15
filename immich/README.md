# Immich on K3s

Self-hosted photo management deployed on the K3s Raspberry Pi 5 cluster using the [official Immich Helm chart](https://github.com/immich-app/immich-charts).

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  K3s Cluster                                        │
│                                                     │
│  ┌──────────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ immich-server│  │  valkey   │  │   postgres   │  │
│  │  (LoadBalancer│  │ (emptyDir)│  │ (local-path) │  │
│  │  :2283)      │  │  :6379   │  │   :5432      │  │
│  └──────┬───────┘  └──────────┘  └──────┬───────┘  │
│         │                               │           │
│         │  NFS                          │  local    │
└─────────┼───────────────────────────────┼───────────┘
          │                               │
          ▼                               ▼
  ┌───────────────┐              Worker node SSD
  │  NAS (OMV)    │              (rpi5-8gb-crucial-
  │ 192.168.0.40  │               bx500-500gb)
  │ /k3s-storage/ │
  │  immich/      │
  │   library/    │
  └───────────────┘

External IP: 192.168.0.201:2283 (MetalLB)
Tailscale:   https://immich.<tailnet>.ts.net (auto TLS)
```

| Component   | Storage        | Why                                        |
|-------------|----------------|--------------------------------------------|
| Photos      | NFS (NAS)      | Large files, shared access, ZFS protection |
| PostgreSQL  | local-path     | Performance, reliability, small dataset    |
| Valkey      | emptyDir       | Ephemeral job queue, acceptable for homelab|
| ML          | **disabled**   | Conserve RAM on 8GB Pi nodes               |

## Prerequisites

1. **NFS client** installed on all K3s nodes:

   ```bash
   sudo apt install -y nfs-common
   ```

2. **NAS directories** created on OMV (192.168.0.40):

   ```bash
   sudo mkdir -p /storage/k3s/immich/library
   sudo chown -R 1000:1000 /storage/k3s/immich
   sudo chmod -R 775 /storage/k3s/immich
   ```

   See [openmediavault/README.md](../openmediavault/README.md) for full NAS setup.

3. **MetalLB** deployed with IP pool including 192.168.0.201.

## Deploy

### 1. Create namespace

```bash
kubectl apply -f immich/namespace.yaml
```

### 2. Create database credentials

Secrets are managed with [Sealed Secrets](../sealed-secrets/). The encrypted `sealed-secret.yaml` is safe to commit — the controller decrypts it in-cluster.

```bash
# Generate a new password and create a SealedSecret
kubectl create secret generic immich-db-credentials \
  --namespace=immich \
  --from-literal=POSTGRES_USER=immich \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  --from-literal=POSTGRES_DB=immich \
  --dry-run=client -o yaml \
  | kubeseal --format yaml > immich/sealed-secret.yaml

# Apply
kubectl apply -f immich/sealed-secret.yaml
```

### 3. Create NFS storage

```bash
kubectl apply -f immich/nfs-pv-pvc.yaml
```

Verify binding:

```bash
kubectl get pv immich-library-nfs-pv
kubectl get pvc -n immich immich-library
# Both should show status: Bound
```

### 4. Deploy PostgreSQL

```bash
kubectl apply -f immich/postgresql.yaml
```

Wait for PostgreSQL to be ready:

```bash
kubectl rollout status statefulset/immich-postgres -n immich --timeout=120s
```

### 5. Install Immich via Helm

```bash
helm install immich oci://ghcr.io/immich-app/immich-charts/immich \
  --namespace immich \
  -f immich/values.yaml \
  --version 0.10.3
```

## Verify

```bash
# All pods running
kubectl get pods -n immich

# Services with external IP
kubectl get svc -n immich
# immich-server should show EXTERNAL-IP 192.168.0.201

# PostgreSQL healthy
kubectl logs -n immich immich-postgres-0 --tail=10

# Immich server responding
curl http://192.168.0.201:2283/api/server/ping
# Expected: {"res":"pong"}
```

Access the web UI at **http://192.168.0.201:2283** and create your admin account.

## Upgrade

To upgrade the Immich app version, set `controllers.main.containers.main.image.tag` in `values.yaml` to the desired version, then run:

```bash
helm upgrade immich oci://ghcr.io/immich-app/immich-charts/immich \
  --namespace immich \
  -f immich/values.yaml \
  --version 0.10.3
```

> **Tip:** Back up PostgreSQL before upgrading — some releases include database migrations.
>
> ```bash
> kubectl exec -n immich immich-postgres-0 -- \
>   pg_dump -U immich -d immich -Fc -f /tmp/immich-backup.dump
> kubectl cp immich/immich-postgres-0:/tmp/immich-backup.dump ./immich-backup.dump
> ```

## Uninstall

```bash
helm uninstall immich -n immich
kubectl delete -f immich/postgresql.yaml
kubectl delete -f immich/nfs-pv-pvc.yaml
kubectl delete -f immich/sealed-secret.yaml
kubectl delete -f immich/namespace.yaml
```

> **Note:** The NFS data on the NAS and the local-path PVC on the worker node are retained (`persistentVolumeReclaimPolicy: Retain`). Delete them manually if no longer needed.

## Tailscale Access

Immich is also exposed over the [Tailscale](https://tailscale.com/) tailnet via the Tailscale Kubernetes operator, providing HTTPS access from any device on the tailnet.

### How it works

The Tailscale operator watches the `immich-tailscale` Ingress (`ingressClassName: tailscale`) and creates a proxy Pod that:
1. Joins the tailnet as a device named `immich`
2. Obtains a LetsEncrypt TLS certificate automatically
3. Forwards traffic to the `immich-server` ClusterIP service

LAN access via MetalLB (`192.168.0.201:2283`) continues to work unchanged.

### Prerequisites

1. **Tailscale operator** installed in the `tailscale` namespace (see [`../tailscale/`](../tailscale/))
2. **MagicDNS** and **HTTPS Certificates** enabled in the [Tailscale admin console](https://login.tailscale.com/admin/dns)

### Deploy

```bash
kubectl apply -f immich/tailscale-ingress.yaml
```

### Verify

```bash
# Ingress proxy Pod created
kubectl get pods -n tailscale -l tailscale.com/parent-resource=immich-tailscale

# Ingress shows address
kubectl get ingress -n immich immich-tailscale

# HTTPS access from a tailnet device
curl https://immich.<tailnet>.ts.net/api/server/ping
# Expected: {"res":"pong"}
```

### Remove

```bash
kubectl delete -f immich/tailscale-ingress.yaml
```

## Future Enhancements

- **Enable ML**: Set `machine-learning.enabled: true` in values.yaml and `helm upgrade`. Consider adding resource limits.
- **Backups**: Schedule PostgreSQL `pg_dump` via a CronJob. NAS photos are protected by ZFS snapshots.
- **External OAuth**: Configure OIDC for SSO authentication.
