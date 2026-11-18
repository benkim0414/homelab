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

- The operator privately completed cluster-key provisioning; its ciphertext is
  published and unsealed. Desktop private credential entry remains pending.
  No project key was read from chat, an existing Secret, another profile or its
  env file.
- Cluster references have now been injected in an approved idle window; the
  remaining cluster blocker is profile-scoped credential delivery under multiplex
  semantics. Use the approved private workflow for desktop credentials.
- Enroll only desktop default/homelab-scientist and cluster default/house-manager,
  preserving live Hermes v0.22.2 and the selected inference providers.
- Verify real metadata-only root/generation/tool traces, failure isolation,
  persistence and CNI network boundaries. No successful real trace is claimed.

## Private client provisioning preparation — before real operator entry

Added `langfuse/seal-hermes-client.py`, reusing the bootstrap's strict sealing
and atomic ciphertext publication with an explicit `hermes` namespace. The
bootstrap retains its original `langfuse` namespace default. The client helper
uses hidden private-terminal prompts, validates the read-only fixed HTTPS
project response is scoped only to `hermes-cluster`, blocks redirects, refuses
overwrite/symlink hazards and publishes only mode-0600 ciphertext. Both helpers
now reject unsupported arguments without argparse echoing possible credentials.
It never applies a cluster resource or writes a plaintext credential file.

The new contracts were exercised RED then GREEN. Full suite: 130 tests, OK with
six skips. Five policy tests passed; full verifier still 21 Applications /
518 resources. A fake-input full helper fixture passed against the actual
kubeseal/controller, with project-authentication success explicitly mocked;
fixture ciphertext was discarded. The real HTTPS project endpoint rejected fake
keys with HTTP 401. Actual operator key authentication remains unverified until
private entry. The real client ciphertext does not yet exist.

Desktop runtime recheck: v0.21.1 upstream `3f5a11f6`, Python 3.11.18, bundled
Langfuse 1.0.0 not enabled on either selected profile. Installed SDK 4.15.2 and
the matching OpenTelemetry 1.39.1 SDK/exporter family while preserving the
previously installed OpenTelemetry API 1.39.1; eight packages added, no existing
package upgraded. All 136 installed packages passed dependency checks and SDK
import succeeded. No desktop key/profile setting, inference provider, messaging
adapter or schedule was changed. Keep the plugin disabled until the actual
private endpoint and metadata-only launch environment are verified; an unwrapped
process otherwise has unsafe Cloud/sanitized defaults for this deployment.

## Cluster credentials staged; earlier restart pause (superseded below)

The operator ran the private helper successfully. Verified the actual new
ciphertext's namespace/name, two encrypted key names and 0600 file permissions,
without displaying values. Full validation with it present: 130 tests, OK with
six skips; full verifier 21 Applications / 519 resources. Published through
[PR #96](https://github.com/benkim0414/homelab/pull/96), merged as
`7ef3c7f496c48c37e685a44129350b37dd315d0c` after green PR CI and successful
[main Verify](https://github.com/benkim0414/homelab/actions/runs/44206308442).

Reviewed the actual root Hermes Application diff: only the directory include
selection changed. The selection also includes already-pending browser/Herdr
files, but root registration does not apply child resources under manual sync.
Registered only that Application, then reviewed the actual client SealedSecret
addition and selectively synced only it. Both operations used the exact green
revision with no prune/force/replace. `hermes/hermes-langfuse` reports Synced and
the generated Secret exists; no Secret payload was read.

As application UID/GID 10000, installed catalog plugin `langfuse` 2.0.0 for the
default cluster profile at immutable ref
`c2a95963c442f3f23e4bc6fe0da898e1dd1fb63d`, using `--yes-deps --no-enable`.
No credential was entered into that install command. Its source is persisted
under `/opt/data/plugins/langfuse`; PM reports writable store `/opt/data/tools`
and runtime facts `/opt/data/installs/351f81cc06284494/facts.json`, also on the
data PVC. Dependency activation and post-recreation import remain unverified.
Read-only CLI discovery shows default's plugin not enabled, while house-manager
does not discover the default-profile installation and still needs its own
installation. Do not assume one installation enrolls multiple profiles.

Before injecting the environment, asked whether the single-pod Hermes workload
was idle and could restart. The operator answered `Not sure`. Did not restart,
patch the Deployment environment, enable plugins or change providers. Exact
readback still shows the v0.22.2 image and no HERMES_LANGFUSE environment entries.
The credentials are safely staged; continue only after a confirmed idle window.

## Approved tracing restart; scoped credential delivery blocked

The operator subsequently confirmed, "It's idle and you can restart it." Installed
the same pinned catalog plugin separately for house-manager with `--no-enable`.
Applied only the seven tracing environment entries already declared in Git to the
live Hermes container, with a resource-version guard and server dry-run. Readback
verified the rest of the Deployment spec was unchanged: no v0.23.1 upgrade,
command/probe/resource changes or volume-reference changes were included.

The env-only Recreate rollout completed successfully. As UID/GID 10000, enabled
`langfuse` for default and house-manager using `--no-allow-tool-override`. Settings
backups were created and verified at mode 0600 inside owner-only PVC directory
`/opt/data/langfuse-config-backup-20261118T004006Z`. Semantic comparison confirmed
all settings outside Langfuse plugin bookkeeping were unchanged. The first strict
comparison stopped on the newly added `plugins.entries.langfuse` entry; inspection
confirmed its sole permission was `allow_tool_override: false`, not a provider or
other settings change. Both supported CLI enable operations reported live hook
reloads.

A final controlled Deployment restart completed, and the replacement pod reported
Ready with zero container restarts. The committed dependency environment remained
on the PVC, SDK 4.15.2 imported successfully after recreation, and an unscoped
official plugin SDK client passed `auth_check()`. Both image and existing provider
configuration were preserved. No Secret payload or credential value was displayed;
no credential was copied between profiles.

The post-restart comparison also detected `_left_core_installed: [langfuse]`
added by normal startup in both settings files. Inspected the image's
`hermes_cli/left_core_migration.py`: this records an already-installed plugin so
the migration does not reinstall it after a later explicit removal. It is
Langfuse migration bookkeeping, not an inference-provider change; account for
this exact marker rather than ignoring arbitrary configuration differences.

The post-restart backup-permission check found files at 0660 and their directory
at 02770, rather than their original 0600/0700. Restored and read back owner-only
permissions on only this task's two settings backups and directory, using
owner/type/no-symlink guards. Recheck these modes after any later recreation;
do not assume the initial backup modes persist through startup. Final semantic
comparison passed for both profiles after accounting for only the reviewed
Langfuse bookkeeping. No existing credential-file permissions were changed.

The stronger profile-context check exposed an incomplete enrollment:

| Check under normal profile secret scope and multiplex semantics | default | house-manager |
| --- | --- | --- |
| Process-level endpoint available through plugin `_env()` | yes | yes |
| Capture mode | metadata | metadata |
| Plugin `_build_client()` returns a client | no | no |

The plugin's `_secret()` delegates credential reads to `agent.secret_scope`,
which does not fall back to ambient pod credentials on a multiplexed scope miss.
The existing pod environment therefore authenticates in a standalone process but
does not supply the keys to multiplexed profile sessions. An initial endpoint
comparison used the external HTTPS URL instead of the declared internal HTTP URL;
the corrected presence check confirmed endpoint configuration is available. The
initially identified blocker was the scoped key pair. This diagnosis was
incomplete: subsequent constructor inspection found scoped endpoint requirements
too; see the [scoped-source safety record](2026-11-18-langfuse-scoped-source.md).

No real trace, privacy, persistence or outage acceptance is claimed. Did not
weaken secret isolation, modify inference-provider authentication, copy keys to
profile files or configure a new secret source. The next credential-source change
needs explicit scope review/approval. Desktop enrollment remains pending. Earlier
idle approval does not establish that a later restart window is idle.

The operator subsequently approved the narrow source/mount correction. Its
applied changes, potential project-key disclosure, verified private scoped setup
exports and remaining Hermes package-storage activation blocker are recorded in
the scoped-source safety record above. That record supersedes this section's
initial key-only diagnosis and earlier no-setup-trace status. Real agent-turn,
persistence/outage and desktop acceptance remain pending.
