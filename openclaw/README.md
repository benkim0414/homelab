# OpenClaw with a Grok subscription

One trusted user's personal assistant, with web chat, workspace files, and shell
commands inside its pod. The Application tracks `main`, uses manual sync, and has
no cascading-delete finalizer. These manifests are not evidence of deployment.
Hermes, Hindsight, and workstation Codex keep their own state and grants.

## Runtime and storage

| Setting | Declaration |
| --- | --- |
| Namespace / Application | `openclaw` |
| Image | Official `ghcr.io/openclaw/openclaw:2026.10.5`, pinned by index digest |
| Architectures | Registry index inspected 2026-10-19: Linux AMD64 and ARM64 |
| Model | `xai/grok-4.7`, explicitly using the built-in `openclaw` runtime |
| Thinking | `medium`; use `/think low` for quick tasks or `/think high` for difficult work |
| Provider authentication | Dedicated xAI OAuth device-code login with an eligible SuperGrok or X Premium subscription |
| Gateway | ClusterIP port 18789; Tailscale HTTPS with token auth and device pairing |
| Expected URL | `https://openclaw.tailbd291c.ts.net` |
| State | `openclaw-data`, 10 GiB Longhorn RWO, at `/home/node/.openclaw` |
| Workspace | `/home/node/.openclaw/workspace` |
| Resources | Request 250m CPU / 2 GiB; limit 2 CPU / 4 GiB |

The reviewed multiarch image digest is
`sha256:f40d1e66fd14d8c5b49c832f4100f83b53fdc01f5108f7db11de38fd0ee6dbe5`.
Both containers use it. Renovate proposes image changes; updates require review
and explicit sync. The standard image bundles the xAI plugin. Preserve the
official tini/Node entrypoint: it coordinates exclusive state maintenance and
Doctor migrations before starting the gateway. A lower image version alone does
not reverse database migrations.

The initial 2 GiB limit passed the unauthenticated startup smoke test but was
exceeded during the first authenticated GPT-6.1 Sol/Codex test, which also ran
the OpenClaw CLI inside the gateway container. Kubernetes recorded `OOMKilled`
and restarted the gateway. Reserve 2 GiB and allow 4 GiB for the gateway, Codex
runtime, and operator commands together. This limit is retained for the Grok
switch; authenticated Grok resource use has not been measured. Confirm node
capacity before syncing this resource change and measure authenticated turns
separately from startup.

The pod runs as UID/GID 1000 with no added capabilities, no privilege escalation,
RuntimeDefault seccomp, and a read-only root filesystem. Only the state PVC and
bounded `/tmp` are writable. XDG cache is on the PVC. One replica and `Recreate`
avoid overlapping writers; RWO alone is insufficient. Fence an unreachable old
node before allowing another pod to mount the state volume.

The PVC contains separate `state/` and `update-captures/` directories. They mount
at `/home/node/.openclaw` and `/home/node/.openclaw.update-captures`, respectively.
Doctor writes pre-repair recovery captures beside the state directory; both
must be writable and retained together. These local captures do not replace an
external backup. The init container creates both directories before subpath mounts.

The PVC has `Prune=false,Delete=false`. These ArgoCD safeguards do not prevent
direct PVC/namespace deletion. Confirm the actual backing PV reclaim policy;
Longhorn replication is availability protection, not a backup.

## Configuration and permissions

The init container copies `openclaw.json` and workspace `AGENTS.md` only when
absent, with a restrictive umask. OpenClaw owns the writable copies afterwards,
so login, pairing, settings, and supported repairs survive restarts. Changing
the ConfigMap or syncing ArgoCD does **not** replace existing copies.

For an existing deployment, stop active work, back up state, and review the exact
configuration change. Apply individual settings through `openclaw config set`,
validate them, and restart only with authorization if necessary. Keep intended
bootstrap settings in Git too. Never delete or overwrite the entire live config
to pick up a ConfigMap change. Check effective model/runtime after login and
upgrades; reject a different model rather than silently substituting another
provider or using billable API credentials.

`tools.exec.mode: full` deliberately runs commands without approval prompts.
The coding profile enables shell and file work; explicit denies remove ordinary
browser, web, media, messaging, automation, and control-plane tools. Heartbeats,
cron, browser automation, memory embeddings, and self-updates are disabled.
Only the bundled xAI provider plugin is allowed. Its `x_search` and remote
`code_execution` tools are explicitly disabled, preserving the existing tool
permissions. There are no configured external channels, MCP servers, paired
worker nodes, API keys, or fallback models.

Grok OAuth uses the subscription route and refreshes its grant on the PVC. It
does not require the Grok Build app or an xAI Console API key. Available models,
thinking levels, and quota depend on the signed-in account; check them after
login. Console API credits and subscription quota are separate. Do not add an API
key as a fallback when subscription auth or quota fails.

This is a trusted personal agent, not a sandbox for untrusted users. Shell can
read its own OAuth grant, gateway environment, transcripts, and configuration,
and can change its writable state. `workspaceOnly` confines file tools, not
arbitrary commands. Tool denies and AGENTS.md guidance are not OS isolation.
The pod has no Kubernetes token, host mount, Docker/containerd socket, or cluster
RBAC binding. Do not mount personal home directories or other apps' credentials.

## Switching an existing Codex installation

The bootstrap is copied only when absent. ArgoCD sync cannot migrate the existing
PVC configuration. Keep the existing state and old grants; do not replace the
entire configuration, delete sessions, or run Doctor repairs for this switch.

With authorization for the live change, back up state and stop active assistant
turns. Use `openclaw config set --batch-json` to update only the reviewed paths,
first with `--dry-run --strict-json`. Enable `plugins.entries.xai.enabled`, add
`xai` to `plugins.allow`, and disable
`plugins.entries.xai.config.xSearch.enabled` and
`plugins.entries.xai.config.codeExecution.enabled`. Keep the existing OpenAI and
Codex plugin entries during login so the current assistant remains available.
Validate configuration before writing. Plugin changes can require an authorized
restart; confirm readiness before login.

Run the xAI OAuth login from rollout step 4. It preserves the existing primary,
so complete login and check the available model and effort levels before switching
`agents.defaults.model.primary` to `xai/grok-4.7`. In the same reviewed batch, set
`agents.defaults.modelPolicy.allow` to `["xai/grok-4.7"]`, retain empty fallbacks,
set `agents.defaults.models["xai/grok-4.7"].agentRuntime.id` to `openclaw`, and set
`agents.defaults.thinkingDefault` to `medium`. Disable the OpenAI/Codex plugin
entries and set `plugins.allow` to `["xai"]` after successful xAI login. Preserve
other model metadata and all gateway, tool, workspace, pairing, and storage
settings. Never inspect or print the saved grant to validate the migration.

Run `openclaw config validate`, inspect only the changed nonsecret paths, and
confirm reload or restart readiness before beginning a new chat. Existing chats
can retain model, thinking, or native runtime overrides; use a new chat for the
Grok acceptance test. Check `/status` and quota, then test one small response and
a harmless workspace operation. Do not claim completion from configuration alone.

## Gateway token prerequisite

`openclaw-gateway-auth` must exist in namespace `openclaw`, with key `token`.
The gateway requires it; no placeholder or plaintext Secret is committed.
[`gateway-sealed-secret.yaml`](gateway-sealed-secret.yaml) contains the encrypted
token and is selected by the Application. It is sealed strictly for that namespace
and name. On 2026-10-20, the controller's validation endpoint confirmed it could
decrypt the manifest; this did not create a live Secret or deploy OpenClaw.
Confirm successful unsealing during rollout. No provider API key is required.

Future token replacement requires separate credential/secrets and cluster-network
authorization. Generate a fresh random token into a mode-0600 file in an ignored,
workspace-local staging directory. Seal it for the exact namespace/name with the
controller's public certificate, following
[Sealed Secrets operations](../docs/operations/sealed-secrets.md).
For example, using an approved token file:

```sh
kubectl create secret generic openclaw-gateway-auth \
  --namespace openclaw --from-file=token=/absolute/workspace/path/gateway-token \
  --dry-run=client -o yaml | \
  kubeseal --controller-name sealed-secrets-controller \
    --controller-namespace kube-system --format yaml \
    > openclaw/gateway-sealed-secret.yaml
```

Review only the encrypted output; include it with the manifests before publishing.
Keep plaintext out of command arguments, chat, logs, and Git. Transfer the token
to the operator through an approved private mechanism. Do not read controller
private keys or refresh other applications' credentials for this setup.
During an approved rotation, update the Secret and restart the gateway so its
environment receives the new token; Secret changes alone do not refresh the
running container's environment. Verify old-token rejection and new-token access.

OAuth state stays writable on the PVC because tokens rotate. Never seal and
remount a credential snapshot at every startup or share a grant with another app.

## Exposure and network policy

The existing Tailscale operator terminates HTTPS and forwards to the ClusterIP.
This is external proxying, not OpenClaw-managed Tailscale Serve. Tokenless
Tailscale identity auth is disabled. Token auth and normal browser device pairing
remain required. The exact public origin and allowed browser origin are seeded
from this repository's current tailnet suffix; confirm the assigned hostname.
No public Ingress, Funnel, NodePort, or LAN LoadBalancer is declared.

Gateway authentication limits failed attempts to 10 per 60 seconds, with a
five-minute lockout. The pinned image's security audit flags an exposed gateway
without this setting. For existing state, apply `gateway.auth.rateLimit` through
`openclaw config set` and validate it before an authorized restart; changing the
bootstrap ConfigMap alone does not update the live configuration. Validated
forwarding attributes these limits to each tailnet client's address. Keep the
limit suited to this single-operator deployment.

The bootstrap trusts only `10.42.3.23/32`, the observed address of the dedicated
`ts-openclaw-w82kg-0` proxy on 2026-10-20. Gateway logs confirmed this socket
source. Tailscale v1.104.1's Serve implementation overwrites `X-Forwarded-For`
with the tailnet connection's client address and rebuilds the forwarded host and
protocol headers. OpenClaw uses this trust for client attribution and rate limits;
token authentication and browser device pairing remain required.

Without this setting, the pinned OpenClaw image rejects externally managed Serve
traffic with HTTP 403 `proxy_attribution_required` before authentication. Direct
CLI calls and health probes can succeed while the tailnet UI remains blocked.
Include a request carrying forwarded headers from the actual proxy in acceptance.

Pod IPs can change. Before a fresh install or after proxy replacement, inspect
the labeled proxy and confirm the socket source in gateway logs:

```sh
kubectl -n tailscale get pods \
  -l 'tailscale.com/parent-resource-type=ingress,tailscale.com/parent-resource=openclaw,tailscale.com/parent-resource-ns=openclaw' \
  -o wide
```

With approval, update the exact `/32` in this bootstrap and the existing writable
config through the supported CLI. For the currently observed address:

```sh
kubectl -n openclaw exec deployment/openclaw -c gateway -- \
  openclaw config set gateway.trustedProxies '["10.42.3.23/32"]' \
  --strict-json --dry-run --json
```

For an approved write, replace `--dry-run --json` with
`--expect-current-absent` if the setting is absent. When replacing an existing
list, use `--expect-current-json` with its reviewed prior value instead.
Conditional expectations cannot be combined with dry-run in this version.
The pinned image supports live reload of this setting;
confirm reload and reconnect clients. ConfigMap sync alone does not update the
writable copy. A changed proxy address fails closed until reviewed and updated;
never trust the whole pod CIDR or leave retired proxy IPs in the list.

Verify the UI through HTTPS, missing/wrong-token rejection on protected routes,
unapproved-browser and unrelated-Origin rejection, and rejection of forwarded
headers from untrusted sources. Do not disable device authentication or allow
wildcard origins to resolve errors. Recheck header rebuilding after a Tailscale
upgrade; this address pin does not manage proxy identity automatically.

Ingress permits only port 18789 from pods in namespace `tailscale` labeled for
this `openclaw` Ingress. Namespace and pod selectors are combined in one peer.
Egress permits CoreDNS on TCP/UDP 53 and public IPv4 HTTPS on TCP 443, excluding
private, link-local, loopback, CGNAT, benchmark, multicast, and reserved ranges.
Other ports and IPv6 egress are denied. This policy does not filter domains or
prevent exfiltration to public HTTPS services. Node-traffic and address-translation
exceptions mean it is not a hard security boundary from the hosting node.
Verify enforcement with the actual K3s controller before relying on it.

## First rollout and acceptance

These procedures require the repository's operation-specific approvals. They do
not authorize publishing, secrets changes, deployment, restarts, or cleanup.

1. Complete the [pre-sync checklist](../argocd/README.md#verification-before-manual-sync).
   Confirm node capacity, Longhorn health, image architectures, AppProject
   permissions, CoreDNS labels, and availability of the `openclaw` tailnet name.
   Review who can reach it through the existing tailnet policy.
2. Confirm the included gateway SealedSecret is ready. Publish the reviewed
   changes through the approved Git workflow. Record the exact commit and
   successful Verify check.
   Review/sync the root to register the child, then review/sync only OpenClaw
   without pruning or force/replace. Namespace and policy precede the workload;
   HTTPS exposure follows its readiness.
3. Check events, ownership and permissions. Verify UID/GID 1000, read-only install
   tree, writable state/cache/workspace, JSON startup/liveness responses, and
   absence of cluster credentials and runtime sockets. OAuth absence must not
   cause liveness restarts; health probes never perform model inference.
4. Complete a fresh subscription login:

   ```sh
   kubectl -n openclaw exec -it deployment/openclaw -c gateway -- \
     openclaw models auth login --provider xai --method oauth
   ```

   The operator completes browser authorization. If account/workspace policy
   disables device login, obtain permission before changing it. Do not copy a
   workstation auth cache. This xAI flow prints a URL and short code and does not
   require a localhost callback. The consent screen may mention Grok Build; the
   app is not required. Do not rerun onboarding for an existing deployment.
5. Inspect provider/model status without printing credentials:

   ```sh
   kubectl -n openclaw exec deployment/openclaw -c gateway -- \
     openclaw models list --provider xai
   kubectl -n openclaw exec deployment/openclaw -c gateway -- \
     openclaw config get agents.defaults.model --json
   kubectl -n openclaw exec deployment/openclaw -c gateway -- \
     openclaw config get agents.defaults.models --json
   ```

   Require `xai/grok-4.7` with explicit `openclaw` runtime and `medium` thinking
   (`openclaw config get agents.defaults.thinkingDefault`). Model inventory alone
   does not prove entitlement. Stop if unavailable; do not add an API key or
   substitute another model. Inspect subscription quota with `openclaw status --usage`.
6. Open the assigned HTTPS URL, authenticate with the gateway token, and complete
   device pairing using `openclaw devices list` and the specific reviewed
   `openclaw devices approve <request-id>` request through pod exec. Verify missing
   and wrong tokens fail protected RPC/WebSocket authentication and an unapproved
   browser cannot operate the assistant. A public HTML page or health 200 is not
   proof of authentication. Confirm an unrelated Origin is rejected.
7. Start a new chat so an existing Codex session or model override cannot retain
   the old selection. Send one small prompt. Check `/status`: require Grok 4.7,
   OpenClaw runtime, and medium thinking. Test streaming, a harmless workspace
   file operation, and a shell command without prompts. Run `openclaw security audit`
   and review findings against the intentional trusted-user/full-command posture. Do not
   run `--fix` or broaden permissions merely to silence findings.
8. From the pod, verify DNS and public TLS succeed while the Kubernetes Service
   and a reachable LAN HTTPS destination fail. Use an approved control context
   to establish destination reachability before calling a timeout a denial.
   Confirm an ordinary pod cannot reach the gateway but its Tailscale proxy can.
   Test IPv6 if the cluster enables it. Use read-only endpoints.
9. With approval, restart the pod and confirm the grant, pairing, model, history,
   and test file persist; repeat one small response. Confirm a single writer and
   inspect CPU/memory before adjusting resources. Observe OAuth refresh separately;
   restart persistence does not prove expiry-driven token rotation.

## Reauthentication, backup, and recovery

If the grant expires terminally or is revoked, stop active work and repeat the
dedicated login. Verify Grok 4.7 and medium thinking again. Do not refresh
another app's grant or fall back to billable API use when quota/authentication fails.

The `openclaw-backup` CronJob runs daily at 04:00 Australia/Melbourne. It
acquires a lease, checks the exact PVC, volume health, target, and single ready
replica, then scales the gateway to zero and waits for pod termination and volume
detachment. It creates an offline Longhorn snapshot and waits for a completed copy
to the configured NAS target before resuming the gateway. A five-minute recovery
watchdog retries resuming after a controller failure. The controller has a
restricted service account, read-only root filesystem, and egress only to the
Kubernetes API endpoints. It receives no OpenClaw PVC or OAuth grant.

Retention keeps the seven newest successfully completed copies and only prunes
backups and snapshots labeled for this source volume and policy. Retention runs
after a new successful copy. The NAS archive contains OAuth state and personal
history; protect access to the backup target. Backup success is not proof of
recoverability: verify the first scheduled copy and test an isolated restore into
a new volume before relying on this schedule. Record the completed backup ID,
image digest, and model. Keep the original volume and both state directories until
a restore has been reviewed.

Before upgrading, stop active work and confirm a recent completed backup. Do not
ArgoCD-sync while intentionally quiesced. Resume the single replica and repeat
acceptance checks. The backup CronJob itself does not authorize rollout or restore.

Existing deployments can retain earlier Codex state and grants. Disabling the
plugin does not revoke its grant or erase its history. This image's Doctor reports
that the Codex plugin has no declared migration backup inventory, so automatic
recovery captures cannot establish complete rollback coverage for that old state.
Back up the entire claim, including both directories, before an upgrade and
verify recovery separately. Grant revocation is a separate authorized action.

Restore into a **new** volume/claim, preserving the original and keeping both
gateways stopped. Inspect the restore in a network-isolated maintenance context.
Before any restored process receives network access, revoke the old dedicated
OpenClaw grant through the account's authorized session controls; never revoke
unrelated grants. Then perform a fresh OpenClaw login against the restored state
before admitting user traffic. Review the PVC identity change in Git and do not
prune the original. Never run source and restored gateways against the same state
or grant. Test recovery before relying on backups for an upgrade. Downgrades need
matching compatible state, not just an older image.

## Local verification and references

Run repository checks from the task worktree using the pinned verification tools:

```sh
verification/venv/bin/python -m unittest discover -s verification/tests -v
verification/cache/bin/conftest verify --policy verification/policy
verification/venv/bin/python scripts/verify.py --all --base main
git diff --check
```

Historical Codex container check, 2026-10-20 (before the Grok switch): the pinned
AMD64 image accepted the bootstrap configuration and started with its official
entrypoint, UID/GID 1000, a read-only root, dropped capabilities, and a 2 GiB limit. The test used rootless Podman,
synthetic gateway credentials, no published ports, and disabled container
networking. All three manifest probes passed. Protected HTTP requests without a
token or with a wrong token returned 401; WebSocket requests rejected a wrong
token, a browser without device identity, and an unrelated origin. Gateway logs
reported only `codex` and `openai` runtime plugins and GPT-6.1 Sol. Recovery
captures succeeded on the persistent sibling mount. Re-running the actual init
script preserved the migrated config, workspace fixture, and state database;
the gateway became ready after restart with the model/runtime selection intact.
No subscription credentials or model inference were used. This historical test
does not validate the Grok bootstrap or OAuth route.

Grok switch, 2026-10-20: full repository verification passed for 18 Applications
and 439 resources using cached dependencies. The running pinned image accepted
both configuration dry runs and final `config validate`. xAI OAuth completed
against the subscription proxy, and `status --usage` showed SuperGrok quota.
The live default is `xai/grok-4.7`, runtime `openclaw`, with medium thinking and
no fallbacks. Both configuration batches applied without a gateway restart.
A fresh Gateway session returned the expected response, then successfully used
`write`, `read`, and `exec` against a dedicated workspace test file. Request
metadata confirmed medium thinking and OAuth profile authentication. The
subscription service returned response model `grok-4.7-build` for the selected
`grok-4.7`; OpenClaw reported that provider route in the terminal receipt.

Existing Codex chats and grants were preserved. Start a new chat for Grok;
historical sessions still show the runtime that created them. The CLI retained
its configuration backup on the PVC; this was not a full state backup or restore
test. The bootstrap ConfigMap still requires Git publication and manual ArgoCD
sync; it does not overwrite existing PVC configuration. OAuth expiry/refresh and
post-restart persistence were not tested during this switch.

Offline verification is partial. Neither schema/policy checks nor a container
smoke test prove live rollout, subscription entitlement, network-policy enforcement,
OAuth refresh, or backup recovery. Record those results only after performing them.

- [Official Kubernetes baseline](https://docs.openclaw.ai/install/kubernetes)
- [Pinned container and entrypoint behavior](https://github.com/openclaw/openclaw/blob/v2026.10.5/docs/install/docker.md)
- [Grok subscription setup](https://docs.openclaw.ai/providers/xai)
- [Pinned xAI provider behavior](https://github.com/openclaw/openclaw/blob/v2026.10.5/docs/providers/xai.md)
- [Thinking levels](https://docs.openclaw.ai/tools/thinking)
- [Grok 4.7 model capabilities](https://docs.x.ai/developers/models/grok-4.7)
- [Runtime selection](https://docs.openclaw.ai/concepts/agent-runtimes)
- [Permission modes](https://docs.openclaw.ai/tools/permission-modes)
- [Gateway exposure](https://docs.openclaw.ai/gateway/security/network-exposure)
- [Pinned proxy attribution requirements](https://github.com/openclaw/openclaw/blob/v2026.10.5/docs/gateway/security/rate-limiting.md)
- [Tailscale v1.104.1 forwarded-header rebuilding](https://github.com/tailscale/tailscale/blob/v1.104.1/ipn/ipnlocal/serve.go#L1014-L1022)
- [JSON health contracts](https://docs.openclaw.ai/gateway/health)
