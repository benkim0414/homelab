# Homelab GitOps

<!-- Canonical sibling doc: CLAUDE.md. Keep shared repo conventions aligned. -->

This repository manages a homelab K3s cluster through GitOps. Prefer declarative
changes in Git over manual cluster mutations, and treat this file as the Codex
entrypoint for repo-specific operating rules.

## Repo Structure

Each app has its own directory containing `values.yaml` (Helm values),
`sealed-secret.yaml` (encrypted and safe to commit), and raw manifests
(namespace, storage, CRDs, and related resources). ArgoCD Application
definitions live in `argocd/apps/*.yaml`.

## ArgoCD Multi-Source Pattern

All apps use a 3-source pattern:

- Source 1: Upstream Helm chart. It references the `$repo` alias for
  `valueFiles`.
- Source 2: This Git repo with `ref: repo`, which allows Source 1 to resolve
  `$repo/<app>/values.yaml`.
- Source 3: Optional raw manifests from this repo at `path: <app>` with a
  `directory.include` glob. Files not covered by `include:` are ignored by
  ArgoCD even if present in the directory.

`targetRevision: '*'` means latest chart release. Immich is pinned because the
chart version must match the `immich-server` image tag in `immich/values.yaml`.
Use `argocd/apps/immich.yaml` as the canonical pinned-version example.

## ArgoCD Is Self-Managed

ArgoCD manages itself through `argocd/apps/argocd.yaml` using the same
3-source pattern. Upgrade flow is normal GitOps: merge to `main`, then let
ArgoCD self-sync. The ArgoCD Tailscale Ingress in
`argocd/tailscale-ingress.yaml` is managed by that same Application.

## Bootstrapping a Fresh Cluster

After `k3s-ansible` provisions the nodes:

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd --create-namespace -f argocd/values.yaml
kubectl apply -f argocd/apps.yaml
```

The root App-of-Apps then creates child Applications from `argocd/apps/`.
Check rollout state with `kubectl get applications -n argocd`.

## Sealed Secrets Workflow

Create a new sealed secret with:

```bash
kubectl create secret generic <name> -n <namespace> \
  --from-literal=KEY=VALUE \
  --dry-run=client -o yaml \
  | kubeseal \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      --format yaml > <app>/sealed-secret.yaml
```

The master key backup lives at
`sealed-secrets/sealed-secrets-master-keys.yaml` and is gitignored. Regenerate
it with:

```bash
kubectl get secrets -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key=active \
  -o yaml > sealed-secrets/sealed-secrets-master-keys.yaml
```

Back it up externally. Without that key, sealed secrets are unrecoverable after
a cluster rebuild.

## Tailscale Operator

OAuth credentials are intentionally not committed in `tailscale/values.yaml`.
Pass them via `--set-string` during initial install as described in
`tailscale/README.md`.

To expose an app through Tailscale:

1. Commit `<app>/tailscale-ingress.yaml`.
2. Add that file to the app's ArgoCD `directory.include` glob.

## Handling Chart-Generated Secrets

Some charts generate random values on render, which causes perpetual
OutOfSync. Fix those by:

1. Adding `ignoreDifferences` on the generated Secret fields and any dependent
   Deployment `checksum/secret` annotation.
2. Adding `RespectIgnoreDifferences=true` to `syncOptions`.

Use `argocd/apps/monitoring.yaml` as the canonical example.

## Renovate Conventions

- Renovate tracks chart versions from `argocd/apps/*.yaml`.
- Custom regex managers handle non-standard `tag:` fields in
  `immich/values.yaml` and `kube-vip/values.yaml`.
- Commits use semantic prefixes such as `feat:`, `fix:`, `chore:`, and
  `docs:`.
- Update schedule is intentionally staggered. Immich is immediate; major
  infrastructure, monitoring, and Home Assistant updates are monthly.
- Immich update reviews should verify that the PostgreSQL backup CronJob ran.

## Adding a New App

1. Create `<app>/` with `values.yaml` plus any raw manifests.
2. Add `argocd/apps/<app>.yaml` using the 3-source pattern.
3. If secrets are needed, create `<app>/sealed-secret.yaml` through `kubeseal`.
4. Merge to `main`; the root `apps` Application will pick it up.

## Cluster Access and Local Environment

Cluster integrations are defined in `.mcp.json`:

- `kubernetes` for cluster resource access
- `grafana` for metrics, logs, dashboards, and alerts
- `argocd` for application state and operations

Environment variables and secrets bootstrap are defined in `.mise.toml`.
`scripts/env-secrets.sh` resolves local secrets into `.env.local`. Run
`mise run secrets` after first clone or after rotating credentials.

## Worktree and Parallel Changes

ArgoCD tracks `main`, so development should happen on feature branches. For
parallel work, prefer Git worktrees:

```bash
git worktree add ../homelab-<task> -b <type>/<app>-<description>
git worktree remove ../homelab-<task> && git branch -d <type>/<app>-<description>
```

## GitOps Safety Rules

- Prefer Git changes over manual `kubectl edit`, `kubectl patch`, or ad-hoc
  drift in the cluster.
- Treat `argocd/apps/immich.yaml` and `argocd/apps/monitoring.yaml` as the
  canonical examples for pinned versions and ignore-differences patterns.
- Before changing manifests for networking, storage, Sealed Secrets, or ArgoCD,
  read the adjacent app README and any relevant report under `reports/`.
- Never commit plaintext credentials. Use Sealed Secrets or local env injection.
- If you must inspect live state, use MCP tools or read-only `kubectl` first,
  then bring the fix back into Git.

## Codex-Specific Notes

- This file is the Codex-facing onboarding doc for the repo.
- `CLAUDE.md` remains the Claude-facing sibling doc and may include
  Claude-runtime-specific details such as hooks and local memory paths.
- Repo-scoped Codex skills live under `.agents/skills/`.
- Use `$cluster-health` for a structured operational health check and
  `$security-audit` for the security review workflow. These skills mirror the
  intent of the existing Claude command docs in `.claude/commands/`.
- Do not mirror `.claude/hooks` into Codex-specific files unless there is a
  concrete Codex runtime consumer for them.
