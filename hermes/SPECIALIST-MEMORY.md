# Specialist memory: fixed scope and discovery blocker

## Subsequent scope approval

The user approved planning the tenant-isolation scope change after this review.
The [fixed implementation plan](SPECIALIST-MEMORY-PLAN.md) records two further
compatibility gates: preserving legacy `public` routing and enforcing read-only
specialist credentials. A custom extension is a proposed scope decision, not an
approved implementation or live change. The assessment below is historical.

Observed at `2026-11-23T00:16:11.135185+00:00`.
Task 2 began only after task 1's live backup/restore checks passed. Its separate
worktree preserved task 1's then-unpublished deliverables without copying them.
Task 1 was subsequently published and adopted, and its restore clone cleaned up.

## Requested routing

| Runtime | Primary bank, literal user-supplied ID |
| --- | --- |
| Learning coach | `infinite-recursion` |
| Career advisor | `next-level` |

Keep the existing independent runtimes, private claims, accepted native CLI,
provider/model selections, request limits, response limits, deadlines, no paid
fallback, and closed approvals/attempts unchanged. Do not resume the frozen
custom authentication/parser pilot. Do not add Gerrit, desktop delegation,
channels, sharing, or a new general-purpose permission subsystem.

Retain only specifically approved content in its named destination. Setup
approval is not permission to store a test fact, ingest conversations, import
local memory, or mirror banks. Cross-specialist sharing remains disabled.
No secondary personal-bank route is activated by this discovery.

## Verified observations

- The trusted Hindsight control-plane version route reports API `1.2.1` and
  `features.access_key_auth: false`.
  **Correction:** this flag describes the Control Plane UI login key, not
  bank-scoped dataplane API keys. It cannot establish whether per-bank grants
  exist. The tagged authentication implementation below establishes that limit.
- Bank metadata was paginated and deduplicated. Exactly four canonical banks
  matched the declared total. Neither requested specialist bank exists.
- No stored fact, document, private history, or model request was read or issued.
- The [current service runbook](../hindsight/README.md#credentials-and-trust)
  documents one trusted-user API credential with access to every bank. A
  bank-specific MCP URL selects routing; it is not itself an authorization boundary.
- Public source in the exact pinned Learning coach image contains only ByteRover
  and RetainDB under `plugins/memory/`. Hindsight is not bundled there. Current
  [Hermes documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers)
  describes Hindsight as an external catalog plugin. Documentation about an
  installable plugin does not prove it is installed in this accepted image.
- The [Hindsight plugin catalog disclosure](https://hermes-agent.nousresearch.com/docs/plugins/hindsight)
  describes conversation capture and built-in memory-write mirroring. A safe
  implementation must inspect and disable all unapproved write paths, not merely
  set the primary bank name or rely on a prompt instruction.

The public discovery projection is retained locally in ignored
`verification/cache/memory-discovery.json`. It contains only version, feature,
bank-ID/count, and existence metadata. It contains no credentials or memory text.

## Activation blocker and scope boundary

The currently documented credential would grant each specialist access to other
banks. Copying it into the specialists would require explicit credential-transfer
approval and would not establish the requested access separation. This task has
neither copied it nor treated bank URLs/tool filters as bank-level authorization.

Before activation, identify a supported restricted access path for the installed
service and accepted immutable runtime. Any needed authentication/security change
must be proposed separately and approved before implementation. Do not silently
enable new service authentication, install packages into accepted containers,
relax isolation, distribute the broad key, or build a new mediator to obtain a pass.
A fixed native MCP route can be evaluated, but it must be verified against the
installed client/server and must not be described as restricted credentials.

## Completed read-only access assessment

### Hindsight server authorization

Selected public Deployment fields confirmed the running API image as
`ghcr.io/vectorize-io/hindsight-api:1.2.1@sha256:662109ece429871a81e036427fb93fbb09ba9dc4b01d320d356f114c0e1aedd8`,
with `hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension` and MCP
authentication bypass disabled. No Secret values were retrieved.

The exact [v1.2.1 tenant source, lines 44–90](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L44-L90)
compares one expected key and returns the same configured database schema for
all authenticated callers. MCP uses the same authentication method. There is no
per-key bank allowlist or read/write grant in this installed extension. Creating
another token string does not create such a grant.

The [Control Plane version route, lines 22–25](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-control-plane/src/app/api/version/route.ts#L22-L25)
sets `access_key_auth` from `HINDSIGHT_CP_ACCESS_KEY`. Enabling that setting would
protect UI login only; it would not restrict the UI's existing dataplane key to
selected banks. UI hardening is not a solution to the specialist access blocker
and is not included in this task.

The upstream [static-keys tenant extension](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-extensions/static-keys-tenant/README.md)
is a source-available alternative, but it isolates users into different database
schemas. It requires packaging a different server image and provisioning tenant
schemas, not a switch for grants on banks in the current schema. Its MCP path
always authenticates. Existing bank/client routing must be preserved through any
separately planned change. No upgrade or Cloud migration is recommended as an
assumed fix. Cloud bank-scoped key features do not establish equivalent features
in this installed OSS extension.

### Exact pinned Hermes runtime

Safe installed-package metadata in both specialists confirmed `mcp 2.3.0`,
`httpx 0.28.1`, `anyio 4.15.1`, and a packaged Streamable HTTP client. The
`hindsight-client` package is absent. This establishes native HTTP MCP packaging,
not an authenticated connection or memory acceptance. No SDK connection or
specialist inference was executed.

The following public source paths are inside `/opt/hermes` in the accepted
specialist image, not private runtime state:

- `tools/mcp_tool_registration.py:250–265` filters server-native names before
  tool registration. An exact recall-only include list is a candidate model-facing
  restriction. MCP resources/prompts, sampling/elicitation and events would need
  explicit review and disabling where unnecessary.
- `hermes_cli/plugins_context.py:311–337` uses a separate, default-deny per-server
  plugin allowlist before direct MCP calls. It does not enforce the registration
  include list. Do not grant that path and claim a tool filter is universal policy.
- `tools/mcp_tool_handlers.py:190–219,833–847` applies the untrusted-server trust
  gate inside the actual call handler before transport. It is distinct from the
  built-in `memory.write_approval` gate.
- `tools/mcp_tool_handlers.py:68–74,247–307` permits remembered Session/Always
  trust grants and approval bypass. Tool read-only annotations also affect the
  gate. It therefore cannot be described as an immutable approval for each exact
  save payload, even though it can prompt for write-capable calls.

The smallest no-install client candidate is native HTTP MCP with exact
recall-only exposure, no external memory provider, and no automatic ingestion or
mirroring. Explicit saves would remain on a separately approved operator path.
This candidate still needs genuine server-enforced bank isolation and approved
credential provisioning. It is not permission to connect the broad key, change
the accepted clarify-only toolset, or activate either specialist now.

### Recommendation and separately proposed security change

Keep memory activation paused under the existing scope. No configuration-only
change to the installed authentication extension meets the required bank
separation. Do not build a mediator or distribute the all-bank credential.

If continuation is requested, the verified upstream self-hosted alternative to
assess in a separately approved plan is schema-per-specialist tenant isolation:
dedicated keys, isolated schemas, reviewed extension packaging, and preservation
of all existing clients/data. This is a service authentication/storage design
change, not implementation already authorized by the read-only assessment.
Strict per-save consent remains a separate requirement; tenant isolation alone
does not satisfy it. No authentication, packaging, schema, bank, key, or toolset
change has been implemented.

Once that access decision is resolved, keep acceptance finite: verify each
specialist reaches only its intended bank, automatic ingestion/mirroring stays
off, unapproved saves are refused or staged, and one separately approved payload
is saved and independently read back. Storage acceptance or empty recall alone
is not end-to-end acceptance. Do not invoke specialist inference, alter LOGIN or
INFERENCE approvals, or claim memory activation from configuration alone.

## Current result

The read-only assessment is complete. No banks were created. No credentials were read, copied or
changed. No plugin/package was installed. No runtime config, toolset, model,
provider, retention setting or memory record changed. Task 2 is blocked pending
a narrowly scoped access decision, not completed. This document is local and
uncommitted. Task 1 was published by [PR 120](https://github.com/benkim0414/homelab/pull/120)
and adopted without pruning. Its cleanup and adoption evidence was published by
[PR 121](https://github.com/benkim0414/homelab/pull/121). Both specialist
Applications were Synced/Healthy after adoption, and the Career advisor clone
was removed with exact-UID deletion and absence checks. The successful backups
and original production claims/volumes were preserved.
