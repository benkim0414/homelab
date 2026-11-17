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
These are local checks, separate from the successful live version probe and the
still-pending corrected server rollout.

## Acceptance still pending

- Publish and apply the placement correction; verify actual ClickHouse startup,
  web migrations, all six workload pods, ArgoCD health and private HTTPS/login.
- Verify node/Longhorn health and unchanged claim identities after rescheduling.
- Create separate desktop/cluster client projects and provision keys privately.
- Enroll only desktop default/homelab-scientist and cluster default/house-manager,
  preserving live Hermes v0.22.2 and the selected inference providers.
- Verify real metadata-only root/generation/tool traces, failure isolation,
  persistence and CNI network boundaries. No successful real trace is claimed.
