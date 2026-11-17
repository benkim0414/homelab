# Langfuse initial rollout and CPU compatibility correction

Date: 2026-11-18 (AEDT). Scope: the approved non-HA Langfuse installation only;
no VM expansion, Hermes core upgrade, provider change or schedule activation.

## Approved rollout executed

After the operator privately unlocked the fixed-service Vaultwarden helper,
`hermes mcp test argocd` connected and discovered 16 tools. Used the configured
launcher normally, without reading its session cache or credential values. A
read-only MCP client in ignored verification cache obtained the actual ArgoCD
managed-resource diff; SDK version 2.3.0 was pinned for repeat invocations.

The root diff for `Application/argocd/langfuse` was a single addition with manual
sync, no finalizer, chart 2.2.4 and both Git sources on main. Root registration
was selective: only that Application, revision
`e5db120844277b1a8e9437dc300035921b23b779`, prune/force/replace disabled.
Readback confirmed the exact operation and successful registration. Existing
OutOfSync children, including Hermes, were not synced.

ArgoCD resolved child sources to `[2.2.4, e5db120844277b1a8e9437dc300035921b23b779,
e5db120844277b1a8e9437dc300035921b23b779]`. All 33 desired managed resources were
new. Every resource matched the locally verified pinned render after removing
only the Argo tracking annotation and consistently redacting credential fields.
The reviewed raw bucket Sync hook and chart Helm test pod account for the two
resources omitted by the managed-resources API. No unreviewed removals, generated
credential payloads, cluster RBAC/CRDs, or public Services were introduced.

The child sync used those exact revisions, explicit no-prune and no-force/replace,
with no retry automation. It completed successfully. All six SealedSecrets report
`Synced=True`; all four original claims are Bound. The bucket hook completed and
was removed by its declared HookSucceeded policy. PostgreSQL, Valkey, SeaweedFS
and the Langfuse worker reached Running/Ready. This was not server acceptance:
ClickHouse and web did not become Ready.

## Observed failure and corrected diagnosis

ClickHouse repeatedly terminated immediately with exit 132, not OOMKilled. The
web log reported connection refused to ClickHouse during migrations; PostgreSQL
reported no pending migrations after its initial schema setup. Sanitized logs
were inspected without printing passwords, connection credentials or raw logs.

CPU features observed from the running worker on k3s-05 identify an Intel Xeon
E5-1650 v2 with SSE4.2/AVX but no AVX2. The
[official ClickHouse Docker requirements](https://clickhouse.com/docs/get-started/setup/self-managed/docker)
require x86-64-v3 (including AVX2) for AMD64, and ARMv8.2-A plus Load-Acquire RCpc
for ARM64. An AMD64 image manifest alone therefore did not establish compatibility.
Increasing the number of vCPUs or RAM would not add missing CPU instructions.

The Pi 5 worker k3s-04 exposes ARM features including atomics, fphp/asimdhp,
asimdrdm and lrcpc, CPU part 0xd0b. The unchanged pinned image index
`sha256:d426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7`
contains both AMD64 and ARM64 platform manifests. A disposable Pod on k3s-04,
using that exact pin, UID/GID 101, RuntimeDefault seccomp, dropped capabilities,
read-only root, no service-account token, no secrets and no data volumes,
completed `clickhouse --version` successfully:

    ClickHouse local version 26.8.36.3 (official build).

The owned probe was deleted and its absence verified. This proves binary CPU
compatibility, not full server initialization or migration acceptance.

## Minimal correction and resource review

Change only ClickHouse's node selector to architecture arm64 and hostname
k3s-04. Preserve its image digest, StatefulSet identity, PVC identity, 30 GiB
claim, credentials, UID/GID, security controls and resource requests/limits.
The existing regression contract was changed to reject the incompatible AMD64
placement: it failed before the manifest correction and passed afterward.

Immediately before the move, k3s-04 requested 970m CPU / 1682 MiB and sampled
about 2818 MiB actual memory usage. Its additional ClickHouse reservation is
500m CPU / 2048 MiB. Requested resources fit, but summed limits can still exceed
physical capacity; the small pilot still requires monitoring. Moving this
reservation off k3s-05 improves its earlier unreserved-capacity estimate; it does
not expand any VM or remove overcommit risk. Web/worker remain on AMD64.

The placement correction must be published with green CI, reviewed against the
actual ArgoCD diff, and synced without pruning/force/replace. This replaces the
single failed ClickHouse Pod through its StatefulSet and reattaches the same
Longhorn volume; no PVC deletion, resize, recreate or credential regeneration is
needed. Preserve all stores if further startup diagnostics are necessary.

## Local validation of the correction

The placement regression failed before the manifest change and passed afterward.
Full unit suite: 119 tests, OK with six skips. Five policy tests passed. Full
repository verifier: 21 Applications / 518 resources. `git diff --check` passed.
These are local checks, separate from the live version probe and the corrected
server rollout verified below.

## Verified server outcome — 10:19 AEDT

[PR #94](https://github.com/benkim0414/homelab/pull/94) merged the placement
correction as `a0a38223b2b5b448f8e131b974f3e6fef6888983` after green PR checks.
The [main Verify run](https://github.com/benkim0414/homelab/actions/runs/44196206724)
also succeeded at that exact commit. ArgoCD resolved both Git sources to it.
The actual normalized-to-predicted StatefulSet diff contained exactly two paths:
`spec.template.spec.nodeSelector.kubernetes.io/arch` and
`spec.template.spec.nodeSelector.kubernetes.io/hostname`. Image, credential
references, container resources and volume definitions matched exactly.

Selectively synced only that StatefulSet, with no prune/force/replace. The update
was held by the old never-Ready pod: the StatefulSet had the new revision but its
old pod retained the AMD64 selector. After checking owner UID, failure state and
the retained claim, gracefully deleted only that failed pod. The replacement
had a different UID, the declared ARM64 selector and the same original PVC. It
reached Ready on k3s-04. No force deletion or node/VM reboot was used.

The web Deployment's old progress deadline and failed pod still reflected its
earlier migration failures. Verified its ReplicaSet/Deployment ownership and
non-Ready state, then gracefully restarted only that failed pod. Its replacement
became Available without a template/image/config change. All six current workload
pods were then Ready with zero restarts on their current pod identities.

ArgoCD reports Langfuse Synced/Healthy with chart 2.2.4 and the reviewed Git
revisions. Private HTTPS `/api/public/health` and `/api/public/ready` both returned
`{"status":"OK","version":"4.77.0"}`. TLS validation succeeded normally;
no insecure option was used. The root page returned HTTP 200; owner login is
still operator verification, not established by that page response.

The deprecated `/api/public/traces` route returned 404. Consulted the official
[v4 API migration guide](https://langfuse.com/faq/all/deprecated-api-migration)
and tested the supported `/api/public/v2/observations` endpoint: HTTP 401 without
credentials. Future privacy/trace retrieval checks must use v2 observations with
a bounded time window and explicit IO fields, not legacy trace-level payloads.
No existing credential value was retrieved to perform this check.

All four original claim-to-volume bindings were compared with their initial
values and remained unchanged/Bound. All four corresponding Longhorn volumes
reported attached/healthy; ClickHouse's volume moved to k3s-04. This verifies
claim preservation and current storage health, not a trace persistence or
coordinated backup/restore test.

## Runtime network checks

Reviewed the actual Hermes NetworkPolicy diff: only a new egress rule to the
Langfuse web selector on TCP/3000; all prior ingress/egress rules were identical.
Selectively synced that NetworkPolicy at the green revision. Did not sync the
Hermes Deployment or root's Hermes Application. Its live image remains v0.22.2;
the unrelated pending upgrade is still explicit drift.

- Real Hermes pod, application UID 10000: Langfuse web health HTTP 200 over the
  intended internal HTTP endpoint. This internal hop is not TLS.
- Same Hermes source: PostgreSQL 5432, Valkey 6379, ClickHouse 8123 and S3 8333
  all rejected with ECONNREFUSED. DNS resolution was checked. Same-namespace
  positive controls from the Langfuse worker connected to all four services,
  so the negative results were not explained by those stores being down.
- Owned no-token/no-secret/no-volume probe in unrelated namespace default,
  using the pinned worker image and nonroot/read-only restrictions: web TCP/3000
  and ClickHouse TCP/8123 both rejected after successful DNS resolution. Default
  had no NetworkPolicies that could explain it as unrelated egress isolation.
  The probe completed successfully and was deleted; its absence was verified.
- Real workstation HTTPS requests demonstrate the allowed Tailscale proxy path.
  All Langfuse Services are ClusterIP; ingressClass is tailscale and Funnel is
  not enabled. No Tailscale ACL or OAuth credential was changed.

These are scoped application checks, not a full cluster security/firewall audit.
The K3s CNI rejects blocked TCP rather than necessarily timing it out; the first
negative-check script expected only timeouts and was corrected to distinguish
DNS failures and use live positive controls before accepting refusals.

## Capacity observation after corrected placement

At the sample, k3s-04 used 3340 MiB / 45% RAM and 6% CPU; k3s-05 used 9346 MiB /
61% RAM and 11% CPU. ClickHouse sampled 331 MiB, web 940 MiB and worker 432 MiB.
These are startup/idle samples, not peak-load or growth guarantees.

Current requests: k3s-04 1470m CPU / 3730 MiB; k3s-05 2700m CPU / 10002 MiB.
No MemoryPressure/DiskPressure/PIDPressure flags were set on either Ready node.
Summed limits remain overcommitted: k3s-04 131% CPU / 130% memory; k3s-05 478%
CPU / 168% memory. Monitor representative use and ingestion growth. No VM
capacity or application resource limit was expanded to obtain readiness.

## Client enrollment and acceptance still pending

- Operator owner login and creation of `hermes-desktop` / `hermes-cluster`
  project-scoped ingestion credentials through the private UI/workflow.
- Seal/inject each source's project keys through the approved private workflow.
- Enroll only desktop default/homelab-scientist and cluster default/house-manager,
  preserving live Hermes v0.22.2 and the selected inference providers.
- Verify real metadata-only root/generation/tool traces, failure isolation,
  persistence and CNI network boundaries. No successful real trace is claimed.
