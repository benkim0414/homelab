---
name: security-audit
description: Run a structured security audit for this homelab using the configured Kubernetes, Grafana, and ArgoCD MCP servers. Use when the user asks for cluster security review, RBAC audit, secrets exposure checks, pod security context review, or LoadBalancer exposure review.
---

# Security Audit

Run a structured security audit of the homelab cluster using MCP tools.
Execute each check in order, then produce a final report.

## Checks

### 1. RBAC cluster-admin bindings

- Call `mcp__kubernetes__resources_list` with `kind=ClusterRoleBinding`.
- For each binding that references `roleRef.name=cluster-admin`, inspect its
  subjects.
- Pass if all subjects are in the expected set: `system:masters`, or names
  matching `argocd-*`.
- Fail for any other subject bound to cluster-admin.

### 2. Pod security contexts

- Call `mcp__kubernetes__pods_list` for every namespace.
- For each container, check:
  - `securityContext.runAsNonRoot`
  - `securityContext.runAsUser`
  - whether `securityContext` is missing entirely
- Flag `runAsNonRoot` false or absent.
- Flag `runAsUser = 0`.
- Mark missing `securityContext` as warning.
- Skip `kube-system`, `kube-public`, and `kube-node-lease` for noise reduction,
  but note that they were skipped.

### 3. Resource limits

- From the pod list above, check every container for `resources.limits.cpu`
  and `resources.limits.memory`.
- Flag containers with missing limits as warning.
- Group findings by namespace.

### 4. Secrets exposure in ConfigMaps

- Call `mcp__kubernetes__resources_list` with `kind=ConfigMap` across all
  namespaces.
- Scan `.data` values for common secret patterns:
  `password=`, `token=`, `apikey=`, `api_key=`, `secret=`, `passwd=`.
- Flag any match as critical because these should be SealedSecrets, not
  ConfigMaps.
- Skip well-known safe ConfigMaps such as `kube-root-ca.crt`.

### 5. SealedSecrets controller health

- Call `mcp__kubernetes__pods_list` for namespace `kube-system`.
- Find the `sealed-secrets-controller` pod.
- Pass if it is running with `restartCount <= 5`.
- Warn if `restartCount > 5`.
- Fail if it is not running.

### 6. LoadBalancer exposure

- Call `mcp__kubernetes__resources_list` with `kind=Service` across all
  namespaces.
- Filter to `type=LoadBalancer` services.
- Compare each external IP against the expected inventory:
  - `192.168.0.201` for Immich
  - `192.168.0.202` for ArgoCD
  - `192.168.0.203` for Grafana
  - `192.168.0.204` for Home Assistant
  - `192.168.0.205` for Vaultwarden
- Warn for any service with an IP outside this list.

## Output format

Produce a structured report with one section per check. Use:

- `[PASS]` for no issues found
- `[WARN]` for lower-urgency issues
- `[FAIL]` for issues requiring remediation

End with a **Remediation Steps** section for every fail and warn result, with
concrete actions.
