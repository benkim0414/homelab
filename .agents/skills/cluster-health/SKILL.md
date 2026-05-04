---
name: cluster-health
description: Run a structured cluster health check for this homelab using the configured Kubernetes, Grafana, and ArgoCD MCP servers. Use when the user asks for cluster health, diagnostics, alerts, restarts, degraded apps, or recent error review.
---

# Cluster Health

Run a structured cluster health check using MCP tools. Execute each step in
order, then produce a final report.

## Steps

### 1. Nodes

- Call `mcp__kubernetes__nodes_top` to get CPU and memory usage per node.
- Call `mcp__kubernetes__resources_list` with `kind=Node` to retrieve node
  conditions.
- For each node, check conditions: Ready, MemoryPressure, DiskPressure,
  PIDPressure.
- Flag any node where Ready is false or any pressure condition is true.

### 2. Pod restarts

- Call `mcp__kubernetes__pods_list` for every namespace, or use a wildcard
  namespace if supported.
- Surface any container where `restartCount > 5` or pod phase is `Failed`.
- Surface any container in `CrashLoopBackOff` state.

### 3. PVCs

- Call `mcp__kubernetes__resources_list` with `kind=PersistentVolumeClaim`
  across all namespaces.
- Flag any PVC not in `Bound` phase.

### 4. ArgoCD applications

- Call `mcp__argocd__list_applications`.
- Flag any application with `sync_status=OutOfSync` or
  `health_status=Degraded`.

### 5. Active alerts

- Call `mcp__grafana__list_alert_groups`.
- If Grafana OnCall is unavailable or returns a settings/API error, call
  `mcp__grafana__alerting_manage_rules` with `operation=list` and
  `states=["firing"]` as the fallback.
- List any alert group that has firing alerts. Include alert name, severity,
  and labels.

### 6. Recent errors

- Call `mcp__grafana__query_loki_logs` with:
  - query: `{namespace=~".+"} | json | level="error"`
  - time range: last 15 minutes
- Summarize error volume by namespace.
- Show the top 5 most frequent error messages.

## Output format

Produce a structured report with one section per category. Use a status badge
at the start of each section:

- `[HEALTHY]` for no issues found
- `[WARNING]` for degraded but not critical
- `[CRITICAL]` for immediate action required

End the report with an **Action Items** section listing concrete next steps for
anything not healthy. If everything is healthy, state that explicitly.
