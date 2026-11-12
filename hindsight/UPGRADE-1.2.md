# Hindsight 0.10.3 → 1.2.1: held

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
- The default reranker changes in 1.2 to hosted `hs-rerank-1`. Our explicit local
  provider/model should override it; preserve and test that, rather than adopting
  a hosted provider. Likewise retain BGE embedding dimensions and local cache.
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
nor a test of the new subscription/schema contract. Those results cannot be
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
