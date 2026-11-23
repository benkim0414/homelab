# Local packaged specialist-memory acceptance

This runner is test-only. The production Docker build excludes this directory.
It does not configure the live Hindsight service or either specialist.

The approved direct-container-IP adjustment is implemented and passed real
service startup checks. No proxy or non-internal network was added.

The approved internal profile-dependency refinement is implemented and passed
independent security review. It uses a revocable server-owned content-read scope.
Direct profile/config APIs and cross-bank access stay denied. Real database
acceptance passed in run `d357ca3d1a224387a8d899edc652f9b2`. The recorded
result and source hashes were checked against the canonical acceptance predicate.
Do not remove a guard or readback acceptance check to obtain a pass.

See [accepted evidence](../../../../hermes/SPECIALIST-MEMORY-PACKAGED-ACCEPTANCE.json)
and [scope/limits](../../../../hermes/SPECIALIST-MEMORY-PACKAGED-RESULT.md).
Legacy recall uses the explicitly approved typed request without inventory
discovery or its automatic output-schema check. Both specialist inventories and
SDK checks remain enabled. The response cap remains 65,536 bytes. Full legacy
inventory compatibility is not claimed. Nothing was deployed to production.

## Scope and effects

- Build the production entrypoint from the immutable API 1.2.1 base and the
  package's direct API/MCP dependency pins. Transitive dependencies are resolved
  normally, not described as fully hash-locked.
- Use a fresh PostgreSQL 17/pgvector container and empty owned volume. The database
  image is digest-pinned in `fixture_env.py`.
- Load six hash-verified public BGE ONNX/tokenizer artifacts from the task cache.
  Model revision: `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`.
- Keep service containers on an owned internal network with a nonoverlapping
  private subnet. The approved adjustment uses only the API's verified address
  on that network, without publishing host ports.
- Use the official `none` LLM provider, chunks retention, local ONNX embeddings,
  RRF reranking, disabled observations/consolidation, and offline model loading.
  Graph/vector maintenance can still run. Do not claim all background tasks stop.
- Use public synthetic keys and exactly three harmless fixture documents.
  There is no production database, existing memory, OAuth, paid provider or
  specialist runtime connection.
- Require real REST and native MCP positive results, exact document readback,
  matching PostgreSQL document/world-memory rows, 42 HTTP refusals and unchanged
  business tables in all three fixture schemas.
- Stop/remove only verified owned resources. Confirm their absence. Never force,
  prune, remove another container by name, or access Docker service logs.
- Retain the local image and public model/dependency caches. Do not publish images.

Schema initialization and the installed native tenant-discovery configuration are
checked. The original lifespan starts the native worker. Async operator retains,
operation polling and background-job completion are not accepted by this test.
Only synchronous operator saves are in scope.

## Prepared environment

The task-specific interpreter is `verification/cache/native-venv/bin/python`.
The model directory is
`verification/cache/specialist-models/bge-small-en-v1.5-5c38ec7`.
Neither belongs in the production Docker context.

The unprivileged preparation and unit/transport tests do not establish Docker,
database persistence or packaged-service acceptance. A successful native host
embedding smoke test does not establish image compatibility.

## Run after command review and Docker access

From the task worktree, execute:

```sh
env -i HOME="$PWD/verification/cache/isolated-home" PATH=/usr/bin:/bin LANG=C.UTF-8 \
  "$PWD/verification/cache/native-venv/bin/python" -B \
  "$PWD/hindsight/extensions/specialist-memory/validation/run.py" --sudo
```

`--sudo` invokes only `sudo -n /usr/bin/docker ...`. It never elevates Python,
reads passwords, installs sudo policy, joins groups, or renews an expired sudo
timestamp. Establish the required sudo authorization privately only when this
reviewed command is ready. Do not send password/authentication console output.
A timestamp from another terminal may not apply to the agent's terminal.

The same command without `--sudo` works when normal Docker access is already
configured. Do not change authentication or group membership for this test.

The runner prints bounded JSON and writes a private result below
`verification/cache/packaged-runs/<run-id>/result.json`. Build logs cover only
public build inputs. Runtime service logging is disabled. A nonzero exit,
`passed:false`, missing client counts, cleanup failure or incomplete checks is
not acceptance. Inspect only this public report, not raw runtime/provider logs.

On failure, stop. Preserve the report and exact owned handles. If cleanup fails,
report that explicitly and recover only the recorded resources after checking
ownership again. Do not start a replacement test over unresolved cleanup.

## Production remains excluded

No live image/auth configuration, bank/schema/key provisioning, specialist MCP
activation, real memory save, reauthentication, commit, image publication or
GitOps rollout is authorized by this local test stage.
