# Hermes Agent

Persistent terminal access through a separate Herdr pod is described in
[the Herdr runbook](../herdr/README.md). It uses Kubernetes exec and does not require
rebuilding the official Hermes image.

One personal Hermes agent with browser chat over Tailscale HTTPS. The ArgoCD
Application tracks `main`, uses manual sync, and has no cascading-delete finalizer.
This directory declares the deployment; it is not evidence of a live rollout.

## Runtime and storage

| Setting | Declaration |
| --- | --- |
| Namespace / Application | `hermes` |
| Image | `nousresearch/hermes-agent:v0.23.1`, pinned to a multiarch index digest |
| Architectures | Registry index inspected on 2026-11-12: Linux AMD64 and ARM64 |
| Processes | Official s6 entrypoint, gateway and dashboard in one container |
| Dashboard | Port 9119; `https://hermes.<tailnet>.ts.net` |
| Provider | `openai-codex`; select an account-supported model during bootstrap |
| Data | `hermes-data`, 10 GiB Longhorn RWO, mounted at `/opt/data` |
| Workspace | `/opt/data/workspace`; tool HOME is `/opt/data/home` |
| Resources | Request 250m CPU / 1 GiB; limit 2 CPU / 2 GiB |

The image index digest is
`sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`.
The reviewed registry release tag is `v0.23.1` (including `v`). The gateway,
init container, browser and both backup runners must use the same reviewed image. Renovate includes this directory for proposals;
updates remain subject to review and manual sync.

The official image requires root for s6 bootstrap, ownership repair, and privilege
drop. Application processes run as UID/GID 10000. The manifest drops all
capabilities and adds only CHOWN, DAC_OVERRIDE, FOWNER, KILL, SETGID and SETUID for
bootstrap/supervision, sets `allowPrivilegeEscalation: false` and RuntimeDefault
seccomp, and preserves the image entrypoint. Do not force the main container to
`runAsNonRoot` or bypass s6. A live smoke test must confirm this capability set
works with the cluster runtime before rollout is considered verified.

One replica and `Recreate` avoid overlapping gateway writers. RWO alone does not
prevent two pods on the same node from sharing state. Never force a replacement
on another node until an unreachable old node is fenced. The Longhorn block
volume supplies a native filesystem for SQLite WAL; do not move this state to NFS.
PVC annotations prevent normal ArgoCD pruning/deletion, but the Longhorn class
has reclaim policy **Delete**: direct PVC/namespace deletion can destroy data.
Replication is not a backup.

## Upgrade review: v0.23.1 (prepared, not deployed)

The [official container guide](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
and [updating guide](https://hermes-agent.nousresearch.com/docs/getting-started/updating)
require replacing the image while keeping the same data mount, not running
`hermes update` in the container or on the workstation. Startup performs
noninteractive config-schema migrations and writes adjacent config/env backups.
These are not a replacement for a completed whole-volume NAS backup.

Review [v0.23.0 upgrade notes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.0)
and [v0.23.1](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.1)
before a separately authorized manual sync. The gateway now owns local sessions;
cutover-interrupted work is not automatically replayed and rollback needs
pre-upgrade state, not just the old image. Migration v51 retires the Bot Chat
delivery timeout. Migration v52 removes `browser.backend` and
`browser.extension_control` and migrates legacy browser environment settings;
review/approve those persisted-config changes before startup rather than editing
the seed in this image-only change. Legacy browser tools/agent-browser were
removed in favor of `browser_exec`, which this deployment already uses with its
separate CDP browser.
Migration v53 also changes the stale default `agent.clarify_timeout: 3600` to
`90`; v0.23.1 therefore uses config schema 53, not merely 52. Preserve the
selected provider/model and review this timeout effect as part of the persisted
configuration migration. Synthetic schema50 -> 53 tests passed, but do not
establish actual configuration, browser or authenticated session-owner acceptance.
Recheck Chromium paths, the tailored node seccomp profile, renderer sandboxing,
idle cleanup, dashboard probes and Herdr CLI attachment against the new image.
The seed deliberately disables the API server; compatibility of the new
session-owner client path with that posture needs an isolated test. Do not enable
the API server, Webapp, schedules or messaging to work around a failure.

The upstream unset-model default changes to GLM-5.3. Preserve the selected
subscription model and auxiliary routes; do not accept a new default or fallback
without approval. Prepared compaction, Daybreak, plugin auto-update and alternate
delegation routing are opt-in and are not enabled here. No config/profile/auth
migration has been executed or approved by this image-only preparation.

## Credentials and configuration

The namespace-scoped `dashboard-sealed-secret.yaml` provisions the dashboard
Secret in namespace `hermes`. It requires the existing controller's sealing key;
follow the [Sealed Secrets workflow](../docs/operations/sealed-secrets.md) for
rotation or recovery. No plaintext credentials or placeholder Secret payloads
belong in Git.

| Secret | Required key | Value |
| --- | --- | --- |
| `hermes-dashboard-auth` | `username` | Personal dashboard login name |
| `hermes-dashboard-auth` | `password-hash` | Hermes scrypt hash of a strong password |
| `hermes-dashboard-auth` | `session-secret` | Stable signing secret with at least 32 random bytes |

Use the pinned image's `plugins.dashboard_auth.basic.hash_password` function to
generate the hash, with the password read interactively rather than placed in
shell history or process arguments. Pass resulting values to the sealing workflow
through a protected local file or stdin, without printing them. Preserve the
encrypted manifest in the Application include glob. Rotate the signing key
deliberately; it invalidates sessions.

Hermes stores its dedicated OAuth grant in `/opt/data/auth.json` and updates it
as tokens rotate. Do not mount a read-only Secret snapshot there, copy a
workstation/Hindsight grant, or restore old rotating credentials from backup.
`auth.adopt_external_logins: false` prevents borrowing another CLI's login.
No OpenAI API key, API fallback, messaging credentials, Kubernetes token, host
filesystem, or container-runtime socket is supplied.

`configmap.yaml` is a **first-boot seed**, copied only when `config.yaml` is absent.
The writable live config, model selection, sessions, skills, memory, and tool
files persist on the PVC. Updating the ConfigMap does not overwrite an existing
installation. Apply reviewed ongoing changes with `hermes config set` or the
dashboard and record the corresponding seed/runbook changes in Git. Do not delete
the live config to apply an update.

The same init container seeds workspace `AGENTS.md` only when absent, including
on an existing installation's next rollout. It uses exclusive creation to
preserve an existing file or symlink. These instructions cover credential
handling, workspace use, subscription-only inference, and changes requiring the
operator's approval. They guide behavior and do not restrict shell access.
Updates to the seed do not replace an existing workspace instruction file;
review and apply later instruction changes separately.

Startup and liveness use the lightweight, local `/api/health` endpoint and
validate its JSON `ok` and `version` fields. Readiness validates `/api/status`:
authentication must be required with the `basic` provider, and the dashboard and
storage components must report `ok`. The probe script is mounted read-only from
the ConfigMap, bypasses HTTP proxies and redirects, bounds response size and
uses no credential or model request. Authentication drift makes the pod unready
without causing a liveness restart loop. Gateway/channel state, resource advisory
fields and upstream OAuth/quota are outside this readiness decision: browser
chat has its own PTY process and must not be disabled by a messaging outage.

The seed records the assigned dashboard origin and the declined shared-metrics
offer (`enabled: false`, `send: false`, `offer_version: 2`). In 0.22.2, the offer
version is needed to keep the first dashboard visit from asking again despite
metrics already being disabled.

The initial CLI/browser-chat toolsets cover local commands, files, skills, memory,
session search, task lists and headless browsing, plus the `hindsight_reserve` MCP tools described
below. Optional paid web/image/voice tools and lazy dependency installation are
not configured. The main provider and configured auxiliary tasks use Codex OAuth,
with no fallback chain. Leave the
model unset until completing `hermes model`; do not send the first prompt before
selection. Background reviews and session summaries can consume additional quota.
Hermes documents the subscription integration, but not exact eligible tiers or
quota accounting; verify entitlement with a small request. There is no promise
of unlimited usage.

### Native browser in an isolated pod

Hermes uses its native `browser_exec` interface with a private CDP connection to
`hermes-browser.hermes.svc.cluster.local:9222`. The old 0.22.2 configuration used
`browser.backend: browser-use`; the 0.23.1 migrator removes that backend selector
and `browser.extension_control`, while retaining the explicit local/CDP routing.
`browser.cloud_provider: local` prevents cloud autodetection; no browser API key,
desktop or extra MCP server is required. The browser workload reuses Chromium
from the same digest-pinned Hermes image, but overrides its root/s6 entrypoint
and runs only the browser bridge as UID/GID 10000. The local `agent-browser`
helper is not needed with this CDP override.

The browser pod runs on `k3s-05` with `hostUsers: false`, all capabilities
dropped, no privilege escalation, a read-only root filesystem and the
`Localhost` seccomp profile `hermes/browser-amd64-v1.json`. No Chromium sandbox
disable flags are used. The pod mounts no PVC, credentials, host files or service
account token. `/tmp` and `/dev/shm` are bounded emptyDir volumes; browser memory
is limited to 2 GiB independently of Hermes. The native tools still execute
model-written Python in Hermes's existing environment; separating Chromium does
not isolate Hermes's Python or terminal tools.

`browser.yaml` exposes only a ClusterIP service. Ingress permits the Hermes pod
on TCP 9222; egress permits CoreDNS and public IPv4 HTTPS, excluding private,
link-local and other reserved ranges. No Ingress resource, Tailscale exposure,
HTTP egress or Hindsight exception is added. Kubernetes NetworkPolicy is not
an absolute host boundary: traffic to the hosting node and loopback can be
exceptions, and permitted DNS traffic remains possible. Validate policies with
the installed CNI; do not treat `security.allow_private_urls` as a firewall.

The bridge exposes only CDP discovery, WebSocket forwarding and a local health
endpoint. Chromium listens on loopback port 9223; the bridge rewrites discovery
to the private service address, without trusting the request Host header.
Requests carrying an Origin header
are rejected, including browser WebSocket attempts from webpages that can reach
the pod’s loopback. This protects the bridge in addition to its NetworkPolicy.
Profiles are temporary. After 600 seconds without client CDP messages, the bridge
terminates Chromium and deletes its profile. Browser-generated events and health
probes do not renew the lease. Active use can retain cookies for longer; no
absolute session lifetime is enforced. Do not import personal profiles or logins.
The fixed CDP endpoint represents **one shared browser for one trusted operator**:
named Hermes sessions do not establish independent browser profiles here. Serialize
unrelated or sensitive tasks and explicitly close/reset the browser between them;
do not use this deployment as a multi-user or concurrent tenant service.

#### Node prerequisite and rollout

Install the profile before creating the browser pod. From a task worktree, with
node-change and SSH authorization plus a verified guest host key:

```bash
ANSIBLE_LOCAL_TEMP="$PWD/verification/cache/ansible-tmp" \
ANSIBLE_SSH_ARGS='-C -o ControlMaster=no' \
ansible-playbook -i k3s-ansible/inventory.yml k3s-ansible/browser-seccomp.yml \
  --limit 192.168.0.22
```

The playbook installs only `/var/lib/kubelet/seccomp/hermes/browser-amd64-v1.json`
with root ownership and mode 0644. It does not restart K3s, change runtime defaults,
or affect other pods. Rebuilt or replacement nodes need this prerequisite again;
a missing profile fails container creation. See the
[profile provenance](../k3s-ansible/files/README.md). Review profile compatibility
when updating the image, kernel or runtime. Image digest pinning ensures
reproducibility, not security freshness: maintain browser security updates with
the upstream Hermes release and recheck renderer sandboxing after upgrades.

`browser-configmap.yaml` embeds `browser-server.py`; keep the two identical.
Regenerate the ConfigMap from the source with the verifier's PyYAML environment:

```bash
verification/venv/bin/python hermes/render-browser.py
```

The Hermes Application includes `browser*.yaml` and keeps manual sync. Rollout
must install the browser NetworkPolicy before its Deployment; apply the ConfigMap
and service, then verify the browser before adding Hermes's egress rule and CDP
setting. The generator updates pod-template checksums for script/profile changes;
a Deployment apply recreates the browser pod to load them.
Do not sync unrelated Hermes resources or enable pruning during this rollout.

The bootstrap ConfigMap seeds only absent files. For an existing installation,
preserve `/opt/data/config.yaml` in an owner-only backup, then update only the
CLI browser toolset and the browser fields shown in `configmap.yaml`, preserving
all model, MCP, credential and security settings. Retain UID/GID 10000 ownership
and mode 0600. Start a new chat; restart Hermes only if configuration reload needs
it. Never replace the live configuration with the bootstrap seed.

Bridge regression checks run locally for the generated manifests and inside the
browser image for aiohttp behavior. With authorized live pod-exec access:

```bash
kubectl -n hermes exec -i deployment/hermes-browser -- \
  env HERMES_BROWSER_SOURCE=/browser/browser-server.py \
  /opt/hermes/.venv/bin/python -B -c \
  '__file__="/tmp/verification/tests/test_hermes_browser.py"; import sys; exec(compile(sys.stdin.read(), __file__, "exec"))' \
  < verification/tests/test_hermes_browser.py
```

Acceptance requires a native-tool public HTTPS navigation and reading test,
a harmless interaction, active renderer namespace/seccomp inspection, network
restriction tests, and idle-profile cleanup. No model request is needed for these
checks. To roll back, first remove only the CDP setting and browser toolset changes
from live config using the protected backup as a field-level reference, then
remove the new browser workload/service/policy and Hermes egress rule. Removing
the CDP setting alone restores the blocked in-pod launch path. Stop browser pods
before removing their node profile. Preserve subsequent unrelated config edits.

References: [Hermes v0.22.2 browser guide](https://github.com/NousResearch/hermes-agent/blob/v0.22.2/website/docs/user-guide/features/browser.md),
[Playwright sandbox guidance](https://playwright.dev/docs/docker),
[Kubernetes user namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/),
[Kubernetes seccomp](https://kubernetes.io/docs/reference/node/seccomp/).

#### Activation investigation — 8 November 2026

The live PVC config was backed up as
`/opt/data/config.before-browser-20261108T053010Z.yaml`, then updated with the
browser toolset and the original four local-browser fields (backend, cloud
provider, headed mode and real-profile selection). Config and backup retain UID/GID 10000
ownership and mode 0600. `hermes pm install agent-browser` installed the
release-pinned 0.26.0 ARM64 helper under `/opt/data/tools`, without enabling lazy
installs or changing the image. Existing model, MCP and security settings were
preserved. No ArgoCD sync, pod restart or GitHub publication was performed.

Native `browser_exec` was exercised directly as UID 10000 without a model
request. Chromium failed with **No usable sandbox**; `unshare -Ur true` also
failed with **Operation not permitted** under the pod's RuntimeDefault seccomp
profile. At this stage browsing was **not accepted as operational**. No sandbox bypass
or privilege increase was applied. The operator selected investigation of a
separate browser workload that keeps Chromium sandboxing. The failed test's
agent-browser daemon was closed explicitly.

Local checks passed for all 18 Applications and 451 resources; 13 Hermes tests
passed and the Prometheus alert test was skipped because `promtool` was absent.
These checks do not establish live browser functionality.

The approved disposable probe on `k3s-05` used `hostUsers: false`, UID/GID 10000,
all capabilities dropped, `allowPrivilegeEscalation: false`, a read-only root
filesystem and an Unconfined outer seccomp profile. Its NetworkPolicy denied
all ingress and egress, and it mounted no credentials or persistent volumes.
Unprivileged user-namespace creation succeeded. Chromium started without
`--no-sandbox`: renderer processes had zero effective capabilities,
`NoNewPrivs: 1`, `Seccomp: 2`, one seccomp filter, and nested PID/user namespaces.
This verifies renderer sandboxing in that isolated pod configuration, not
end-to-end browsing. The internal `chrome://sandbox` DOM dump did not complete
before cleanup, so no page-render acceptance is claimed. The probe pod and its
NetworkPolicy were deleted after inspection; the original Hermes pod and node
settings were unchanged. No permanent browser workload had been deployed at
this investigation stage.

#### Separate browser rollout — 8 November 2026

The operator approved the tailored-profile approach. The `k3s-05` guest's SSH
host key was verified against its console fingerprint using a task-local known
hosts file. The scoped Ansible playbook installed the profile; a repeat run
reported zero changes. No node restart, runtime-default change or added pod
capability was required. The capability-free adaptation needed an explicit
`chroot` syscall rule for Chromium's nested user-namespace sandbox.

The browser NetworkPolicy was applied before its ConfigMap, service and
Deployment. Hermes's policy gained only the browser TCP 9222 exception. The live
config was backed up privately as
`/opt/data/config.before-browser-cdp-20261108T075927Z.yaml`, then its browser
fields were updated without replacing other configuration. Ownership remains
10000:10000, mode 0600. The bootstrap ConfigMap was updated for future installs.
No Hermes restart, ArgoCD sync, GitHub publication or main-branch merge occurred.
The Application include change and browser declarations remain on the task branch;
main must receive them through review before ArgoCD can manage the new resources.

Live acceptance passed:

- Native `browser_exec` under UID 10000 navigated to a public HTTPS page, read it,
  populated an in-page test input and clicked an in-page test button. No model
  requests or paid browser service were used.
- Chromium renderers showed nested PID namespaces, zero effective capabilities,
  `NoNewPrivs: 1`, `Seccomp: 2`, and two filters (outer profile plus Chromium).
- Browser public HTTPS succeeded; public HTTP, Kubernetes API, Hermes dashboard
  and Hindsight TCP checks failed as expected. Hermes retained its Hindsight
  connection. An unrelated temporary pod reached public IPv4 HTTPS while its
  browser-service connection was blocked; temporary probe pods were removed.
- The real 600-second idle period removed the profile. Inspection revealed adopted
  zombie processes; the bridge was corrected to reap children after awaiting the
  browser. A separate real Chromium start/stop test then removed its profile and
  left no live or unreaped children. The bridge's idle-reaper, shutdown ordering,
  discovery rewrite, browser-Origin rejection and health-lease tests passed in
  the deployed image. A fresh profile had no earlier test cookie.

Local verification passed for 18 Applications and 455 resources. Hermes's local
suite passes with the alert-evaluation test skipped without `promtool`; aiohttp
bridge cases run separately inside the deployed image because the pinned local
verifier environment has no aiohttp dependency. The source/ConfigMap and both
rollout-checksum checks run locally. These results cover the single-operator
configuration, not concurrent-user isolation or every destination/CNI exception.

### Shared Hindsight personal bank

The seed connects `hindsight_reserve` to
`http://hindsight-api.hindsight.svc.cluster.local:8888/mcp/reserve-bank/` using the
existing Hindsight API bearer token. Only `recall`, `reflect` and `retain` are
exposed; MCP sampling is disabled. The connection works with either Codex or
Grok. Hermes's built-in memory remains available. The native Hindsight memory
provider and automatic conversation ingestion are not enabled.

With explicit credential-access approval, inject the existing
`hindsight/hindsight-api-credentials` key `HINDSIGHT_API_TENANT_API_KEY` into
`/opt/data/.env` as `HINDSIGHT_API_KEY`, preserving other entries. Use a protected
stdin workflow, ownership `10000:10000`, and mode `0600`; never print the value
or place it in process arguments or Git. The config uses environment substitution,
so it contains no token. The token authorizes all Hindsight banks: the personal-bank
URL and tool filter guide the client, rather than enforcing bank-level access.
An API token rotation also requires updating Hermes's injected copy.

The first-boot workspace `AGENTS.md` instructs Hermes to recall relevant shared
context and save personal facts, preferences and cross-agent decisions only on
explicit request. This file is seeded
only when absent. Existing installations need the reviewed MCP entry, CLI toolset
addition and memory instructions applied to their writable PVC without replacing
unrelated configuration or instructions. Start a new dashboard chat after setup.
Repository changes alone do not update an existing PVC.

Activation requires approval to apply the narrow NetworkPolicy change, inject the
token and update the live config/instructions. Verify with `hermes mcp test
hindsight_reserve`, then a read-only `recall` through Hermes. Do not write test
memories to reserve-bank. Record the actual rollout and verification separately from
this declaration. The API connection uses HTTP within the cluster; the existing
Tailscale HTTPS endpoint remains available for external clients.

The live `reserve` compatibility alias routes old connections to `reserve-bank`.
The connector name `hindsight_reserve` remains unchanged. Updating this seed does
not rewrite existing PVC configuration. See the [personal-memory status](../hindsight/README.md#personal-memory-across-ai-agents)
for the renewed model login and external-client verification;
external client setup does not change this cluster deployment's writable PVC.

On 2026-10-21, the approved activation injected the existing API token into
Hermes's private `.env`, added the MCP config/toolset and workspace instructions
to the PVC, and applied this task's ConfigMap, NetworkPolicy and Deployment
(including the unchanged Service). Server dry-run succeeded before application.
The Recreate rollout became available with one ready replica. `hermes mcp test
hindsight_reserve` passed; an authenticated MCP initialization, tool discovery and
read-only `recall` using Hermes's resolved configuration also succeeded. No test
memory was retained. The live token copy must be kept current on rotation.
These resources were applied directly with approval; this does not establish
that ArgoCD's `main` source contains the change or reports Synced.

## Network boundary

The Service is ClusterIP and the Ingress uses the existing Tailscale operator.
Keep dashboard authentication enabled even on the tailnet. Port 8642's API server
is disabled through `platforms.api_server.enabled: false` in the seed config;
`API_SERVER_ENABLED=false` has no effect in 0.22.2. The official entrypoint still
generates a local API key in `.env`, but the explicit config setting prevents
the listener from starting. Gateway features that need that listener, including
cron fire dispatch, are unavailable. No public ingress, Funnel, NodePort, or LAN
LoadBalancer is declared.

The NetworkPolicy permits dashboard ingress on 9119 only from pods in namespace
`tailscale` labeled for the `hermes` Ingress in namespace `hermes`. Namespace and
pod selectors are combined in one peer. Egress permits CoreDNS on TCP/UDP 53 and
public IPv4 HTTPS on TCP 443, excluding private, link-local, loopback, CGNAT,
benchmark and multicast/reserved ranges. One additional peer combines namespace
`hindsight` and pod label `app: hindsight-api`, permitting only TCP 8888 for MCP.
Other ports and IPv6 egress are denied.

Validate enforcement on the actual K3s network-policy controller. Kubernetes
policies have node-traffic and address-translation exceptions; they are not a
hard isolation boundary from the hosting node. They do not filter HTTPS domains
or prevent exfiltration to public services. Local commands can read the agent's
own OAuth credentials and dashboard environment; treat this as a trusted personal
agent, not a sandbox for untrusted users. Hermes's private-URL guard is an extra
application check, not a replacement for the NetworkPolicy.

## First rollout and acceptance

These are operator procedures requiring the repository's operation-specific
approvals, not authorization to execute them.

1. Complete the [pre-sync checklist](../argocd/README.md#verification-before-manual-sync).
   Confirm storage/capacity, the image's node architecture, default AppProject
   permissions, CoreDNS labels, network-policy enforcement, and availability of
   the `hermes` Tailscale name. Review tailnet ACL access before exposure.
2. Bootstrap the namespace and provision the dashboard Secret. Publish through
   the approved Git workflow, then separately review/sync the root to register
   `hermes`. Review/sync the child without pruning. Configuration and network
   policy must exist before exposing the running workload.
3. Inspect startup events and the dashboard/gateway processes. PID 1/supervision
   starts as root; application processes must have UID 10000. Confirm `/opt/hermes`
   is not writable by that UID and the PVC state is writable. Investigate
   ownership or s6 failures without granting privileged mode.
4. Complete a fresh device-code login and model selection:

   ```sh
   kubectl -n hermes exec -it deployment/hermes -c hermes -- hermes auth add openai-codex
   kubectl -n hermes exec -it deployment/hermes -c hermes -- hermes model
   ```

   Select **ChatGPT or Codex Subscription** and the recommended available model.
   The image's `hermes` shim drops exec commands to the runtime user. Complete
   browser approval yourself; do not print `auth.json`. If device login is disabled
   by account/workspace policy, obtain approval before enabling it. Alternatively,
   use the documented `--browser` login with a local port-forward to pod port 1455;
   do not expose that callback through an Ingress.
5. Get the assigned dashboard URL and configure its exact HTTPS origin:

   ```sh
   kubectl -n hermes get ingress hermes
   kubectl -n hermes exec -it deployment/hermes -c hermes -- hermes config set dashboard.public_url https://hermes.<tailnet>.ts.net
   ```

   Replace `<tailnet>` with the assigned suffix. Restart with approval if required
   to reload the dashboard. Do not add wildcard trusted proxies. If forwarded
   headers are needed, trust only the observed ingress proxy IP; the namespace
   NetworkPolicy must continue to restrict traffic to that proxy.
6. Visit the HTTPS URL. Verify unauthenticated protected routes and WebSockets
   are rejected, invalid passwords fail, and `/api/status` advertises
   `auth_required: true` with the `basic` provider. This public status endpoint is
   used by readiness; HTTP 200 alone does not verify login or inference. Confirm
   startup/liveness succeed on `/api/health`, readiness succeeds with dashboard
   and storage health, and gateway state is inspected separately. Do not test
   auth-disabled or storage-failure scenarios against the running installation.
7. Log in and open Chat. Send a small prompt and test a harmless workspace file
   operation. Check WebSocket streaming, selected provider/model, and persistent
   history. Confirm cluster credentials and runtime sockets are absent.
8. From the Hermes pod, verify cluster DNS and public HTTPS succeed while the
   Kubernetes Service on 443, LAN services on 443, and metadata addresses fail.
   A timeout counts as denial only after confirming the same destination is
   reachable from an approved control context. Test IPv6 if enabled. Do not probe
   application secrets or invoke mutating endpoints. Confirm another ordinary pod
   cannot connect to dashboard port 9119 while the Tailscale proxy can.
9. Restart the pod with approval and confirm the grant, model, history and test
   file survive. Confirm no overlapping gateway during updates. Review actual
   CPU/memory and adjust the initial limits if required. Do not run inference
   from health probes or restart solely because OAuth or upstream quota expired.

## Reauthentication, backup, and recovery

Nightly backups are declared for 04:00 Australia/Melbourne with seven successful
NAS copies retained. See the [backup runbook](BACKUP.md) for the consistency
boundary, recovery watchdog, permissions, immediate execution and isolated
restore procedure. The [20 October verification record](BACKUP.md#verification-record-20-october-2026)
documents the first successful NAS backup and isolated restore. Inspect recent
execution results before upgrades; the schedule alone does not prove success.

If OAuth is revoked or terminally expired, stop active chat/cron work and repeat
the dedicated `hermes auth add openai-codex` flow, then verify one small request.
Do not refresh another application's grant or silently switch to paid API use.

Before an upgrade, take a consistent offline Longhorn backup:

1. Obtain approval to stop the workload and take a backup. Scale the Deployment
   to zero and wait until its pod is fully terminated and the volume is detached.
   Manual ArgoCD sync means this is intentional temporary drift; do not sync the
   child while quiesced. Do not delete the Deployment or PVC.
2. Use Longhorn's configured backup target to create a backup of `hermes-data`.
   Record backup ID, successful completion, image digest and selected model.
   Protect access to the archive: `/opt/data` contains credentials and personal
   history. A snapshot or scheduled backup definition alone is not proof that a
   recoverable backup exists.
3. Restore the replica count to one and repeat dashboard/chat checks. The initial
   deployment introduced no schedule; the subsequent backup configuration above
   adds the nightly job and a separate recovery watchdog.

For recovery, keep Hermes stopped and restore the selected successful Longhorn
backup to a **new** volume/claim, preserving the original. Use an isolated
maintenance pod with no network access to inspect the restored filesystem and
remove its stale OAuth grant before any Hermes process starts. Record the
approved PVC identity change in Git, review it without pruning/replacing the
original claim, then start one instance and perform a fresh device login.
Never run source and restored gateways against the same data or grant. Verify
history and workspace files after recovery; test this procedure before relying
on the backup for an upgrade. Reverting an image does not reverse state migrations.

## Verification and references

Run from the task worktree:

```sh
verification/venv/bin/python -m unittest discover -s verification/tests -v
verification/cache/bin/conftest verify --policy verification/policy
verification/venv/bin/python scripts/verify.py --all --base main
git diff --check
```

Probe regression tests cover HTTP-200 HTML, malformed/oversized responses,
authentication drift and component failures. The seeding test checks that
existing config, instructions and symlinks are preserved. With `promtool` on
`PATH` or at `verification/cache/bin/promtool`, unit discovery also evaluates
the Hermes backup alert rules against fresh, stale, never-successful and missing
schedules, plus backup/recovery Job failures. Without that optional binary the
alert evaluation test is explicitly skipped; YAML/schema checks do not evaluate
PromQL. Use a checksum-verified official Prometheus release for `promtool`.

These checks validate declared state, schemas and policy behavior; they do not
authenticate, deploy, test the container startup, or prove live network isolation.

A local Docker smoke test on 2026-10-19 used the pinned AMD64 image, the declared
capabilities, no-new-privileges, the 2 CPU / 2 GiB limits, and temporary bind-mounted
state. Networking was disabled and no ports were published. It confirmed:

- s6 starts one gateway and the dashboard as UID/GID 10000; the install tree is
  not writable by that user and the workspace is writable.
- Status reports `auth_required: true` with `basic`. Protected APIs reject missing
  sessions, invalid passwords fail, authenticated requests succeed, and WebSocket
  RPC works with a single-use ticket. Missing and reused tickets are rejected.
- Port 8642 stays closed with the explicit config setting above. No OAuth grant,
  Kubernetes token, or Docker socket was supplied to Hermes.
- A changed model setting, synthetic SQLite history, and a workspace file survive
  rerunning the config seed and stopping/starting the container.

This local test used temporary dashboard credentials and made no model requests.
The subsequent cluster rollout is recorded below. Neither test establishes
long-term OAuth refresh, quota availability, or backup recovery.

## Initial cluster rollout: 2026-10-19

The approved rollout registered and manually synced only Hermes, without pruning
or force/replace. The existing root Application exclusions and all manual sync
policies were preserved. The ArgoCD MCP connector rejected its existing token;
the rollout used Kubernetes Application operations without refreshing that token.

The live dashboard is [hermes.tailbd291c.ts.net](https://hermes.tailbd291c.ts.net),
available over the tailnet with separate dashboard authentication. Its credentials
were sealed with the existing controller's public certificate; the dedicated
Codex grant was created through browser-approved device login on the PVC.
`hermes model` offered and selected `gpt-6.1-sol` with medium reasoning through
`openai-codex`. No API key or paid fallback was configured. Keep the first-boot
model seed unset so a new installation selects a currently entitled model.

Acceptance checks on K3s confirmed:

- The pinned ARM64 image starts on `k3s-01`; application processes use UID/GID
  10000. The install tree is not writable by that user, the workspace is writable,
  port 8642 is closed, and cluster tokens/runtime sockets are absent.
- The 10 GiB Longhorn claim is bound and healthy. Its original volume identity is
  `pvc-d4c53ad4-a9a2-4d28-91a9-0c4e3c884383`.
- Chromium loads the actual Tailscale HTTPS login and dashboard. Missing sessions
  and invalid passwords receive 401; valid login succeeds. Authenticated RPC,
  event and terminal WebSockets upgrade with 101 and exchange frames. Browser
  chat returns the expected answer through the terminal WebSocket.
- A Codex model request creates and reads back `workspace/hermes-acceptance.txt`.
  After a Recreate restart, the grant, model, six-message acceptance history,
  browser history and file remain present, and another model request succeeds.
  The grant is not world-readable; the mounted volume presents its mode as 0660
  after restart, owned by the dedicated Hermes user/group.
- Cluster DNS and public TLS on 443 work. Connections to the Kubernetes Service
  and an existing LAN HTTPS service fail from Hermes while both succeed from a
  temporary control pod. Public HTTP on port 80 is denied. The control pod cannot
  reach Hermes by Pod IP or ClusterIP, while the Tailscale proxy can.

The initial 512 MiB request was below observed usage with chat. The request is
now 1 GiB with the 2 GiB limit retained; multiple browser terminals reached about
1.5 GiB during acceptance. Review usage before adding concurrent sessions.
Metadata-address denial was not independently verified against a reachable
control, and this cluster has no IPv6 pod network to test. Node-traffic policy
exceptions still apply. At the end of the initial rollout, no recurring backup
or successful restore had been established; see the backup runbook for the
subsequent configuration and verification record.

- [Official Docker guide](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes providers and subscription limitations](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Dashboard authentication and browser chat](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard)
- [OpenAI headless authentication](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)
- [Tailscale proxy labels and troubleshooting](https://tailscale.com/docs/kubernetes-operator/reference/troubleshooting)
- [Kubernetes NetworkPolicy behavior and limitations](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
