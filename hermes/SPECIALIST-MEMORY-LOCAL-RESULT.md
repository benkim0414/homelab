# Specialist memory: local implementation result

Observed on 2026-11-23 UTC. This is local source and synthetic transport evidence,
not specialist activation or production database acceptance. Local implementation,
tests and independent re-review are complete. Repairs passed the re-review with
no remaining findings. This report does not approve live rollout.

## Scope

The user approved local implementation and tests of the bounded custom extension.
The [plan](SPECIALIST-MEMORY-PLAN.md) and
[package runbook](../hindsight/extensions/specialist-memory/README.md) define the
fixed bank/schema mapping and preserve existing clients' schema routing.
No production manifests, image pins, authentication, provider/model routing,
credentials, schemas, banks, agent toolsets, volumes or backup policies changed.
No memory payload was saved. No commits, pushes or deployments were performed.

The first delegated candidate was accidentally authored in the historical
`default-career-learning` worktree and still blocked specialist authentication.
Only its four task-owned new files were transparently transferred into the
assigned `default-specialist-memory` worktree. The historical files and unrelated
work were preserved. Parent implementation and verification used the assigned
worktree. The candidate's original 23-test result was not treated as completion.

## Local implementation

- Fixed specialist identities map Learning coach to `infinite-recursion` in
  `user_learning_coach`, and Career advisor to `next-level` in
  `user_career_advisor`.
- The normal existing key retains the configured legacy schema and authority.
  Worker discovery includes that schema and both proposed specialist schemas.
- Tenant and operation-validator extensions independently validate keys. Missing,
  malformed, duplicated or mismatched key mappings fail closed.
- A pure ASGI boundary wraps the complete official application factory, outside
  native HTTP and MCP. Specialist keys can dispatch only own-bank recall.
  Other paths, other banks, writes, generation, unknown tools and future endpoints
  are denied before upstream dispatch.
- Specialist authentication outside that boundary remains blocked. Caller claims
  do not grant a role. Operator credentials are optional, separate and bank-bound.
  They must remain outside agent dispatch and do not approve memory contents.
- Native MCP discovery exposes only recall. Issued sessions are bound to exact
  identities. Missing credentials, other-role replays and unknown sessions are
  denied. Pending initialization counts toward the bounded session capacity.

## Executed verification before review fixes

1. Dedicated isolated environment: Python 3.12.16, real
   `hindsight-api-slim==1.2.1`, native MCP SDK 2.3.0.
   The focused suite ran 41 tests successfully, without skips.
2. Actual upstream HTTP application factory: allowed synthetic recall dispatch
   resolved to the own schema. Mutating API calls were rejected before backend
   access. Direct extension loading without the ASGI boundary remained blocked.
3. Actual upstream MCP application and SDK: real server lifespans, initialization,
   tool discovery, recall dispatch and session termination completed through an
   in-process HTTP transport. Discovery returned only recall. A retain call was
   rejected. An event-stream GET with a session but no credentials was rejected.
4. Regression test first reproduced missing-auth session-stream dispatch, then
   passed after the boundary rejected it. The test used a synthetic stream
   fixture, not private or production session data.
5. Wheel built successfully. The wheel installed into the workspace-only test
   environment and imported with isolated Python from `site-packages`, not the
   source directory.
6. Ordinary repository suite: 268 tests ran with 66 skipped, without failures.
   Optional Hindsight integration tests skip when the dependency is absent.
   The dedicated environment above supplies the real compatibility execution.
7. Full repository verifier passed: 23 Applications and 537 resources against
   the task's original HEAD, which predated the published backup changes.
   This render is not verification of current main or live cluster health.
8. Scoped whitespace and local documentation links passed before this report.
   No production service was contacted by these tests.

## Independent review

The initial source-only review found no reachable cross-schema, cross-bank, mutation,
generation or role-escalation bypass in the reviewed transport paths. This is a
bounded review result, not proof of production security or database behavior.
The review did not run tests or inspect live services.

The initial review rejected the candidate for two concrete correctness defects:

- Abandoned or upstream-expired MCP sessions can permanently fill the boundary
  quota. Upstream expiry does not clear the boundary map. A DELETE returning 404
  also leaves its entry behind. The repair must bound idle entries, release
  authenticated expired-session entries and preserve role binding.
- List/object-valued MCP tool names cause TypeError during set membership rather
  than controlled request rejection. The repair must validate names explicitly
  before membership checks, without swallowing unrelated implementation errors.

The factory also accepted a custom MCP mount path that its fixed boundary did not
support. The local repair rejects that unsupported configuration rather than
add custom routing. Initialization reservation and several suggested session,
header and body regression tests had already been added while review ran.

These are repairs within the approved local extension, not additional services
or rollout authorization. The final tests and re-review are recorded below.

## Repair verification

The local repairs now include a one-hour monotonic idle deadline, same-role
session-not-found cleanup, explicit method/tool name validation and rejection of
nondefault MCP mount paths. Concurrent initialization and cancellation tests
verify that quota reservations are released. No new service or store was added.

Parent testing then reproduced a related native transport problem after cache
pruning: a validated legacy key could terminate a still-live specialist session.
The real upstream test received 200 rather than the required rejection. Missing
credentials already received 401 from upstream. This was a synthetic in-process
session, not a production session or private record.

The fix supplies the already validated nonlegacy identity through the native
MCP SDK's public authenticated-user scope interface. Native session ownership
then rejects legacy replay with 404 even after the boundary entry is gone.
Existing legacy scopes remain unchanged. Hindsight 1.2.1 and MCP SDK 2.3.0 are
both pinned and checked before constructing the guarded app. No OAuth flow,
shared session store, credential provisioning or new service was introduced.

Parent execution after these fixes:

- Dedicated installed-dependency suite: 51 tests passed, no skips or failures.
- The native SDK test now covers legacy replay after cache removal. A separate
  native legacy-client session still resolves recall to the original public
  schema using the explicit backend fixture.
- Ordinary repository suite: 278 tests ran, 76 skipped, no failures.
- Rebuilt wheel installed and imported successfully from isolated `site-packages`.
- Full verifier passed again: 23 Applications and 537 resources against this
  worktree's HEAD. This does not establish current main or live cluster health.

A fresh independent re-review passed with no security concerns, logic errors or
suggestions. The reviewer checked the installed SDK's native ownership logic and
independently ran the then-current 50-test suite successfully. Parent execution
ran 51 tests after adding a further native legacy-client compatibility test.
The source was unchanged by that final test addition. The earlier failed review
remains recorded as a failure, not retroactive approval of the original code.

## Publication validation

The user subsequently authorized an atomic commit and merge. Before committing,
the task branch was advanced to `origin/main` at
`445e690d3693bab59c890533d90a707306c2ba07`, preserving the reviewed source.
The publication candidate passed 51 focused installed-dependency tests, the
327-test repository suite (76 skipped), all nine policy tests, and the full
verifier against `origin/main` (23 Applications, 561 resources).

Only the nine extension, test and documentation files belong to this change.
Publishing does not authorize activating memory, modifying the deployed server,
provisioning credentials or saving any memory payload. Pull-request and merge
state must be verified separately from these pre-publication test results.

## Explicit limits

The recall backend, bank-config resolver and alias resolver are synthetic fixtures.
The successful empty response proves native dispatch and schema selection, not
production retrieval, extraction, embeddings, database persistence or personal
memory quality. Backend sentinels ensure the compatibility fixtures do not reach
an actual database. No provider inference, paid fallback or private bank read ran.

The test environment lacks optional local ML dependencies and does not start a
full database-backed MemoryEngine. A warning about those dependencies is not a
verified server-startup failure in the deployed runtime.

Production container/entrypoint wiring, schema provisioning, credential injection,
database-backed read semantics and operator save/readback remain unimplemented
or unexercised in this stage. Internal audit or housekeeping effects of native
recall must be checked before activation. Stateful MCP requires a single process
or process affinity. No shared session service is introduced.

Both specialist memory integrations remain inactive. Approval of this source work
is not approval to create keys, deploy the extension or retain a memory payload.
