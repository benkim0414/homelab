# Vaultwarden 1.37.1 Compatibility Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Vaultwarden server 1.37.1 so the image version matches the current Helm chart application version.

**Architecture:** Keep the existing three-source ArgoCD Application and floating chart revision unchanged. Update the single image-tag override that currently forces the chart to deploy Vaultwarden 1.35.8, then validate the YAML input and resulting configured tag.

**Tech Stack:** Kubernetes GitOps, ArgoCD, Helm values YAML, Python 3 with PyYAML for local validation

**Spec:** `docs/superpowers/specs/2026-08-18-vaultwarden-1-37-1-compatibility.md`

## Global Constraints

- Set `vaultwarden/values.yaml` `image.tag` to the exact string `"1.37.1"`.
- Preserve `argocd/apps/vaultwarden.yaml`, including `targetRevision: '*'`.
- Preserve all Vaultwarden storage, networking, secrets, sign-up policy, and admin-token settings.
- Do not mutate or manually sync the live cluster.
- Do not add a repository test framework for this one-value GitOps change.

---

### Task 1: Align the Vaultwarden image pin

**Files:**
- Modify: `vaultwarden/values.yaml:1-2`
- Verify: `argocd/apps/vaultwarden.yaml`

**Interfaces:**
- Consumes: the `image.tag` value consumed by the `guerzon/vaultwarden` Helm chart
- Produces: a Helm values document selecting `docker.io/vaultwarden/server:1.37.1`

- [ ] **Step 1: Run the compatibility assertion and verify it fails**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

values = yaml.safe_load(Path("vaultwarden/values.yaml").read_text())
actual = values["image"]["tag"]
assert actual == "1.37.1", f"expected Vaultwarden 1.37.1, got {actual}"
PY
```

Expected: FAIL with `expected Vaultwarden 1.37.1, got 1.35.8`.

- [ ] **Step 2: Implement the minimal compatibility fix**

Change the opening values block to:

```yaml
image:
  tag: "1.37.1"
```

Do not modify any other runtime configuration.

- [ ] **Step 3: Run the compatibility assertion and YAML validation**

Re-run the Step 1 command.

Expected: PASS with exit status 0 and no output.

Then run:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

for path in (Path("vaultwarden/values.yaml"), Path("argocd/apps/vaultwarden.yaml")):
    list(yaml.safe_load_all(path.read_text()))
    print(f"validated {path}")
PY
```

Expected:

```text
validated vaultwarden/values.yaml
validated argocd/apps/vaultwarden.yaml
```

- [ ] **Step 4: Confirm scope and commit**

Run:

```bash
git diff -- vaultwarden/values.yaml argocd/apps/vaultwarden.yaml
```

Expected: only `vaultwarden/values.yaml` changes, replacing `1.35.8` with
`1.37.1`.

Then stage explicit paths and commit:

```bash
git add vaultwarden/values.yaml
git commit -m "fix(vaultwarden): align image with chart version"
```
