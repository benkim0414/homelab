# Homelab Health Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a GitOps-first health/access investigation, fix durable repo issues when found, and reserve live node changes for explicit approval.

**Architecture:** Validate local SSH access first, including read-only hostname probes for the access baseline; inspect cluster state through configured read-only integrations second; and use other direct SSH only as a targeted fallback. Findings are classified into repository fixes, manual recovery, or observe-only conditions before any mutation.

**Tech Stack:** Bash, OpenSSH, Kubernetes MCP tools, optional ArgoCD/Grafana MCP tools, existing `k3s-ansible` inventory and scripts, Markdown reports.

## Global Constraints

- Read-only SSH hostname probes are permitted for access-baseline verification.
- Other direct SSH inspection is used only when read-only cluster evidence points to a node-local problem.
- State-changing SSH actions require supporting cluster evidence and explicit approval.
- Completed backup and Helm job pods are not treated as active failures.
- Durable fixes are made in this repository where possible.
- Any live mutation is explicitly approved, targeted, and documented.
- Sandbox and network failures are not treated as node failures.
- Destructive node, Kubernetes, GitHub, or storage operations require explicit approval.
- For repo changes, work in the linked worktree and stage explicit paths only.

---

## File Structure

- Read: `docs/superpowers/specs/2026-07-12-homelab-health-access-design.md`
  Approved design and source of truth for scope.
- Read: `k3s-ansible/inventory.yml`
  Expected node IPs and Ansible user.
- Read: `k3s-ansible/host_vars/*.yml`
  Expected node role intent and per-node k3s role arguments.
- Read: `k3s-ansible/scripts/verify-cluster.sh`
  Existing cluster verification script and checks to reuse where safe.
- Read: `.codex/hooks/cluster-session-start.sh`
  Existing lightweight session health pattern.
- Create: `reports/2026-07-12-homelab-health-access.md`
  Final investigation report with evidence, issue classification, fixes, and remaining risks.
- Modify only if evidence requires it: repo files listed by the issue classification step.

## Task 1: Access Baseline

**Files:**
- Read: `k3s-ansible/inventory.yml`
- Read: `k3s-ansible/host_vars/*.yml`
- Create: `reports/2026-07-12-homelab-health-access.md`

**Interfaces:**
- Consumes: approved design constraints from `docs/superpowers/specs/2026-07-12-homelab-health-access-design.md`
- Produces: access evidence table in `reports/2026-07-12-homelab-health-access.md`

- [ ] **Step 1: Confirm repo and worktree state**

Run:

```bash
pwd
git status --short
git branch --show-current
```

Expected:

```text
/home/benkim0414/workspace/homelab/.worktrees/design-homelab-health-investigation
docs/homelab-health-investigation
```

`git status --short` may be empty or may show only files created by this plan.

- [ ] **Step 2: Extract expected node inventory**

Run:

```bash
sed -n '1,90p' k3s-ansible/inventory.yml
for file in k3s-ansible/host_vars/*.yml; do printf '\n# %s\n' "$file"; sed -n '1,80p' "$file"; done
```

Expected evidence to record:

```text
192.168.0.11 rpi5-8gb-crucial-p3-plus-500gb server/control-plane
192.168.0.12 rpi5-8gb-crucial-bx500-500gb server/control-plane
192.168.0.13 rpi5-8gb-samsung-980-500gb server/control-plane
192.168.0.14 rpi5-8gb-rpi-256gb agent/worker
ansible_user pi
```

- [ ] **Step 3: Verify local SSH permission baseline**

Run:

```bash
stat -c '%A %U:%G %n' ~/.ssh ~/.ssh/config ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub ~/.ssh/known_hosts
readlink -f ~/.ssh/config
ssh -F ~/.ssh/config -G github.com >/tmp/homelab-ssh-explicit.out
ssh -G github.com >/tmp/homelab-ssh-global.out
```

Expected:

```text
~/.ssh is mode drwx------
~/.ssh/id_ed25519 is mode -rw-------
~/.ssh/id_ed25519.pub is mode -rw-r--r--
~/.ssh/known_hosts is not world-writable
explicit -F ~/.ssh/config parse succeeds
plain global ssh parse may fail inside Codex if system ownership is namespace-mapped
```

If `ssh -G github.com` fails but `ssh -F ~/.ssh/config -G github.com` succeeds, classify it as local Codex/global-config diagnostic, not a Pi node failure.

- [ ] **Step 4: Verify access-baseline SSH hostnames with explicit config**

Read-only hostname probes are permitted for access-baseline verification even
when the cluster is healthy. Do not run any state-changing SSH command without
supporting cluster evidence and explicit approval.

Run after network approval:

```bash
for ip in 192.168.0.11 192.168.0.12 192.168.0.13 192.168.0.14; do
  ssh -F ~/.ssh/config -i ~/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=5 "pi@$ip" hostname
done
```

Expected:

```text
rpi5-8gb-crucial-p3-plus-500gb
rpi5-8gb-crucial-bx500-500gb
rpi5-8gb-samsung-980-500gb
rpi5-8gb-rpi-256gb
```

If the command is blocked by sandbox networking, rerun with escalated network approval. If it fails with authentication errors, record the exact failure and stop before changing keys.

- [ ] **Step 5: Start the report**

Create `reports/2026-07-12-homelab-health-access.md` with:

```markdown
# Homelab Health And Access Report

Date: 2026-07-12

## Scope

GitOps-first cluster health and local access investigation. Read-only SSH
hostname probes verify the access baseline; other direct SSH is limited to
targeted read-only node probes unless supporting evidence and a separate
live-change approval are granted.

## Access Baseline

| Check | Result | Evidence |
| --- | --- | --- |
| Expected inventory | pending | pending |
| Explicit SSH config parse | pending | pending |
| Global SSH config parse | pending | pending |
| Node SSH hostnames | pending | pending |

## Cluster Health

Pending.

## Findings

Pending.

## Fixes Applied

Pending.

## Remaining Risks

Pending.
```

- [ ] **Step 6: Commit access baseline report skeleton**

Run:

```bash
git add reports/2026-07-12-homelab-health-access.md
git diff --cached -- reports/2026-07-12-homelab-health-access.md
git commit -m "docs(cluster): start health access report"
```

Expected: commit succeeds with only the report file staged.

## Task 2: Cluster Health Collection

**Files:**
- Modify: `reports/2026-07-12-homelab-health-access.md`

**Interfaces:**
- Consumes: access evidence table from Task 1
- Produces: normalized cluster health section with node, metrics, pod, event, ArgoCD, and Grafana evidence

- [ ] **Step 1: Collect Kubernetes node state**

Use Kubernetes MCP tools:

```text
mcp__kubernetes.resources_list(apiVersion="v1", kind="Node")
mcp__kubernetes.nodes_top()
```

Expected evidence:

```text
4 nodes present
.11, .12, .13 are control-plane/etcd/master
.14 has no control-plane role
all nodes Ready
all nodes report v1.31.12+k3s1 unless live state differs
```

- [ ] **Step 2: Collect non-running pod state**

Use Kubernetes MCP:

```text
mcp__kubernetes.resources_list(apiVersion="v1", kind="Pod", fieldSelector="status.phase!=Running")
```

Classify each result:

```text
Completed backup job pod: observe-only
Completed helm-install pod: observe-only
Failed/Evicted/Unknown/Pending pod: finding
CrashLoopBackOff is not returned by phase!=Running; inspect running pods separately if symptoms suggest it
```

- [ ] **Step 3: Collect warning events if kubectl is available**

Run:

```bash
kubectl get events --all-namespaces --field-selector type=Warning --sort-by=.lastTimestamp | tail -50
```

Expected:

```text
Recent warnings are either empty or concrete symptoms to classify.
```

If `kubectl` is unavailable or kubeconfig fails, record that as local tooling status and continue with MCP evidence.

- [ ] **Step 4: Collect ArgoCD application state if tool is available**

Use ArgoCD MCP tools if loaded or discoverable through `tool_search`. Capture:

```text
application name
sync status
health status
message or condition summary
```

Expected classification:

```text
Synced/Healthy: observe-only
OutOfSync with expected ignored differences: observe-only if documented
OutOfSync/Degraded/Progressing without documented reason: finding
```

- [ ] **Step 5: Collect Grafana alert state if tool is available**

Use Grafana MCP tools if loaded or discoverable through `tool_search`. Capture:

```text
firing alerts
recent incidents
relevant datasource query failures
```

Expected classification:

```text
No firing alerts: observe-only
Firing alert mapped to a known transient condition: observe-only with note
Firing alert mapped to node/app/storage/network issue: finding
```

- [ ] **Step 6: Update report cluster health section**

Edit `reports/2026-07-12-homelab-health-access.md` so `## Cluster Health` contains:

```markdown
## Cluster Health

| Area | Result | Evidence |
| --- | --- | --- |
| Kubernetes nodes | pending | pending |
| Node metrics | pending | pending |
| Non-running pods | pending | pending |
| Warning events | pending | pending |
| ArgoCD apps | pending | pending |
| Grafana alerts | pending | pending |
```

Replace `pending` with actual results from Steps 1-5.

- [ ] **Step 7: Commit health evidence**

Run:

```bash
git add reports/2026-07-12-homelab-health-access.md
git diff --cached -- reports/2026-07-12-homelab-health-access.md
git commit -m "docs(cluster): record health evidence"
```

Expected: commit contains only the report update.

## Task 3: Issue Classification And Fix Decision

**Files:**
- Modify: `reports/2026-07-12-homelab-health-access.md`
- Modify only if evidence requires it: exact repo files that own durable fixes

**Interfaces:**
- Consumes: cluster health evidence from Task 2
- Produces: issue list with one of `repo fix`, `manual recovery`, or `observe-only`

- [ ] **Step 1: Build the issue table**

Update the report `## Findings` section with this table:

```markdown
## Findings

| Severity | Component | Finding | Classification | Evidence | Next Action |
| --- | --- | --- | --- | --- | --- |
| info | access | Explicit SSH config path works or failed | observe-only | pending | pending |
| info | cluster | Expected node roles match or differ | observe-only | pending | pending |
```

Replace or add rows based on actual evidence.

- [ ] **Step 2: Classify access problems**

Use these rules:

```text
Explicit SSH config succeeds and all hostnames respond: observe-only
Global ssh parse fails only inside Codex: observe-only, document namespace ownership difference
Key mode is too open: repo fix is not applicable; manual local chmod was already used, document as local environment fix
Remote auth fails for a node: manual recovery, ask before changing authorized_keys
Remote host key changed: manual recovery, ask before modifying known_hosts
```

- [ ] **Step 3: Classify node role drift**

Use these rules:

```text
Live .11/.12/.13 control-plane and .14 worker matches host_vars: observe-only
README prose contradicts host_vars but live state matches host_vars: repo documentation fix
Inventory contradicts live state: repo fix if inventory is stale, manual recovery if node is actually misjoined
```

- [ ] **Step 4: Classify workload health**

Use these rules:

```text
Completed CronJob or Helm install pod: observe-only
Failed Job for backup: repo fix if schedule/config is wrong, manual recovery if one-off rerun is needed
Pending pod due resource/taint/affinity: repo fix in app values/manifests
Evicted pod due pressure: inspect node metrics; repo fix if limits/requests are wrong, manual recovery if disk/node is unhealthy
Degraded ArgoCD app: repo fix in owning app directory unless live-only drift is proven
Firing Grafana alert: map to app, node, storage, or network and classify by owner
```

- [ ] **Step 5: Decide whether SSH fallback is needed**

Use this decision table:

```text
All nodes Ready, metrics normal, no failed workload symptoms: no SSH fallback
Node NotReady or metrics missing: SSH fallback probe for service status and journal
DiskPressure/MemoryPressure/PIDPressure: SSH fallback probe for df, free, systemctl, journal
Specific k3s/k3s-agent service suspicion: SSH fallback probe for systemctl status
No node-local symptom: do not SSH
```

- [ ] **Step 6: Commit classification**

Run:

```bash
git add reports/2026-07-12-homelab-health-access.md
git diff --cached -- reports/2026-07-12-homelab-health-access.md
git commit -m "docs(cluster): classify health findings"
```

Expected: commit contains only classification/report updates unless a repo fix is clearly needed and included as a separate commit in Task 4.

## Task 4: Apply Durable Fixes Or Approved Live Probes

**Files:**
- Modify: exact owner files identified in Task 3
- Modify: `reports/2026-07-12-homelab-health-access.md`

**Interfaces:**
- Consumes: classified findings from Task 3
- Produces: applied fixes or explicitly documented no-op decision

- [ ] **Step 1: If the only issue is stale README node-role prose, fix docs**

Modify `k3s-ansible/README.md` so the node table and role descriptions match live and `host_vars` intent:

```text
192.168.0.11 control plane / etcd
192.168.0.12 control plane / etcd
192.168.0.13 control plane / etcd
192.168.0.14 worker / agent
```

Do not change inventory or host_vars for this case.

- [ ] **Step 2: If an app issue is found, modify the owning GitOps files**

For each app finding, identify the owner:

```text
argocd/apps/<app>.yaml owns source, sync policy, ignoreDifferences
<app>/values.yaml owns Helm values
<app>/*.yaml owns raw manifests included by the ArgoCD Application
```

Make the smallest repo change that addresses the finding. Do not use `kubectl edit` or live patches for Git-managed resources.

- [ ] **Step 3: If SSH fallback is needed, run read-only probes**

Run after network approval, substituting the affected IP and expected service:

```bash
ssh -F ~/.ssh/config -i ~/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=5 pi@192.168.0.X 'hostname; uptime; free -h; df -h / /var/lib/rancher 2>/dev/null || df -h /; systemctl is-active k3s 2>/dev/null || systemctl is-active k3s-agent 2>/dev/null; systemctl --no-pager --full status k3s 2>/dev/null | sed -n "1,35p"; systemctl --no-pager --full status k3s-agent 2>/dev/null | sed -n "1,35p"'
```

Expected:

```text
hostname matches target
disk and memory are not exhausted
expected k3s or k3s-agent service is active
```

If the probe identifies a needed restart, file edit, package action, or deletion, stop and request a separate approval with the exact command and reason.

- [ ] **Step 4: Verify any repo fix**

Run the narrowest applicable command:

```bash
git diff --check
```

For README-only fixes, expected:

```text
no output
```

For manifest or values fixes, also run a relevant YAML check if available:

```bash
python - path/to/changed.yaml <<'PY'
import sys
import yaml

for path in sys.argv[1:]:
    with open(path) as f:
        list(yaml.safe_load_all(f))
    print(f"ok {path}")
PY
```

Expected:

```text
ok path/to/changed.yaml
```

- [ ] **Step 5: Update report fixes section**

Update `## Fixes Applied` with:

```markdown
## Fixes Applied

| Type | Target | Change | Verification |
| --- | --- | --- | --- |
| repo/manual/none | pending | pending | pending |
```

Use `none` when evidence shows no fix is required.

- [ ] **Step 6: Commit each durable repo fix separately**

For README role-doc correction:

```bash
git add k3s-ansible/README.md reports/2026-07-12-homelab-health-access.md
git diff --cached
git commit -m "docs(k3s): align node role documentation"
```

For app fixes, choose the concrete scope:

```bash
git add argocd/apps/<app>.yaml <app>/values.yaml reports/2026-07-12-homelab-health-access.md
git diff --cached
git commit -m "fix(<app>): describe concrete health fix"
```

If no repo fix is needed:

```bash
git add reports/2026-07-12-homelab-health-access.md
git diff --cached -- reports/2026-07-12-homelab-health-access.md
git commit -m "docs(cluster): record no durable fixes needed"
```

## Task 5: Final Verification And Handoff

**Files:**
- Modify: `reports/2026-07-12-homelab-health-access.md`

**Interfaces:**
- Consumes: all evidence and fixes from Tasks 1-4
- Produces: final report and concise user handoff

- [ ] **Step 1: Run final read-only verification**

Use Kubernetes MCP:

```text
mcp__kubernetes.resources_list(apiVersion="v1", kind="Node")
mcp__kubernetes.nodes_top()
mcp__kubernetes.resources_list(apiVersion="v1", kind="Pod", fieldSelector="status.phase!=Running")
```

Run local checks:

```bash
ssh -F ~/.ssh/config -G github.com >/tmp/homelab-final-ssh-explicit.out
git status --short
git log --oneline "$(git merge-base main HEAD)"..HEAD
```

Expected:

```text
explicit SSH config parses
cluster nodes remain Ready unless an active finding explains otherwise
git status is clean after final commit
branch commits show design, plan, report, and any fixes
```

- [ ] **Step 2: Fill remaining risks**

Update `## Remaining Risks` with one of:

```markdown
## Remaining Risks

- None found in the read-only checks.
```

or concrete risks:

```markdown
## Remaining Risks

- `<component>` still needs `<action>` because `<evidence>`.
```

- [ ] **Step 3: Commit final report update**

Run:

```bash
git add reports/2026-07-12-homelab-health-access.md
git diff --cached -- reports/2026-07-12-homelab-health-access.md
git commit -m "docs(cluster): finalize health access report"
```

Expected: commit succeeds or there is nothing to commit because the final update was included in Task 4.

- [ ] **Step 4: Final response**

Report:

```text
Spec: docs/superpowers/specs/2026-07-12-homelab-health-access-design.md
Plan: docs/superpowers/plans/2026-07-12-homelab-health-access.md
Report: reports/2026-07-12-homelab-health-access.md
Access result: <summary>
Cluster result: <summary>
Fixes: <summary>
Remaining risks: <summary>
Verification: <commands/tools used>
```
