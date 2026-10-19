# OpenClaw with a Codex subscription

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
| Model | `openai/gpt-6.1-sol`, explicitly using the `codex` runtime |
| Provider authentication | Dedicated ChatGPT/Codex device-code login |
| Gateway | ClusterIP port 18789; Tailscale HTTPS with token auth and device pairing |
| Expected URL | `https://openclaw.tailbd291c.ts.net` |
| State | `openclaw-data`, 10 GiB Longhorn RWO, at `/home/node/.openclaw` |
| Workspace | `/home/node/.openclaw/workspace` |
| Resources | Request 250m CPU / 1 GiB; limit 2 CPU / 2 GiB |

The reviewed multiarch image digest is
`sha256:f40d1e66fd14d8c5b49c832f4100f83b53fdc01f5108f7db11de38fd0ee6dbe5`.
Both containers use it. Renovate proposes image changes; updates require review
and explicit sync. The standard image bundles the Codex plugin. Preserve the
official tini/Node entrypoint: it coordinates exclusive state maintenance and
Doctor migrations before starting the gateway. A lower image version alone does
not reverse database migrations.

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
upgrades; reject a different model rather than silently substituting Astra.

`tools.exec.mode: full` deliberately runs commands without approval prompts.
The coding profile enables shell and file work; explicit denies remove ordinary
browser, web, media, messaging, automation, and control-plane tools. Heartbeats,
cron, browser automation, memory embeddings, and self-updates are disabled.
Only the OpenAI provider and Codex runtime plugins are allowed. There are no
configured external channels, MCP servers, paired worker nodes, API keys, or
fallback models.

This is a trusted personal agent, not a sandbox for untrusted users. Shell can
read its own OAuth grant, gateway environment, transcripts, and configuration,
and can change its writable state. `workspaceOnly` confines file tools, not
arbitrary commands. Tool denies and AGENTS.md guidance are not OS isolation.
The pod has no Kubernetes token, host mount, Docker/containerd socket, or cluster
RBAC binding. Do not mount personal home directories or other apps' credentials.

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

Do not trust the whole pod CIDR as a proxy. Start with no trusted proxies; remote
requests must authenticate and pair. If correct forwarded-client attribution
requires proxy trust, inspect the actual source addresses and header handling,
then configure only those proxy addresses. Preserve token auth. Update the
trusted addresses after proxy replacement and verify rejection of forged headers.
Do not disable device authentication or allow wildcard origins to resolve errors.

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
     openclaw models auth login --provider openai --device-code
   ```

   The operator completes browser authorization. If account/workspace policy
   disables device login, obtain permission before changing it. Do not copy a
   workstation auth cache. Use the documented browser flow with a local callback
   port-forward if device login is unavailable; never expose the callback by Ingress.
5. Inspect provider/model status without printing credentials:

   ```sh
   kubectl -n openclaw exec deployment/openclaw -c gateway -- \
     openclaw models list --provider openai
   kubectl -n openclaw exec deployment/openclaw -c gateway -- \
     openclaw config get agents.defaults.model --json
   kubectl -n openclaw exec deployment/openclaw -c gateway -- \
     openclaw config get agents.defaults.models --json
   ```

   Require `openai/gpt-6.1-sol` with explicit `codex` runtime. Model inventory alone
   does not prove entitlement. Stop if unavailable; do not select Astra or add an
   API key. Subscription limits are shared with the account's other Codex use.
6. Open the assigned HTTPS URL, authenticate with the gateway token, and complete
   device pairing using `openclaw devices list` and the specific reviewed
   `openclaw devices approve <request-id>` request through pod exec. Verify missing
   and wrong tokens fail protected RPC/WebSocket authentication and an unapproved
   browser cannot operate the assistant. A public HTML page or health 200 is not
   proof of authentication. Confirm an unrelated Origin is rejected.
7. Send one small prompt. Check `/status` and `/codex status`: require GPT-6.1 Sol
   and `Runtime: OpenAI Codex`. Test streaming, a harmless workspace file operation,
   and a shell command without prompts. Run `openclaw security audit` and review
   findings against the intentional trusted-user/full-command posture. Do not
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
dedicated login. Verify GPT-6.1 Sol again. Do not refresh another app's grant or
fall back to billable API use when quota/authentication fails.

Before upgrading, obtain approval to stop the gateway and take a consistent
Longhorn backup. Scale to zero, wait for termination and volume detachment, and
do not ArgoCD-sync while intentionally quiesced. Back up `openclaw-data` through
the configured Longhorn backup target. Record successful completion, backup ID,
image digest, and model. Protect the archive as credentials and personal history.
A snapshot or scheduled job definition is not evidence of a recoverable backup.
Resume the single replica with approval and repeat acceptance checks. No recurring
backup schedule is introduced here.

This image's Doctor reports that the Codex plugin has no declared migration
backup inventory. Its automatic recovery capture cannot establish complete Codex
rollback coverage. Back up the entire claim, including both directories, before
an upgrade and verify recovery separately.

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

Local container check, 2026-10-20: the pinned AMD64 image accepted the bootstrap
configuration and started with its official entrypoint, UID/GID 1000, a read-only
root, dropped capabilities, and a 2 GiB limit. The test used rootless Podman,
synthetic gateway credentials, no published ports, and disabled container
networking. All three manifest probes passed. Protected HTTP requests without a
token or with a wrong token returned 401; WebSocket requests rejected a wrong
token, a browser without device identity, and an unrelated origin. Gateway logs
reported only `codex` and `openai` runtime plugins and GPT-6.1 Sol. Recovery
captures succeeded on the persistent sibling mount. Re-running the actual init
script preserved the migrated config, workspace fixture, and state database;
the gateway became ready after restart with the model/runtime selection intact.
No subscription credentials or model inference were used.

Offline verification is partial. Neither schema/policy checks nor a container
smoke test prove live rollout, subscription entitlement, network-policy enforcement,
OAuth refresh, or backup recovery. Record those results only after performing them.

- [Official Kubernetes baseline](https://docs.openclaw.ai/install/kubernetes)
- [Pinned container and entrypoint behavior](https://github.com/openclaw/openclaw/blob/v2026.10.5/docs/install/docker.md)
- [OpenAI subscription setup](https://docs.openclaw.ai/providers/openai/setup)
- [Runtime selection](https://docs.openclaw.ai/concepts/agent-runtimes)
- [Permission modes](https://docs.openclaw.ai/tools/permission-modes)
- [Gateway exposure](https://docs.openclaw.ai/gateway/security/network-exposure)
- [JSON health contracts](https://docs.openclaw.ai/gateway/health)
- [OpenAI model availability](https://learn.chatgpt.com/docs/models)
- [OpenAI headless login](https://learn.chatgpt.com/docs/auth#login-on-headless-devices)
