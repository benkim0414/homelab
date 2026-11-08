# Herdr access to cluster Hermes

Herdr runs independently in namespace `hermes`. Its pinned image contains Herdr
0.9.5, kubectl 1.36.5, and OpenSSH on Debian 13.4. It does not contain Hermes.
Hermes upgrades therefore need no Herdr image rebuild. The initial image supports
AMD64 and the Deployment selects that architecture. Rebuild for Herdr, kubectl,
OpenSSH or base OS security updates; the Dockerfile also records ARM64 tool hashes.

## Connection

The Tailscale operator exposes ordinary OpenSSH at `herdr.tailbd291c.ts.net:22`.
This is TCP Service exposure, not Tailscale SSH or an HTTP Ingress. The existing
operator credentials are reused without modification. The server accepts only
the dedicated workstation public key declared in `../herdr-access.yaml`, as user
`herdr`. Password/root login and forwarding are disabled. Tailnet policy should
also limit access to this workstation; SSH key authentication remains mandatory.

After verifying the host fingerprint through Kubernetes and configuring a strict
SSH alias named `hermes-herdr`, register the existing remote server:

```bash
herdr machine add hermes-herdr --label 'Cluster Hermes' --remote-session default
```

Open its workspace in Herdr, then run:

```bash
hermes-cluster
# To reopen a known conversation after a connection ends:
hermes-cluster --resume SESSION_ID
```

The wrapper discovers exactly one Ready, non-terminating `app=hermes` pod,
selects container `hermes`, drops to the existing `hermes` user, and uses the live
`/opt/data` home and `/opt/data/workspace`. Existing OAuth, configuration, tools,
and private browser remain inside Hermes. No login is copied into Herdr.
The wrapper sets `HERDR_AGENT=hermes` outside the container for screen detection.

This opens a CLI conversation rather than attaching to a dashboard PTY. Avoid
simultaneous tasks that change the same workspace or use the browser's shared
cookies. Closing the local client leaves the remote Herdr server and its exec
terminal running. A broken exec stream, Hermes restart, or scheduled backup
scale-down can end that CLI. Reconnect explicitly, using its session ID when
needed; do not assume disconnect killed the old process or start duplicate work.

Automatic agent restore is disabled. The native Hermes integration is not
installed: its local Herdr socket cannot directly cross the Kubernetes exec
boundary. Herdr's saved layout is persistent, but live processes are not restored
after pod replacement. Herdr also does not copy local files into Hermes directly;
clipboard files arrive in Herdr's filesystem and need an explicit transfer before
Hermes can read them.

## Security and storage

The service account can get/list pods and get/create pod exec in namespace
`hermes`. It cannot directly read Secrets, change workloads, or access other
namespaces. **Exec still grants administration of every pod in this namespace**,
including access to credentials mounted in those pods and any authority their
service accounts possess. Wrapper labels are not a security boundary.

Default-deny networking admits SSH from only the matching Tailscale Service proxy.
Egress allows DNS and Kubernetes API Service IP `10.43.0.1:443`, plus its current
control-plane endpoints `192.168.0.11–13:6443` for post-DNAT enforcement. Update
those rules deliberately if control-plane addresses change. There is no general
Internet or direct Hermes/browser egress. Kubernetes exec travels via the API.
Kubernetes NetworkPolicy does not promise host or loopback isolation.

One supervised container runs the SSH daemon and Herdr server. Bootstrap and SSH
privilege separation use a bounded capability set; Herdr, shells, and kubectl
run as UID/GID 10000. The root filesystem is read-only, privilege escalation is
disabled, and seccomp is RuntimeDefault. The pod has no host mounts or runtime
socket. The projected namespace-scoped service-account token is intentionally
available to its trusted user.

The separate `herdr-data` PVC holds `/data/home` and root-only `/data/ssh` host
keys. Runtime sockets live in `/run/herdr`, outside persistent storage. Config is
seeded only when absent; edits to image defaults do not replace an existing config.
ArgoCD prune/delete protection does not protect against direct PVC deletion:
Longhorn's reclaim policy is Delete. Existing Hermes application archives do not
include this new PVC. Back it up through the NAS/Longhorn archive procedure before
relying on its layout or host identity; keep the workstation private key separately.

## Build, rollout, and rollback

The manual image workflow builds and smoke tests before publishing to
`ghcr.io/benkim0414/hermes-herdr:<source commit>`. It uses the workflow's temporary
package token, not a new stored PAT. During initial setup, invoke the existing
Verify workflow on the task branch with `build_herdr=true`; its reusable image job
does not run on normal PRs or pushes. After merging, the image workflow can also
be dispatched directly. Repository verification remains independent.

```bash
gh workflow run verify.yml --ref feat/herdr-cluster -f build_herdr=true
```

The first GHCR package may default to private. Make this credential-free image
public before deploying, or stop and arrange an explicitly approved pull-secret
workflow. Never embed workstation keys, Kubernetes credentials, or live home data
in the image. Pin the published digest in `../herdr-deployment.yaml` after the
smoke test succeeds. The smoke test covers nonroot SSH, the headless server, and
host-key persistence across restart under the declared capabilities.

Apply only reviewed `herdr-*.yaml` resources for the initial authorized rollout;
do not restart Hermes or sync unrelated drift. Keep the Application's manual sync
posture. Until this branch is published to remote main, the new live resources are
an explicitly deployed addition awaiting GitOps adoption.

Verify service-account allow/deny cases, SSH access from this workstation,
rejection of unrelated pod ingress, namespace-only API egress, wrapper launch,
client disconnect/reconnect, and Herdr pod replacement. Check Hermes UID and
browser configuration without sending a model prompt unless explicitly needed.

For rollback, scale only Herdr to zero and remove its private exposure after
review. Preserve `herdr-data`; do not delete the namespace or Hermes PVC. Revoke
the workstation public key in the ConfigMap and remove its local machine profile
if retiring access. Rotate SSH host keys deliberately and verify the replacement
fingerprint independently before changing known_hosts. Never bypass strict host
verification. Runtime sockets, process IDs, and stale exec streams are disposable;
conversation recovery uses Hermes's own persistent sessions.

References: [Herdr remote access](https://herdr.dev/tui/docs/persistence-remote/),
[agent wrappers](https://herdr.dev/tui/docs/agents/#vms-and-sandbox-wrappers),
[Tailscale TCP Service exposure](https://tailscale.com/docs/kubernetes-operator/ingress).
