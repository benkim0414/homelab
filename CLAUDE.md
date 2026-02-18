# Homelab GitOps

## Repo Structure

Each app has its own directory containing `values.yaml` (Helm values),
`sealed-secret.yaml` (encrypted — safe to commit), and raw manifests
(namespace, storage, CRDs, etc.). ArgoCD Application definitions live in
`argocd/apps/*.yaml`.

## ArgoCD Multi-Source Pattern

All apps use a 3-source pattern:

- **Source 1**: Upstream Helm chart. References `$repo` alias for `valueFiles`.
- **Source 2**: This Git repo with `ref: repo` — required so Source 1 can
  resolve `$repo/<app>/values.yaml`.
- **Source 3** (optional): This Git repo at `path: <app>` with a
  `directory.include` glob for raw manifests. Files not in the `include:` list
  are ignored by ArgoCD even if present in the directory.

`targetRevision: '*'` means latest chart release. Immich uses a pinned version
because the chart version must match the `immich-server` image tag in
`values.yaml`.

See `argocd/apps/immich.yaml` for the canonical pinned-version example.

## ArgoCD Is Self-Managed

ArgoCD manages itself via `argocd/apps/argocd.yaml` (3-source pattern).
Chart upgrades go through the normal GitOps flow — merge to `main`, ArgoCD
self-syncs. The Tailscale Ingress for ArgoCD (`argocd/tailscale-ingress.yaml`)
is also managed by this Application.

## Bootstrapping a Fresh Cluster

After running k3s-ansible to bring up the K3s nodes:

```bash
# 1. Install ArgoCD (one-time manual step)
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd --create-namespace -f argocd/values.yaml

# 2. Apply the root "App of Apps" — ArgoCD takes over everything else
kubectl apply -f argocd/apps.yaml
```

ArgoCD syncs `argocd/apps/` and creates all child Applications automatically.
Monitor progress with `kubectl get applications -n argocd`.

## Sealed Secrets Workflow

Create a new SealedSecret:

```bash
kubectl create secret generic <name> -n <namespace> \
  --from-literal=KEY=VALUE \
  --dry-run=client -o yaml \
  | kubeseal \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      --format yaml > <app>/sealed-secret.yaml
```

The master key backup lives at `sealed-secrets/sealed-secrets-master-keys.yaml`
(gitignored). Regenerate it with:

```bash
kubectl get secrets -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key=active \
  -o yaml > sealed-secrets/sealed-secrets-master-keys.yaml
```

Keep it backed up externally — without it, all SealedSecrets are unrecoverable
after a cluster rebuild.

## Tailscale Operator

OAuth credentials are **not** in `tailscale/values.yaml` — they are passed via
`--set-string` at initial install time (see `tailscale/README.md`).

To expose a service via Tailscale, commit a `tailscale-ingress.yaml` in the app
directory and add it to the ArgoCD Application's `include:` glob.

## Handling Chart-Generated Secrets

Charts that generate random values on each render (e.g., Grafana admin
password) cause perpetual OutOfSync. Fix pattern:

1. Add `ignoreDifferences` on the Secret's data fields and any Deployment
   `checksum/secret` annotation.
2. Add `RespectIgnoreDifferences=true` to `syncOptions`.

See `argocd/apps/monitoring.yaml` for the canonical example.

## Renovate Conventions

- Renovate detects chart versions from `argocd/apps/*.yaml` (ArgoCD preset)
  and image tags from `immich/`, `monitoring/`, `home-assistant/` manifests.
- Custom regex managers handle non-standard `tag:` fields in `immich/values.yaml`
  and `kube-vip/values.yaml`.
- Commit format: semantic (`feat:`, `fix:`, `chore:`, `docs:`).
- Update schedules: Immich — immediate; infrastructure, monitoring,
  home-assistant — monthly (first of month, before 6am).
- Immich PRs include a reminder to verify the PostgreSQL backup CronJob ran.

## Adding a New App

1. Create `<app>/` with `values.yaml` and raw manifests.
2. Add `argocd/apps/<app>.yaml` using the 3-source pattern.
3. If secrets are needed, create `<app>/sealed-secret.yaml` via kubeseal.
4. Commit and merge to `main` — the root `apps` Application picks it up automatically.

## Cluster Access

The Kubernetes MCP server is configured in `.mcp.json`. Claude can query the
cluster directly via the `mcp__kubernetes__*` tools without running kubectl.

The Grafana MCP server is also configured in `.mcp.json`. Claude can query
metrics (PromQL), logs (LogQL), and dashboards via `mcp__grafana__*` tools.
Grafana is at `http://192.168.0.203`. The service account token is read from
the `GRAFANA_SERVICE_ACCOUNT_TOKEN` environment variable — export it before
starting Claude Code.

## Git Workflow for Parallel AI Agents

ArgoCD tracks the `main` branch — changes only go live after merging to main.
All work happens on feature branches via PRs.

### Branch Naming

```
<type>/<app>-<description>

feat/immich-add-s3-backup
fix/monitoring-fix-alertmanager-config
```

### Parallel Work with Git Worktrees

When running multiple Claude Code agents in parallel, use worktrees so each
agent has an isolated working directory without interfering with each other:

```bash
git worktree add ../homelab-<task> -b <type>/<app>-<description>
git worktree list
git worktree remove ../homelab-<task> && git branch -d <type>/<app>-<description>
```

### Committing Changes

After completing any set of file edits, always commit before moving on:

- **Atomic commits** — one logical change per commit. Don't bundle unrelated
  edits (e.g., a values change and a manifest fix) into a single commit.
- Stage only the files for that change (`git add <file>...`), never `git add -A`.
- Write a conventional commit message scoped to the app (see format below).
- Commit on the current feature branch — never directly to `main`.
- Verify with `git status` that the working tree is clean after committing.

### Commit and PR Format

Use semantic commits scoped to the app name:

```
feat(immich): add S3 backup configuration
fix(monitoring): correct alertmanager webhook URL
chore(home-assistant): bump chart to 0.5.1
```
