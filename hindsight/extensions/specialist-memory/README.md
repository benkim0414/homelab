# Local specialist extension

Local source and synthetic transport tests only. This package does not activate
memory or change the deployed server. No live key/schema creation, memory
migration, provider change, consent state, or operator-write service is included.
Database-backed recall, durable saves and production container packaging remain untested.

The tenant and validator slots alone deliberately reject specialist access.
Call `homelab_hindsight_specialists.ingress.create_guarded_app(memory, **kwargs)`
instead of the upstream `hindsight_api.api.create_app(memory, **kwargs)` when
constructing a local test application. This public factory seam places the ASGI
boundary outside both native HTTP and MCP routing. It does not monkeypatch
upstream code, create a reverse proxy, start another service, or replace providers.
Production entrypoint/image wiring is not included or authorized by this stage.

## Fixed policy

| Identity | Bank | Schema |
| --- | --- | --- |
| existing legacy key | existing banks, unchanged | current configured database schema (normally `public`) |
| `learning_coach` | `infinite-recursion` | `user_learning_coach` |
| `career_advisor` | `next-level` | `user_career_advisor` |

Optional, separate operator keys target those same two fixed banks/schemas.
They are not specialist keys. Configure both operator keys or neither.
Their authority must remain outside every agent runtime and tool dispatcher.

Keys are compared using `hmac.compare_digest` for all identities, without
short-circuiting comparisons. Caller-supplied `tenant_id` / `api_key_id` never
select an identity. Auth clears those fields before validating credentials.
Missing, malformed, duplicate or unexpected configuration fails construction;
legacy schema collisions fail closed. Workers discover the current configured
legacy schema and both fixed specialist schemas, without provisioning them.

The operation validator independently classifies keys; it does not rely on
mutable authentication labels. It allows own-bank recall and explicit content
read hooks, rejects mutation/generation/import/bank creation, denies config
changes and admin/profile/config read hooks, narrows bank listings before query,
and returns an empty **write tag scope**, not `None`. Unknown read/precheck
operation names are denied. Internal worker contexts are accepted only without
keys/identity claims in an allowlisted active schema. Upstream transport parsers
cannot set `internal`; this is a trusted in-process worker boundary, not a public
API flag. Key-bearing contexts never use the worker exception.

The outer boundary permits only the exact own-bank REST recall path and native
single-bank MCP protocol messages needed for `recall`. Unknown paths, other
banks, generation, mutation, batch JSON-RPC and unknown tools are denied before
upstream dispatch. This default denial also covers future endpoints. Requests
cannot select a bank using query strings, encoded paths, `x-bank-id`, or tool
arguments. Specialist MCP discovery advertises only `recall`.

Parsed JSON bodies are limited to 65,536 bytes, 128 frames and five seconds. Queries are
limited to 4,096 characters. Duplicate JSON keys, non-finite values, duplicate
authorization/session headers and non-object bodies are rejected. A bounded
per-process map binds each issued MCP session to its fixed identity. Credentials
remain required on every request, including event-stream GET. Unknown sessions
and cross-role replays fail closed. Each map entry holds its identity and monotonic
last-admission timestamp together; there is no separate timestamp index. Entries
expire after one hour (`SESSION_IDLE_TIMEOUT_SECONDS`) without an admitted
same-role request. Expiration is pruned at request/initialization admission,
including after body receipt, not by a background task. Rejected requests do not
extend the deadline; an open stream alone does not refresh it. Expired IDs are
denied before upstream dispatch, so clients must reconnect by initializing a new
session without the old ID. The boundary does not retry requests automatically.
An authenticated same-role upstream MCP session-not-found (404), or successful
session deletion, also releases the entry. Pending initialization counts toward
the shared 64-session capacity. Restart clears the map. Stateful MCP therefore
requires one process or process affinity; there is no new shared session store.

The boundary also supplies the validated nonlegacy identity through the MCP
SDK's public `AuthenticatedUser`/`AccessToken` scope interface. The native
transport retains session ownership independently of this expiring cache.
Therefore a legacy caller cannot reuse a still-live specialist session after
its cache entry expires. Existing legacy requests keep their original scope.
This contract is pinned to MCP SDK 2.3.0. No OAuth flow or separate credential
service is added.

Only optional operator keys can pass own-bank creation (`PUT`), own-bank retain
(`POST .../memories`), or native MCP `retain`. These keys do not enable a
specialist retain tool. They provide no automatic save approval: the human
operator must approve the exact content and destination outside agent dispatch.
No consent service, approval ledger or operator UI is introduced.

## Environment references only (do not deploy)

The package uses upstream extension-loader slots:

- `HINDSIGHT_API_TENANT_EXTENSION`: `homelab_hindsight_specialists:SpecialistTenantExtension`
- `HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION`: `homelab_hindsight_specialists:SpecialistOperationValidator`

Supply existing/injected secret **references**, not values in repository files:

| Tenant slot reference | Validator slot reference | Meaning |
| --- | --- | --- |
| `HINDSIGHT_API_TENANT_API_KEY` | `HINDSIGHT_API_OPERATION_VALIDATOR_API_KEY` | same existing legacy key |
| `HINDSIGHT_API_TENANT_LEARNING_COACH_API_KEY` | `HINDSIGHT_API_OPERATION_VALIDATOR_LEARNING_COACH_API_KEY` | same learning-coach key |
| `HINDSIGHT_API_TENANT_CAREER_ADVISOR_API_KEY` | `HINDSIGHT_API_OPERATION_VALIDATOR_CAREER_ADVISOR_API_KEY` | same career-advisor key |

Optional paired references use the suffixes
`OPERATOR_LEARNING_COACH_API_KEY` and `OPERATOR_CAREER_ADVISOR_API_KEY` under
each of those two extension prefixes. Do not generate or inject them during
local validation. Tests use explicitly synthetic fixture strings only.

Do not set `HINDSIGHT_API_MCP_AUTH_TOKEN` (even empty presence is rejected) or
enable `HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED`. Legacy normal-key behavior is
preserved, not the optional legacy transport-auth bypass. The existing database
schema configuration is read through upstream `get_config()`; do not change it
to either specialist schema. There is no schema override accepted by this package.
Never distribute an operator key or the existing legacy key to a specialist.
Existing clients remain in their existing schema. The guarded factory rejects
mismatched extension-slot key mappings, versions other than Hindsight 1.2.1
and MCP SDK 2.3.0,
and nondefault `mcp_mount_path` values (only `/mcp` is supported).
It does not provision schemas or start a server process by itself.

## Coverage status and upstream evidence

Reviewed public `vectorize-io/hindsight` tag `v1.2.1`, archive revision prefix
`b5e6d3d`, and exercised installed PyPI `hindsight-api-slim==1.2.1`.
Relevant upstream sources under `hindsight-api-slim/hindsight_api/`:

- `extensions/tenant.py`, `extensions/operation_validator.py`, `models.py`:
  actual public extension/context interfaces.
- `engine/memory_engine.py:4010`: `_refuse_bank_wide_if_scoped` blocks bank-wide
  export through non-`None` write scope. Runtime tests verify both async export
  submission methods reject before backend access; lack of a direct validator
  call in those methods is **not** evidence of a bypass.
- `engine/memory_engine.py:3852`: `_check_retain_writes` is the indirect scope
  gate used by `submit_async_file_retain`. HTTP retain's `precheck_for` runs before
  attachment persistence. These indirect gates must be included in route audits.
- `delete_memory_unit(s)` has no direct validator gate, but no exposed REST/MCP
  call site was found; trusted Python helpers are not proof of a transport gap.
- `extensions/http.py` only contributes routers. It cannot install an app-wide
  authorization boundary. `api/__init__.py:create_app` composes the actual HTTP
  app, MCP middleware and MCP lifespans. The local guarded factory wraps its
  returned ASGI application through that public factory seam.
- MCP middleware authenticates each POST before routing; a supplied session ID
  does not skip that authentication. Its unauthenticated GET-without-session
  probe returns 200 without reaching memory; this is not a data-access grant.

The boundary does not depend on proving that every upstream mutator calls a
validator. Only the bounded read path reaches upstream for specialist keys.
Extension-only loading still fails closed, without the required outer boundary.
The test suite exercises successful HTTP and native MCP dispatch with synthetic
empty recall results. It does not establish database-level behavior or provision
the real specialist banks. Any audit writes or other internal side effects of
database-backed recall require review before activation.

## Local verification

Use a workspace-only Python environment with the exact dependency installed:

```sh
python -m unittest discover -s verification/tests -p 'test_hindsight_specialist*.py' -v
```

Tests use synthetic keys and actual upstream types/loader. Actual upstream engine
methods run against synthetic engine objects with backend sentinels, not a
database. HTTP tests use the actual upstream factory in process. Native MCP
tests run the real server lifespans and MCP SDK 2.3.0 initialization, discovery,
recall and session termination through an in-process HTTP transport. The recall
backend and bank-config resolver are explicit fixtures. No network listener,
provider, current bank read or database call is required. Missing Hindsight
dependencies cause skips in the ordinary repository environment. Run the
dedicated installed-version environment to obtain real compatibility results.
This is not live or database-backed successful-recall verification.

TDD evidence: initial package test failed (1 failure), then passed; tenant tests
failed for missing implementation (7 failures), then passed; policy tracer failed
for missing validator, then passed; MCP transport-override regression failed
before the presence rejection was added. Final counts are reported with the
execution result, not frozen here.
