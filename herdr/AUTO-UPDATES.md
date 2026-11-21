# Automatic Herdr releases

## Scope and activation

On 2026-11-21 the operator selected fully automatic testing, merging, building
and deployment for Herdr's legacy TUI/server and Herdr Core/mobile backend.
This is a **Herdr-only exception** to the repository's manual update posture.
It does not authorize changes to other apps, credentials, volume identities,
pruning, automatic agent restoration, or network exposure/egress.

The files describe the pipeline; their presence is not evidence of activation.
Initial publication, successful exact-SHA CI, a tested image digest, and a reviewed
Herdr Application adoption are still required. Do not enable the live automatic
sync policy before reviewing the complete generated-to-live Herdr diff. In
particular, preserve the workstation and both approved mobile access keys.

## Release path

1. The existing daily Renovate run checks four custom HTTP datasources in
   `../renovate.json5`: legacy Herdr's GitHub release assets and Core's official
   `latest.json`, separately for AMD64 and ARM64.
2. One grouped PR updates the four version/SHA256 entries in
   `image/releases.json`. Root automerge remains disabled; only these four
   source-pin dependencies opt into PR automerge. The custom container image
   remains excluded from ordinary image-update proposals.
3. `../.github/workflows/herdr-image.yml` runs for pin PRs. It validates GitOps,
   tests wrappers/pins/installation/publishing, builds AMD64, and runs disposable
   SSH, TUI, Core terminal, restart, old-binary replacement and host-key tests.
   The independent `Verify` workflow also checks the PR.
4. After checks pass, Renovate merges using its existing bot authentication and
   normal REST merge, not GitHub platform auto-merge. Global GitHub auto-merge and
   Actions PR-creation permissions are not enabled. A later daily run may perform
   the merge; it is not an immediate platform-managed merge queue.
5. A main-branch run builds/tests again. The read-only GitHub-permission build job exports the
   exact tested image with an archive SHA256 and image ID. A separate main-only
   publish job verifies both, pushes the artifact, and invokes
   `publish_tested_image.py`.
6. The publisher creates a generated commit changing **only the two image digest
   references** in `deployment.yaml`. It checks the tested Herdr tree against
   current main, skips stale builds, updates the ref with `force: false`, and
   reads back the exact commit/file. Concurrent main updates are not forced or
   silently retried. No PR is created with `GITHUB_TOKEN`; such PRs would not
   trigger normal CI. Token-generated commits also do not recurse into Actions;
   ArgoCD observes Git independently.
7. Only the Herdr Application opts into automated sync, explicitly disabling
   pruning, self-healing and empty sync. The policy exception pins its identity,
   repository, main revision, app path and destination. All other apps remain
   manual. Automatic sync covers the selected Herdr manifests, so future manual
   edits to those manifests still need review before merging.

The deployed node is AMD64. ARM64 artifacts are pinned and checksum-validated,
but ARM64 runtime/image execution is not established by the AMD64 smoke test.
A latest-only feed cannot describe old releases; Renovate can log an old-version
extra-digest lookup warning while still producing a valid version update.
A feed/schema/checksum failure must not be treated as permission to use `latest`
or download arbitrary binaries at runtime.

## Immutable binaries and persistent data

`image/install_releases.py` accepts only stable numeric versions, complete
architecture pairs, and SHA256 pins. It downloads official release URLs during
image build, verifies bytes, and rejects unexpected archive members, paths and
links. Core's license and third-party notices are retained. A SHA256 match proves
byte identity to the published pin, not an independent signature verification.

The image provides legacy `/usr/local/bin/herdr` and image-owned Core/hc.
Before opening SSH, `managed_clients.py` runs as UID/GID 10000 and atomically
reconciles `~/.local/bin/herdr`, `herdr-core`, and `hc` to the image paths. This
covers mobile clients invoking absolute installer paths as well as normal PATH
lookups. Old regular public binaries are preserved as `*.before-image-*`; links
are replaced without following their targets. Unexpected directory symlinks,
foreign ownership and hardlinked regular binaries fail closed. Configuration,
Core databases, saved layout, host keys and SSH access lists are not replaced. Backups use a separate, flushed copy and
atomic publication, not a source hardlink: interrupted copying or link replacement
must leave the original binary eligible for a later startup retry. Regression
tests inject failures at both boundaries while retaining unrelated-hardlink rejection.

Core starts before SSH as the same unprivileged user. Its lifetime belongs to
the container, not an SSH login; no systemd user-manager enrollment is introduced.
Do not use `hc server status` as a health probe: Core 0.1.21 auto-starts a stopped
daemon. `core_health.py` instead connects to the existing default Unix socket,
checks peer UID/GID and the immutable executable inode, without invoking the CLI.
It allows a legitimate Core-only restart and rejects a missing/stopped listener.
This is listener/process health, not a complete application API transaction.

Pod replacement disconnects both client paths and ends their running terminal
processes. Saved data stays on `herdr-data` / `herdr-k3s-data`; Hermes/OpenClaw
workloads, credentials and stored conversations are not restarted by this
pipeline. Reconnect deliberately; do not assume active exec-backed work survived.

## Verification and failure handling

Local validation and live rollout evidence are separate. Use the commands in
[README.md](README.md#build-and-verification), plus:

```sh
python3 -m unittest discover -s verification/tests -p 'test_herdr*.py' -v
verification/cache/bin/actionlint .github/workflows/herdr-image.yml
```

Renovate validation/extraction uses the selected runner and the commands in
[the Renovate runbook](../renovate/README.md#validation); include new pin files in
Git's file inventory (intent-to-add suffices for a local extraction). Do not claim
a local extraction proves authenticated bot merge or live HTTP lookup success.

A Docker socket permission error is a local blocker, not an image smoke pass.
CI must exercise the actual image before activation. Native sandboxed binary
checks do not establish container SSH, storage restoration or mobile login.
After activation verify the exact image digest in init/runtime containers,
completed rollout, Argo revision/health, unchanged host key/PVC, and both clients.

On failed tests or publication, leave the current deployment unchanged. A failed
rollout is not permission to repeatedly restart, prune, force-replace or blindly
downgrade state. Stop Herdr automation before operator recovery; remove its
`automated` block to restore manual policy and disable only the source-pin
rule's automerge. Keep other applications untouched.

A Git/image rollback cannot reverse an upstream data migration. Preserve current
state and review backup/restore and compatibility before a downgrade. Rolling
back to a historical image without Core additionally requires restoring the old
public Core executable/alias from its preserved backup; do not restore old
configuration, SSH keys or databases merely to undo binary packaging.
