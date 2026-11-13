# Monitoring upgrades

Applications and chart pins live in [monitoring.yaml](../argocd/apps/monitoring.yaml).
The [ArgoCD runbook](../argocd/README.md#monitoring-rollout-lessons-and-results)
records installation history, not the current desired versions.

## Reviewing the 93.x Prometheus stack upgrade

Keep manual, no-prune sync, `ServerSideApply=true`, the narrow Grafana generated
credential/checksum ignores and `RespectIgnoreDifferences=true`. Apply the chart's
matching CRDs before the updated operator and dependent monitoring resources.
The [upstream upgrade guide](https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-93.2.2/charts/kube-prometheus-stack/UPGRADE.md#from-92x-to-93x)
introduces operator 0.95.x; chart 93.2.2 packages operator/CRDs 0.95.2.

The admission create hook now requests `kubernetes.io/tls` and the operator reads
`tls.crt`/`tls.key`; its ServiceMonitor reads `ca.crt`. Certgen 1.11.1 migrates an
existing Opaque admission Secret by validating and preserving its certificate
payload, adding standard TLS keys, then deleting/recreating **that Secret only**
with UID/resourceVersion preconditions. The hook Role consequently gains `delete`
restricted to `kube-prometheus-stack-admission`. This is a real migration even
without pruning: do not skip hooks or use apply-only sync. Review a maintenance
window and recovery of the admission Secret before rollout; a failed recreate can
leave it missing. This does not require reading or exporting credentials for local
validation. See [certgen implementation](https://github.com/jkroepke/kube-webhook-certgen/blob/v1.11.1/pkg/k8s/k8s.go).

Grafana 13.3.1 may migrate its database on the existing 2 GiB PVC. Review backup
and downgrade compatibility before sync; chart rollback alone is not a database
rollback. Prometheus and Alertmanager also restart with updated default images.
Do not resize, rename, recreate or prune monitoring claims as part of this upgrade.

## Loki chart metadata is not the rendered image

Loki chart 7.6.0 advertises `appVersion: 3.6.18`, but its packaged default
`loki.image.tag` is **3.6.11**, as in chart 7.3.0. With the repository's unchanged
values, the new chart still renders `docker.io/grafana/loki:3.6.11`; a chart bump
alone is **not** a Loki runtime/security upgrade. The Application currently holds
the live chart at **7.3.0** while recovery prerequisites are established. A
separately reviewed image override must consider the chart's
3.6.x target rather than blindly selecting the latest 3.7.x release.

Preserve the `loki` StatefulSet and `storage` claim template, filesystem TSDB v13
schema/date/index prefix, 10 GiB Longhorn volume, `/var/loki/compactor` working
directory, filesystem delete requests, seven-day asynchronous retention and
existing gateway/auth settings.

### Loki retention safeguard before recovery maintenance

The values explicitly declare `whenDeleted: Retain` and `whenScaled: Retain`.
This retention-only stage keeps chart 7.3.0, runtime 3.6.11, one replica and the
existing claim template unchanged. It is not a runtime upgrade or a backup.
The operator approved a temporary verifier `storage-identity` exception for
`apps/StatefulSet/monitoring/loki` on 13 November 2026 for these two retention
fields only. Publish and require exact-commit CI for that change, then remove
the exception in a separately CI-verified follow-up before live sync. Do not
change policy code or exempt other resources; future storage changes must
continue to fail closed without their own review.
Keep the chart's `enableStatefulSetAutoDeletePVC` gate enabled so the explicit
policy renders; do not enable StatefulSet recreation for size changes.

Before scaling down, require a reviewed no-prune sync and verify the live policy
is Retain/Retain, the StatefulSet controller has removed its and any Pod's owner
references from `storage-loki-0`, and the same PVC/PV/CSI identities remain Bound.
The safeguard should not change the pod template or restart Loki; verify the
writer pod UID and readiness are unchanged. Do not manually strip owner
references to bypass controller reconciliation.

The existing dynamically provisioned PV still has reclaim policy **Delete**.
Explicit PVC/namespace deletion can destroy data despite StatefulSet retention.
Do not change global StorageClass policy, prune storage, force-detach, or treat
an unavailable/removed snapshot as a backup. After retention is verified, a
separate checkpoint must observe normal shutdown, complete a durable whole-volume
backup, resume the original writer/claim and pass an isolated restore/replay test
before any runtime upgrade. The single-replica maintenance interval interrupts
ingestion/queries; collector buffering and log rotation require RPO review.

## Alloy and post-sync checks

Chart 1.15.0 defaults to Alloy 1.21.3; the optional distroless mode is not enabled.
Keep node-local discovery, `/var/log` mounts, control-plane toleration, `file_match`,
CRI parsing and the existing Loki gateway push URL unchanged. Preserve the numeric
config-reloader IDs and five-second readiness timeout.

Local render/lint does not prove ingestion or live health. After a separately
reviewed rollout, verify admission hooks/operator readiness, Prometheus target and
rule health, Grafana LAN/Tailscale access and existing login, unchanged bound
claims, Loki readiness and recent logs from every node/workload. A ready Alloy
DaemonSet alone does not establish log delivery.
