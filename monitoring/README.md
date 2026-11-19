# Monitoring upgrades

Applications and chart pins live in [monitoring.yaml](../argocd/apps/monitoring.yaml).
The [ArgoCD runbook](../argocd/README.md#monitoring-rollout-lessons-and-results)
records installation history, not the current desired versions.

## Reviewing the 93.4.0 Prometheus stack candidate

### Verified rollout — 18 November 2026 UTC

The operator approved bounded backup maintenance and the protected named admission
Secret migration. Chart 93.4.0 was deployed at
`dfdb91d69f013db62b35e3aefa13e80ee21dfe6e`: operator/reloader 0.95.2,
Prometheus 3.16.0, Alertmanager 0.35.0 and Grafana 13.3.1. The Application finished
Synced/Healthy/Succeeded, all 32 scrape targets were up, Grafana database health
passed, and the pre-existing recording-rule timeout alert cleared. All five
node-exporter pods remained available; claims and manual sync were preserved.

Fresh cold full NAS backups and independent restore checks preceded rollout.
Grafana's SQLite integrity/schema check passed; Alertmanager's inert target
readiness/normal shutdown passed. Prometheus opened restored blocks/replayed WAL,
but restore/attachment consumed its first Pod deadline. A second check on the
already-restored copy proved HTTP readiness and normal shutdown at the unchanged
1536 MiB limit; the failed original test was preserved.

The ten packaged CRDs were established before the operator. Admission SAN/CA/key
validation, strict sealing/controller validation and NAS ciphertext readback were
verified without displaying private keys. The hook converted Opaque→TLS and kept
legacy entries with matching standard aliases. The first sync was marked Failed
during transient CR init-container health, then reached Synced/Healthy. Its failed
history was preserved. A reviewed completion sync ran the PostSync CA hook with
the existing TLS Secret UID/data unchanged and no workload replacements/restarts.
Do not automatically retry failed migrations or hide real health failures.

The offsite-backup warning remains a separate gap; Watchdog is intentionally
firing. No controller private-key export or independent key-disaster custody was
inspected/claimed. See the
[cohort rollout record](../reports/2026-11-19-remaining-application-upgrades.md).

At 19 November UTC closeout, all four upgrade Applications were Synced/Healthy
and 32/32 targets were up, but the 30-day API-server recording-rule timeout
recurred alongside k3s-03 memory/I/O/load warnings. This remains a critical
monitoring-health follow-up, not a rule failure hidden by a green rollout. No
rules were disabled, timeouts raised or workloads moved/restarted to suppress it.

### Placement/resource correction — 19 November UTC

A later preflight found a recovered Prometheus OOMKilled event at 05:00:20Z and
mapped busy node03 `sde` to its existing Longhorn volume. The prepared values pin
Prometheus to schedulable k3s-04, request 500m CPU/1536Mi memory and allow 2Gi
memory; **published in PR103, deployed and live-verified**. The pinned render
changes only its CR's selector/resources, not images, storage, rules or timeouts.
See the [preflight and maintenance plan](../reports/2026-11-19-prometheus-placement.md)
for capacity, retained-volume, fresh-checkpoint, selective-sync and interruption
requirements. Hard hostname selection is not HA and needs reviewed recovery if
that node fails. Do not rerun admission hooks or move other workloads for this fix.
The first wrapper failed before any pause and was preserved. A subsequently
approved corrected attempt completed cold full NAS backup
`upgrade-prometheus-20261119095749-1536cc`, resumed the original and then moved
only the Prometheus CR at exact-main b8c07ea9. The Pod is Ready on k3s-04 with the
same original claim/image; no admission hooks or other monitoring Pods restarted.
The 901-second observation passed with zero restarts/OOM and a maximum sampled
working set of 1765Mi. Both previously failing rule groups repeatedly evaluated
healthy in under one second, 32/32 targets were up and no critical alerts fired.
The historical target-health sample matched; original volume/image identities
and all other monitoring Pods remained unchanged. k3s-03 memory fell from 94%
to 74%, while k3s-04 sampled 57%. This is measured acceptance, not a worst-case
memory bound. OffsiteBackupMissing and the preserved recovery-job warning remain.

### Pre-rollout review

This is a **prepared candidate, not a deployed upgrade**. Review the actual live
chart **92.7.0 → 93.4.0**, not the superseded desired pin 93.2.2. The 93.4.0
release was published on 17 November 2026. Exact public 92.7.0 and 93.4.0 packages
were downloaded and matched against their Helm repository index SHA-256 digests:

- 92.7.0: `af35d3e93750ce46d90cbb6537483c8fa914f19fbffa19fbabcb2825181a0f1a`
- 93.4.0: `2ff4547dbe30aa7f6c7ef9fb49e35dfef43a36486cd8e463cd43cdda93914b24`

Keep manual, no-prune/no-force/no-replace sync, `ServerSideApply=true`, the narrow
Grafana generated credential/checksum ignores and `RespectIgnoreDifferences=true`.
Alloy/Loki chart pins and monitoring values are unchanged by this candidate.

| Component | 92.7.0 render | 93.4.0 render |
| --- | --- | --- |
| Operator / config reloader / CRDs | 0.94.1 | 0.95.2 |
| Prometheus | 3.15.0-distroless | 3.16.0-distroless |
| Alertmanager | 0.34.1 | 0.35.0 |
| Grafana | 13.2.4-distroless | 13.3.1-distroless |
| Grafana sidecar | 2.14.1 | 2.14.3 |
| Admission certgen | 1.11.0 | 1.11.1 |
| node-exporter | 1.12.1-distroless | unchanged |
| kube-state-metrics | 2.20.0 | unchanged |

The bundled Grafana **chart** is 14.5.0, not Grafana runtime 14.5.0; its new 14.x
values schema accepts these repository values. The node-exporter and
kube-state-metrics subcharts move to 5.1.0 and 9.0.1 without runtime image bumps.
Public image indexes for all seven changed runtime/hook images include linux/amd64
and linux/arm64; unknown-platform attestation entries are not executable platforms.
This checks availability, not signatures or a vulnerability scan. Operator 0.95.2
fixes non-amd64 image builds. Grafana 13.3.1 release notes list fixes for
CVE-2026-102589, CVE-2026-107509, CVE-2026-110992, CVE-2026-111024,
CVE-2026-13721 and CVE-2026-14242; this is not a claim that all images are CVE-free.
Alertmanager 0.35.0 also redacts Telegram bot tokens from notification errors and
adds an experimental ConnectRPC API alongside its existing API on the same service.
Its removed auto-gomemlimit feature flag and eventrecorder output/schema changes
are not configured in these values; verify actual generated/live configuration
before rollout. Prometheus 3.16.0 includes WAL/replay/compaction data-loss fixes.

### CRDs, hooks and security effects

Apply the exact chart's ten matching **0.95.2 CRDs first**, wait for Established
and discovery, then validate/sync the operator and dependent ServiceMonitors,
Prometheus/Alertmanager and custom rules. The
[93.x upgrade guide](https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-93.4.0/charts/kube-prometheus-stack/UPGRADE.md#from-92x-to-93x)
still gives 0.95.1 examples: do not substitute those for the packaged 0.95.2 CRDs.
The optional CRD-upgrade Job remains disabled; the candidate does not enable it.
Existing admission pre-sync hooks are not proof that CRDs have already been updated.
Schema review found extraScrapeMetrics, Alertmanager route labels, Telegram
Secret/file selection and config-filesystem mode, TLS client-auth enum validation,
Webex CEL validation and embedded PVC health-field constraints. CRD names and
served/storage versions remain unchanged. Local schema checks do not execute CEL
or prove API-server admission compatibility.

The operator ClusterRole adds patch on managed CR finalizers and
create/update/patch/delete on `alertmanagerconfigs/status`, while removing core
Pod delete. Optional aggregate
roles add ThanosRuler permissions in templates but are not rendered with these
values. Node-exporter adds no privilege escalation, drop ALL capabilities and
RuntimeDefault seccomp, preserving host mounts/network; its probe timeouts become
five seconds. kube-state-metrics gains Linux node selection. Kubelet scraping now
keeps `container_memory_swap`, potentially increasing series/cardinality. Rules
and dashboards change, so target/rule evaluation still needs live verification.
Rendered Service specs, workload selectors, PVC specs, Prometheus/Alertmanager
storage and retention are unchanged. Grafana stays on LAN LoadBalancer
`192.168.0.203` and the existing Tailscale ingress; outside the admission TLS-key
migration below, no new ingress, NetworkPolicy, authentication setting or
credential reference is introduced.

The admission create hook now requests `kubernetes.io/tls` and the operator reads
`tls.crt`/`tls.key`; its ServiceMonitor reads `ca.crt`. Certgen 1.11.1 migrates an
existing Opaque admission Secret by preserving legacy entries, checking required
keys, adding standard TLS keys, then deleting/recreating **that Secret only**
with UID/resourceVersion preconditions. Its hook Role gains `delete` restricted
to `kube-prometheus-stack-admission`. Key-presence checks are not certificate-chain
or SAN validation. The create Job remains pre-install/pre-upgrade; the webhook
CA patch Job remains post-install/post-upgrade, with before-hook-creation and
hook-succeeded cleanup. The certgen source internally uses forced SSA for webhook
CA patching; this is distinct from, and does not authorize, Argo force/replace.
This is a destructive Secret-type migration even without pruning: do not skip
hooks or use apply-only sync. A failed recreate can leave the Secret missing.
See [certgen implementation](https://github.com/jkroepke/kube-webhook-certgen/blob/v1.11.1/pkg/k8s/k8s.go).

### Backup-first rollout requirements (pre-rollout review)

Grafana 13.3.1 may migrate its database on the existing 2 GiB PVC. Chart rollback
alone is not database rollback. Prometheus and Alertmanager restart on their
existing 20 GiB and 2 GiB claims; preserve all claim/PV/CSI identities and reclaim
policies. Do not resize, rename, recreate or prune storage. The prior checkpoint
reported Grafana backup six days old, no Prometheus/Alertmanager checkpoint, and
an unexecuted admission recovery checkpoint; these are unresolved evidence gaps,
not a fresh backup/health assessment.

Before maintenance, obtain narrowly scoped approval to create and independently
restore-verify fresh Grafana DB/data, Prometheus TSDB and Alertmanager state
checkpoints, including only the specific writer pauses and backup destination
access required. Separately authorize encrypted recovery custody of **only**
`monitoring/kube-prometheus-stack-admission` (or an operator-run checkpoint that
never exposes payloads here), SAN/CA/key validation and its exact-name
get/create/delete migration plus the chart webhook/RBAC changes. Do not grant
blanket Secret export, credential rotation, namespace deletion, PVC deletion,
force-detach or broad RBAC. Resume originals after checkpointing; restoring a
consistent checkpoint plus old images is the rollback path. Approval for these
backup actions is not approval for sync. Require a separate reviewed maintenance
window, exact-commit successful CI, full generated-to-live diff and scoped
admission dry-run before any rollout. The earlier approval timeout grants nothing.

Local Helm 3.19.0 renders (including CRDs) and strict lint passed for both exact
packages with repository values: 120 resources each, ten CRDs, no resource identity
additions/removals. The repository verifier's two-pass render and strict
Kubeconform 0.7.0 schema check against declared Kubernetes 1.36.5 also passed for
both versions: 122 resources each including the two raw manifests, zero invalid,
errors or skipped resources. Full-repository policy/CI validation remains separate.
Generated Secret payloads were excluded from review output.
Local validation is not deployment, recovery validation or live health evidence.

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
fields only. The initial exception-bearing commit `ebe1ceb` passed local full
validation, but Verify run `43357839805` failed because a synthetic unit-test
fixture inherited the production exception. The repair isolates fixture
exceptions and removes the temporary production exception; it does not change
policy code. Require successful exact-commit CI for this repair/cleanup commit
and the complete Argo generated-to-live review before live sync. The original
failed CI run remains recorded; future storage changes still fail closed.
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
