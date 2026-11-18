# Hindsight 0.10.3 → 1.2.1

## Verified rollout — 18 November 2026 UTC

The operator explicitly authorized the previously denied isolated PostgreSQL
rehearsal, scoped publication after CI, and bounded backup maintenance/rollout.
Chart/API/UI 1.2.1 were deployed at main
`dfdb91d69f013db62b35e3aefa13e80ee21dfe6e`, with verified multiarchitecture API/UI
index pins. The Application finished Synced/Healthy/Succeeded.

After the rehearsal below, the sole API/worker was stopped with observed exit 0.
A fresh final custom dump was fully parsed, then independently copied and
byte/hash-verified on the workstation while writers remained excluded. The
original database and credential claims were preserved; no grants were cloned.
Production migrated to `05867433a58c`, preserving 3 banks, 2 aliases and 8 memory
units, with zero invalid/unready indexes. Live health, unauthenticated REST 401,
and normal project-bank recall/reflect passed. No memories were retained for
testing. Expiry-driven refresh and new-retain acceptance remain unexercised;
this is not full row-content equivalence or an auth redesign.

Seven offline contracts and a generated PG17.8/pgvector0.8.1 rehearsal passed:
old revision `c8e2f4a6b1d3` to `05867433a58c`, repeated target migration and
independent original-checkpoint recovery. A separate fresh online real-data dump
was fully parsed and its independent local copy hash-verified. Its isolated
opaque-data rehearsal passed: all 24 original-table counts, including 3 banks
and 2 aliases, were preserved on independent target and old-recovery restores.
Target migration took 2.238 seconds, repeated in 2.181 seconds at the same head;
old recovery remained at the original revision. Both branches had zero invalid
or unready indexes and matching extension versions. The source dump remained
unchanged; normal shutdown and no OOM events were verified under a 4 GiB memory,
zero-swap, 200% CPU, 512-task scope and a 2 GiB writable state tmpfs.

This is database-library execution, not API/provider startup, ARM64 execution,
full row-content equivalence or authenticated REST/MCP/UI/subscription acceptance.
The online rehearsal input was not the final cutover checkpoint; the separate
final write-excluded capture above supplied that gate. Preserve the existing database, grants, provider,
model, storage, disabled chart components, exposure and manual sync unchanged.
Do not deploy on generated evidence alone or downgrade against migrated data.

The original hold and unhold criteria below are retained as historical evidence;
the new authorization resolves the sandbox denial, not every acceptance item.

## Original review — 12 November 2026

**Do not bump the chart, API or UI images yet.** All remain `0.10.3`. This is a
compatibility/recovery hold, not a claim that upstream 1.2.1 cannot run on our
PostgreSQL 17/pgvector deployment. No database engine/image/extension change,
authentication change, client reconfiguration or paid-provider fallback is
included or authorized by this review.

## Specific evidence

Reviewed the tagged [1.0.0](https://github.com/vectorize-io/hindsight/releases/tag/v1.0.0),
[1.1.0](https://github.com/vectorize-io/hindsight/releases/tag/v1.1.0),
[1.2.0](https://github.com/vectorize-io/hindsight/releases/tag/v1.2.0),
[1.2.1](https://github.com/vectorize-io/hindsight/releases/tag/v1.2.1),
[tagged changelog](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-docs/src/pages/changelog/index.md),
[chart](https://github.com/vectorize-io/hindsight/tree/v1.2.1/helm/hindsight),
[configuration](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-api-slim/hindsight_api/config.py)
and [migration sources](https://github.com/vectorize-io/hindsight/tree/v1.2.1/hindsight-api-slim/hindsight_api/alembic/versions).

- The 1.1 changelog explicitly warns that startup migrations alter high-volume
  `memory_units` tables and need extra time. The upgrade adds scheduled-full-
  refresh schema/routine changes, index repair, wider mental-model references,
  placeholder-date cleanup, attachment-window routine and graph queue claim state.
- `e8c1a4f7b2d9` drops global vector indexes on per-bank backends (including
  pgvector), with a 10-second lock timeout. Downgrade is intentionally a no-op.
  This changes indexes, not the PostgreSQL extension identity; do not swap the
  database image or vector extension to work around it.
- `c7e2f9a4d1b8` clears placeholder event dates and explicitly states it is
  **not reversible**. `f2a9c4e7b1d3` widens references and deliberately does not
  narrow them on downgrade. `d4f7a2c9e1b5` drops/recreates a maintenance function
  because its return shape changes. An image/Git revert is therefore not a
  verified recovery path.
- 1.0 rejects tag-scoped callers on whole-bank operations; 1.1 rejects invalid
  and reserved-prefix import bank IDs; 1.2.1 further tightens ID/alias handling
  and fixes base-schema migration with tenant extensions. The actual deployment
  uses `ApiKeyTenantExtension`, canonical banks and compatibility aliases. Its
  authenticated REST/MCP behavior and alias preservation have not been exercised
  on the new version.
- 1.2 changes LLM tool calls to response schemas. 1.1/1.2 also change Codex
  request/history/cache behavior. The existing dedicated `openai-codex` grant,
  explicit `gpt-5.6-luna`, writable credential PVC, single owner and no-fallback
  policy must survive. A chart render/health probe cannot establish retain,
  recall, reflect or refresh compatibility. No token was read or copied here.
- Tagged 1.2.1 source keeps the default reranker provider **local**, with model
  `hindsight-ai/hs-rerank-1`. This corrects the earlier hosted-reranker assumption.
  Preserve our explicit local MiniLM override, BGE dimensions and local cache;
  do not switch models or enable a hosted provider as part of this upgrade.
- Tagged 1.2.1 remains MIT licensed; no mandatory self-hosted Hindsight
  subscription/license gate was found. Existing Codex entitlement and dedicated
  grant ownership are separate operational checks, not a new Hindsight fee.
- Source chart review shows the control-plane template adds optional revision
  history configuration; newer charts also offer API strategy/startup settings.
  That does not justify replacing/adopting the hand-written API Deployment in
  the same upgrade. Preserve `Recreate`, stable worker ID, Secret references,
  Service identities, RWO claims and the currently chart-disabled API/worker/DB.

## Recovery evidence and why the pin remains held

Read-only Job metadata on 2026-11-12 confirms successful scheduled backup
`hindsight-pg-backup-29906850`, completed `2026-11-11T15:30:03Z`. This verifies
Job completion only. No archive contents were opened. The [runbook](README.md)
records an isolated restore on 2026-10-17 for the old release; it is not a
rehearsal of today's bank/alias state through the new irreversible migrations,
nor a test of the new provider/schema contract. Those results cannot be
inferred from a successful dump Job, package diff or old test bank.

Safe major-version recovery and functional compatibility are **not established**
within this read-only/local-preparation task. Leave all runtime pins unchanged
until separately authorized isolated rehearsal and acceptance evidence exists.

## Unhold checklist

1. Refresh/verify a pre-upgrade dump and restore into an isolated fresh database
   using the exact current PG17/pgvector image and extension identity. Keep the
   original database/PVCs and dump intact. Never restore over production.
2. Run the pinned 0.10.3 API on that checkpoint to establish baseline bank/alias
   configuration and counts, then stop it and migrate using 1.2.1. Record exact
   migration revisions, duration, locks, index validity and count preservation.
   Isolate clients/outbound hooks and background writers; the existing 15-minute
   startup budget must be justified by measurements, not optimistic assumptions.
3. Use a separately approved isolated subscription grant/test mechanism. Never
   mount the production rotating OAuth PVC in two processes or copy the user's
   interactive token. Verify configured model entitlement, refresh persistence,
   retain/recall/reflect, local embeddings/reranking and no paid fallback.
4. Test the current MCP/REST clients, 401 rejection for wrong/absent credentials,
   valid authenticated calls, canonical IDs/aliases, UI proxy and initializer
   idempotence. Verify the UI does not disclose its server credential. Do not
   treat a bank name or alias as an authorization boundary.
5. Rehearse restoring the untouched checkpoint and running 0.10.3 as rollback;
   the downgrade functions above do not reconstruct the old state. Confirm the
   new release's image manifests support every eligible architecture.
6. Only then propose chart/API/UI `1.2.1` together, render/review the full diff,
   and obtain deployment authorization. Keep manual sync and no pruning/force.
   Database/PVC migrations, authentication redesign and cleanup remain separate.

No production backup, restore, rehearsal, login, schema query or live write was
performed during this review. Checked-in runbooks and tagged upstream sources
support the hold; historical evidence does not replace a target-version rehearsal.

## Follow-up isolated preparation (2026-11-13)

Offline initializer/OpenAPI/migration-graph fixtures passed seven tests. The exact
eight-revision path is `c8e2f4a6b1d3` -> `05867433a58c`; profile/background REST
operations return 410 in the target and must not be confused with supported bank
config and bank-scoped MCP APIs. External client compatibility remains unverified.

The local PostgreSQL sandbox probe was explicitly denied by the execution approval
gate. It was not retried or replaced with another execution path. No database
restore/migration or API startup proof resulted. Do not run the prepared harness
until the operator explicitly resolves that denial through the approval workflow.
Production pins remain unchanged. No production grant is available for cloning;
any inference/refresh acceptance needs a separate owner-provisioned test mechanism.
