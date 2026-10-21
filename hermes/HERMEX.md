# Hermex mobile access

Hermex connects to the third-party `nesquena/hermes-webui` backend, not Hermes's
built-in dashboard. WebUI runs alongside the existing dashboard and gateway in
one pod. This is for one trusted personal operator.

## Connect after rollout

1. Connect the iPhone/iPad to the existing Tailscale network.
2. Confirm the `hermex` Ingress's assigned hostname, then enter
   `https://hermex.tailbd291c.ts.net` in Hermex, without a port or `/api` suffix.
3. Enter the dedicated WebUI password provisioned below. The original dashboard
   remains at `https://hermes.tailbd291c.ts.net` with its separate credentials.
4. Verify streaming, reopening history, model selection and workspace access.
   Browser access to the WebUI URL is useful for diagnosis.

Both interfaces share agent configuration, the dedicated provider grant, skills,
memory and workspace. WebUI keeps its own UI/session records in `/opt/data/webui`.
Existing CLI/dashboard sessions may need WebUI's agent-session visibility/import
controls; do not promise identical session lists or replace the existing database.
Avoid simultaneous configuration changes from both interfaces.

Port 8642 remains disabled. Scheduled task execution is outside this integration;
WebUI may report gateway health as unavailable. Creating a task does not prove
that it will execute unattended.

## Runtime and boundaries

| Component | Declaration |
| --- | --- |
| WebUI | `ghcr.io/nesquena/hermes-webui:0.52.492` |
| Image index | `sha256:e507cafa7b112de9abd58348423ded28a8182539e6ebb5f95be603f20aff52e6` |
| Architecture | Registry index verified for Linux AMD64 and ARM64 |
| Agent source | Same pinned Hermes `v0.22.2` image as the gateway |
| Python | `UV_PYTHON=3.14.8`; installed under `/app/python` |
| Persistent state | Original `hermes-data` PVC at `/opt/data` |
| Service | ClusterIP `hermex`, port 8787; Tailscale Ingress `hermex` |
| WebUI resources | Request 250m CPU / 1 GiB; limit 2 CPU / 2 GiB |

The existing single-replica `Recreate` Deployment owns both containers. No second
gateway starts. An unprivileged init container copies agent source into an
`emptyDir`, excluding the virtualenv, Git metadata, bytecode, browser cache and
build-time `.install.lock` files. WebUI mounts it read-only at `/opt/hermes`.
Kubernetes does not automatically populate image-directory volumes like Docker.

The upstream WebUI entrypoint starts as root for user/filesystem preparation and
drops to UID/GID 10000. It stages agent code under `/app/hermes-agent-src` for an
editable install. That copy and WebUI's `/app` are runtime-writable: this is the
upstream personal-agent trust model, not immutable code or isolation from hostile
agent commands. No Kubernetes token, Docker socket or host filesystem is mounted.

The image's default Python 3.12 skips Hermes 0.22.2's Python-3.14-gated core
dependencies: `/health` can return 200 while `run_agent` imports fail. The explicit
Python version fixes this. The startup probe imports `AIAgent` and checks HTTP
health; ordinary readiness/liveness probes use `/health`. No probe calls a model.

`/app`, managed Python and `/uv_cache` are temporary. Upstream startup downloads
Python/packages over public HTTPS on every new pod. Container restarts reuse
these volumes, but nightly backup resumption or pod replacement installs again.
The ten-minute startup allowance cannot guarantee recovery during dependency
server outages. Images, source and Python are pinned; WebUI's package installation
is not fully locked. `HERMES_WEBUI_AUTO_INSTALL=0` disables additional Python
startup repair, not the Docker entrypoint's dependency installation.

NetworkPolicy allows 8787 only from the `hermex` Tailscale proxy and 9119 only from
the existing `hermes` proxy. DNS/public-IPv4-HTTPS egress restrictions remain.
`HERMES_WEBUI_SECURE=1` marks cookies secure behind Tailscale TLS without trusting
arbitrary forwarded headers. Keep both interfaces private to the tailnet.

## Password prerequisite

The supplied `hermes/hermex-sealed-secret.yaml` contains a newly generated strong
password, sealed to the exact name `hermex-auth` and namespace `hermes` using the
existing controller's public certificate. The Application includes this exact
filename. The plaintext handoff is in the ignored, mode-0600 local file
`verification/cache/hermex-secrets/password.txt` in the implementation worktree;
it is not available from a fresh clone.

Before replacing the pod, reconcile the SealedSecret and confirm that the
controller created Secret `hermes/hermex-auth` with a nonempty `password` key,
without displaying its value. The required reference prevents passwordless
startup, but a missing Secret would interrupt the existing dashboard because
the Deployment uses `Recreate`. Preparing the encrypted manifest does not create
the live Secret or deploy the integration.

Creation/sealing requires approval under the [Sealed Secrets procedure](../docs/operations/sealed-secrets.md).
Use a new strong password and the existing controller's public certificate. Do
not read its private key, reuse dashboard/OAuth values, or put the password in
arguments, history, Git, logs or chat. Use a restricted local file for any approved
plaintext handoff, and enter it directly into Hermex. Rotation and restart are
separately reviewed operations.

## Verification and rollout

1. Run the [repository verifier](../verification/README.md) and review the diff,
   manifest selection and sealed password. Preserve manual sync and storage IDs.
2. Confirm live capacity, tailnet hostname availability, and a recent successful
   consistent backup. Local validation does not establish those live conditions.
3. Review shared OAuth behavior before using production state: Hermes 0.22.2
   re-reads tokens under its auth-store lock before refresh. Both runtimes must
   use the same source and `/opt/data`. Never copy/restore a rotating grant to test.
4. After approval, publish through the normal Git workflow and sync the root's
   child Application definition. Sync the new SealedSecret first and confirm its
   successful reconciliation, then sync Hermes without pruning or force/replace.
   Do not sync during the backup controller's maintenance window.
5. Verify WebUI runs as UID/GID 10000 and its source mount is read-only. Missing
   sessions and invalid passwords must fail; correct login must succeed. On the
   actual phone, test streaming, a small request through the existing model,
   history and a harmless workspace operation. Recheck the original dashboard.
6. After an approved restart, verify persistence and the original PVC identity.
   Confirm both containers terminate before backup snapshots. Inspect memory and
   cold-start time before declaring acceptance complete.

Local tests must use fresh synthetic state, the two pinned images and manifest
commands/permissions. Exercise login rejection/success, session/workspace APIs,
agent imports, `/api/chat/start` and streaming. A loopback mock model can exercise
real agent code and persistence without a subscription request. This does not
verify iOS networking, Tailscale enforcement or production OAuth.

### Local verification: 21 October 2026

An AMD64 rootless Podman test used the pinned upstream images, fresh synthetic
state, declared UID/capabilities, and 2 CPU / 2 GiB limits. The source-copy init
command passed after excluding the image's unreadable build-time lock file.
The upstream entrypoint selected Python 3.14.8 (SQLite 3.53.1), installed its
dependencies, and ran the server as UID/GID 10000. Authentication rejection and
login, secure cookies, session/workspace APIs, agent imports and the declared
startup probe passed. Two processes serialized on the shared Hermes auth lock.

Chat streaming passed through the real agent implementation against a loopback
OpenAI-compatible mock model, and the response/history survived container
restart. No subscription request, real OAuth grant, production volume or cluster
credential was supplied. The fixture server and WebUI used loopback-only test
ports; test containers were stopped afterwards. ARM64 was verified in the image
index, not executed locally. Kubernetes network isolation, real provider calls,
tailnet ingress and the installed Hermex app remain rollout acceptance checks.

Rollback removes the WebUI container, its init/temporary volumes and exposure
through reviewed Git changes. Preserve the PVC, `/opt/data/webui`, selected model
and current grant. Without pruning, removing manifests does not remove live
Service/Ingress resources; separately review deletion of those exact Hermex
resources if needed. Never restore an old `auth.json` as an image rollback.

## References

- [Hermex setup](https://hermexapp.com/)
- [Upstream container integration](https://github.com/nesquena/hermes-webui/blob/v0.52.492/docker-compose.two-container.yml)
- [Pinned startup implementation](https://github.com/nesquena/hermes-webui/blob/v0.52.492/docker_init.bash)
- [uv Python selection](https://docs.astral.sh/uv/reference/environment/#uv_python)
