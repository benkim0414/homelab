Run a structured security audit of the homelab cluster using MCP tools. Execute each check in order, then produce a final report.

## Checks

### 1. RBAC — cluster-admin bindings
- Call `mcp__kubernetes__resources_list` with `kind=ClusterRoleBinding`.
- For each binding that references `roleRef.name=cluster-admin`, inspect its subjects.
- PASS if all subjects are in the expected set: `system:masters`, or names matching `argocd-*`.
- FAIL for any other subject (user, group, or service account) bound to cluster-admin.

### 2. Pod security contexts
- Call `mcp__kubernetes__pods_list` for every namespace.
- For each container, check:
  - `securityContext.runAsNonRoot` — flag if false or absent
  - `securityContext.runAsUser` — flag if 0 (root)
  - Missing `securityContext` entirely — flag as WARN
- Skip system namespaces (`kube-system`, `kube-public`, `kube-node-lease`) for noise reduction, but note them.

### 3. Resource limits
- From the pod list above, check every container for `resources.limits.cpu` and `resources.limits.memory`.
- Flag containers with missing limits as WARN.
- Group by namespace for readability.

### 4. Secrets exposure in ConfigMaps
- Call `mcp__kubernetes__resources_list` with `kind=ConfigMap` across all namespaces.
- Scan `.data` values for common secret patterns: `password=`, `token=`, `apikey=`, `api_key=`, `secret=`, `passwd=`.
- Flag any match as CRITICAL — these should be SealedSecrets, not ConfigMaps.
- Skip well-known safe ConfigMaps (e.g., `kube-root-ca.crt`).

### 5. SealedSecrets controller health
- Call `mcp__kubernetes__pods_list` for namespace `kube-system`.
- Find the `sealed-secrets-controller` pod.
- PASS if Running with restartCount <= 5.
- WARN if restartCount > 5.
- FAIL if pod is not Running.

### 6. LoadBalancer exposure
- Call `mcp__kubernetes__resources_list` with `kind=Service` across all namespaces.
- Filter to `type=LoadBalancer` services.
- Compare each external IP against the expected inventory:
  - `192.168.0.201` — Immich
  - `192.168.0.202` — ArgoCD
  - `192.168.0.203` — Grafana
  - `192.168.0.204` — Home Assistant
  - `192.168.0.205` — Vaultwarden
- WARN for any service with an IP not in this list; investigate before dismissing.

## Output format

Produce a structured report with one section per check. Use a status badge:

- `[PASS]` — check passed, no issues
- `[WARN]` — potential issue; low urgency but should be tracked
- `[FAIL]` — security issue requiring remediation

End with a **Remediation Steps** section for every FAIL and WARN, with concrete actions.

Example structure:
```
## Security Audit Report — <timestamp>

### 1. RBAC cluster-admin bindings [PASS|WARN|FAIL]
...

### 2. Pod security contexts [PASS|WARN|FAIL]
...

### 3. Resource limits [PASS|WARN|FAIL]
...

### 4. Secrets in ConfigMaps [PASS|WARN|FAIL]
...

### 5. SealedSecrets controller [PASS|WARN|FAIL]
...

### 6. LoadBalancer exposure [PASS|WARN|FAIL]
...

## Remediation Steps
1. ...
```
