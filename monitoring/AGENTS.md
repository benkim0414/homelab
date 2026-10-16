# Monitoring instructions

These rules also apply to `argocd/apps/monitoring.yaml`. See the monitoring
sections of [the ArgoCD runbook](../argocd/README.md) for rollout history.

## Configuration constraints

- Follow [ArgoCD instructions](../argocd/AGENTS.md) for sources and sync policies.
  Preserve Grafana generated-Secret ignores, the dependent Deployment checksum
  ignore, and `RespectIgnoreDifferences=true`; do not mask unrelated drift.
- Preserve existing PVC identities and review Longhorn capacity/replication before
  changing retention or storage. Loki retention is asynchronous and is not a hard
  disk-usage ceiling; preserve persistent compactor markers/delete-request storage.
- Install monitoring CRDs/operator before syncing dependent ServiceMonitors or
  custom rules. For Home Assistant metrics, also read
  [Home Assistant instructions](../home-assistant/AGENTS.md).
- Alloy discovers node-local pods and tails local CRI files. Preserve node-scoped
  discovery, mounts/tolerations, path glob expansion (`file_match`), CRI parsing,
  and forwarding to Loki when changing its configuration.

## Verification

- Check YAML and embedded Alloy/Loki configuration, chart values, and referenced
  rules. Render the affected chart when dependencies and network approval permit.
- A ready collector alone does not establish log ingestion. For an authorized
  live check, confirm recent logs by node and workload in Loki, and metrics/target
  health in Prometheus. Do not report live success from a local render.

## Code Review Rules

- Flag removal or broadening of generated-secret ignores that causes perpetual
  drift or hides unrelated changes. Keep the generated fields, dependent checksum,
  and `RespectIgnoreDifferences=true` aligned.
- Flag Alloy pipeline changes that lose node-local selection, path expansion, or
  CRI parsing. Preserve those stages or provide an equivalent ingestion path;
  readiness alone is not evidence of logs reaching Loki.
