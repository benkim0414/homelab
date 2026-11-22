# Langfuse

Private LLM observability for the selected Hermes profiles. This directory declares
an installation; it does not establish that it is deployed or collecting traces.

## Implementation status

Published through [PR #93](https://github.com/benkim0414/homelab/pull/93), merged
as `e5db120844277b1a8e9437dc300035921b23b779` after green PR checks. The
[main-branch Verify run](https://github.com/benkim0414/homelab/actions/runs/44189306576)
also succeeded at that exact revision. The server is now deployed and verified
Synced/Healthy. Subsequent cluster and desktop CLI enrollment and real-turn
privacy checks passed. Scoped web-restart persistence and disposable desktop-client
outage checks also passed; see the [resilience record](../reports/2026-11-18-langfuse-resilience.md)
for coverage and limits.
On 2026-11-17, both configured kubectl and Kubernetes
MCP failed to reach `192.168.0.11:6443` with `no route to host`. The workstation
was on `192.168.86.0/24`, no homelab subnet route was advertised over Tailscale,
and a down Docker bridge claimed `192.168.0.0/20`. No host networking was changed.
On 2026-11-18, a temporary host route through `192.168.86.1` on `wlp192s0`
restored access. Both ordinary kubectl and the Kubernetes MCP node-list call
succeeded without kubeconfig/TLS changes or an MCP restart. All five nodes were
Ready at API version `v1.36.5+k3s1`. This supersedes the connectivity blocker;
no route was changed by this implementation task.

The operator approved private hostname `langfuse`, new application/datastore
credentials, metadata-only tracing, the enrollment list below, and treating
initial telemetry as disposable. This does not approve publishing Git changes,
rotating existing credentials, enabling schedules or changing model providers.

The operator subsequently approved the proposed non-HA capacity budget and
privately generated all six infrastructure ciphertext manifests. Their identities,
encrypted key sets and 0600 file permissions were verified without displaying
values. Full verification passed with those files present. All six have now
successfully unsealed in the cluster. The operator explicitly authorized task commits, push, PR
creation/merge after checks, and the reviewed no-prune rollout while preserving
live Hermes v0.22.2.

An expired Vaultwarden helper session initially blocked ArgoCD access; the
operator unlocked it privately. The normal fixed-service MCP connection then
succeeded. Its actual 33 managed desired resources matched the pinned local
render exactly after tracking-ID and credential redaction. The bucket Sync hook
and Helm test pod account for the managed-resource API's two hook omissions.
Only Langfuse was registered through the root; its child then synced the exact
reviewed revisions with pruning, force and replace disabled. All four claims
bound and the bucket hook succeeded. Hermes remains on live v0.22.2.

The first readiness check found ClickHouse exiting 132 on the Xeon VM, which
lacks AVX2/x86-64-v3; web migrations consequently could not connect. This is a CPU
instruction compatibility failure, not evidence of insufficient CPU/RAM. The
correction targets the existing ARM64 Pi 5 worker `k3s-04`, whose exposed features
include LRCPC. The pinned image index includes ARM64. The correction was merged
through [PR #94](https://github.com/benkim0414/homelab/pull/94) at
`a0a38223b2b5b448f8e131b974f3e6fef6888983` after green PR and main checks. The
actual ArgoCD diff changed only its two node-selector entries. A selective
StatefulSet sync plus graceful restart of the stuck, never-Ready old pod moved
ClickHouse to `k3s-04` with its original PVC. The failed web pod was then
gracefully restarted without changing its template. No force deletion was used.

At 2026-11-18 10:19 AEDT, all six workload pods were Ready, all four original
claim/volume bindings were unchanged and healthy, and private HTTPS health and
readiness returned `{"status":"OK","version":"4.77.0"}` with valid TLS.
Unauthenticated `GET /api/public/v2/observations` returned 401. Only the Hermes
NetworkPolicy was selectively synced: real Hermes-to-web HTTP 200 was verified,
while all four datastore TCP paths were rejected. An unrelated-namespace probe
could not reach web or ClickHouse; both owned diagnostic pods were cleaned up.
See the [rollout record](../reports/2026-11-18-langfuse-rollout.md) for scope,
capacity caveats and still-pending checks. Both cluster profiles are now enabled
after private client-key replacement and a successful v0.22.2 restart. The
approved in-place expansion to 20Gi is complete; post-activation available space
was 9.14 GiB. Both scoped SDKs authenticated and exported verified zero-model
setup spans after restart; subsequent real cluster-turn privacy checks passed. See the
[scoped-source record](../reports/2026-11-18-langfuse-scoped-source.md), including
the potential project-key disclosure during endpoint verification.

**Scoped resilience acceptance passed:** previous traces survived a web-only
restart, and a real desktop `homelab-scientist` CLI turn completed despite injected
Langfuse connection failures. This does not establish cluster-client outage behavior,
slow-network latency or backup recovery; see the
[resilience record](../reports/2026-11-18-langfuse-resilience.md).
Desktop CLI real-turn privacy and per-turn grouping now pass in both
selected profiles; see the [desktop record](../reports/2026-11-18-langfuse-desktop-guard.md).
The operator confirmed old-key
revocation; the replacement Secret unsealed and both profiles passed private
post-restart authentication/export checks. Do not rerun either sealing
helper blindly over existing ciphertext, and do not rerun server bootstrap.

## Architecture and versions

| Component | Declaration |
| --- | --- |
| Namespace / Application / Helm release | `langfuse` |
| Official Helm chart | `langfuse` `2.2.4` from `https://langfuse.github.io/langfuse-k8s` |
| Web / worker | `docker.langfuse.com/langfuse/langfuse:4.77.0` / `docker.langfuse.com/langfuse/langfuse-worker:4.77.0` |
| PostgreSQL | Chart dependency `postgres` `1.6.3`, image `postgres:18` |
| Queue | Chart dependency `valkey` `0.9.4`, image `valkey/valkey:8.0`, persistent standalone, noeviction |
| Object store | Raw all-in-one Deployment, image `chrislusf/seaweedfs:4.23`; bundled subchart disabled |
| ClickHouse | Raw single-replica StatefulSet, `clickhouse/clickhouse-server:26.8.36.3` |
| Workstation endpoint | `https://langfuse.tailbd291c.ts.net` |
| Cluster endpoint | `http://langfuse-web.langfuse.svc.cluster.local:3000` |

The tailnet suffix was verified through normal `tailscale status` metadata.
The Langfuse ingress itself has not been created or verified. The Application
uses manual sync, no pruning or cascading deletion finalizer. All repository
sources stay on `main`; chart 2.2.4 is an exact pin. All six runtime images and
their init/hook uses are pinned to manifest-index digests. Anonymous registry
reads verified the tag/index hashes and Linux AMD64/ARM64 support on 2026-11-17;
this is not signature verification or native runtime validation. Do not substitute
`latest` or upgrade PostgreSQL as part of a tracing setup.

| Image | Manifest-index SHA-256 |
| --- | --- |
| Langfuse web 4.77.0 | `2b47d0ae63ae737996a58cc03536a73230c809a2371c230c9bea4b7653a0b6a0` |
| Langfuse worker 4.77.0 | `1bc3597ff4c953e98ff9ee474a7d634e97664e4df298fdf20f13ecc834c89438` |
| PostgreSQL 18 | `2ea8630df176ad090ec92136dee850397c5af8781e4bcf2e4162593691c61bbc` |
| Valkey 8.0 | `04b9002ae24bbe66687fb025052ed9bcebb54f8da3937338eb718d98d362887f` |
| SeaweedFS 4.23 | `c6d6fb84b081f1f09bb089184ff4b45d2f163a1bfa8b354d04cf400c6e06f242` |
| ClickHouse 26.8.36.3 | `d426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7` |

The chart's supported external ClickHouse configuration avoids introducing its
alpha ClickHouse operator, Keeper and cert-manager dependencies. The raw instance
is inside this namespace, has no Keeper, and uses nonclustered schema migrations.
There is no AI gateway, inference proxy, MCP connector, paid evaluator, provider
credential, public ingress, Funnel, SMTP or new scheduled workload.

### Audited deviations from the initial plan

The bundled SeaweedFS 4.23.0 subchart emits an SFTP credential Secret whenever
all-in-one mode is enabled, even with SFTP disabled. It includes random passwords
and an upstream SSH private-key literal. The same configuration defaults to a
cluster-wide pod-write ClusterRole. Do not accept either as harmless drift or
add a broad ignore/secret exception. `s3.deploy: false` disables that subchart;
`objectstore.yaml` declares only the required PVC, ConfigMap, server/service and
idempotent bucket-creation Sync hook. No chart fork or extra cluster permission
is needed. The raw server runs nonroot with no service-account token or added
capabilities; actual startup under this UID remains a live acceptance gate.

The bucket hook runs at wave -1 with the object store, after namespace/policies/
SealedSecrets and before the chart's default-wave web/worker. It checks existing
buckets, creates only `langfuse` when missing, then verifies presence; it never
deletes a bucket. Master/filer metadata are on the same persistent claim through
an explicit LevelDB directory. One-GiB volume files with a maximum of 16 leave
metadata/headroom within the 20 GiB claim; this is not a global data retention or
quota guarantee. Valkey also uses Recreate and explicit Argo claim protection.

`s3.mediaUpload.enabled: false` is not a server-side media-upload prohibition in
this chart: the helper still emits media bucket/credential settings. Capture
minimization is enforced by the clients. Batch export is disabled. The chart's
media size needs an explicit string to survive a Helm/PyYAML/schema roundtrip.
The verifier's report sanitizer now handles null empty Secret maps without
weakening redaction of nonempty maps; regression tests cover both behaviors.

## Capacity and persistence

Proposed requests are 1600m CPU and 5376 MiB memory before init/hook overhead.
Live preflight on 2026-11-18 found no node pressure and sufficient requested-resource
headroom. Web and worker target AMD64. ClickHouse targets the ARM64 Pi 5 worker
`k3s-04` because its pinned AMD64 image requires CPU instructions the Xeon lacks.
The earlier estimate placing all three on AMD64 left 600m CPU / about 3181 MiB;
moving ClickHouse's 500m CPU / 2048 MiB reservation off that node improves that
estimate without expanding the VM. Before the move, `k3s-04` requested 970m CPU /
1682 MiB; adding ClickHouse fits its observed request budget, though combined
limits can still exceed physical resources. The AMD64 node already had CPU limits at 373%
and memory limits at 142% of allocatable: fitting requests does not guarantee all
containers can simultaneously consume their limits. The operator approved this
non-HA budget; capacity must still be rechecked immediately before rollout.
All five Longhorn disks were Ready/Schedulable with substantial available space;
the StorageClass uses two replicas and reclaim policy Delete. The four claims
below are now Bound; preserve them during any placement correction.

| Store | Proposed Longhorn claim |
| --- | --- |
| PostgreSQL | 10 GiB |
| ClickHouse | 30 GiB, `langfuse-clickhouse-data` |
| Valkey | 5 GiB |
| SeaweedFS | 20 GiB |

Claims total 65 GiB before Longhorn replicas and filesystem headroom. Longhorn
replication is not a backup. Check the live StorageClass reclaim policy; a Delete
policy can destroy data on direct PVC/namespace deletion despite annotations.
Preserve every claim identity, retention annotation and PostgreSQL major version.
The SeaweedFS all-in-one Deployment uses Recreate to prevent concurrent writers.

This is non-HA personal observability. Initial traces are explicitly disposable;
there is no backup schedule, automated retention/deletion, or lossless client
spool. Review capacity manually. Metadata-only traces still contain potentially
sensitive IDs, timing, tool names, model names and usage.

## Stable secrets and owner initialization

Follow [Sealed Secrets operations](../docs/operations/sealed-secrets.md). Never
print Secret payloads, controller private keys, project keys or full rendered
manifests. Do not retrieve existing secrets to provision a new installation.

| Secret (namespace `langfuse`) | Required keys |
| --- | --- |
| `langfuse-app-credentials` | `salt`, `encryption-key`, `nextauth-secret` |
| `langfuse-bootstrap` | `email`, `password` |
| `langfuse-postgresql-auth` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `USERDB_USER`, `USERDB_PASSWORD` |
| `langfuse-redis-auth` | `default` |
| `langfuse-clickhouse-auth` | `password` |
| `langfuse-s3-auth` | `accessKey`, `secretKey`, `seaweedfs_s3_config` |

SALT and ENCRYPTION_KEY must remain stable across deploys and recovery. The chart
must not generate new credentials on every ArgoCD render. Its empty `langfuse-app`
Secret may exist but must have no generated data. All actual credential fields
reference the operator-provisioned SealedSecrets.

The live controller is 0.41.2. A matching checksum-verified `kubeseal` executable
was downloaded into the task worktree's ignored tool cache; fetching its public
sealing certificate succeeded. No private key or existing Secret value was read.
The operator runs this in a private terminal from the task worktree:

```bash
PATH="$PWD/verification/cache/bin:$PATH" python3 -B langfuse/seal-bootstrap.py
```

It prompts privately for the owner password, generates new datastore credentials,
and seals directly through stdin. The owner password must have at least 20
characters, match its confirmation, and contain no control characters. The prompt
states this minimum; validation reports a controlled reason without echoing input.
Sealing failures identify the stage while raw subprocess output stays withheld.
Save the owner password in the approved vault.
Only ciphertext manifests belong under this directory; never use a plaintext
placeholder to get verification passing. The helper refuses existing destinations;
re-running is not a rotation/recovery procedure.

Owner initialization environment goes only to web. Signup stays disabled. Verify
headless owner login through HTTPS after deployment; do not enable public signup
as an installation workaround. The bootstrap secret is sensitive persistent
configuration, not an expiring invitation. Removing it or its references later
requires review, not pruning.

## Networking

`network-policy.yaml` permits namespace-internal store traffic and DNS only.
Only Hermes pods labeled `app=hermes` and the designated Tailscale ingress proxy
may reach the web API on TCP 3000 from outside the namespace. The Hermes egress
exception matches the web labels and port only; it does not permit datastore
access or all private addresses. Existing HA, browser, Hindsight and DNS rules
are preserved.

Namespace-internal traffic is trusted, not per-store microsegmentation. Service
traffic inside the cluster is HTTP, not encrypted transport. Validate NetworkPolicy
enforcement on the installed CNI, including denial from unrelated namespaces and
Hermes-to-datastore denial. Never loosen the policy for an unrelated feature.
Kubelet/node paths can be exceptions to NetworkPolicy.

Tailscale terminates HTTPS and does not replace Langfuse login/project auth. Check
for a stale `langfuse` device before creating the ingress; do not delete devices
or change ACLs without separate approval.

## Local verification

Run from the implementation worktree after reading the bootstrap script:

```bash
python3 verification/bootstrap.py
verification/venv/bin/python -m unittest discover -s verification/tests -v
verification/cache/bin/conftest verify --policy verification/policy
verification/venv/bin/python scripts/verify.py --all --base main
git diff --check
```

Offline verification is partial and does not authorize rollout. Inspect the
pinned chart's PostgreSQL init scripts and the raw SeaweedFS bucket hook before
executing them. Require a deterministic render with one bucket `langfuse`, no destructive
hook, no additional controller/CRDs or unexpected Secret payloads, four persistent
stores and the intended security/resource settings. See the tests for static
contracts and the rollout report for actual executed results.

## Manual deployment

Follow the [pre-sync checklist](../argocd/README.md#verification-before-manual-sync).
Record the exact published commit and green Verify status; stop if `main` advances
before the reviewed sync. Inspect the root separately from its child. Preserve
manual sync and never use prune, force, replace or cascading deletion.

```bash
argocd app diff apps
argocd app sync apps --resource argoproj.io:Application:langfuse
argocd app diff langfuse
argocd app sync langfuse
argocd app wait langfuse --sync --health --timeout 600
kubectl -n langfuse get pods,pvc,svc,ingress
kubectl -n langfuse get sealedsecrets,jobs
curl --fail --silent --show-error --max-time 15 https://langfuse.tailbd291c.ts.net/api/public/health
curl --fail --silent --show-error --max-time 15 https://langfuse.tailbd291c.ts.net/api/public/ready
```

Expected after an authorized rollout: reviewed revisions Synced/Healthy, four
Bound claims, six Synced SealedSecrets, completed bucket creation, HTTP 200 health
and readiness with valid TLS, and owner login. The observed server results are recorded in the
[rollout report](../reports/2026-11-18-langfuse-rollout.md); owner login and
authenticated client tracing remain separate acceptance steps.

## Hermes projects, versions and enrollment

Create two projects under organization `Homelab`: `hermes-cluster` and
`hermes-desktop`. Use their project-scoped ingestion key pairs, never admin API
credentials. Keep keys private and never put them in command arguments, a
ConfigMap, documentation or chat. For stronger profile isolation, use individual
project/key pairs rather than treating tags as an authorization boundary.

Approved enrollment:

| Location | Profiles | Plugin |
| --- | --- | --- |
| Workstation | `homelab-scientist`, `default` | Existing bundled `observability/langfuse` |
| In-cluster | default, existing `house-manager` | Live v0.22.2 uses catalog `langfuse`, not a bundled copy |

The workstation source inspected during planning was `2237be3559` with pyproject
version 0.21.1 and the bundled plugin. Live cluster inspection on 2026-11-18 found
v0.22.2 (upstream `d923a5eb`), no bundled Langfuse plugin or SDK, and catalog plugin
2.0.0 pinned to `c2a95963c442f3f23e4bc6fe0da898e1dd1fb63d`. That exact plugin's
pyproject pins SDK `langfuse==4.15.2`. The repository's pending v0.23.1 image would
instead select catalog commit `e7a218f26db88426ab3e7376f0e000b6e356f5e7`; it is not
the current live image and is not authorized by the tracing rollout.
Do not upgrade core or enable both plugin names. Recheck installed versions before
configuration; an absent/disabled SDK or client is fail-open and not proof of
working tracing.

### Cluster

Create Secret `hermes-langfuse` in namespace `hermes`, keys `public-key` and
`secret-key`, through the approved private input/sealing workflow. Its encrypted
manifest is `hermes/profiles/house-manager/langfuse-sealed-secret.yaml`, selected by the Hermes Application.
Server credentials and the cluster client Secret are now unsealed. Client
provisioning was published through PR #96; do not rerun the helper over the
existing ciphertext. The following is the original private provisioning command,
not a command to repeat for routine setup checks:

```bash
PATH="$PWD/verification/cache/bin:$PATH" python3 -B langfuse/seal-hermes-client.py
```

Enter only the `hermes-cluster` key pair, with secret-key confirmation. The
helper authenticates a read-only GET to the fixed private HTTPS project endpoint,
requires the single returned project to be `hermes-cluster`, refuses redirects,
then reuses strict sealing and atomic no-overwrite ciphertext publication. It
writes only `hermes/profiles/house-manager/langfuse-sealed-secret.yaml` at mode 0600. No plaintext files,
credential arguments, existing Secret reads or cluster apply are supported. Do
not rerun the six-server bootstrap. Review/publish the client ciphertext and
verify unsealing before consuming it; root registration must include the new
Hermes Application file selection before a selective client-Secret sync.

PR #96 merged at `7ef3c7f496c48c37e685a44129350b37dd315d0c` after successful
PR/main CI. Root registration changed only Hermes Application file selection;
it also exposes already-pending browser/Herdr files for comparison, but none of
those child resources were synced. Only `SealedSecret/hermes-langfuse` was then
selectively synced and verified Synced, with the generated Secret present.

Pinned catalog plugin 2.0.0 is installed separately for cluster default and
house-manager, under each profile's own `plugins/langfuse` directory. Both are
currently enabled with built-in tool override permission false.
PM's writable store is `/opt/data/tools`, and its runtime facts live under
`/opt/data/installs`; those paths persist on the PVC. SDK 4.15.2 imports from the
committed environment after container recreation. Both scoped SDK clients passed
authentication and setup-span export/readback after the correction below; this is
not real model/tool tracing acceptance.

The operator subsequently confirmed Hermes was idle and approved restarting it.
Applied only the seven declared tracing environment entries using a guarded
env-only patch; server dry-run and readback verified the remaining Deployment
specification was unchanged. Enabled both plugins as UID/GID 10000 with
`--no-allow-tool-override`, preserving private owner-only settings backups and
verifying settings outside Langfuse plugin bookkeeping were unchanged. The env
rollout and final controlled restart completed successfully with live v0.22.2
preserved and the replacement pod Ready. This supersedes the earlier restart
pause; do not assume that idle approval extends to a later operational window.

The approved correction mounts `hermes-langfuse` read-only at
`/var/run/hermes-langfuse` and the tested helper ConfigMap at `/langfuse-key-source`.
Each selected profile now has a native `secrets.command` source pointing to
`/opt/hermes/.venv/bin/python -B /langfuse-key-source/langfuse-key-source.py`, with
`enabled: true`, `helper_timeout_seconds: 3`, `override_existing: false`.
Neither had a previous command source or explicit source ordering. Preserve those
if adapting this setup elsewhere; do not overwrite an unrelated credential source.

**Critical:** `_build_client()` uses `_secret()` for BASE_URL, ENV and SAMPLE_RATE
as well as credentials. Its `_env()` status helper seeing the private pod URL is
not proof of the constructor's destination. A key-only scope falls back to
Langfuse Cloud. The first scoped authentication attempt may have disclosed this
self-hosted project pair there; it returned Unauthorized before any setup span.
The source now supplies both keys and all four fixed scoped settings atomically,
and the probe asserts the exact scoped internal URL **before constructing the
SDK or making any network call**. Normal source hydration must precede scope
construction. Do not globalize credentials or copy another profile's keys.

Never run the helper directly to troubleshoot: stdout is credential IPC consumed
and captured by Hermes. Use scoped SDK checks with pre-network URL guards.
Both selected scopes authenticated and their zero-model setup spans were read
back through v2 observations with empty input/output. House-manager re-enablement
then failed on package-manager storage capacity: five root managed environments
used about 8.19 GiB, leaving about 0.87 GiB free. No environment was deleted and
no PVC was expanded. Both profiles were left paused; default was paused with the
supported native config setter rather than attempting another environment build.
The operator then approved expansion to 20Gi: it completed online with the same
PVC/PV identity and about 10.71 GiB available at verification. No environments
were deleted. The operator subsequently entered replacement credentials privately,
confirmed revocation and a fresh idle window, and both profiles were activated
and restarted successfully. New post-restart private scoped setup spans passed
v2 readback with empty input/output. See the scoped-source record above for the
remaining real agent-turn, persistence/outage and desktop acceptance gates.

`hermes/profiles/house-manager/deployment.yaml` supplies a common cluster project key pair to the process.
Both selected profiles share this trusted-pod credential boundary; future profiles
are not automatically enrolled. Enable the plugin only on the allowlist. The
launch environment sets the internal URL, metadata capture, `homelab-cluster`,
service name `hermes-cluster` and sample rate 1. Do not replace the writable PVC
config with `hermes/profiles/house-manager/configmap.yaml`; that file is only an absent-file seed.

Run the actual installed CLI as application UID 10000, not as root.
`s6-setuidgid` was not found on the live image's PATH. A verified alternative is
to drop supplementary groups/GID/UID before execing its actual CLI:

```bash
kubectl -n hermes exec deployment/hermes -c hermes -- /opt/hermes/.venv/bin/python -B -c \
  'import os; os.setgroups([]); os.setgid(10000); os.setuid(10000); os.execv("/opt/hermes/bin/hermes", ["hermes", "--version"])'
```

Live `plugins install --help` supports `--ref COMMIT_SHA`, `--yes-deps` and
`--no-enable`; never use `--force` or `--allow-removed` as a setup workaround.
Use the reviewed live catalog pin above, rather than upgrading core. Install the
catalog plugin and enable only the selected
profiles through supported commands; the named profile uses `hermes -p house-manager`.
Preserve config with a private owner-only backup and preserve selected providers,
model routing, OAuth, MCP filters and tools. Confirm plugin dependencies survive
container replacement; do not install into an ephemeral image-only path.

A Hermes rollout uses Recreate and interrupts active chats. Agree an idle point,
review the whole diff and deploy the client Secret first, then only the reviewed
network policy/tracing fields. Do not sync the whole repository Deployment:
it would also install the pending v0.23.1 image. Use a reviewed guarded env-only
patch against the live container, preserving image, command, mounts and resources;
the corresponding tracing fields are already declared in Git. Keep the unrelated
image-upgrade drift explicit and do not alter its repository pin. Do not sync
unrelated resources just to enable tracing.
Verify readiness/auth probes and actual profiles after restart.

### Private cluster project-key replacement

The operator approved this workflow after the potential disclosure described
above. Keep tracing paused. In the private Langfuse UI, create a replacement
project-scoped API key pair for **hermes-cluster**, store it privately, and revoke
the old potentially disclosed cluster pair. Do not change desktop-project,
owner-login, inference-provider or server-bootstrap credentials.

From this task worktree in a private terminal:

```bash
PATH="$PWD/verification/cache/bin:$PATH" python3 -B langfuse/rotate-hermes-client.py
```

Enter only the new cluster pair at hidden prompts. The helper verifies the single
expected project at the fixed private HTTPS endpoint with redirects blocked,
strictly seals it for `hermes/hermes-langfuse`, and atomically replaces only the
client ciphertext after validation. It retains the previous ciphertext under
ignored `verification/cache/rotation-*/previous-ciphertext.yaml` with owner-only
permissions. Do not edit the manifest concurrently: helper instances serialize,
but the final stat-check/rename is not an OS-level compare-and-swap against other
writers. Never restore a revoked pair just because its ciphertext was backed up.

No plaintext credential files, key revocation, cluster apply, commit or push are
performed by the helper. On success, report only its success line and whether
the old pair was revoked; never send keys in chat. Review and apply the new
SealedSecret separately, verify unsealing, then activate the selected profiles
and restart in a confirmed idle window. Do not rerun either initial sealing helper
or server bootstrap. On failure, inspect ciphertext state privately before retrying.

### Workstation

Do not modify profile credentials until the server/project keys exist. Install the
reviewed SDK in Hermes' real interpreter, not global Python:

```bash
uv pip install --python /home/benkim0414/.hermes/hermes-agent/venv/bin/python \
  'langfuse==4.15.2' 'opentelemetry-api==1.39.1' \
  'opentelemetry-sdk==1.39.1' 'opentelemetry-exporter-otlp-proto-http==1.39.1'
```

The inspected desktop runtime reports v0.21.1, upstream `3f5a11f6`, Python
3.11.18. SDK 4.15.2 is now installed and imports successfully. The existing
OpenTelemetry API 1.39.1 was preserved rather than upgraded; all 136 installed
packages passed the dependency check. The operator subsequently staged desktop
keys privately for both selected profiles. The guarded user plugin is now
installed and enabled in both; the bundled plugin remains disabled. Native-loader
setup export and fail-closed negative checks passed. Real desktop no-tool/tool
privacy checks subsequently passed for both profiles. Trace-ID reuse was found
and corrected in guard v1.0.1, installed in both profiles. Separate real no-tool
and terminal-tool turns in new sessions now pass privacy and distinct-trace checks
with stable session grouping. Older processes must be relaunched to load the fix. See the
[desktop guard verification](../reports/2026-11-18-langfuse-desktop-guard.md).
Do not repeat key provisioning for already staged profiles.

The inspected tools checklist does not expose Langfuse, despite its provider
registration in the source. Do not toggle unrelated tools to find it. Use the
operator-private helper below instead. It uses hidden prompts, verifies that the
pair belongs only to `hermes-desktop` through fixed HTTPS with redirects blocked,
and saves only project keys through Hermes' native credential writer. Settings
remain in the launch environment. Never print `.env`, auth.json or credentials.

From this task worktree in a private terminal, run separately for each profile:

```bash
/home/benkim0414/.hermes/hermes-agent/venv/bin/python -B langfuse/setup-desktop.py homelab-scientist
/home/benkim0414/.hermes/hermes-agent/venv/bin/python -B langfuse/setup-desktop.py default
```

The helper refuses enabled plugins, existing project keys, unsafe credential-file
permissions and noninteractive entry. It leaves tracing disabled. Keys are stored
in the selected profile's normal plaintext credential file, not encrypted, with
no extra copies. The native pair write is not atomic: on a write failure leave
tracing disabled and inspect privately before retrying. Do not edit credentials
concurrently. Before enabling either profile, verify the actual launcher endpoint
and metadata capture with scoped/runtime checks; key entry alone is not tracing
acceptance. The tools wizard's post-setup hook auto-enables the plugin if invoked
through another route, so it is unsuitable for disabled credential staging.

Desktop activation uses the separate repository-managed native user plugin
`homelab-langfuse-desktop`, not the unguarded bundled plugin. Keep both bundled
identifiers (`langfuse` and `observability/langfuse`) disabled. The guard requires
the exact private HTTPS endpoint, metadata capture, desktop environment and sample
rate supplied by the launcher; missing or changed policy must produce no tracing.
Its delegated capture mode is fixed to metadata, even if the environment changes
after registration. It binds one profile home, rejects multiplexed execution and
pins the reviewed bundled source. Source drift requires review, not a blind pin
update. Separate clean processes per desktop profile avoid SDK resource sharing.

`install-desktop-guard.py PROFILE` copies only reviewed local plugin code and
verifies its readback. It never enables plugins, reads credentials or replaces a
different existing installation. Validate the guard and its negative controls
before enabling it with the supported plugin CLI. Do not enable the bundled
plugin as a fallback when the guard refuses admission.

Start new processes with the launcher; existing processes are not restarted by
installation. Plain `hermes` without the required settings must remain untraced,
not silently use Cloud or sanitized content. Native/remote backends need their
own verified launch environment; an interactive shell wrapper does not configure
them. Multiplexed desktop backends are outside this initial guarded CLI enrollment.

```bash
bash scripts/hermes-langfuse-desktop.sh homelab-scientist
bash scripts/hermes-langfuse-desktop.sh default
```

For a native Desktop UI, first verify that the installed version supports that
command and configure its actual local backend launch environment. A Desktop UI
connected to the cluster executes there; do not trace the same turn again locally.
No existing desktop launcher/autostart is changed by repository preparation.

## End-to-end acceptance

Run a zero-model-cost authenticated SDK check without displaying keys, then one
small no-tool and one harmless tool turn on every selected profile. Preserve the
operator-selected inference provider/model and use configured authentication;
OAuth/quota failure is a blocker, not permission to switch providers. Also send a
turn from the actual browser/native UI surface; CLI-only evidence is insufficient
for a different backend process.

Expected in each source's project within 120 seconds:

- One `Hermes turn`, its generation observation and a tool observation for the
  tool test, correctly associated with session and source/environment.
- Metadata-only capture proven from omission stubs, without prompt, response,
  memory, tool arguments/results or system prompt payloads.
- Timing and available token usage, no duplicate bundled/catalog observations.
- Profile metadata where supported. Older plugin versions may instead require
  project/service/session evidence; report that limit explicitly.

Use timestamps/session/trace IDs to find metadata-only traces, not the prompt
text. A trace health check alone does not establish real ingestion. Subscription
cost estimates are not subscription billing. Record trace IDs and statuses only,
not payloads, in the rollout report.

For this v4 server, use the current `/api/public/v2/observations` API with a
bounded time window and trace ID; include the `io` field group when checking
metadata-only omission stubs. Trace-level input/output are reconstructed from
root observations, not legacy trace fields. The deprecated `/api/public/traces`
route returns 404 here; that is not an authentication test. The supported
observations endpoint returned 401 without credentials. See the
[v4 API migration guide](https://langfuse.com/faq/all/deprecated-api-migration).

Verify previous traces survive a web-only restart and that normal agent work
continues in a controlled disposable-client backend-outage test. The older
bundled plugin may flush at session end and add shutdown delay. Neither version
provides a durable offline spool or lossless/exactly-once export.

The 2026-11-18 [scoped resilience check](../reports/2026-11-18-langfuse-resilience.md)
passed these checks with preserved desktop observation identities, post-restart
cluster trace readbacks and one real desktop CLI turn under immediate transport
failures. Stalled networking, other clients and datastore recovery were not tested.

## Recovery and backup status

No backup schedule or retention automation is enabled. Initial traces may be lost
under the approved disposable-data policy. See [NAS storage](../nas/README.md)
and [Sealed Secrets recovery](../docs/operations/sealed-secrets.md); NAS snapshots
do not back up Longhorn database volumes automatically.

Before treating the installation as durable, separately approve and test a
coordinated backup/restore of PostgreSQL, ClickHouse schema/data, SeaweedFS object
and metadata state, Valkey queues, and the stable application/sealing keys.
Restore to isolated new volumes and prove old trace IDs and owner login before
claiming recovery. An image rollback cannot reverse every schema migration.

The [coordinated recovery proposal](BACKUP.md) documents the approval gates,
confidential recovery-set contents, writer coordination, isolated restore and
acceptance criteria. It is a proposal, not an implemented or tested backup.
No schedule, secret export, archive creation or restore is enabled by publishing it.

Immediate client rollback: disable only the selected version-appropriate plugin
with `hermes [-p PROFILE] plugins disable NAME` and restart affected idle processes
if needed. Revert only this change's env/egress/reference edits through review;
never overwrite the whole live config or change model/auth settings. Keep all
server claims, namespace, ciphertext and data intact. Do not prune, uninstall,
cascade-delete, force-replace, or rotate keys as a rollback shortcut.
