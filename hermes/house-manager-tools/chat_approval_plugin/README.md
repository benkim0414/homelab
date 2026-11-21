# Source-only human chat approval plugin

This package registers only `/house-approve <proposal_id> <sha256>`, and only in
`house-manager`. It registers **no tools, RPC methods, hooks or model approval
interface**. Nothing in this source change installs or enables it.

The raw argument grammar is exactly
`house_manager_general_[0-9a-f]{32} [0-9a-f]{64}` (one ASCII space, no trimming,
case folding, extra arguments, tabs or trailing newline). Hermes surfaces may
normalize surrounding command whitespace before invoking a plugin; this handler
validates the exact string delivered by the runtime and never repairs it.

## Loader packaging and separate enrollment

Verified against public installed Python source under `/opt/hermes`:

* A Python directory plugin needs **`plugin.yaml` (or `plugin.yml`) and
  `__init__.py` containing `register(ctx)` at the same package root**.
  `PluginManager._load_directory_module` imports that `__init__.py` as a package;
  a lone connector script or portable `plugin.json` is not this Python plugin.
* This directory is the complete package. For a separately authorized enrollment,
  its intended destination is
  `$HERMES_HOME/plugins/house-manager-chat-approval/`, with `HERMES_HOME` resolving
  to the **house-manager** profile, not the launch/default profile. Keep its
  manifest name and installed directory name aligned. No pip dependencies or
  sibling repository imports are required (Python stdlib only).
* Explicit operator plugin enablement is required. Do not copy this package into
  a discovered plugin directory, enable it, edit a live profile, or provision a
  credential merely because these source files exist.
* Use an in-process trusted Python plugin runtime. An isolated host that omits or
  serializes source/session provenance is not automatically authorized; the
  handler fails closed rather than accepting a dict as a `SessionSource`.
* Operator enrollment must separately provision `HOUSE_MANAGER_APPROVAL_TOKEN`
  for the command process and the corresponding dedicated, active, non-admin HA
  approver identity on the HA endpoint. This credential must differ from the
  model connector's `HA_MCP_TOKEN`; there is no fallback or shared token lookup.
  Production reads use only the mapping returned by `current_secret_scope()`;
  missing scopes AND missing keys fail closed. Do not use `get_secret()` here:
  it may fall back to ambient env on a single-profile scope miss.
  No real credential was inspected during development/testing.

`ctx.register_command` accepts a synchronous `fn(raw_args, *, source,
session_id, session_key, platform)` handler and `argument_mode='text'`.
`plugin_command_dispatch.invoke_plugin_command` supplies only declared context
keywords. `ctx.ask_choice(question, choices)` returns the choice **value**, or
`None` on unavailable picker/cancellation/timeout. Only `approve_exact` proceeds.
The complete exact JSON document is sent to the picker, without truncation,
including all edit before/after data, bindings, hash and original lifetime.

## Runtime provenance and fail-closed limitations

This plugin now requires the reviewed downstream `ctx.session_launch_source()`
API, live command-dispatch lease and an established secret scope. It allows only coherent cli/tui/gui frozen
launch evidence matching the presentation surface; tool/oneshot sessions are
denied even when their presentation surface is cli. Unpatched installations,
including standalone paths without a scoped secret context, fail closed.
Before POST it must claim dispatch once on the owning event loop. A cancelled
worker cannot reuse copied context to submit after its async command ended.
Cancellation after an admitted request cannot undo remote I/O; inspect status.

The installed classic CLI passes `source=None`, `platform='cli'` and its runtime
session ID/key. The legacy TUI/serve backend also passes `source=None`, with its
runtime `_session_source(session)` and ID/key. These explicit-None contexts are
accepted only when `ctx.session_surface()` agrees with `cli`, `tui`, or `desktop`.
A missing source keyword is **not** treated as explicit None.

The installed messaging/unified gateway passes a **`gateway.session.SessionSource`**
object; `source.platform` is a **`gateway.config.Platform` enum**, not a string.
Only exact `SessionSource` instances with `Platform.LOCAL`, `is_bot=False`,
non-rejected matching profile, no upstream relay and no detached route can pass.
The runtime surface must also independently identify `cli`, `tui` or `desktop`.
Discord/Telegram/other messaging, ACP, cron executions and bot/hosted-room
surfaces are denied. Strings, dicts, user labels and user-supplied session IDs
cannot substitute for the runtime context.

**Known installed-runtime limitation:** the unified gateway's command path binds
`HERMES_SESSION_PLATFORM='local'` outside the active frozen-policy scope, so
`ctx.session_surface()` may yield only `local`. That is insufficient to distinguish
CLI/TUI/Desktop from ACP or bot-room sessions. This plugin intentionally refuses
that path instead of treating all local sessions as human. A trusted upstream
surface binding is needed before that route can be enrolled; do not loosen the
allowlist to `local`. The prepared `runtime_context/` patch fixes policy binding
and supplies the narrow public accessor without exposing the whole policy. It
is packaged in the reviewed init overlay but has not yet been deployed.

## Credential and human trust boundary

This is a trusted local-human feature, **not** secure model-accessible approval.
Its security assumption is that the enrolled house-manager profile lacks arbitrary
code execution, shell, file/environment reading/writing, credential-bearing HTTP
and equivalent escape tools. A model with those powers could extract the approval
credential or modify/invoke the plugin and bypass its UI. Restrict tools and
protect plugin files/environment at the process/operator boundary before
credential enrollment. Session/source labels are runtime provenance, not HA
credentials. Human possession of the trusted local UI and its confirmation is
required; bot-to-bot messages are not approvals.

The fixed URL is the same HA service origin as `general_connector_v3.py`, with
only `/api/house_manager_general/chat-approvals/<identifier>` reachable. GET must
return exactly `{proposal: <document>, status: 'awaiting_approval', interaction_id}`.
The interaction ID is server-generated lowercase 32-hex preview binding, never
an argument accepted from the user or model. The document's
exact v3 outer keys and canonical SHA256 (sorted keys, compact UTF-8 JSON,
`ensure_ascii=False`, no NaN, excluding `sha256`) are checked against both literal
arguments. Action proposals, nonpending records, malformed/changed documents and
expired/future lifetimes are rejected. Null lifetimes remain null; finite legacy
lifetimes must remain exactly 900 seconds. No expiry is extended or rewritten.
HA remains authoritative for payload policy, current inventory/bindings, native
config/on-off drift, lifetime and atomic ledger replay protection at GET and POST.

Create confirmation explicitly warns that saving **enables a persistent routine**.
Edit confirmation warns that the current **on/off state is preserved**. POST sends
exactly `{sha256, interaction_id, surface: 'local_chat', session_id: <runtime session id>}`.
The server checks the preview interaction, hash and approver under the mutation
coordinator's lock; a newer preview invalidates an older confirmation prompt.
Confirmation interactions expire after 300 seconds, independently of the stored
proposal's no-expiry or legacy lifetime. A stale interaction needs a fresh prompt.
Success requires the matching proposal ID and HA's `verified_enabled` or
`verified_edit` receipt for the respective kind. Device physical state is never
claimed verified. There is no general HA route or model tool.

HTTP makes one attempt per GET/POST, disables environment proxies and redirects,
uses a 10-second socket timeout and reads at most 1 MiB plus an overflow sentinel.
Oversized/malformed responses, duplicate JSON keys, NaN, redirects and non-200
responses fail closed. This is a bounded socket timeout, not an overall wall-clock
deadline against a peer that continually drips bytes. Neither remote errors nor
response bodies/headers/credentials are returned to chat. A failed POST may have
committed; the generic result tells the operator to inspect proposal status,
never automatically retries. A replay after uncertainty remains HA-ledger gated.

## Offline verification

From the parent `house-manager-tools` directory:

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_chat_approval_plugin.py
```

Tests use synthetic contexts, synthetic credentials and fake HTTP responses only;
no network, installation, credential read or live approval is performed.
