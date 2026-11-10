# Herdr cluster access

Herdr runs in its own `herdr` namespace and provides terminal access to the
existing Hermes and OpenClaw containers. Its manually synced ArgoCD Application
tracks `main`. The image contains Herdr, kubectl, SSH, and launchers; it does not
contain either agent. See [the image sources](image/) and
[the original rollout record](rollout-2026-11-08.md).

## Connect and select a conversation

The local machine is **K3s**, targeting SSH alias `k3s` and remote Herdr session
`default`. SSH connects to `herdr.tailbd291c.ts.net` as user `herdr`, using the
existing dedicated key and strict host-key verification. This is ordinary SSH
over the Tailscale TCP Service, not Tailscale SSH.

In a remote terminal, run:

```sh
hermes
hermes --resume SESSION_ID
openclaw
openclaw --session homelab
openclaw --session main
```

`openclaw` defaults to conversation `herdr`. Each name selects persistent
conversation history on the existing gateway. Conversations share the same
OpenClaw agent, credentials, tools, and workspace; names are not profiles or
filesystem isolation. Gateway session reset/retention policies still apply.
The web UI can open the same conversation. Avoid simultaneous tasks that modify
the same files. Existing live provider/model settings are preserved.

The launcher requires one Ready, non-terminating `app=openclaw` pod and enters
container `gateway` as its existing UID 1000. It runs `openclaw tui` against the
existing local gateway, never `--local` or a second gateway. Credentials remain
inside OpenClaw, and no token is passed on the command line. OpenClaw currently
appears as a normal terminal pane rather than a supported Herdr activity manifest.

Closing the client leaves remote terminals running. A broken exec stream, agent
restart, or scheduled backup can end a connection. Reconnect explicitly to the
same conversation; do not assume a disconnect stopped active work. Automatic
agent restoration remains disabled. Herdr pod replacement interrupts its panes;
saved layout and agent-side history persist. Clipboard uploads arrive in Herdr,
not automatically in an agent's workspace.

## Permissions and storage

ServiceAccount `herdr/herdr` can get/list pods and get/create pod exec in `hermes`
and `openclaw` through Roles and RoleBindings owned by those Applications. It
cannot directly read Secrets, change workloads, or access other namespaces.
Exec nevertheless gives access to every pod and its mounted credentials in each
permitted namespace; launcher selectors are not authorization boundaries.

Networking allows SSH only from this Service's Tailscale proxy, plus outbound DNS
and Kubernetes API traffic. Exec uses the API; no direct gateway/browser ingress
or general Internet egress is added. Preserve the bounded capabilities, read-only
root, unprivileged server user, and strict SSH configuration in the manifests.

`herdr-data` is prebound to PV/Longhorn volume `herdr-k3s-data`. The PV uses Retain
and both resources disable ArgoCD prune/delete. The restored filesystem contains
the writable home and root-owned SSH host keys. The migration source PVC
`hermes/herdr-data` remains declared in `hermes/herdr-legacy-storage.yaml` for
rollback; its existing Longhorn reclaim policy is Delete. Never delete it.
The new volume must be restored before rollout; an empty filesystem must not be
accepted as a successful migration. There is no recurring Herdr archive schedule.

## Build and verification

The existing image workflow builds `herdr/image`, runs wrapper tests and SSH
smoke checks, then publishes `ghcr.io/benkim0414/hermes-herdr:<commit>`.
The historical package name is retained. Dispatch/publishing require applicable
approval. Pin the resulting image digest in `deployment.yaml` before rollout.

```sh
python3 verification/bootstrap.py
verification/venv/bin/python -m unittest discover -s verification/tests -v
verification/cache/bin/conftest verify --policy verification/policy
verification/venv/bin/python scripts/verify.py --all --base main
bash -n herdr/image/herdr.sh herdr/image/smoke-test.sh
git diff --check
```

Local checks do not prove live SSH access, RBAC enforcement, restore integrity,
or model responses. Follow [the pre-sync checklist](../argocd/README.md#verification-before-manual-sync)
for GitOps adoption. Never sync an Application whose complete diff includes
unreviewed unrelated changes.

## Namespace migration

This procedure interrupts Herdr panes and copies SSH host identity as part of a
protected whole-volume restore. It does not authorize arbitrary credential
extraction, publication, destructive cleanup, or an unreviewed deployment.

1. Inspect active terminals and record the source PVC UID, PV/volume identity,
   current image, host-key fingerprint, and remote layout. Back up affected local
   machine/SSH configuration into protected, ignored task-local storage. Do not
   print private keys, session contents, or credential values.
2. Build/smoke-test the new image and pin its published digest. Review manifests,
   RBAC, network selectors, capacity, and the healthy Longhorn NAS backup target.
   Stage namespace, access, policy, service account, and application RBAC without
   starting the new server or exposing a second `herdr` tailnet hostname.
3. Quiesce the old Herdr Deployment. Wait for its pods to terminate and the
   source Longhorn volume to detach. Do not restart either copy during capture.
4. Create an offline Longhorn Snapshot and Backup labeled for this migration and
   source volume. Require Snapshot `readyToUse`, Backup state `Completed`, no
   error, matching source volume, and a URL under the configured NAS target.
   Retain both snapshot and backup; do not apply routine retention to them.
5. Restore that exact backup into a new Longhorn volume named `herdr-k3s-data`,
   with 2 GiB capacity, two replicas, v1 data engine, ext4 filesystem, and the
   current engine image. Bind it using `storage.yaml`. Wait for restore completion
   and healthy replicas before opening it to clients.
6. Mount restored state in an isolated maintenance pod with no service-account
   token and denied ingress/egress. Verify ownership/modes, saved configuration
   and layout, and the original SSH public-key fingerprint. Compare file content
   through private checksums without emitting contents. Remove the maintenance
   pod before starting the new Deployment. Leave the old Deployment at zero.
7. Remove exposure from the old Service and wait for its operator-managed proxy
   to retire and release the hostname. Start the new server, then expose the new
   Service. Check the actual assigned hostname rather than accepting a suffixed
   duplicate. Update proxy network-policy selectors for namespace `herdr`.
8. Update the local SSH alias to `k3s`, retaining its endpoint, user, key, known
   hosts file, and strict checks. Register with
   `herdr machine add k3s --label K3s --remote-session default`; require a new
   opaque machine ID. Verify remote workspaces before removing the old machine
   registration. Do not reinstall or replace the remote server during setup.
9. Verify allow/deny RBAC, both launchers, named-session continuity, unchanged
   model selection, rejected unauthorized SSH, and host-key continuity. Record
   image/backup/volume identities and actual results. Retire only obsolete Herdr
   resources after review; retain the source PVC, namespace, and agent workloads.

If capture/restore fails before cutover, keep the new server stopped and resume
the old Deployment after checking it is the sole writer. After cutover, stop the
new server and preserve any new state before rollback. Restore the old exposure
and local configuration, then resume the old server against its retained volume.
Never start both servers against independently diverging copies without an
explicit reconciliation plan.
