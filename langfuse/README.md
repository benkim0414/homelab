# Langfuse

Private LLM observability for the selected Hermes profiles. This directory declares
an installation; it does not establish that it is deployed or collecting traces.

## Implementation status

Published through [PR #93](https://github.com/benkim0414/homelab/pull/93), merged
as `e5db120844277b1a8e9437dc300035921b23b779` after green PR checks. The
[main-branch Verify run](https://github.com/benkim0414/homelab/actions/runs/44189306576)
also succeeded at that exact revision. The initial reviewed no-prune rollout has
now run, but server readiness and tracing acceptance are not yet complete.
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
include LRCPC. The pinned image index includes ARM64. Runtime acceptance of this
placement correction is still pending; do not enable clients yet.

**Rollout gates:** publish/review/sync the placement correction and verify server
readiness; create client projects/keys; seal the Hermes client credentials; then
roll out and enroll agents. Do not sync the Hermes Deployment before its
`hermes-langfuse` Secret exists and the server is healthy.

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
and readiness with valid TLS, and owner login. These are expected results, not
recorded deployment successes.

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
manifest is `hermes/langfuse-sealed-secret.yaml`, selected by the Hermes Application.
The six server ciphertext files have been generated privately and validated locally;
this client ciphertext is still pending creation of its Langfuse project/keys.
Check unsealing before consuming either set.

`hermes/deployment.yaml` supplies a common cluster project key pair to the process.
Both selected profiles share this trusted-pod credential boundary; future profiles
are not automatically enrolled. Enable the plugin only on the allowlist. The
launch environment sets the internal URL, metadata capture, `homelab-cluster`,
service name `hermes-cluster` and sample rate 1. Do not replace the writable PVC
config with `hermes/configmap.yaml`; that file is only an absent-file seed.

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
it would also install the pending v0.23.1 image. Use a reviewed env-only strategic
patch against the live container, preserving image, command, mounts and resources;
the corresponding tracing fields are already declared in Git. Keep the unrelated
image-upgrade drift explicit and do not alter its repository pin. Do not sync
unrelated resources just to enable tracing.
Verify readiness/auth probes and actual profiles after restart.

### Workstation

Do not modify profile credentials until the server/project keys exist. Install the
reviewed SDK in Hermes' real interpreter, not global Python:

```bash
uv pip install --python /home/benkim0414/.hermes/hermes-agent/venv/bin/python 'langfuse==4.15.2'
```

Use the selected profile's supported private credential wizard to store only
project keys. Noncredentials are launch environment settings, not API keys. Never
open or print `.env`, auth.json or another profile's credentials for diagnostics.
For each approved profile, run the interactive wizard in a private terminal:

```bash
bash scripts/hermes-langfuse-desktop.sh homelab-scientist tools
hermes -p homelab-scientist plugins enable observability/langfuse
hermes -p homelab-scientist plugins list
bash scripts/hermes-langfuse-desktop.sh default tools
hermes -p default plugins enable observability/langfuse
hermes -p default plugins list
```

Select Langfuse Observability, enter only the desktop project credentials and
verify that the self-hosted launch URL is retained, rather than Langfuse Cloud.
Start new processes with the launcher; a running process may cache the no-client
state. Plain `hermes` launched without this environment is not claimed configured.

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

Verify previous traces survive a web-only restart and that normal agent work
continues in a controlled disposable-client backend-outage test. The older
bundled plugin may flush at session end and add shutdown delay. Neither version
provides a durable offline spool or lossless/exactly-once export.

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

Immediate client rollback: disable only the selected version-appropriate plugin
with `hermes [-p PROFILE] plugins disable NAME` and restart affected idle processes
if needed. Revert only this change's env/egress/reference edits through review;
never overwrite the whole live config or change model/auth settings. Keep all
server claims, namespace, ciphertext and data intact. Do not prune, uninstall,
cascade-delete, force-replace, or rotate keys as a rollback shortcut.
