# ArgoCD on K3s

GitOps continuous delivery for the homelab K3s cluster. ArgoCD watches the Git repo and automatically reconciles cluster state when changes are merged.

## Architecture

```
GitHub repo (main branch)
    │
    │  push / merge PR
    ▼
┌──────────────┐     ┌──────────────────────────────┐
│   ArgoCD     │────▶│  K3s Cluster                 │
│  (sync loop) │     │                              │
│              │     │  immich        (Helm + raw)   │
│  192.168.0.  │     │  metallb       (Helm + CRDs) │
│    202:443   │     │  sealed-secrets (Helm)        │
│              │     │  kube-vip      (Helm)         │
└──────────────┘     │  tailscale     (Helm)         │
                     └──────────────────────────────┘
```

| Component              | Resources        |
|------------------------|------------------|
| Application controller | 256-512 MB RAM   |
| Server (UI/API)        | 128-256 MB RAM   |
| Repo server            | 128-256 MB RAM   |
| Redis                  | 64-128 MB RAM    |
| ApplicationSet         | 64-128 MB RAM    |

Total: ~640 MB-1.3 GB RAM (fits comfortably on 8 GB Pi nodes).

## Prerequisites

1. **GitHub remote** configured for the repo
2. **Helm** v3 installed locally
3. **MetalLB** deployed (ArgoCD server uses 192.168.0.202)

## Deploy

### 1. Add the ArgoCD Helm repo

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
```

### 2. Install ArgoCD

```bash
kubectl create namespace argocd
helm install argocd argo/argo-cd \
  --namespace argocd \
  -f argocd/values.yaml
```

### 3. Get the initial admin password

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d
```

### 4. Access the UI

Open **https://192.168.0.202** in your browser. Log in with username `admin` and the password from step 3.

### 5. Connect the Git repo

```bash
# If the repo is public, no credentials needed.
# For a private repo, add a deploy key or token:
argocd repo add https://github.com/benkim0414/homelab.git
```

### 6. Apply the Application manifests

```bash
kubectl apply -f argocd/apps/infrastructure.yaml
kubectl apply -f argocd/apps/immich.yaml
```

ArgoCD will detect that existing Helm releases match the declared state and show them as "Synced" without making changes.

## How upgrades work with Renovate

1. Renovate detects a new Immich version and opens a PR bumping `tag:` in `immich/values.yaml` and/or `targetRevision:` in `argocd/apps/immich.yaml`
2. You review and merge the PR
3. ArgoCD detects the change on `main` and syncs automatically
4. The PostgreSQL backup CronJob ensures a recent backup exists before the upgrade runs

## Adopting existing Helm releases

ArgoCD can adopt resources it didn't originally create. When you first apply the Application manifests, ensure the chart versions and values match what's currently deployed. ArgoCD will recognize everything is in sync and take over management without disrupting the running workloads.

> **Note:** For the Tailscale operator, OAuth credentials are passed via `--set-string` at install time and are not in `values.yaml`. After ArgoCD adoption, manage these credentials via a Secret referenced in the Helm values, or use Sealed Secrets.

## Upgrade ArgoCD

```bash
helm repo update
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  -f argocd/values.yaml
```

## Uninstall

```bash
kubectl delete -f argocd/apps/immich.yaml
kubectl delete -f argocd/apps/infrastructure.yaml
helm uninstall argocd -n argocd
kubectl delete namespace argocd
```

> **Warning:** Deleting Applications with `prune: true` enabled will also delete the managed resources. To keep resources, disable automated sync or remove the `finalizer` before deleting the Application.
