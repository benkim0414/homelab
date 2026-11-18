# Langfuse scoped resilience acceptance — 2026-11-18

## Outcome and authorization

The operator's `proceed`, following desktop publication PR #99, authorized the
remaining controlled web-restart persistence and disposable-client outage checks.
Both scoped checks passed. This is live operational evidence, not a render result,
a coordinated backup/restore test, or proof of every client's outage behavior.

No ArgoCD sync, image upgrade, credential change, datastore restart, firewall or
routing change, schedule activation, or restart of an existing Hermes session was
performed. Two additional successful model requests occurred while correcting
the diagnostic harness before its final accepted run; these were not counted as
accepted outage evidence. All model requests used `openai-codex` / `gpt-6.1-sol`;
no configured fallback chain was present.

## Web restart preflight

The live web Deployment used the existing pinned Langfuse 4.77.0 image, had no
volumes, and used a rolling update. All six Langfuse pods were Ready, all four
claims were Bound, and node conditions showed no memory/disk/PID pressure.
The web node had capacity for the modest replacement. Recovery was limited to
returning web to its prior revision 1 if the replacement failed; no data deletion
or image rollback was needed.

The actual running image's `/app/web/entrypoint.sh` was inspected before restart.
It can run PostgreSQL cleanup/migrations and ClickHouse migrations. Read-only
checks using the containers' configured CLI authentication established:

- Zero PostgreSQL rows matched the startup cleanup's four migration names.
- Zero unfinished/non-rolled-back PostgreSQL migrations.
- All 470 migration directories in the running image were already applied.
- ClickHouse's latest migration record was version 56, `dirty=0`, matching the
  image's 56 migration files. Its migration table retains historical dirty rows;
  the relevant record is selected by `ORDER BY sequence DESC LIMIT 1`.

These checks ruled out pending image migrations for this same-image restart.
No credential values were retrieved or printed.

## Live persistence result

Only `deployment/langfuse-web` was restarted with `kubectl rollout restart`.
Its revision advanced from 1 to 2 without changing the image. Rollout completed.
The first subsequent private readiness request returned HTTP 502; the next check
returned `{"status":"OK","version":"4.77.0"}`. No continuous availability or
measured outage duration is claimed.

Readbacks and identity comparisons established:

- The four previously accepted desktop traces and all twelve observation
  identities, trace IDs, parent IDs, types and environments matched exactly
  before and after the restart.
- The two previously accepted cluster traces remained readable afterward, with
  six observations across `default` and `house-manager`; their recursive
  metadata-only privacy audit still passed. Their observation identities were
  not independently captured immediately before this restart.
- All four Langfuse PVC UIDs, bound PV names, capacities and Bound status were
  unchanged. All five non-web Langfuse pods retained their UIDs and restart counts.
- The Hermes Deployment, running service pods and storage were unchanged. Its
  live image remained v0.22.2, not the repository's pending upgrade.
- An unrelated completed Hermes backup Job pod disappeared during the test,
  consistent with history garbage collection; its removal cause was not
  independently audited. An initial whole-namespace comparison rejected that
  difference; comparison was corrected to the controlled workloads and
  persistent storage rather than ephemeral backup history.
- All six Langfuse pods were Ready afterward. Read-only ArgoCD status remained
  Langfuse `Synced/Healthy`, Hermes `OutOfSync/Healthy`, both without automated sync.

Local ignored evidence: `verification/cache/resilience-{before,after}-workloads.json`,
`resilience-{before,after}-desktop-traces.json`, and
`resilience-after-cluster-traces.json`. These files contain only projected test
metadata; they are not committed and are not a recovery backup.

## Disposable-client outage result

A separate desktop `homelab-scientist` CLI process used the installed v1.0.1
guard, native profile authentication, and complete approved launch policy,
including `OTEL_SERVICE_NAME=hermes-desktop-homelab-scientist`. It made one bounded,
no-tool model request using the selected provider/model, without changing any
profile configuration.

Only that process's `requests.Session.send` and synchronous `httpx.Client.send`
were intercepted. Requests to the exact private Langfuse hostname raised an
intentional connection exception before transmission; all other destinations
retained their original transports. No fake HTTP/API response was supplied.
Headers, key values and request bodies were not inspected or printed. Raw CLI
output was held in memory, reduced to allowlisted evidence and discarded.

Accepted run:

- Expected reply `LF_OUTAGE_AGENT_OK` observed; CLI and probe exit codes both 0.
- Two actual Langfuse connection failures injected through the requests transport.
- Native callbacks observed: one `on_pre_llm_call`, two `on_post_llm_call`, one
  `_flush`, and two `on_session_finalize` calls. Callback counts are not asserted
  to equal generation counts.
- Native `_flush` consumed 0.005 seconds; aggregate `on_post_llm_call` time was
  0.006 seconds; total process wall time was 6.954 seconds.
- No quota or authentication error was reported. No fallback provider was used.

The harness initially omitted the required OTEL service name, so the guard
correctly remained inert and the run was rejected for zero injected failures.
After fixing launch policy, its assertion still used a nonexistent callback
name; that run was also rejected. The accepted run used the actual reviewed
native callback names and required both real export failure and a successful
model reply. Neither earlier diagnostic mistake was treated as a product pass.

After the outage process exited, a fresh normal installed-loader probe
successfully authenticated to `hermes-desktop`, exported synthetic no-model trace
`66243c998c2ec18ebd9dad32a6e49b09`, and read it back through the v2 observations
API. Its content was omitted, the canary was absent, and changing capture to
`full` was refused. Private server readiness remained healthy.

Local ignored evidence: `verification/cache/outage-scientist-result.json` and
its disposable `outage-one-shot.py` harness. Transport interception was confined
to that exited process; no production plugin/core code was modified.

## Coverage and remaining limits

- This proves a real desktop `homelab-scientist` CLI turn completes when its
  observability transport fails immediately. It does not prove bounded latency
  under stalled networking, HTTP throttling, or slow server responses.
- No outage was injected into live multiplexed cluster Hermes, desktop `default`,
  or other sessions. Their prior real-turn privacy acceptance remains separate.
- The normal post-test export used a fresh process; replay/recovery of the failed
  process's spans was not tested or promised. Neither integration has a durable
  offline spool or lossless/exactly-once export guarantee.
- Only web restarted. No datastore, node/power-loss, or coordinated restore test
  occurred. Preserved PVC bindings and Longhorn replication are not backup proof.
- Checks were app-scoped. Grafana/Loki alerts, full cluster RBAC, all-namespace
  security auditing and VM capacity changes were outside this test.
- A coordinated backup/restore remains a separately approved requirement before
  treating traces as durable rather than disposable.

## Local validation versus live verification

The changes for this acceptance record are documentation only. Local checks cover
links and `git diff --check`; existing full source/manifest test results belong to
PR #99 and are not re-labelled as deployment proof. The live results above came
from actual rollout, authenticated readbacks, workload identities and the real
bounded CLI request. Publication does not deploy changes or authorize further
recovery operations; the [backup/restore proposal](../langfuse/BACKUP.md) remains
unimplemented and requires a reviewed execution scope.
