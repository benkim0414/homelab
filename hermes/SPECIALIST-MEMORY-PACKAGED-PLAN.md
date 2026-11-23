# Specialist memory: approved isolated packaged validation

## Fixed scope

Status: the approved local stage passed in run
`d357ca3d1a224387a8d899edc652f9b2`. See
[results](SPECIALIST-MEMORY-PACKAGED-RESULT.md) and
[accepted evidence](SPECIALIST-MEMORY-PACKAGED-ACCEPTANCE.json).

The user approved local pinned server packaging and isolated database validation
following the merged local component in PR #122. This stage must not deploy to
Kubernetes, publish an image, provision production credentials/schemas, read
personal banks, mount existing runtime state, use a subscription grant, or make
paid provider calls. It does not authorize a commit, push or merge.

Use task worktree `default-specialist-memory-packaging`, based on
`fa00ed4bf04d02253960ee61ce80eee608cd7ed0`. Preserve the existing extension's
fixed identities, legacy routing, readonly specialist keys, native session
ownership and operator-only writes. No proxy, consent service, shared session
store or new authentication subsystem belongs to this stage.

## Acceptance checklist

1. Package a runnable server from the pinned native API image. The installed
   entrypoint must construct the real MemoryEngine, preserve native configuration
   defaults, initialize its database/lifespan/workers, and place the reviewed
   boundary outside HTTP and MCP. Execute image-owned code, not a host overlay.
2. Run the packaged service against a fresh disposable PostgreSQL/pgvector
   database. Use synthetic credentials and literal validation-marker records.
   Do not invent personal facts. Save through the real operator API and confirm
   durable document contents from a separate request. Use a source-confirmed
   non-LLM retain mode and local embeddings. No fake model response can substitute
   for actual storage or retrieval. If paid or real-credential access is required,
   stop and report that blocker rather than change providers.
3. Exercise actual HTTP and native MCP clients. Require nonempty own-bank recall,
   rejection of cross-bank reads and specialist writes, and unchanged legacy
   routing. Compare real persisted content before and after denied writes. Check
   the native startup/worker schema-discovery behavior rather than infer it from
   direct validator tests.
4. Verify exact-owned test resource containment and cleanup. Retain bounded
   public evidence and image identity. No production resource changes are allowed.

Success requires all four items. Source tests, wheel import, socket readiness,
empty recall or an accepted asynchronous save alone do not satisfy this stage.

## Test isolation and resource authority

Use fresh labelled local containers and an isolated internal network. Allow no
host HOME, production volumes, existing credentials or Docker-socket mounts.
Database storage must be disposable and separate from production. Bind any host
listener to loopback only. Run the API under its intended non-root identity.
Resolve the native API and database image references to immutable identities and
record the actual executed platform. Multiarchitecture availability is not proof
of executing every architecture.

Public image/dependency/model downloads may occur while preparing the build.
Runtime tests must have no route to paid providers or production services.
Never copy authentication state or silently select a paid fallback. Do not
capture authentication console or use Docker logs for diagnosis. Prefer bounded
health/status/exception-class evidence without headers, keys or raw responses.

Bind stop/delete operations to the exact container IDs returned by this run,
plus verified task labels and image identities. Do not prune Docker resources,
remove foreign objects, or alter another task's networks. Do not reuse a failed
run's identities as a fresh passing run. Preserve the original failure evidence.

## Current prerequisites

The normal Docker CLI cannot access `/var/run/docker.sock`. Local unprivileged
source preparation can continue. Request elevation only when a reviewed, exact
build-and-validation command is ready to execute. Do not change daemon/socket
permissions, group membership, authentication, sudo policy or global networking.

The disposable contract was checked against actual Hindsight 1.2.1 source. Use
the official `LLM_PROVIDER=none` chunks-retain path, local ONNX embeddings and
the `rrf` reranker. The test uses synchronous operator retain; async operator
retention/completion is not accepted by this stage. Operator document readback
needed a narrow own-bank GET route. Specialist permissions remain unchanged.

Six public BGE model/tokenizer files were downloaded from immutable revision
`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` and verified against published
Git/LFS digests. A real host-side ONNX smoke produced one finite 384-dimensional
embedding with zero observed network attempts. This is not image or database
acceptance. Runtime models will be a fresh read-only data mount, never a native
code overlay or existing production model cache.

The production entrypoint and pinned Dockerfile were built and exercised on
amd64. Real synchronous saves/readback, HTTP/MCP recall, denial-side-effect
checks and owned cleanup passed. User-approved refinements use the verified
internal container IP, revocable internal profile-dependency admission, and typed
legacy recall without inventory-based output-schema validation. No response cap
was raised. Both live specialist memory integrations remain inactive.
