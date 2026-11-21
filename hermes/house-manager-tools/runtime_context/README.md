# Minimal plugin-command frozen-policy context fix

**Local implementation and regression artifact only; not installed or enabled.**
Parent integration now includes the narrow downstream public launch-source API
and a reproducible five-module init overlay; the initial two-module findings
below have been extended. See `../CHAT-APPROVALS.md` for enrollment and cutover.
No live Deployment, ConfigMap, image, profile credentials, model settings, auth
gate or core runtime files were changed. Local deployment manifests now contain
the reviewed overlay declaration. Public installed source was read with
`kubectl -n hermes exec deploy/hermes -c hermes -- python -c ...`.

## Reviewed base and mechanism

The public `/opt/hermes/install-stamp.json` identifies Hermes **0.23.2**, commit
`ae2a81ccc00e9b7c06301523e5bb09608397149c` (Docker, external updates).
These exact original bytes, not a mutable tag or a version string, are required:

| Runtime module | Original SHA256 |
| --- | --- |
| `gateway/session_policy.py` | `22b42f98d6ae57c23a0963530f5aa50852f55fc623dc0c7a77940d7647ab6e09` |
| `gateway/session_commands.py` | `04d0887612721c979ba254d9492a24632ae934b5afb369182e162543091db628` |
| `hermes_cli/plugin_session.py` | `4311b653262e9bed2b73cebd23824b83d943c5df99e1aa0ee88d711f8d7efe74` |
| `hermes_cli/plugins_context.py` | `2984a4def458cb1ac4b6f6406861f4dd905a00e4bb11000f3383ffca9136c25f` |
| `gateway/plugin_command_choice.py` | `f3a04b3fac8da831201b7b668652a5dca58befd87b97d3c4f16f9a6262555b77` |

`render.py:render(dict[str, bytes])` verifies all five hashes before transformation,
compiles all results, and returns only those five patched modules. Drift, partial
inputs, double application, or ambiguous anchors fail closed. CLI input/output
roots must be disjoint. The renderer uses only the standard library and never
imports/executes the source tree or modifies it in place.

The change adds `active_policy_scope(policy)` to `gateway/session_policy.py`:
set the existing `_ACTIVE_POLICY` ContextVar and reset its token in `finally`.
`_session_workspace` wraps its yield in that scope, including explicitly clearing
a nested active policy when `policy_for_source` returns None. The existing
terminal/cwd scope remains intact. Nothing calls `policy_scope`, `config`,
`effective`, `read_profile`, or credential recovery: commands must not acquire
agent-turn/model/secret side effects just to expose provenance.

The rest of `session_commands.py`, including `execute_command` and its actor,
profile, capability, admission and local-source checks, is byte-identical.
`policy_for_source` still requires the authorized `LocalSessionAdapter` route.

Rendered output SHA256:

- `gateway/session_policy.py`: `c131b910413c16108baa95a7e325d9b804345a83640480fb814cd2bf2f3acaec`
- `gateway/session_commands.py`: `7c5a59fcf459a0e530a4d8211a5fa96a2c31aed2f1d99dee5333d93a915fa32f`
- `hermes_cli/plugin_session.py`: `0cdbb86cf3a796ef57e1a7dc42b6600f38f92c6f019612b1a00eae6e7d9822d4`
- `hermes_cli/plugins_context.py`: `8e6c966cae30f614368d436ac65ab7b2492d02fa54a67abb07a348374aa8a8cf`
- `gateway/plugin_command_choice.py`: `b469fe89e4b81d4eaa097d48bdf399ab3106d6899b9d7cd7b9d358860ec4b303`

## Launch provenance and the remaining plugin seam

`ctx.session_surface()` uses `hermes_cli/plugin_session.py:context_surface` /
`session_surface`, which reads `active_policy().platform`. Before this fix a
unified-gateway command sees session-env platform **local**. After it, the
presentation surfaces are **cli**, **tui**, **desktop**.

**Never authorize on presentation surface alone.** `SURFACES` maps both `tool`
and `oneshot` to `cli`. The frozen `LocalSessionPolicy.source` retains the launch
label. `build_policy` records the same label in `request_json['source']`, defaults
it explicitly to `cli`, and uses `SURFACES[source]` for `platform`.
`provenance.py:trusted_launch_source(policy)` is a separate, fail-closed predicate
for later adapter integration. It accepts only coherent frozen evidence:

| Frozen source | Required platform | Predicate |
| --- | --- | --- |
| `cli` | `cli` | allow label |
| `tui` | `tui` | allow label |
| `gui` | `desktop` | allow label |
| `acp`, `tool`, `oneshot`, `bot_room`, `a2a` | any | deny |
| missing/unknown/`local`/`desktop`, malformed or inconsistent request | any | deny |

Installed Desktop source confirms canonical Bot Chat does **not** imply
`source='bot_room'`: `apps/desktop/src/plugins/hermes-bots/canonical-chat.ts`
lines 538–555 issues `session.create`; `apps/desktop/src/api/canonical-protocol.ts`
line 556 supplies `source: 'gui'`. Owner-created fallback Bot Chats can use
`cli` (`gateway/session_bot.py` lines 369–371). Title, `follow_profile_config`,
client name, and route labels are not authorization evidence.

**Resolved local API seam:** upstream's installed public API does not expose the
whole active policy to plugins. The reviewed downstream patch instead adds only
`PluginContext.session_launch_source()`, backed by `context_launch_source()` and
`session_launch_source()` in `hermes_cli/plugin_session.py`. It returns cli/tui/gui
or None after the same coherent frozen-source checks; it never returns policy,
configuration, model or credential objects. The plugin calls that public method,
not a private core import, and refuses a missing accessor or inconsistent surface.
Classic interactive CLI uses the owner's attached CLI reference; credentials
still require an established scoped secret context. This downstream API is not
claimed to exist in unmodified upstream Hermes. The predicate never accepts
model/client-supplied policy objects.

This is runtime provenance, **not independent human attestation**. Keep the
adapter's existing profile + verified actor gate, separately enrolled approval
principal, exact stored proposal/hash checks, server-bound choice interaction,
freshness, replay and effect-boundary readback checks. A client that already has
control/choice authority, or model code with equivalent credential authority,
is outside the protection this ContextVar fix can provide.

## Reproduce locally

From the worktree root (all fixture writes are ignored local public source):

```sh
python3 hermes/house-manager-tools/runtime_context/capture_public_sources.py
python3 hermes/house-manager-tools/runtime_context/capture_public_sources.py --upstream
python3 hermes/house-manager-tools/test_runtime_context.py
python3 hermes/house-manager-tools/runtime_context/render.py \
  --source-root hermes/house-manager-tools/runtime_context/.test-state/installed \
  --output-root hermes/house-manager-tools/runtime_context/.test-state/rendered
git diff --check
```

The collector reads a fixed allowlist below `/opt/hermes`; it never reads a
profile, session store, transcript, configuration or auth file. It pins all
fixture hashes, including an AST-extracted executor body from public
`gateway/run.py`. No upstream repository is vendored. Fresh capture refuses drift;
review and repin intentionally for another build, never weaken the hash gate.
The optional `--upstream` path captures the identical public files from immutable
commit `ae2a81ccc00e9b7c06301523e5bb09608397149c` and requires the same hashes.
It was exercised successfully and needs no cluster authentication. Use that mode
for fresh local/CI reproduction or after production has the overlay; capturing
from an already-overlaid pod must fail the pristine-source gate.

The stdlib unittest harness compiles actual installed definitions in isolation:
`LocalSessionPolicy`, `policy_for_source`, `_session_workspace`,
`_hm_run_plugin_handler`, `invoke_plugin_command`, plugin surface accessors,
and `_run_in_executor_with_context`. Unrelated dependencies are explicit stubs;
this is not a full gateway integration/UI acceptance test. It reproduces original
`local`, exercises sync/async commands across all three surfaces, denies the
noninteractive labels, verifies nested/None/error/cancel resets, concurrent tasks,
actual executor `copy_context` propagation, source-authorization refusal and
original execute-command actor/profile refusals. Input and output modules compile.

Initial local result: 11 tests passed under a clean `env -i` with
`PATH=/usr/bin:/bin TZ=UTC`. The extended 12-test suite additionally exercises the
real plugin handler using the patched accessor on all launch labels, including
full-preview cancellation without POST. Three packaging tests cover deterministic
bundle generation, mount/image/credential invariants, init idempotence and drift/
symlink refusal. This is local regression verification, not UI acceptance.

Cancellation does not erase copied provenance, so the downstream patch now also
binds a shared command-dispatch lease. Teardown closes it, and the final one-shot
claim is decided on the owning event loop, checking its task's pending cancel
count even before `finally` runs. A synchronous worker whose picker later returns
`approve_exact` cannot POST after cancellation won admission. Native viewer
pickers receive the lease cancellation predicate so the existing request loop
retires their cards. Missing leases deny this approval plugin, while unrelated
legacy picker callers keep their old behavior.

The claim is the external-I/O admission point: a cancellation that wins before it
denies submission. Cancellation AFTER an admitted request cannot unsend or undo
remote I/O. Check the ledger/readback and never automatically retry an uncertain
outcome. Provenance alone, finite preview expiry alone, or rechecking surface
labels does not provide this cancellation boundary. The regression suite includes
immediate cancel-then-release of the real synchronous picker worker.

## Packaging for parent review (not applied here)

Prefer a **reviewed derived image**, pinned to the base image digest:
verify the five original files, run the renderer into a separate build directory,
copy only the five generated modules into the derived layer, run the regression
suite, and publish under a new immutable digest. Preserve the base provenance and
record this downstream patch; do not label it an unmodified upstream build.

If a ConfigMap overlay is necessary:

1. The prepared `build_bundle.py` generates an immutable content-addressed
   ConfigMap containing only renderer/init code plus reviewed output digests,
   not vendored upstream modules. The init generates the five output files into
   disposable emptyDir; no persistent or running-image code is patched in place.
2. Use an init container with the **same exact base image digest** as the main
   container. Its `/opt/hermes` must remain unoverlaid. Verify original hashes,
   render locally in disposable scratch, and compare all generated modules
   against the reviewed output hashes. A mismatch must
   prevent startup. Do not merely verify the already-overlaid main files.
3. Mount only the five declared Python files into the main container's existing
   `gateway/` and `hermes_cli/` packages using separate **read-only subPath file
   mounts**. Do not shadow package directories or delete sibling modules.
   The init check must cover exactly the ConfigMap revision mounted by main.
4. Roll out through reviewed GitOps with a practical rollback: restore the prior
   image/overlay declaration. No shell patching, mutable entrypoint rewriting,
   `kubectl cp`, or ad hoc edits in a running container.

Before approval enablement: deploy the reviewed public provenance accessor,
exercise real CLI/TUI/Desktop Bot Chat choice rendering and verified actor/profile
isolation, test disallowed ACP/tool/oneshot/room/peer command paths end-to-end,
and verify the enrolled approval-principal boundary. Nothing here claims those
live checks or deployment have occurred.

References: [official plugin guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/)
and [published API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api/).
