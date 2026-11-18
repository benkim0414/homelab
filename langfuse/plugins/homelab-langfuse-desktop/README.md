# Desktop native tracing guard

Repository-managed **standalone user plugin**, named `homelab-langfuse-desktop`.
It must replace, not accompany, an enabled bundled `observability/langfuse`.
This directory is staged code, not evidence of installation or runtime tracing.

## Contract

Version 1.0.1 gives each newly created turn root a fresh SDK trace ID through a
root-local client view. It deliberately ignores the pinned delegate's repeating
session/task seed, but preserves the original session ID and existing active-root
lookup. Requests/retries/tools within an active turn keep that root. This changes
neither the real SDK client nor canonical bundled code; older shared traces are
left intact. New processes are required to load this fix.

`register(ctx)` uses native `ctx.register_hook(name, callback)` for the eleven
manifest hooks and `ctx.on_unload(callback)` for cleanup. Each registration loads
a fresh private child module using importlib, checks `SOURCE_SHA256` before
executing exactly those bytes, then calls the native `register` once. It does not
import or patch the canonical native module or write Hermes core/environment.

Only profiles `default` and `homelab-scientist` are admitted, using
`hermes_cli.profiles.get_active_profile_name()` and
`hermes_constants.get_hermes_home()`. The following launch settings must all be
present **exactly**, at registration and each callback:

```text
HERMES_LANGFUSE_BASE_URL=https://langfuse.tailbd291c.ts.net
HERMES_LANGFUSE_CAPTURE=metadata
HERMES_LANGFUSE_ENV=homelab-desktop
HERMES_LANGFUSE_SAMPLE_RATE=1
OTEL_SERVICE_NAME=hermes-desktop-<profile>
```

Multiplexing is refused using `agent.secret_scope.is_multiplex_active()`.
Authentication uses only normal scoped `get_secret()` for the two primary
`HERMES_LANGFUSE_*_KEY` names. Alternate `LANGFUSE_*` values are never returned
by the delegate-local `_env`. The delegate's `_capture_mode` is fixed to metadata;
changing launch capture settings additionally prevents hook admission. Delegate
logging and exception diagnostics are disabled, without changing global logging.
SDK debug mode via `LANGFUSE_DEBUG` is refused.

The actual constructor wrapper checks the complete native kwargs against fixed
URL/environment/sample-rate and primary scoped credentials before calling the
SDK. It refuses pre-existing same-public-key resource managers under the SDK's
RLock, then checks actual client `_base_url`, `_environment`, `_resources` and
manager `base_url`/cache identity before returning the client. It uses a private
OpenTelemetry tracer provider, not the process-global provider, so reloading does
not accumulate exporters on a shared global provider. Hooks recheck destination,
cache identity and credential scope before delegate work.

Unload is idempotent: deactivate, unregister this generation's atexit callback,
finalize private traces only when still admitted, clear state, remove the private
child from `sys.modules`, and release only the newly owned client/cache entry and
private provider. The native atexit registration is intercepted locally, never
added to process-global atexit. Session shutdown hooks do not independently shut
the SDK down. Existing/replaced foreign cache entries are never removed or shut
down. Final SDK/provider shutdown can drain already queued metadata events; a
policy change is not a guarantee to cancel previously queued exports.

## Review and testing

```sh
verification/venv/bin/python -m unittest discover \
  -s verification/tests -p test_langfuse_desktop_guard.py -v
```

Tests use fake credentials, fake SDK/resources/providers and temporary homes;
they execute the reviewed public native source, not real profile state. Set
`HERMES_TEST_CORE` to a Hermes source checkout if it is not available at the test
module's workstation default. Source-dependent tests skip when absent; a skipped
suite is not an acceptance result. Tests never construct the real SDK or contact
Langfuse. Source pin drift intentionally fails valid-registration tests.

Compatibility was reviewed against native source SHA-256
`75f0959a4152145a7c33591d6ddd3c4c8bfd53b29e0807f18abdc19bb8a485d1`
and Langfuse SDK 4.15.2 public source. Private SDK APIs used:
`LangfuseResourceManager._lock`, `_instances`, `base_url`, client `_base_url`,
`_environment`, `_resources`; public SDK API: constructor `tracer_provider`,
`flush` and `shutdown`. Unsupported layouts fail closed. Re-review those APIs and
native serializers before updating either dependency or source pin. Keep SDK
construction behind policy/kwargs/cache checks, and use private tracer providers
for reloadable integrations to avoid duplicate process-global exporters.

## Limits / installation review

This protects this adapter's native hooks, not arbitrary code in the Python
process. It cannot prevent another plugin or direct SDK user from independently
exporting, mutating globals, or taking a reference to a manager after this adapter
created it. Do not run another same-project SDK consumer in this single-profile
process: the SDK has no consumer reference-count API to detect later foreign
reuse. The resource lock prevents this guard's concurrent creations; it cannot
force unrelated SDK callers to honor a single-owner policy. Metadata mode keeps
IDs, roles, tool names and structural metadata; it is not zero-data collection.
No runtime profiles, credentials or configuration are installed/changed here.
Real endpoint/project routing and end-to-end metadata readback remain separate
operator acceptance checks before enabling either desktop profile.
