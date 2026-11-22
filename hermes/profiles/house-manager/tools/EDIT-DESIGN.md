# Conditional managed-automation edits (0.3.2 source)

The 0.3.1 edit capability is already deployed; this document now also describes
the **0.3.2 source-only no-expiry change**, not a claim of its deployment. No live
proposal, edit, restart, Discord message, or device call was made by this change.

## Proposal lifetime (0.3.2)

- New `automation` creation and `edit` proposals explicitly contain
  `expires_at: null`. The null is part of the exact immutable SHA256 document;
  previews say **No expiry**, not a null date. Future `created_at` is still invalid.
- Device `action` proposals retain an exact **900-second** lifetime and cannot use
  null. Legacy finite create/edit documents retain their original 900-second
  deadlines and exact hashes. No migration, rewriting, or renewal occurs.
- Expired ledger tombstones never revive, including
  `house_manager_general_b4342777fbeb49f0a03d9e0cfd3942ec`. Replacement requires a
  separately created immutable proposal and independently authenticated approval.
- No expiry removes only the time deadline. Exact human sender/channel/reply/hash,
  one-use ledger consumption, current registry bindings/schema/timezone, and edit
  base configuration/runtime-state freshness remain required at the write boundary.
  Drift rejects the proposal, even years later. There is no automatic retry.
- Component version is `0.3.2`; connector server version is `3.2.0` (wire document
  version remains 3). All consumers accept null only for automation mutations;
  historical finite receipts remain readable but cannot authorize expired writes.
- Local evidence for this increment is in `NO-EXPIRY-VERIFICATION.json`.

## Public workflow

1. `list_managed_home_automations {}` / `GET /api/house_manager_general/managed`
   returns `automations` and separately identified `unavailable` candidates.
2. `get_managed_home_automation {target_id}` / `GET .../managed/{identifier}`
   returns exact native `config`, lowercase canonical `config_hash`, stable native
   `target_id`, `owner_record_id`, resolved `entity_id`, and current `runtime_state`.
   Discovery does not adopt definitions, trigger routines, or change their state.
3. `propose_home_automation_edit {target_id, base_config_hash, spec}` /
   `POST /api/house_manager_general/edits` accepts a **complete typed v3 spec**.
   It is not a partial merge: include the intended title, all triggers, all actions,
   and conditions (omission means none). Reconstruct those fields from discovery
   when changing only a schedule. No raw YAML, ID changes, scripts, arbitrary
   services, enable flags, deletion, or force-trigger capability is exposed.
4. The existing independent HA-side Discord worker attaches the entire immutable
   proposal. Its edit-specific preview identifies the target and preserved on/off
   state and displays exact before/after SHA256 values. The attachment contains
   complete `before`, `after`, normalized `spec`, target, base hash, bindings and
   explicit `expires_at` (null for new proposals). The entire document is hash-bound,
   including those snapshots.
5. Only the existing authenticated human reply to that exact preview can approve:
   `APPROVE <new proposal ID> <whole-document SHA256>`. No MCP/HTTP approval route
   or model-supplied confirmation flag exists. Existing sender/channel/reply/bot/
   webhook/edited-message/replay checks remain; lifetime follows the policy above.
6. Read the new proposal's status. Successful edits return `verified_edit`, stable
   `target_id`, exact config hash and current state. The preceding create/edit
   receipt becomes `superseded` with `superseded_by`, not falsely still current.
   Later edits resolve ownership through the latest successful receipt. Historical
   receipts are not a claim that an old configuration is still loaded.

## Ownership and conditional persistence

Only verified v3 automation creation or verified v3 edit ledger records with
preview, approval, verification timestamp and stored config hash are candidates.
Native prefix/alias alone conveys no authority. v2 routines, manual definitions,
missing/tampered/uncertain ledger ownership and ambiguous owners are not adopted.
The original creation record remains the provenance root and is never deleted.

Proposals bind the exact target and base hash from discovery. At approval, the
manager serializes operations, persists a pending tombstone, validates the current
policy/inventory/applicable lifetime/timezone, and acquires the **actual registered native config
view's mutation_lock**. Under that lock it verifies a single matching persisted
ID, its exact hash, matching loaded raw config, entity identity and captured
runtime state; validates the new config; replaces exactly that row in place;
reads back the entire list; targeted-reloads only that ID; and checks the exact
loaded definition/state. Fresh authorization is checked again immediately before
write. Other rows, including their order and IDs, remain semantically unchanged.
Native YAML formatting/comments are not preserved by HA's native writer.

Both edits and creates now retain the shared view lock through reload/readback,
closing the native-UI write/reload gap. The 2026-11-21 review found that the
preexisting create path released it too early; the follow-up fixes that path too.
The `reload_edit` boundary delegates to the same lock-required reload boundary,
pinned to HA 2026.11.1 and tested against that real HA library under a timeout.
Concurrent approved edits of the same base serialize; only the first can succeed.
The second refuses the now-stale base, without overwriting the first.

Failures/interruptions after consuming an approval remain `uncertain` and are not
retried or automatically rolled back. A possibly persisted edit must be reconciled
by an operator. Before a successful verified edit, the old recorded receipt can
remain historical `verified_enabled`/`verified_edit`; its status readback detects
that the old config no longer matches and reports `uncertain`, and discovery
refuses it. No failed edit silently adopts the new definition.

## Enabled/off semantics

HA 2026.11.1's existing automation entity restores its last state when its internal
`initial_state` is `None` (the ordinary config omits the key). A non-None explicit
`initial_state` can override a manual off during entity recreation. Editing refuses
**both explicit true and explicit false policies**, rather than modifying them or
promising unsafe preservation. Full-spec edits leave the original ID and other
native keys unchanged; the typed v3-owned fields alone are replaced.

For an off routine, the boundary explicitly calls the exact automation's
`turn_off` with `stop_actions: false` before reload and again after exact loaded
config readback. This does not run device actions or cancel in-flight actions.
On routines rely on native restoration, with verification; edits never call
`turn_on`. Unexpected reload activation of a verified-exact off definition is
corrected off and reported uncertain, not claimed as a normal success. An on
routine unexpectedly restored off is never automatically enabled.

Pinned-source references:
- [automation entity restoration](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/automation/entity.py)
- [targeted reload implementation](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/automation/services.py)
- [native config view mutation lock](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/config/view.py)

## Validation and reusable local procedure

See `EDIT-VERIFICATION.json` for actual outputs and source hashes. Commands from
this directory:

```sh
python3 -m unittest discover -s tests_general -q
python3 -m unittest test_edit_connector test_general_connector_v3 -q
uv venv --python /usr/bin/python3 .test-venv
uv pip install --python .test-venv/bin/python --cache-dir .test-cache 'homeassistant==2026.11.1'
.test-venv/bin/python tests_general/isolated_edit_runtime.py
```

Choose Python >=3.14.2 explicitly: this repository's uv default selected Python
3.11 and HA correctly refused installation. Local Docker access was unavailable;
no Docker permissions were changed. The isolated local runner uses a disposable
config below this worktree, synthetic registry entities, no live credentials,
blocked socket connect/connect_ex/bind/listen, and an exact automation-only service
guard. It exercises the real manager, native validation/writer/lock/loaded resolver,
real targeted reload, actual off and on restoration, and unchanged unrelated
runtime entity identity. It is not the older remote/pod acceptance runner.

TDD evidence observed before implementation:
- Missing managed discovery/edit methods failed the first end-to-end edit test.
- Native disable and restart ledger tests failed on missing boundary/status support;
  the edit Discord preview test failed because it described a device action.
- Route/tool tests failed until all new paths and dispatch were implemented.
- Real HA locked-edit-reload assertion failed before `reload_edit` held the lock.
- Unexpected reload-on test failed with state still on; fail-safe off was added.
- Forged verified-edit runtime evidence was accepted by the connector; validation
  now checks state, target, config hash, entity and verified timestamp.
- Runtime drift during prewrite policy refresh initially wrote the edited config;
  the late exact state/entity check now refuses before persistence.

Prior 0.3.1 local results: **64 integration/policy/worker unit tests passed; 16 connector tests
passed; real isolated HA 2026.11.1 probe PASS**, both off/on preserved, exact ID
and unrelated config/runtime retained, zero device/network calls. HA emitted its
normal custom-integration-not-tested warning. No production/channel acceptance
or independently authenticated live approval is claimed.

## Limits and rollout handoff

- No legacy v2 ownership migration or manual adoption; complete v3 spec only.
- Atomicity covers writers honoring the real native view lock. Privileged direct
  filesystem/add-on writers do not honor it; do not claim protection from them.
- Runtime on/off service calls are not governed by that config lock. Observed
  changes while approval waits or during late checks refuse; independent toggles,
  scheduled triggers and concurrent reloads are not globally transaction-isolated.
  Enabled automations can execute naturally around the approved reload. There is
  no force trigger or claim to suppress ordinary scheduled execution.
- Running automations may be interrupted/recreated by HA's native targeted reload;
  this is not a durable transaction across disk, runtime, ledger and real devices.
- Preview attachment transport/readback and Discord authentication remain the
  existing mechanism, tested offline; this change did not contact Discord.
- Revalidate on any HA version change. The strict version gate intentionally fails
  closed outside 2026.11.1.
- Deploy only `general_connector_v3.py` plus the six component Python files and
  `manifest.json`; never package `.test-venv`, `.test-cache`, local test state,
  ledger/enrollment or credentials. Parent operator handles reviewed installation,
  authorized restart, house-manager profile tool exposure and live read-only
  acceptance before any separately approved real edit.
- Hindsight banks were unavailable in the delegated tool catalog; no historical
  memory was treated as authorization. No other worktrees or profiles were changed.
  No commits were made.
