# Renovate GitOps and Vaultwarden Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Renovate as a GitOps-managed cluster workload and make Renovate detect Vaultwarden server image updates from `vaultwarden/values.yaml`.

**Architecture:** Add a Renovate ArgoCD Application using the official Renovate Helm chart, repo-local Helm values, and an externally bootstrapped Kubernetes Secret for the GitHub token. Extend `renovate.json5` with a Vaultwarden regex manager and remove the monthly delay for Vaultwarden updates.

**Tech Stack:** ArgoCD Application manifests, Helm values, Renovate self-hosted config, Renovate regex custom manager, Kubernetes Secret via Sealed Secrets, Markdown docs.

## Global Constraints

- Work only in the linked worktree for this branch.
- Prefer declarative GitOps changes over manual cluster mutations.
- Do not commit plaintext credentials, tokens, generated Secret manifests, or local env files.
- The Renovate token must be supplied as `RENOVATE_TOKEN` in a Kubernetes Secret named `renovate-token` in namespace `renovate`.
- It is acceptable for the committed deployment to require secret bootstrap before the CronJob can run successfully.
- Preserve the repo's ArgoCD multi-source pattern.
- Stage explicit paths only.
- Validate changed YAML, Renovate config syntax when tooling is available, Vaultwarden regex extraction, and the absence of plaintext token material before committing.

---

## File Structure

- Read: `docs/superpowers/specs/2026-08-22-renovate-gitops-vaultwarden-design.md`
  Approved design and source of truth for scope.
- Read: `argocd/apps/immich.yaml`
  Canonical pinned app and multi-source pattern.
- Read: `argocd/apps/monitoring.yaml`
  Canonical sync options and ignore-differences pattern.
- Read: `argocd/apps/vaultwarden.yaml`
  Existing Vaultwarden app shape.
- Read: `renovate.json5`
  Existing Renovate repository configuration.
- Read: `vaultwarden/values.yaml`
  Source file for Vaultwarden image tag extraction.
- Create: `argocd/apps/renovate.yaml`
  ArgoCD Application for Renovate.
- Create: `renovate/values.yaml`
  Helm values for self-hosted Renovate.
- Create: `renovate/README.md`
  Bootstrap documentation for the required token Secret.
- Modify: `renovate.json5`
  Add Vaultwarden extraction and schedule policy changes.

## Task 1: Add Renovate GitOps Deployment

**Files:**
- Read: `argocd/apps/immich.yaml`
- Read: `argocd/apps/vaultwarden.yaml`
- Create: `argocd/apps/renovate.yaml`
- Create: `renovate/values.yaml`
- Create: `renovate/README.md`

**Interfaces:**
- Consumes: official Renovate Helm chart values and repo ArgoCD multi-source conventions.
- Produces: a GitOps-managed Renovate CronJob definition that expects a pre-existing token Secret.

- [ ] **Step 1: Confirm branch and clean state**

Run:

```bash
pwd
git branch --show-current
git status --short
```

Expected:

```text
/home/benkim0414/workspace/homelab/.worktrees/fix-renovate-vaultwarden-clean
fix/renovate-vaultwarden-clean
```

`git status --short` may show only the plan file before implementation begins.

- [ ] **Step 2: Review relevant ArgoCD app patterns**

Run:

```bash
sed -n '1,220p' argocd/apps/immich.yaml
sed -n '1,220p' argocd/apps/vaultwarden.yaml
sed -n '1,260p' argocd/apps/monitoring.yaml
```

Use these patterns:

```text
chart source first
repo source with ref: repo second
optional raw manifest source third when app-local manifests may exist
destination namespace set per app
syncPolicy automated prune/selfHeal
CreateNamespace=true
```

- [ ] **Step 3: Create Renovate values**

Create `renovate/values.yaml` with:

```yaml
cronjob:
  schedule: "0 4 * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3

envFrom:
  - secretRef:
      name: renovate-token

renovate:
  configIsJson5: true
  config: |
    {
      platform: "github",
      repositories: ["benkim0414/homelab"],
      onboarding: false,
      requireConfig: "required",
      dependencyDashboard: true,
      gitAuthor: "Renovate Bot <bot@renovateapp.com>"
    }
```

Do not add `RENOVATE_TOKEN` to this file. The chart consumes it from the `renovate-token` Secret via `envFrom`.

- [ ] **Step 4: Create Renovate ArgoCD Application**

Create `argocd/apps/renovate.yaml` with:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: renovate
  namespace: argocd
spec:
  project: default
  sources:
    - repoURL: ghcr.io/renovatebot/charts
      chart: renovate
      targetRevision: "*"
      helm:
        valueFiles:
          - $repo/renovate/values.yaml
    - repoURL: git@github.com:benkim0414/homelab.git
      targetRevision: main
      ref: repo
    - repoURL: git@github.com:benkim0414/homelab.git
      targetRevision: main
      path: renovate
      directory:
        include: "{sealed-secret.yaml}"
  destination:
    server: https://kubernetes.default.svc
    namespace: renovate
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

The third source intentionally allows a future `renovate/sealed-secret.yaml` to be managed without changing the Application.

- [ ] **Step 5: Document secret bootstrap**

Create `renovate/README.md` with:

````markdown
# Renovate

Renovate is deployed by ArgoCD from `argocd/apps/renovate.yaml` using the official Renovate Helm chart.

## GitHub Token

The CronJob expects a Kubernetes Secret named `renovate-token` in the `renovate` namespace with a `RENOVATE_TOKEN` key. Do not commit a plaintext Secret.

Create the SealedSecret after generating a GitHub token with repository write access:

```bash
kubectl create namespace renovate --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic renovate-token -n renovate \
  --from-literal=RENOVATE_TOKEN='<github-token>' \
  --dry-run=client -o yaml \
  | kubeseal \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      --format yaml > renovate/sealed-secret.yaml
```

Commit `renovate/sealed-secret.yaml` after confirming it contains only encrypted data.

## Validation

After the secret is synced, confirm the CronJob exists and inspect the latest run:

```bash
kubectl get cronjob -n renovate
kubectl get jobs -n renovate --sort-by=.status.startTime
kubectl logs -n renovate job/<job-name>
```
````

- [ ] **Step 6: Validate no plaintext secret material was added**

Run:

```bash
git diff -- argocd/apps/renovate.yaml renovate/values.yaml renovate/README.md
rg -n "RENOVATE_TOKEN=|ghp_|github_pat_|token:|password:" argocd/apps/renovate.yaml renovate/values.yaml renovate/README.md
```

Expected:

```text
rg may match documentation placeholders only.
No actual GitHub token or password appears in the diff.
```

## Task 2: Teach Renovate Vaultwarden Extraction

**Files:**
- Read: `vaultwarden/values.yaml`
- Modify: `renovate.json5`

**Interfaces:**
- Consumes: Vaultwarden image tag from `vaultwarden/values.yaml`.
- Produces: Renovate dependency extraction for `docker.io/vaultwarden/server` and faster Vaultwarden PR creation.

- [ ] **Step 1: Add custom regex manager**

In `renovate.json5`, add this object to `customManagers` after the kube-vip manager:

```json5
    {
      // Vaultwarden server image tag in Helm values (chart supplies repository)
      "customType": "regex",
      "fileMatch": ["^vaultwarden/values\\.yaml$"],
      "matchStrings": [
        "image:\\s*\\n\\s*tag:\\s*\"(?<currentValue>[^\"]+)\""
      ],
      "depNameTemplate": "docker.io/vaultwarden/server",
      "datasourceTemplate": "docker",
      "versioningTemplate": "docker"
    }
```

- [ ] **Step 2: Remove Vaultwarden monthly schedule**

In the Vaultwarden package rule, change:

```json5
      "description": "Group Vaultwarden packages, schedule monthly",
      "matchPackagePatterns": ["vaultwarden"],
      "groupName": "vaultwarden",
      "schedule": ["before 6am on the first day of the month"]
```

to:

```json5
      "description": "Group Vaultwarden packages",
      "matchPackagePatterns": ["vaultwarden"],
      "groupName": "vaultwarden"
```

- [ ] **Step 3: Verify regex extraction locally**

Run:

```bash
node - <<'NODE'
const fs = require('fs');
const text = fs.readFileSync('vaultwarden/values.yaml', 'utf8');
const match = text.match(/image:\s*\n\s*tag:\s*"([^"]+)"/);
if (!match) {
  throw new Error('Vaultwarden image tag regex did not match');
}
console.log(`docker.io/vaultwarden/server ${match[1]}`);
NODE
```

Expected:

```text
docker.io/vaultwarden/server 1.37.1
```

## Task 3: Validate and Commit

**Files:**
- Read: `argocd/apps/renovate.yaml`
- Read: `renovate/values.yaml`
- Read: `renovate/README.md`
- Read: `renovate.json5`

**Interfaces:**
- Consumes: changed files from Tasks 1 and 2.
- Produces: committed GitOps fix with local validation evidence.

- [ ] **Step 1: Validate YAML syntax**

Run whichever YAML validators are available, preferring repo-installed tools if present:

```bash
yq e '.' argocd/apps/renovate.yaml >/dev/null
yq e '.' renovate/values.yaml >/dev/null
```

If `yq` is unavailable, run:

```bash
python3 - <<'PY'
import sys
try:
    import yaml
except ImportError:
    raise SystemExit('PyYAML unavailable; use kubectl dry-run and manual review')
for path in ['argocd/apps/renovate.yaml', 'renovate/values.yaml']:
    with open(path, encoding='utf-8') as fh:
        yaml.safe_load(fh)
    print(f'{path}: ok')
PY
```

If neither parser is available, run:

```bash
kubectl apply --dry-run=client -f argocd/apps/renovate.yaml
```

and manually inspect `renovate/values.yaml`.

- [ ] **Step 2: Validate Renovate config syntax**

Run:

```bash
npx --yes renovate-config-validator renovate.json5
```

If sandbox networking blocks package download, rerun with network approval. If the validator cannot be run, record that limitation and rely on local regex verification plus diff review.

- [ ] **Step 3: Review final diff and secret scan**

Run:

```bash
git diff -- argocd/apps/renovate.yaml renovate/values.yaml renovate/README.md renovate.json5
rg -n "ghp_|github_pat_|RENOVATE_TOKEN=.*[^'<]|password:|clientSecret|secretKey" argocd/apps/renovate.yaml renovate/values.yaml renovate/README.md renovate.json5
```

Expected:

```text
No plaintext token, password, client secret, or secret key appears.
```

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add argocd/apps/renovate.yaml renovate/values.yaml renovate/README.md renovate.json5
git diff --cached -- argocd/apps/renovate.yaml renovate/values.yaml renovate/README.md renovate.json5
git commit -m "fix(renovate): deploy gitops updater for vaultwarden"
```

Expected: commit succeeds with only the four implementation files staged.

## Final Verification

- [ ] `git status --short` is clean after commits.
- [ ] `git log --oneline -3` shows the design, plan, and implementation commits.
- [ ] The final diff contains no plaintext credential material.
- [ ] Local regex extraction reports `docker.io/vaultwarden/server 1.37.1`.
- [ ] Any skipped validation command is reported with the reason.
