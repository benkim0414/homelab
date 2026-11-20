# Routine patch pre-review — 2026-11-20

Scope: review queued Renovate proposals while preparing the first Langfuse
recovery set. This is not an upgrade PR or rollout record. At the fresh GitHub
check, only Langfuse datastore PRs [#106](https://github.com/benkim0414/homelab/pull/106)
and [#107](https://github.com/benkim0414/homelab/pull/107) were open; they remain
blocked by [recovery prerequisites](../langfuse/RECOVERY-FIRST.md).
[Dashboard #71](https://github.com/benkim0414/homelab/issues/71) still had the
routine proposals queued. No new Renovate run, rate-limit override, global
recreation of ignored updates, merge or deployment occurred during this review.

## Home Assistant: chart 0.3.91 → 0.3.92

Repository/live pin 0.3.91; Application Synced/Healthy. The observed running
server is 2026.11.1, Ready with zero restarts. This candidate changes the server
to **2026.11.2**, not merely Helm metadata.

Downloaded the exact official chart packages and rendered both using the current
repository values, including CRDs and the existing release/namespace identity.
Each produced seven resources. Effective changed paths were version/chart labels,
StatefulSet image, Pod labels and configuration/init-script checksums. ConfigMap
data, ServiceMonitor content, storage, RBAC and resource identities were unchanged.
The checksums include chart-rendered metadata; their change does not establish
changed configuration payloads. No added/removed resources were observed.

Upstream package changes include ServiceMonitor namespace/auth controls; the
current values retain the existing namespace, token reference and custom
configuration template. The disabled code-server addon's default version also
changes but does not cause an addon rollout. Existing Helm test Pod is a test
hook; no new migration/install/upgrade hook was identified.

[Core 2026.11.2 release notes](https://github.com/home-assistant/core/releases/tag/2026.11.2)
include integration fixes, security/dependency updates and `input_text.set_value`
pattern enforcement. Review applicability against actual installed integrations;
no credential-bearing runtime config was inspected for this task.

Hold rollout pending a **fresh recoverable complete `/config` checkpoint**,
including hidden storage, integrations, automations and recorder DB. No namespace
backup Job/CronJob exists. The November 13 checkpoint/rehearsals recorded in the
[runbook](../home-assistant/README.md) are historical, not a fresh gate.
Live claim UID remains `c5c6efef-10e1-4810-91c4-2107c61edb49`, bound to
`pvc-c5c6efef-10e1-4810-91c4-2107c61edb49`; preserve it. Do not infer safe image
rollback against changed on-disk state.

When the actual PR exists: verify exact-head CI, full generated-to-live diff,
ARM64 image availability and current checkpoint/recovery. Preserve forceInit=false,
1Gi memory limit, service exposure, credentials and manual sync. After reviewed
rollout, verify sustained memory/readiness, authenticated scrape, both entry
points and operator device/automation acceptance.

## Tailscale operator: chart 1.104.4 → 1.104.7

Repository/live pin 1.104.4; Application Synced/Healthy. Operator and all observed
managed proxy Pods are Ready, zero restarts, running v1.104.4. External
`operator-oauth` exists with expected `client_id`/`client_secret` key names; values
were not read.

Only Chart.yaml differs between the exact upstream packages; templates, CRDs,
RBAC and default values are byte-identical. Local full renders each produced
18 resources. The entire effective candidate diff was two operator Deployment
fields: operator image v1.104.4 → v1.104.7 and PROXY_IMAGE v1.104.4 → v1.104.7.
The latter can roll **every managed proxy**, including ArgoCD and agent access.
It is not an operator-only restart. No rendered storage/auth/RBAC/CRD change or
resource removal/addition was observed.

[Official changelog](https://tailscale.com/changelog) covers lossy/dormant
connection fixes and Go/TLS-control-plane compatibility. The API-server proxy
caller-identification change does not justify enabling that currently disabled
feature or altering authentication.

This is the stronger routine candidate once its actual PR exists. Require
exact-SHA CI, full Argo desired/live review, target ARM64 manifests, recorded
proxy StatefulSet/device/Secret identities and a retained independent Kubernetes
connection. Preserve `helm.releaseName: tailscale-operator`, external OAuth
reference, CRs, proxy state Secrets and tailnet registrations. Do not uninstall,
recreate credentials or delete devices as recovery.

The configured Kubernetes API returned authenticated `/readyz` = `ok` during
this review. The independent ArgoCD LAN URL `http://192.168.0.202` failed to
connect (HTTP000); no route/firewall change was attempted. Do not claim that
LAN access passed or depend exclusively on a Tailscale endpoint for recovery.
Review the direct Kubernetes operational path before rollout and verify all
managed proxies and affected HTTPS endpoints afterward. A declaration revert
alone does not prove every reconciled proxy reverted.

## Exact packages and validation limits

| Package | SHA-256 |
| --- | --- |
| Home Assistant 0.3.91 | `1f21589c551a2c1cbc9ae5dcf09a25ddaa2cbb82753f0981fada06c9aad638a7` |
| Home Assistant 0.3.92 | `f6075634c2d52b4cfdb9c47ae2b01323dd7e7aacfdf290abde6993163598fdf2` |
| Tailscale operator 1.104.4 | `971ff11ecc285613cd29d6f48a8ada180d7bdf716ac3301a1e663837f6419998` |
| Tailscale operator 1.104.7 | `55d1df3c16b2ac1871908b78f37b4c341b963b3bb626ab1c18ed48b69620ef8b` |

Chart sources were the repository-declared official indexes. Tailscale asset
filenames contain version/build/digest suffixes; use the actual resolved index
asset rather than guessing a short filename. An initial local render invocation
used the guessed short filename, failed before deployment and was corrected to
use the downloaded exact artifact. No validation policy was weakened.

This review exercised exact-package comparison and old/new local rendering, not
full candidate repository validation, authenticated live diff acceptance, backup
recovery, native target-runtime compatibility or deployment. There is no eligible
open routine PR to merge at this point. Let the existing schedule produce the
next proposals, or obtain explicit approval for an additional controlled run
without overriding existing proposal limits or closed/ignored updates.
