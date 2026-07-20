# Mac Pro K3s Worker VM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `macpro-vm-16gb-samsung-980-120gb` at `192.168.0.21` as a compute-only Debian 12 K3s agent node managed by `k3s-ansible`.

**Architecture:** The Proxmox VM is created manually, then this repo manages cluster membership, node labels, and verification through `k3s-ansible`. The node joins as an agent only, gets explicit opt-in scheduling labels, and does not get the Longhorn default-disk label.

**Tech Stack:** Proxmox VE 9.2, Debian 12 Bookworm VM, K3s `v1.31.12+k3s1`, k3s-ansible, Bash preflight/verification scripts, Kubernetes/Longhorn validation.

## Global Constraints

- VM identity: `macpro-vm-16gb-samsung-980-120gb`.
- VM IP: `192.168.0.21`.
- VM spec: `4 vCPU`, `16 GiB RAM`, `120 GiB disk`.
- VM OS: Debian 12 Bookworm.
- VM network: Proxmox `vmbr0` on `192.168.0.0/24`.
- K3s role: agent only; do not add it to the `server` inventory group.
- Storage role: compute-only; do not add `node.longhorn.io/create-default-disk=true`.
- Scheduling policy: opt-in through labels; do not add a broad taint in the first rollout.
- First workload migration target: OpenClaw, after the worker VM is joined and verified.
- Out of scope: arr-stack migration, Longhorn storage expansion, Terraform/OpenTofu, Pi control-plane role changes.
- Known pre-existing issue: ArgoCD may report `alloy` as `Progressing`; do not treat that as caused by this rollout unless it changes during implementation.

---

## File Structure

- `k3s-ansible/inventory.yml`: add the Mac Pro VM under `agent.hosts`, and document the mixed Pi/VM assumptions.
- `k3s-ansible/host_vars/192.168.0.21.yml`: set Mac Pro VM node labels through `extra_agent_args` without enabling Longhorn disk creation.
- `k3s-ansible/scripts/preflight-check.sh`: replace hardcoded Pi-only arrays with per-node records that include IP, hostname, SSH user, required interface, and whether Raspberry Pi cgroup boot parameter repair applies.
- `k3s-ansible/scripts/verify-cluster.sh`: update expected node and speaker counts from 4 to 5, add Mac Pro label checks, and verify the new node is not a control-plane node.
- `k3s-ansible/README.md`: document the new topology, VM spec, manual Proxmox provisioning boundary, join flow, labels, and validation.
- `docs/superpowers/specs/2026-07-20-macpro-k3s-vm-design.md`: read-only origin design; do not modify unless implementation discovers a direct spec contradiction.

---

### Task 1: Add Mac Pro VM To K3s Inventory

**Files:**
- Modify: `k3s-ansible/inventory.yml`
- Create: `k3s-ansible/host_vars/192.168.0.21.yml`

**Interfaces:**
- Consumes: existing `agent_config_yaml` from `k3s-ansible/inventory.yml`.
- Produces: a k3s-ansible inventory where `192.168.0.21` is an agent node with stable scheduling labels.

- [ ] **Step 1: Inspect current inventory and host var pattern**

Run:

```bash
sed -n '1,120p' k3s-ansible/inventory.yml
for file in k3s-ansible/host_vars/*.yml; do
  printf '\n# %s\n' "$file"
  sed -n '1,80p' "$file"
done
```

Expected: `192.168.0.11`, `.12`, and `.13` are under `server`; `.14` is under `agent`; Pi host vars use `extra_server_args` or `extra_agent_args`.

- [ ] **Step 2: Add the Mac Pro VM to the agent group**

Modify the `agent.hosts` block in `k3s-ansible/inventory.yml` to include:

```yaml
    agent:
      hosts:
        192.168.0.14:    # rpi5-8gb-rpi-256gb (agent - no etcd)
        192.168.0.21:    # macpro-vm-16gb-samsung-980-120gb (agent - compute-only amd64 VM)
```

Keep `ansible_user: pi` as the group default for existing Pi nodes. The Mac Pro VM will override this in host vars during Task 2 if the implementation confirms k3s-ansible supports `ansible_user` from host vars with this inventory shape.

- [ ] **Step 3: Create Mac Pro VM host vars**

Create `k3s-ansible/host_vars/192.168.0.21.yml` with:

```yaml
---
# Per-node overrides for macpro-vm-16gb-samsung-980-120gb (.21)
#
# Proxmox VM on pve-macpro. Compute-only K3s agent for selected amd64
# workloads. Intentionally do not add node.longhorn.io/create-default-disk=true;
# the first rollout must not add this node to Longhorn storage scheduling.
ansible_user: benkim0414
extra_agent_args: >-
  --node-label homelab/host=macpro
  --node-label homelab/node-class=vm
  --node-label homelab/workload-tier=heavy
```

- [ ] **Step 4: Validate YAML syntax**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file("k3s-ansible/inventory.yml"); Dir["k3s-ansible/host_vars/*.yml"].each { |f| YAML.load_file(f) }; puts "yaml-ok"'
```

Expected:

```text
yaml-ok
```

- [ ] **Step 5: Verify no Longhorn disk label is present for `.21`**

Run:

```bash
if rg -n '192\.168\.0\.21|node\.longhorn\.io/create-default-disk' k3s-ansible/inventory.yml k3s-ansible/host_vars/192.168.0.21.yml; then
  true
fi
```

Expected: output may show `192.168.0.21`, but `node.longhorn.io/create-default-disk` must not appear in `k3s-ansible/host_vars/192.168.0.21.yml`.

- [ ] **Step 6: Commit inventory change**

Run:

```bash
git add k3s-ansible/inventory.yml k3s-ansible/host_vars/192.168.0.21.yml
git diff --cached
git commit -m "chore(k3s-ansible): add macpro worker inventory"
```

Expected: commit includes only the inventory and `.21` host var file.

---

### Task 2: Generalize Preflight For Mixed Pi And VM Nodes

**Files:**
- Modify: `k3s-ansible/scripts/preflight-check.sh`

**Interfaces:**
- Consumes: node identities from Task 1.
- Produces: a preflight script that checks all five nodes without applying Raspberry Pi boot-cmdline edits to the Debian VM.

- [ ] **Step 1: Capture current hardcoded assumptions**

Run:

```bash
sed -n '1,180p' k3s-ansible/scripts/preflight-check.sh
```

Expected current assumptions:

```text
NODES=(...)
NAMES=(...)
SSH_USER="pi"
CMDLINE_FILE="/boot/firmware/cmdline.txt"
eth0 interface exists
```

- [ ] **Step 2: Replace the node arrays with pipe-delimited records**

Modify the top of `k3s-ansible/scripts/preflight-check.sh` so the node metadata block is:

```bash
# Format: ip|name|ssh_user|required_interface|pi_cgroup_check
NODES=(
    "192.168.0.11|rpi5-8gb-crucial-p3-plus-500gb|pi|eth0|true"
    "192.168.0.12|rpi5-8gb-crucial-bx500-500gb|pi|eth0|true"
    "192.168.0.13|rpi5-8gb-rpi-512gb|pi|eth0|true"
    "192.168.0.14|rpi5-8gb-rpi-256gb|pi|eth0|true"
    "192.168.0.21|macpro-vm-16gb-samsung-980-120gb|benkim0414|ens18|false"
)
```

Keep:

```bash
SSH_OPTS="-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
CGROUP_PARAMS="cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory"
CMDLINE_FILE="/boot/firmware/cmdline.txt"
MIN_RAM_MB=3000
MIN_DISK_MB=10000
```

- [ ] **Step 3: Update the loop to parse per-node fields**

Replace:

```bash
for i in "${!NODES[@]}"; do
    node="${NODES[$i]}"
    name="${NAMES[$i]}"
```

with:

```bash
for record in "${NODES[@]}"; do
    IFS='|' read -r node name ssh_user required_interface pi_cgroup_check <<< "$record"
```

- [ ] **Step 4: Use per-node SSH user everywhere**

Replace every occurrence of:

```bash
"$SSH_USER@$node"
```

with:

```bash
"$ssh_user@$node"
```

Do not keep the old global `SSH_USER` variable.

- [ ] **Step 5: Skip Raspberry Pi boot cmdline repair for the Mac Pro VM**

Wrap the existing cgroup parameter block with:

```bash
    # --- Raspberry Pi cgroup parameters ---
    if [[ "$pi_cgroup_check" == "true" ]]; then
        cmdline=$(ssh $SSH_OPTS "$ssh_user@$node" "cat $CMDLINE_FILE 2>/dev/null || echo ''")
        missing_params=""
        for param in $CGROUP_PARAMS; do
            if ! echo "$cmdline" | grep -q "$param"; then
                missing_params="$missing_params $param"
            fi
        done

        if [[ -n "$missing_params" ]]; then
            warn "$name: Missing cgroup params:$missing_params"
            info "$name: Adding cgroup params to $CMDLINE_FILE"
            ssh $SSH_OPTS "$ssh_user@$node" "sudo sed -i 's/$/ ${missing_params## }/' $CMDLINE_FILE"
            warn "$name: REBOOT REQUIRED for cgroup changes to take effect"
            REBOOT_NEEDED=true
        else
            ok "$name: cgroup params present"
        fi
    else
        ok "$name: Raspberry Pi cgroup cmdline check skipped"
    fi
```

Remove the old unguarded cgroup block.

- [ ] **Step 6: Use the per-node interface check**

Replace:

```bash
    # --- eth0 interface ---
    if ssh $SSH_OPTS "$SSH_USER@$node" "ip link show eth0" &>/dev/null; then
        ok "$name: eth0 interface exists"
    else
        error "$name: eth0 interface not found"
        FAILED=true
    fi
```

with:

```bash
    # --- required network interface ---
    if ssh $SSH_OPTS "$ssh_user@$node" "ip link show $required_interface" &>/dev/null; then
        ok "$name: $required_interface interface exists"
    else
        error "$name: $required_interface interface not found"
        FAILED=true
    fi
```

- [ ] **Step 7: Run shell syntax verification**

Run:

```bash
bash -n k3s-ansible/scripts/preflight-check.sh
```

Expected: exit code `0`, no output.

- [ ] **Step 8: Run dry inspection**

Run:

```bash
rg -n 'SSH_USER|eth0|ens18|192\.168\.0\.21|pi_cgroup_check|macpro-vm' k3s-ansible/scripts/preflight-check.sh
```

Expected:

- `SSH_USER` does not appear.
- `eth0` appears only in Pi node records or descriptive text.
- `ens18`, `192.168.0.21`, and `macpro-vm-16gb-samsung-980-120gb` appear in the Mac Pro VM record.

- [ ] **Step 9: Commit preflight script change**

Run:

```bash
git add k3s-ansible/scripts/preflight-check.sh
git diff --cached
git commit -m "fix(k3s-ansible): support vm preflight checks"
```

Expected: commit includes only `k3s-ansible/scripts/preflight-check.sh`.

---

### Task 3: Update Cluster Verification For Five Nodes

**Files:**
- Modify: `k3s-ansible/scripts/verify-cluster.sh`

**Interfaces:**
- Consumes: node identity and labels from Tasks 1-2.
- Produces: verification that expects five nodes, three control-plane nodes, Mac Pro VM labels, and no Mac Pro control-plane role.

- [ ] **Step 1: Replace hardcoded expected counts with named constants**

Near the top of `k3s-ansible/scripts/verify-cluster.sh`, after `FIRST_SERVER`, add:

```bash
EXPECTED_NODES=5
EXPECTED_CONTROL_PLANES=3
EXPECTED_KUBE_VIP_PODS=3
EXPECTED_METALLB_SPEAKERS=5
MACPRO_NODE="macpro-vm-16gb-samsung-980-120gb"
```

- [ ] **Step 2: Update node count check**

Replace:

```bash
if [[ $node_count -eq 4 && $ready_count -eq 4 ]]; then
    ok "All 4 nodes are Ready"
else
    fail "Expected 4 Ready nodes, got $ready_count/$node_count"
fi
```

with:

```bash
if [[ $node_count -eq $EXPECTED_NODES && $ready_count -eq $EXPECTED_NODES ]]; then
    ok "All $EXPECTED_NODES nodes are Ready"
else
    fail "Expected $EXPECTED_NODES Ready nodes, got $ready_count/$node_count"
fi
```

- [ ] **Step 3: Update control-plane count check**

Replace the hardcoded `3` checks with:

```bash
if [[ $cp_count -eq $EXPECTED_CONTROL_PLANES ]]; then
    ok "$EXPECTED_CONTROL_PLANES control-plane nodes found"
else
    fail "Expected $EXPECTED_CONTROL_PLANES control-plane nodes, got $cp_count"
fi
```

- [ ] **Step 4: Update kube-vip count check**

Replace the hardcoded kube-vip `3` check with:

```bash
if [[ $kvip_ready -eq $EXPECTED_KUBE_VIP_PODS ]]; then
    ok "$EXPECTED_KUBE_VIP_PODS kube-vip pods running"
else
    fail "Expected $EXPECTED_KUBE_VIP_PODS kube-vip pods, got $kvip_ready running"
fi
```

- [ ] **Step 5: Update MetalLB speaker count check**

Replace the hardcoded MetalLB speaker `4` check with:

```bash
if [[ $mlb_speakers -eq $EXPECTED_METALLB_SPEAKERS ]]; then
    ok "MetalLB speakers running on all $EXPECTED_METALLB_SPEAKERS nodes"
else
    fail "Expected $EXPECTED_METALLB_SPEAKERS MetalLB speakers, got $mlb_speakers"
fi
```

- [ ] **Step 6: Add Mac Pro VM role and label checks**

After `kubectl get nodes -o wide`, add:

```bash
macpro_ready=$(kubectl get node "$MACPRO_NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
macpro_cp_label=$(kubectl get node "$MACPRO_NODE" -o jsonpath='{.metadata.labels.node-role\.kubernetes\.io/control-plane}' 2>/dev/null || echo "")

if [[ "$macpro_ready" == "True" ]]; then
    ok "$MACPRO_NODE is Ready"
else
    fail "$MACPRO_NODE is not Ready"
fi

if [[ -z "$macpro_cp_label" ]]; then
    ok "$MACPRO_NODE is not labeled as control-plane"
else
    fail "$MACPRO_NODE unexpectedly has control-plane label"
fi
```

- [ ] **Step 7: Add Mac Pro opt-in scheduling label checks**

After the existing storage-tier label loop, add:

```bash
header "Mac Pro VM Labels"
declare -A macpro_labels=(
    ["homelab/host"]="macpro"
    ["homelab/node-class"]="vm"
    ["homelab/workload-tier"]="heavy"
)

for key in "${!macpro_labels[@]}"; do
    expected="${macpro_labels[$key]}"
    jsonpath_key="${key//\//\\.}"
    value=$(kubectl get node "$MACPRO_NODE" -o jsonpath="{.metadata.labels.$jsonpath_key}" 2>/dev/null || echo "")
    if [[ "$value" == "$expected" ]]; then
        ok "$MACPRO_NODE: $key=$value"
    else
        fail "$MACPRO_NODE: expected $key=$expected, got '${value:-missing}'"
    fi
done
```

- [ ] **Step 8: Run shell syntax verification**

Run:

```bash
bash -n k3s-ansible/scripts/verify-cluster.sh
```

Expected: exit code `0`, no output.

- [ ] **Step 9: Commit verification script change**

Run:

```bash
git add k3s-ansible/scripts/verify-cluster.sh
git diff --cached
git commit -m "fix(k3s-ansible): verify macpro worker node"
```

Expected: commit includes only `k3s-ansible/scripts/verify-cluster.sh`.

---

### Task 4: Document VM Provisioning And Rollout

**Files:**
- Modify: `k3s-ansible/README.md`

**Interfaces:**
- Consumes: inventory and script behavior from Tasks 1-3.
- Produces: operator-facing instructions for manual VM creation, Ansible join, and validation.

- [ ] **Step 1: Update architecture node table**

In `k3s-ansible/README.md`, update the node table to include:

```markdown
| macpro-vm-16gb-samsung-980-120gb | 192.168.0.21 | Worker / agent       | Proxmox VM, compute-only |
```

Keep the existing four Raspberry Pi rows.

- [ ] **Step 2: Update architecture diagram text**

In the README architecture section, add a worker entry for the Mac Pro VM using ASCII text:

```text
                      +------------------+
                      | macpro-vm-16gb   |  Worker
                      | samsung-980-120gb|  (Proxmox VM, compute-only)
                      |    .0.21         |
                      +------------------+
```

Do not use Unicode box-drawing characters.

- [ ] **Step 3: Add a Mac Pro VM provisioning section**

Add this section after `## Prerequisites`:

```markdown
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
```

- [ ] **Step 4: Add labels documentation**

Add this section after the existing label instructions:

````markdown
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
````

- [ ] **Step 5: Update verification checklist counts**

Update the verification checklist row:

```markdown
| `kubectl get nodes` | 5 nodes Ready (3 control-plane, 2 workers) |
```

Update MetalLB expectation to:

```markdown
| MetalLB pods | 1 controller + 5 speakers |
```

- [ ] **Step 6: Run markdown sanity checks**

Run:

```bash
rg -n '4 nodes|4 speakers|all 4 nodes|Raspberry Pi 5 nodes' k3s-ansible/README.md || true
LC_ALL=C rg -n '[^\x00-\x7F]' k3s-ansible/README.md || true
```

Expected:

- Any remaining `4 nodes` or `4 speakers` references are either historical troubleshooting text or are updated.
- No new non-ASCII characters are introduced by this task.

- [ ] **Step 7: Commit README change**

Run:

```bash
git add k3s-ansible/README.md
git diff --cached
git commit -m "docs(k3s-ansible): document macpro worker rollout"
```

Expected: commit includes only `k3s-ansible/README.md`.

---

### Task 5: Run Pre-Join Validation

**Files:**
- Read: `k3s-ansible/inventory.yml`
- Read: `k3s-ansible/host_vars/192.168.0.21.yml`
- Read: `k3s-ansible/scripts/preflight-check.sh`

**Interfaces:**
- Consumes: repo changes from Tasks 1-4 and a manually created Debian 12 VM.
- Produces: evidence that the VM is reachable and ready for k3s-ansible.

- [ ] **Step 1: Confirm manual VM facts**

From the operator machine, verify SSH:

```bash
ssh benkim0414@192.168.0.21 'hostname -f; ip -br addr; free -h; df -h /; sudo -n true && echo sudo-nopass || echo sudo-prompts'
```

Expected:

- Hostname includes `macpro-vm-16gb-samsung-980-120gb`.
- IP includes `192.168.0.21`.
- Memory is about 16 GiB.
- Root filesystem has enough free space from the 120 GiB disk.

- [ ] **Step 2: Confirm Ansible can parse inventory**

Run from the repo:

```bash
ANSIBLE_LOCAL_TEMP=$PWD/.ansible/tmp \
ANSIBLE_REMOTE_TEMP=/tmp/.ansible-benkim0414/tmp \
ansible-inventory -i k3s-ansible/inventory.yml --list >/tmp/macpro-k3s-inventory.json
```

Expected: command exits `0`.

- [ ] **Step 3: Confirm Ansible resolves `.21` as `benkim0414`**

Run:

```bash
ANSIBLE_LOCAL_TEMP=$PWD/.ansible/tmp \
ANSIBLE_REMOTE_TEMP=/tmp/.ansible-benkim0414/tmp \
ansible-inventory -i k3s-ansible/inventory.yml --host 192.168.0.21
```

Expected output includes:

```json
"ansible_user": "benkim0414"
```

- [ ] **Step 4: Run preflight script**

Run:

```bash
bash k3s-ansible/scripts/preflight-check.sh
```

Expected:

- All five nodes pass SSH, RAM, disk, and interface checks.
- Pi nodes run cgroup cmdline checks.
- Mac Pro VM reports Raspberry Pi cgroup cmdline check skipped.

- [ ] **Step 5: Do not commit validation output**

Run:

```bash
git status --short
```

Expected: no new tracked changes from validation. If `.ansible/` appears, leave it untracked and do not stage it.

---

### Task 6: Join The Mac Pro VM And Verify Cluster State

**Files:**
- Read: `k3s-ansible/inventory.yml`
- Read: `k3s-ansible/scripts/verify-cluster.sh`

**Interfaces:**
- Consumes: preflight success from Task 5.
- Produces: a live K3s agent node named `macpro-vm-16gb-samsung-980-120gb`.

- [ ] **Step 1: Run k3s-ansible from the upstream playbook repo**

Run from the k3s-ansible upstream repo root, not from this homelab repo:

```bash
cd ~/workspace/k3s-ansible
ANSIBLE_LOCAL_TEMP=~/workspace/homelab/.worktrees/macpro-k3s-vm-design/.ansible/tmp \
ANSIBLE_REMOTE_TEMP=/tmp/.ansible-benkim0414/tmp \
ANSIBLE_COLLECTIONS_PATH=~/workspace/homelab/.worktrees/macpro-k3s-vm-design/.ansible/collections \
ansible-playbook playbooks/site.yml \
  -i ~/workspace/homelab/.worktrees/macpro-k3s-vm-design/k3s-ansible/inventory.yml \
  --limit 192.168.0.21
```

Expected:

- Playbook completes successfully.
- Existing server nodes are used for token/API discovery.
- Only `192.168.0.21` is targeted by `--limit`.

- [ ] **Step 2: Verify node readiness**

Run:

```bash
kubectl get nodes -o wide
```

Expected:

```text
macpro-vm-16gb-samsung-980-120gb   Ready   <none>   ...
```

- [ ] **Step 3: Verify node labels**

Run:

```bash
kubectl get node macpro-vm-16gb-samsung-980-120gb \
  -L homelab/host,homelab/node-class,homelab/workload-tier,kubernetes.io/arch
```

Expected:

```text
homelab/host=macpro
homelab/node-class=vm
homelab/workload-tier=heavy
kubernetes.io/arch=amd64
```

- [ ] **Step 4: Verify the node is not control-plane**

Run:

```bash
kubectl get node macpro-vm-16gb-samsung-980-120gb --show-labels | rg 'node-role.kubernetes.io/(control-plane|master)' || true
```

Expected: no output.

- [ ] **Step 5: Verify Longhorn did not add schedulable storage**

Run:

```bash
kubectl -n longhorn-system get nodes.longhorn.io macpro-vm-16gb-samsung-980-120gb -o yaml 2>/dev/null || true
```

Acceptable results:

- No Longhorn node object exists for the Mac Pro VM.
- Or a Longhorn node object exists, but it has no default disk and is not scheduling replicas.

If a schedulable disk appears for the Mac Pro VM, stop and remove Longhorn scheduling from that node before migrating workloads.

- [ ] **Step 6: Run repo verification script**

Run:

```bash
bash ~/workspace/homelab/.worktrees/macpro-k3s-vm-design/k3s-ansible/scripts/verify-cluster.sh
```

Expected:

- 5 nodes Ready.
- 3 control-plane nodes.
- 3 kube-vip pods.
- 5 MetalLB speakers.
- Mac Pro VM labels pass.

---

### Task 7: Prepare OpenClaw Migration As A Separate GitOps Work Item

**Files:**
- Create later: `openclaw/namespace.yaml`
- Create later: `openclaw/values.yaml` or raw manifests based on the actual OpenClaw deployment model
- Create later: `argocd/apps/openclaw.yaml`

**Interfaces:**
- Consumes: a verified Mac Pro worker from Task 6.
- Produces: a scoped follow-up plan for declarative OpenClaw migration, without stopping LXC `101` prematurely.

- [ ] **Step 1: Inventory current OpenClaw LXC**

Run on Proxmox:

```bash
ssh -F ~/.ssh/codex_homelab_config pve-macpro 'sudo pct config 101; sudo pct exec 101 -- systemctl --no-pager --type=service --state=running; sudo pct exec 101 -- ss -ltnp'
```

Expected: output identifies OpenClaw services, listening ports, persistent paths, and whether it uses local-only state.

- [ ] **Step 2: Decide packaging source**

Inspect the OpenClaw install source found in Step 1 and decide whether to package it as:

```text
Helm values + ArgoCD Application
```

or:

```text
Raw Kubernetes manifests + ArgoCD Application
```

Decision rule:

- If OpenClaw has an upstream Helm chart, use the repo's ArgoCD multi-source Helm pattern.
- If it is currently a single container or compose-style service, convert to raw manifests first.

- [ ] **Step 3: Record follow-up scope**

Create a follow-up issue/spec or ask the user before implementation. The follow-up must include:

```text
OpenClaw image/source
required ports
persistent paths
secrets
health endpoint
nodeSelector: homelab/host=macpro
rollback: restart LXC 101
```

- [ ] **Step 4: Keep LXC `101` running until K3s OpenClaw is verified**

Run:

```bash
ssh -F ~/.ssh/codex_homelab_config pve-macpro 'sudo pct status 101'
```

Expected:

```text
status: running
```

Do not stop LXC `101` in this task.

---

## Plan Self-Review

- Spec coverage: The plan covers manual VM boundary, inventory join, labels, compute-only Longhorn policy, script updates, README docs, live join validation, and OpenClaw as the first migration target.
- Placeholder scan: No unfinished markers or unspecified implementation steps are intentionally left in the plan.
- Scope check: OpenClaw packaging is intentionally scoped as a follow-up because the approved design identified that OpenClaw is not currently represented in GitOps and its runtime details must be inventoried from LXC `101` first.
- Type/path consistency: The node identity is consistently `macpro-vm-16gb-samsung-980-120gb` and the IP is consistently `192.168.0.21`.
