# House manager standing permissions

## Operator authorization

On 2026-11-22 (Australia/Melbourne), the operator explicitly selected:
“Use the recommended standing permissions.” The approved scope is routine
Home Assistant management without repeated per-change approval. This supersedes
the previous requirement for independent approval of every non-hazardous
managed automation create/edit. It does not approve hazardous actions.

Authorized routine scope:

- Ordinary household device controls within fresh server-validated bounds.
- Safe automation creation, editing, enabling and disabling, preserving unrelated
  definitions, stable identities and the current state unless a state change is
  requested.
- Dashboards, helpers and non-security integration maintenance through explicit,
  bounded management operations.
- Non-secret diagnostics, configuration checks and recoverable HA maintenance,
  including restarts after prerequisite and recovery checks.

Retained approval boundaries:

- Heating, appliance starts and other hazardous physical actions, including
  enabling routines that perform such actions.
- Users, credentials, authentication, authorization and external exposure.
- Data deletion, storage replacement, destructive recovery and changes outside HA.
- Git publication, app pruning/force/replace and changes to manual sync policies.

Standing authorization is not blanket shell, arbitrary HA service/REST access,
a human approval credential, HA administrator credential or cluster-admin access.
Unknown operations fail closed rather than expanding the approved scope.

## Enforcement requirements

Keep the operational HA bot non-admin. Enforce standing permission on the HA
server, not only in the model instructions. Every mutation must revalidate the
current target, schema, device bindings and safety classification. Preserve
immutable receipts, native mutation locking, stale-config checks, crash
uncertainty tombstones and at-most-once dispatch. Never automatically consume old
pending proposals merely because standing permissions were enabled.

The optional HA integration setting `standing_permissions: true` enables the
new routine authority. Omitted/false preserves the existing approval behavior.
Consequential actions continue through the existing independent human approval
adapters. Model arguments cannot grant approval or select a broader policy.

New tools must expose fixed typed operations, not arbitrary paths, templates,
Python/YAML code, shell commands or authentication/configuration objects.
Readbacks must redact secrets and distinguish accepted requests, verified
software state and physical device observations. Do not blindly retry uncertain
mutations.

## Activation and evidence

This document records authorization, not proof of deployment or capability.
The task's implementation, tests and live activation record must state exactly
which operations are exposed and which remain unavailable. Do not claim full
Home Assistant administration merely from a policy change or successful render.
No physical device action or enabled test routine is required to validate a
permission change; use isolated synthetic HA tests and live non-mutating probes.
