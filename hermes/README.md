# Hermes Agent

One personal Hermes agent with browser chat over Tailscale HTTPS. The ArgoCD
Application tracks `main`, uses manual sync, and has no cascading-delete finalizer.
This directory declares the deployment; it is not evidence of a live rollout.

## Runtime and storage

| Setting | Declaration |
| --- | --- |
| Namespace / Application | `hermes` |
| Image | `nousresearch/hermes-agent:v0.22.2`, pinned to a multiarch index digest |
| Architectures | Registry index inspected on 2026-10-19: Linux AMD64 and ARM64 |
| Processes | Official s6 entrypoint, gateway and dashboard in one container |
| Dashboard | Port 9119; `https://hermes.<tailnet>.ts.net` |
| Provider | `openai-codex`; select an account-supported model during bootstrap |
| Data | `hermes-data`, 10 GiB Longhorn RWO, mounted at `/opt/data` |
| Workspace | `/opt/data/workspace`; tool HOME is `/opt/data/home` |
| Resources | Request 250m CPU / 512 MiB; limit 2 CPU / 2 GiB |

The image index digest is
`sha256:36099926da316742423544e055d4734777105ffe6341873af5459b957d0c2919`.
The registry's release tag includes `v`; `0.22.2` does not exist. Both containers
must use the same reviewed image. Renovate includes this directory for proposals;
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

## Credentials and configuration

Provision this external Secret in namespace `hermes` before starting the workload.
Use local injection or the [Sealed Secrets workflow](../docs/operations/sealed-secrets.md).
No plaintext credentials or placeholder Secret payloads belong in Git.

| Secret | Required key | Value |
| --- | --- | --- |
| `hermes-dashboard-auth` | `username` | Personal dashboard login name |
| `hermes-dashboard-auth` | `password-hash` | Hermes scrypt hash of a strong password |
| `hermes-dashboard-auth` | `session-secret` | Stable signing secret with at least 32 random bytes |

Use the pinned image's `plugins.dashboard_auth.basic.hash_password` function to
generate the hash, with the password read interactively rather than placed in
shell history or process arguments. Pass resulting values to Kubernetes through
a protected local file or stdin, without printing them. If adopting Sealed
Secrets later, add the encrypted manifest to the Application include glob in
the same change. Rotate the signing key deliberately; it invalidates sessions.

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

The initial CLI/browser-chat toolsets cover local commands, files, skills, memory,
session search and task lists. Optional paid web/image/voice tools, remote MCP
servers and lazy dependency installation are not configured. The main provider
and configured auxiliary tasks use Codex OAuth, with no fallback chain. Leave the
model unset until completing `hermes model`; do not send the first prompt before
selection. Background reviews and session summaries can consume additional quota.
Hermes documents the subscription integration, but not exact eligible tiers or
quota accounting; verify entitlement with a small request. There is no promise
of unlimited usage.

## Network boundary

The Service is ClusterIP and the Ingress uses the existing Tailscale operator.
Keep dashboard authentication enabled even on the tailnet. Port 8642's API server
is disabled through `platforms.api_server.enabled: false` in the seed config;
`API_SERVER_ENABLED=false` has no effect in 0.22.2. The official entrypoint still
generates a local API key in `.env`, but the explicit config setting prevents
the listener from starting. Gateway features that need that listener, including
cron fire dispatch, are unavailable. No public ingress, Funnel, NodePort, or LAN
LoadBalancer is declared.

The NetworkPolicy permits dashboard ingress only from pods in namespace
`tailscale` labeled for the `hermes` Ingress in namespace `hermes`. Namespace and
pod selectors are combined in one peer. Egress permits CoreDNS on TCP/UDP 53 and
public IPv4 HTTPS on TCP 443, excluding private, link-local, loopback, CGNAT,
benchmark and multicast/reserved ranges. Other ports and IPv6 egress are denied.

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
   also used by probes; HTTP 200 alone does not verify login or inference.
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
3. Restore the replica count to one and repeat dashboard/chat checks. No recurring
   backup schedule is introduced by this initial deployment.

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

This test used temporary dashboard credentials and made no model requests. It
does not verify Codex entitlement, OAuth refresh, browser rendering, Tailscale,
Longhorn, K3s startup, or network-policy enforcement; complete the rollout checks
above on the cluster. The default 512 MiB memory request is close to the roughly
500 MiB idle usage observed locally; review real workload usage after bootstrap.

- [Official Docker guide](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes providers and subscription limitations](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Dashboard authentication and browser chat](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard)
- [OpenAI headless authentication](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)
- [Tailscale proxy labels and troubleshooting](https://tailscale.com/docs/kubernetes-operator/reference/troubleshooting)
- [Kubernetes NetworkPolicy behavior and limitations](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
