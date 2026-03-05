Run a structured cluster health check using MCP tools. Execute each step in order, then produce a final report.

## Steps

### 1. Nodes
- Call `mcp__kubernetes__nodes_top` to get CPU/memory usage per node.
- Call `mcp__kubernetes__resources_list` with `kind=Node` to retrieve node conditions.
- For each node, check conditions: Ready, MemoryPressure, DiskPressure, PIDPressure.
- Flag any node where Ready=False or any pressure condition is True.

### 2. Pod restarts
- Call `mcp__kubernetes__pods_list` for every namespace (or use a wildcard namespace if supported).
- Surface any container where `restartCount > 5` or pod phase is `Failed`.
- Surface any container in `CrashLoopBackOff` state.

### 3. PVCs
- Call `mcp__kubernetes__resources_list` with `kind=PersistentVolumeClaim` across all namespaces.
- Flag any PVC not in `Bound` phase.

### 4. ArgoCD applications
- Call `mcp__argocd__list_applications`.
- Flag any application with `sync_status=OutOfSync` or `health_status=Degraded`.

### 5. Active alerts
- Call `mcp__grafana__list_alert_groups`.
- List any alert group that has firing alerts. Include alert name, severity, and labels.

### 6. Recent errors (last 15 minutes)
- Call `mcp__grafana__query_loki_logs` with:
  - query: `{namespace=~".+"} | json | level="error"`
  - time range: last 15 minutes
- Summarize error volume by namespace. Show the top 5 most frequent error messages.

## Output format

Produce a structured report with one section per category. Use a status badge at the start of each section:

- `[HEALTHY]` — no issues found
- `[WARNING]` — degraded but not critical
- `[CRITICAL]` — immediate action required

End the report with an **Action Items** section listing concrete next steps for anything not HEALTHY. If everything is healthy, state that explicitly.

Example structure:
```
## Cluster Health Report — <timestamp>

### Nodes [HEALTHY|WARNING|CRITICAL]
...

### Pod Restarts [HEALTHY|WARNING|CRITICAL]
...

### PVCs [HEALTHY|WARNING|CRITICAL]
...

### ArgoCD Apps [HEALTHY|WARNING|CRITICAL]
...

### Active Alerts [HEALTHY|WARNING|CRITICAL]
...

### Recent Errors [HEALTHY|WARNING|CRITICAL]
...

## Action Items
1. ...
```
