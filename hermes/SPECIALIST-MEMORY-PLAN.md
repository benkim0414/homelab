# Specialist memory: approved scope and compatibility gate

Prepared on 2026-11-23 UTC after the user approved the tenant-isolation scope
change described in the [access assessment](SPECIALIST-MEMORY.md).
This records the approved scope and the boundary between local source and rollout.

## Local implementation approval

The user subsequently approved local implementation and tests of the bounded
custom extension described below. This permits authored extension source and
synthetic tests only. Live rollout, credential creation/distribution, schema
provisioning, memory writes and specialist activation remain unapproved.
Existing clients must retain their current routing and authority.

Acceptance for this local stage is working extension source tested against the
real Hindsight 1.2.1 interfaces, preserved legacy routing, isolated specialist
identity, and denial of specialist writes through the actual exposed API paths.
Interface stubs and direct validator tests alone are not protocol acceptance.
Report database, packaging and live-deployment checks separately if unexercised.
See the [local result](SPECIALIST-MEMORY-LOCAL-RESULT.md) for executed evidence
and remaining limits. Local acceptance does not activate either specialist.

## Fixed deliverable

Connect the existing independent specialist runtimes to their own memory domains:

| Runtime | Bank ID | Proposed new tenant schema |
| --- | --- | --- |
| Learning coach | `infinite-recursion` | `user_learning_coach` |
| Career advisor | `next-level` | `user_career_advisor` |

The schema names are candidate identifiers derived from the upstream extension,
not provisioned databases or authorization claims. Preserve bank IDs literally.

Preserve existing clients and their current schema, credentials, banks, aliases,
background processing, subscription ownership, provider/model pins, manual sync,
production volumes and nightly backups. Do not copy the existing all-bank key to
specialists. Do not migrate existing banks, rotate credentials, enable automatic
retention/mirroring, reopen closed approvals, or revive the frozen custom pilot.

## Finite sequence

1. Resolve the compatibility and read-only-credential gates below, then freeze the
   exact permitted implementation. Stop if either requires an unapproved change.
2. Validate the chosen tenant and read/write boundaries with synthetic credentials
   and disposable data in isolation. Verify both REST and MCP, legacy-client
   compatibility, worker tenant discovery, and rollback without production data.
3. Review the pinned server packaging, manifests, backup/recovery prerequisites,
   credential creation/injection procedure, and complete rollout diff. Never read
   or copy existing credential values as a compatibility test.
4. Activate only after those checks pass. Connect one specialist at a time using
   native HTTP MCP without installing packages into accepted Hermes containers.
   Expose only verified recall operations. Keep provider lifecycle ingestion off.
   Prove cross-tenant reads and specialist-initiated writes are rejected before
   declaring activation complete. Preserve existing clients and original claims.

Explicit saves use an operator-controlled path, outside specialist dispatch.
Present the complete exact content and destination before each save. A setup or
scope approval does not approve a memory payload. Do not enable a specialist
retain tool, Session/Always write grant, mirroring, or automatic conversation
capture as a substitute for this operator path. Save/readback acceptance requires
a separately approved payload; do not invent a personal fact for testing.

## Gate 1: legacy schema compatibility

Live selected non-secret environment metadata shows no
`HINDSIGHT_API_DATABASE_SCHEMA` override and confirms `ApiKeyTenantExtension`.
The v1.2.1 config default is `public` (`config.py:1236,4781`).

The tagged `StaticKeysTenantExtension` constructs every schema as
`{schema_prefix}_{normalized_user_id}` (`extension.py:200–209`) and lists only
those derived schemas for worker processing (`extension.py:354–356`).
Its configuration does not provide an arbitrary schema map for legacy clients.
Switching the existing service directly to this extension would change legacy
routing and worker discovery. Do not assume the current banks disappeared or
move them to make the test pass. No such change has occurred.

## Gate 2: specialist read-only credentials

The upstream extension maps multiple keys to tenants but supplies no read-only
role. A new specialist key would isolate the schema, not prevent mutation within
it. Native MCP registration filtering limits the agent-facing tool surface but
is not a server-side read-only credential. The strict requirement for approved
saves cannot be claimed from the native trust gate's Session/Always permissions.

## Approved local custom alternative

The bounded custom alternative to review is one Hindsight extension that:

- Preserves the existing credential-to-`public` mapping without exposing its value.
- Maps newly created specialist credentials to only the two new tenant schemas.
- Enforces read-only specialist authority on both REST and MCP, including direct
  calls and administrative/mutation paths, not merely advertised tool names.
- Includes the legacy schema and both specialist schemas in worker discovery.
- Leaves operator-approved writes outside specialist authority.

The user approved local implementation and tests, not live rollout. The local
[package](../hindsight/extensions/specialist-memory/README.md) includes both
extension slots and a default-deny outer ASGI boundary. Its guarded factory uses
the public upstream application factory. It is not another service or proxy.
Only own-bank recall is admitted for specialist keys. Operator-only keys remain
separate and do not confer approval for any memory payload.

Keep both specialist memory integrations inactive. Production entrypoint/image
wiring, schema provisioning, credential injection and database-backed acceptance
remain outside this local stage. No live authentication, schema, bank, key,
package, or toolset changes have occurred. Do not infer live readiness from
synthetic protocol tests or enable writes to obtain a pass.

## Source evidence

- [Tagged static tenant implementation](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-extensions/static-keys-tenant/hindsight_ext_static_keys_tenant/extension.py).
- [Tagged server configuration](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-api-slim/hindsight_api/config.py).
- [Tagged tenant interface](https://github.com/vectorize-io/hindsight/blob/v1.2.1/hindsight-api-slim/hindsight_api/extensions/tenant.py).
- The accepted image's public native MCP handler and direct-plugin-call paths are
  recorded in the access assessment. No private state was read during this check.
