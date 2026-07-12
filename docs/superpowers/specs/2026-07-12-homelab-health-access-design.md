# Homelab Health And Access Investigation Design

## Purpose

Investigate and fix homelab cluster issues using a GitOps-first workflow. The
scope includes cluster health and local access reliability. Read-only SSH
hostname probes are permitted to verify the access baseline; other direct SSH
inspection is used only when read-only cluster evidence points to a node-local
problem. State-changing SSH actions require that evidence and separate approval.

## Success Criteria

- Codex can verify the intended SSH route to all four Raspberry Pi nodes.
- Local SSH configuration problems are separated from remote node failures.
- Kubernetes health is summarized from live node, pod, and metrics state.
- Completed backup and Helm job pods are not treated as active failures.
- ArgoCD and Grafana findings are included when their configured tools are
  available.
- Durable fixes are made in this repository where possible.
- Any live mutation is explicitly approved, targeted, and documented.

## Architecture

The workflow has three layers.

Layer 1 is local access validation. It checks `~/.ssh` permissions, explicit
SSH config parsing, key or agent availability, and node hostname access through
`ssh -F ~/.ssh/config`. Plain global SSH config parsing is checked separately
because this Codex environment can see different ownership mappings for system
paths than the user's terminal.

Layer 2 is cluster inspection through configured control-plane integrations:
Kubernetes first, then ArgoCD and Grafana when available. This layer identifies
node readiness, resource pressure, pod failures, app health, sync status, and
alerts without changing live state.

Layer 3 is node-local SSH inspection. Read-only hostname probes are part of
Layer 1 access-baseline verification. Other node-local inspection is used only
after Layer 2 gives a specific reason to inspect a host, such as NotReady
status, pressure, missing metrics, failed system pods, disk pressure, or a
suspected service failure. State-changing SSH actions require that evidence and
separate approval.

## Components

### Access Verifier

The access verifier confirms that Codex can use the intended SSH path without
depending on global SSH config. It checks:

- `~/.ssh` directory and key file permissions.
- Explicit config parsing with `ssh -F ~/.ssh/config -G`.
- Key or agent usability with `BatchMode=yes`.
- Hostname responses from `192.168.0.11`, `.12`, `.13`, and `.14`.

### Cluster Health Collector

The health collector reads Kubernetes node status, node metrics, unhealthy pods,
recent warning events, and relevant workload state. It classifies non-running
pods as benign completed jobs, failed jobs, pending pods, crash loops, evictions,
or unknown states.

### GitOps Drift And Fix Mapper

The mapper compares live findings against repository intent, especially:

- `k3s-ansible/inventory.yml`
- `k3s-ansible/host_vars/*.yml`
- `argocd/apps/*.yaml`
- existing reports and documented gotchas

Each finding is classified as a repository fix, manual recovery, or observe-only
condition.

### SSH Fallback Probe

The SSH fallback probe runs targeted node commands only when evidence supports
it. It is separate from the access-baseline hostname probes, which are always
read-only. Initial fallback probes are read-only, such as service status, disk
and memory pressure, k3s or k3s-agent status, and recent journal lines. Sudo
changes, restarts, package operations, and file edits require both the
supporting evidence and a separate approval.

## Data Flow

The workflow starts by validating local access behavior. Explicit SSH config is
the authoritative Codex path, while global SSH config is a separate diagnostic.

Next, live cluster state is collected from Kubernetes and optional ArgoCD or
Grafana tools. Findings are normalized into an issue list containing evidence,
severity, affected component, and likely fix location.

Each issue is then mapped back to repository intent. If the repo is stale or
incorrect, the durable output is a branch change plus verification. If live
state is healthy or transient, the issue is reported as observe-only. If the
cluster needs recovery that Git cannot provide quickly, the next step is an
explicitly approved live operation.

## Error Handling

Sandbox and network failures are not treated as node failures. SSH errors are
classified as sandbox restriction, key or agent problem, host-key problem,
config parse problem, remote authentication failure, or remote service failure.

Kubernetes API failures are classified as local kubeconfig/tooling failure or
cluster control-plane failure. Any destructive or state-changing action is held
behind a separate approval.

## Verification Plan

- Verify explicit SSH config parses.
- Verify all four Pi nodes respond to hostname probes when network access is
  approved.
- Verify Kubernetes reports the expected four nodes, roles, versions, and
  readiness.
- Separate completed jobs from actual pod failures.
- Include ArgoCD and Grafana findings when configured tools are callable.
- For any repository fix, inspect the diff and run the narrowest relevant
  validation command.
- For any live operation, record the command, target, reason, and result.

## Out Of Scope

- Rebuilding the cluster from scratch.
- Broad manual drift from Git-managed resources.
- Persistent direct SSH access changes beyond the agreed access verifier unless
  approved separately.
- Destructive node, Kubernetes, GitHub, or storage operations without explicit
  approval.
