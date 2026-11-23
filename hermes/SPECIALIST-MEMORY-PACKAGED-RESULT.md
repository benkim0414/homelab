# Specialist memory: packaged validation status

## Final local acceptance: passed

Run `d357ca3d1a224387a8d899edc652f9b2` completed all canonical acceptance
checks on the real packaged service and disposable PostgreSQL database.
The parent read the saved report, verified its terminal-success predicate,
matched all production-module source hashes, and checked the recorded resource
cleanup results. Public evidence is preserved in
[SPECIALIST-MEMORY-PACKAGED-ACCEPTANCE.json](SPECIALIST-MEMORY-PACKAGED-ACCEPTANCE.json).

- Three synchronous fixture saves and exact durable document readbacks passed.
- Three REST recalls and three native MCP recalls returned the expected records.
- Both specialist MCP inventories exposed only `recall`.
- All 42 denial probes and both uncontaminated own-bank recall controls passed.
- PostgreSQL contained the expected document/world-memory rows in all three
  schemas. Business-table snapshots stayed unchanged across the denial phase.
- The service ran image-owned code as non-root with `none` LLM, local ONNX
  embeddings and RRF reranking. All three schemas initialized. Observation counts
  were zero. The checked retains reported zero LLM usage.
- The runner stopped/removed both owned containers, the disposable volume and
  internal network, then checked their absence. A later independent Docker
  query required sudo authentication and supplied no additional absence proof.

Executed API image, `amd64`:
`sha256:1e22376532760ec7c6e93cbfc09d722ac1c438cd98e6d030f1eac1a231d32883`.
Only this architecture and the documented synchronous/no-LLM fixture path were
accepted. Legacy MCP recall used the explicitly approved typed request and
manual result checks. Full legacy tool-inventory compatibility at 65,536 bytes,
SDK inventory-based output-schema validation for that legacy fixture, async
operator retention and background-job completion are not claimed.

No production configuration, credentials, banks or agent runtimes changed.
The acceptance run committed, published and deployed nothing. Subsequent Git
publication is separate from image publication or live rollout. Specialist
memory remains inactive.
The following sections retain intermediate evidence, superseded by this result.

## Scope

The user approved local pinned server packaging and isolated database-backed
validation only. Production changes, credential access, image publication,
commits and specialist activation remain excluded.

The task worktree is `default-specialist-memory-packaging`, based on merged
PR 122 (`fa00ed4bf04d02253960ee61ce80eee608cd7ed0`).

## Evidence before privileged execution

- The six public BGE ONNX/tokenizer artifacts were downloaded and checked against
  pinned Git/LFS hashes at revision
  `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.
- A real host ONNX smoke test produced one finite 384-dimensional vector with
  zero observed network attempts. This does not establish image compatibility.
- The dedicated native dependency environment ran 103 focused tests successfully.
  These are unit and in-process transport tests, not real database acceptance.
- The ordinary repository environment ran 378 tests successfully, with 94
  optional-dependency tests skipped. The dedicated environment exercised the
  specialist tests without skips.
- Conftest passed 9/9 policy checks. Repository rendering validated 23
  Applications and 561 resources. These are local checks, not cluster evidence.
- The real runner's Docker preflight failed at `docker-access`, exit 1.
  Its result recorded no images, resources or lifecycle events.
  The checked report is
  `verification/cache/packaged-runs/691b300f1cdb45e78395484bfbf0ad5f/result.json`.

## Independent review: repair and re-review passed

Review `deleg_342186b1` found no security concerns but rejected one concrete
acceptance defect. An interruption after the final successful check could be
recorded as an error, then incorrectly relabelled successful during cleanup.
The canonical predicate did not require terminal completion or exclude errors.

A separate fix agent repaired only this defect with RED/GREEN regressions.
Both finalization and canonical acceptance now require `stage == 'complete'`
and absence of the `error` key. Falsey error values still block acceptance.
The interruption regression exercises the actual catch/finally without running
Docker or database operations. It verifies the persisted result stays failed.

The parent reran all 102 focused tests successfully. Independent re-review
`deleg_b0237dd1` passed with no security concerns, logic errors or suggestions.
It independently ran all 102 focused tests without skips and checked additional
offline finalization/missing-field cases. Privilege may now be requested for the
reviewed local command. This is not packaged runtime acceptance.

The initial reviewer independently ran the preceding 98-test snapshot. The
parent added the database-positive-row regression afterward and observed 99
passing tests. The repair increased the focused suite to 102. Do not describe
the initial review as a 102-test pass.

## Real execution: image built, connection mechanism blocked

The user's run `d3948b6836be404c90861e6960b47ed9` built the API image but
failed subnet selection before resource creation. The sole candidate pool,
`172.30.200.0/21`, lies inside an existing `172.30.0.0/16` host route.
A regression reproduced this error. A collision-checked fallback pool,
`10.254.240.0/20`, now preserves host/Docker overlap checks and fail-closed
exhaustion behavior. All 103 focused tests passed after the change.

Sudo became available and the parent executed the corrected runner. Run
`2f492467a05147c4a102a4e3d747d522` built the image, selected
`10.254.240.0/28`, started PostgreSQL and the API container, then stopped at
`loopback-binding`. All owned containers, the volume and network were removed
with absence checks. No client phase ran. Image ID:
`sha256:ba4b4e3c2b5dfd040435780480bd17734e887016ea42ac78b23d8c59cb6fc9ac`.

A separate no-inference, owned sleep-container probe reproduced the Docker
behavior: the container remained running and `HostConfig.PortBindings` retained
the requested loopback mapping, but `NetworkSettings.Ports` returned
`{"8888/tcp": null}`. The probe's container and network were removed and their
absence checked. No service logs or authentication console were accessed.

Docker's explanation is that exclusively internal networks have no default
gateway through which Docker can publish ports. Linux can instead reach a
container directly through its internal bridge address. See
https://github.com/moby/moby/discussions/53256 and
https://docs.docker.com/engine/network/port-publishing/.

The user approved the bounded adjustment to direct access to the verified
disposable container IP, preserving the internal network and adding no proxy or
outbound network. This is implemented. The parent verifies exact owned
container/image/name/run label, internal network ID and matching attachment
address before health requests and each client phase. No host port is published.
Standalone client CLI admission remains loopback-only. The parent supplies the
explicit verified target only through the test client's Python API.

A separate native-image embedding smoke subsequently passed. The same built
image ran real `OnnxEmbeddings` against the read-only public model artifacts in
an owned container with Docker networking disabled. It produced one finite
384-dimensional vector. The container was removed and its absence checked.
Evidence: `verification/cache/native-image-model-smoke.json`. This establishes
the image's local embedding path, not service or database acceptance.

## Latest real execution: internal content-read dependency blocked

Run `81fb3c7dde724af183779348e42695f7` passed real service readiness,
installed-code hashes, non-root identity, no-LLM/local-ONNX/RRF configuration and
all three initialized schemas. The client then received 403 at an unnecessary
bank-profile PUT. No server permission was changed. The test now uses native
retain's existing, validator-protected lazy bank creation instead of requesting
profile administration. A regression demonstrates the save test works without
profile-administration permission.

The client now preserves only its existing redacted stage/exception/status on
failure, never response bodies or stderr. Latest focused suite: 109 tests passed.

Run `5e59ea4856ee46fcadc4fb93da245536` passed startup/runtime/schema checks
and acknowledged the first synchronous synthetic operator retain with zero LLM
usage. Document GET then returned 403. Its redacted diagnostic is
`verification/cache/packaged-runs/5e59ea4856ee46fcadc4fb93da245536/client-positive-failure.json`.
All owned containers, volume and network were removed and their absence checked.

Source tracing found the dependency: native `api_get_document` calls
`attachments_for_documents` even for a document without attachments. That helper
calls `get_bank_profile`, which invokes `GET_BANK_PROFILE` authorization. The
current validator intentionally excludes this operation for scoped identities.
The content-read guard has not been relaxed and no server policy was changed.

The user approved a narrowly scoped local compatibility refinement for this
internal dependency. It is implemented and passed independent security review
`deleg_6859390e` with no security concerns or logic errors. That reviewer ran all
115 focused tests and an additional offline concurrent-native-session check.
The existing server-owned admission now carries a revocable content-read scope.
It permits the dependency only for the matching authenticated identity, bank and
extension key mapping during an admitted document or recall operation. Scope
revocation also affects copied task contexts after completion/error/cancellation.
Direct profile/config endpoints, cross-bank access and read-only mutations must
remain denied. Do not globally add profile reads to the content-read allowlist.
The refinement must use server-owned admission, not caller-supplied claims.

The parent ran all 115 native focused tests successfully. The ordinary repository
suite ran 391 tests successfully, with 104 optional-dependency skips. The added
tests exercise the real native document/attachment/profile handler chain with
synthetic backend fixtures and stateful native MCP context propagation. They are
not real database acceptance.

The parent attempted the reviewed real rerun, but Docker access again requires
sudo authentication. Run `de94acfd29cf4f7182fe1f8778c35437` stopped at
`docker-access` before creating resources. The exact reviewed command is ready
for private sudo authentication and immediate execution.

Until the repair passes real execution, do not claim durable HTTP
readback, real MCP recall, SQL positive/snapshot checks or the denial matrix
passed. No production configuration changed and no real personal memory was
saved. The database test remains incomplete.

## Subsequent real execution: legacy MCP discovery failure

The user's run `a5e0f524b6d3408e92d416248e2201a8` progressed beyond the
repaired document readback and stopped at `mcp-inventory` with a nested SDK
exception. No guard was changed. A regression added bounded exception-group
diagnostics containing only a fixed fixture role and exception class names,
never error messages, response bodies, credentials or stderr.

Run `cc15a9968f414edf9e7c956fa4f09273` identified the failing role as
`legacy`, with leaf exception class `MCPError`. By the serial client flow, all
three fixture saves, document reads and REST recalls completed before that step,
as did both specialist inventories and MCP recalls. The legacy MCP recall,
SQL positive/snapshot checks and denial matrix have not completed. The overall
result remains failed. Cleanup verified all owned resources removed.

The parent observed 116 focused tests passing after the diagnostic regression.
A read-only in-process investigation measured actual native tool definitions
using synthetic backend fixtures. Each specialist exposed one recall tool:
1,966 JSON payload bytes, 1,992 SSE wire bytes and 1,986 decoder-counted bytes.
The unrestricted legacy inventory exposed 36 tools: 66,018 JSON payload bytes,
66,044 SSE wire bytes and 66,038 decoder-counted bytes. The latter exceeds the
unchanged 65,536-byte cap and reproduced `MCPError` code `-32000`.
These measurements are native transport/schema evidence, not real DB results.

Merely omitting explicit legacy `list_tools()` is insufficient: high-level SDK
`call_tool()` also fetches the inventory for its output-schema validation cache.
The investigated typed `send_request(CallToolRequest(...), CallToolResult)` path
can perform legacy recall without inventory discovery, retaining typed envelope
parsing and the client's explicit result checks, but avoiding that SDK
inventory-based validation path. Both specialist SDK inventories/recalls remain
unchanged. The user explicitly approved this legacy-test-only adjustment,
including the stated output-schema-validation tradeoff. It is implemented and
passed independent review `deleg_7a969a3c` with no concerns or suggestions.
The reviewer and parent each ran all 117 focused tests without
skips. The ordinary repository suite ran 393 tests with 106 optional-dependency
skips. Native SDK wire tests verify two specialist inventories and three recalls,
with no explicit or automatic legacy inventory. Ten malformed/error legacy wire
cases fail closed. This adjustment changes no response limit or server
permission. Full legacy inventory compatibility under this cap must not be
claimed. Overall database acceptance is still incomplete.

The reviewed rerun `35d3c750d23d47a6806e5aa3dcef3caf` stopped at
`docker-access` before resource creation because sudo authentication is again
required. The command is ready for private authentication and execution.

The test procedure and bounded effects are documented in
`../hindsight/extensions/specialist-memory/validation/README.md`.
