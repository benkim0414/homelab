# Bot and TUI automation approval (source preparation)

This is an opt-in source change, not deployment evidence. The existing deployed
component is 0.3.2; this prepared component is 0.4.0. HA remains pinned to
2026.11.1. No live account, credential, profile, integration or automation has
been changed by this preparation.

**Latest validation:** [DUAL-APPROVAL-VERIFICATION.json](DUAL-APPROVAL-VERIFICATION.json)
records the 2026-11-21 continuation: 168 unit tests passed, the isolated real HA
2026.11.1 probe passed with no network/device calls, and the current five-module
recipe passed render/init/hash/compile checks inside the running Hermes image.
That probe uses only disposable scratch and does not import the patched gateway
or establish real UI acceptance. The original continuation readback showed no
approval plugin, enrollment receipt or runtime-overlay init container. No rollout
occurred in that validation stage.

**Enrollment follow-up (2026-11-21):** the operator completed the private helper.
Readback verified the non-secret receipt and a fresh normal scoped HA WebSocket
authentication confirmed the enrolled user matches that receipt, is non-admin /
non-owner and differs from the operational bot. No token was printed or copied
to this repository. Current profile settings retain the restricted HA/memory
toolsets and only the preexisting Langfuse plugin; no shell/file/code/delegation
toolset was enabled. Fresh unit validation passes 168 tests, and the complete
repository verifier passes 21 Applications / 521 resources. These checks do not
activate the approval plugin. Publication, fresh recovery checkpoints, reviewed
rollout and real UI acceptance remain outstanding.

**Deployment status:** the previously identified Hermes v0.23.2 context blocker
has a local implementation and regression tests in `runtime_context/`. It binds
the frozen policy and adds the narrow downstream `ctx.session_launch_source()`
API. The plugin requires coherent CLI/TUI/GUI creation evidence, not merely the
presentation surface, and continues to reject ambiguous contexts. The immutable
recipe ConfigMap and same-image init overlay are prepared in
`../runtime-context.yaml` and `../deployment.yaml`. No runtime rollout has occurred.

The operator authorized all reviewed stages, including enrollment and restarts.
The operator-private enrollment gate described below has now completed, as
verified above. No authenticated administrative session or plaintext approval
token has been supplied through chat.
Do not fabricate an identity or modify HA authentication storage. The requested
modern Bot Chat/TUI capability is **not operational** until the remaining
checkpoints, deployment and real two-surface acceptance complete.

## Intended operator workflow

### Approved role separation and cross-channel contract

On 2026-11-21 the operator requested implementation with the existing
house-manager bot as the operational identity and a separate human approval
identity. House manager remains the only assistant the operator needs to chat
with. The approval account is infrastructure behind the trusted command, not
another assistant or a model-accessible credential.

For supported automation create/edit proposals, request origin does not select
or restrict the approval transport. A request made through Discord can be
approved through the trusted local command, and a request made through
TUI/Desktop Bot Chat can be approved through Discord. Other permitted proposal
sources use the same server-stored proposal; arbitrary sources/users are not
thereby authorized to propose or approve. No new messaging adapter is enabled
by this contract.

Both transports consume the same immutable proposal ID/hash and shared ledger.
Only the authorized human confirmation is approval. A competing approval,
stale local confirmation, replay or uncertain outcome must never cause a second
mutation. The operational bot remains unable to call the approval endpoint.

This is **at-most-once approval consumption**, not guaranteed exactly-once
completion. A durable pending claim can precede any effect; restart/uncertainty
requires reconciliation and never automatic redispatch. Approval of a create or
edit changes a persistent routine, not a one-time run of that routine.

The independent review identified a create-time native UI write/reload race and
a fixed 100-message Discord poll window. The continuation fixes both: create
holds the actual native mutation lock continuously through write, reload and
readback/enable, like edits; Discord scans one bounded newest-to-oldest page per
poll with volatile finite-sweep cursors and exact reply re-fetch before claim.
Tests cover the competing writer, deep replies/new traffic/restart, invalid
pages, and pending snapshots at four interruption boundaries. The real isolated
HA probe also passes with the create reload lock held. These follow-up fixes
have local regression coverage, not a second independent review or live rollout.

This is staged HA management, not unrestricted administrator access:

| Stage | Scope | Current status |
| --- | --- | --- |
| Existing operational tools | Inventory, policy-scoped device requests, managed automation discovery/proposals | Existing connector contract; this change does not broaden it |
| Dual human approval | Automation creation and owned complete-spec edits, including a title change | Source prepared; enrollment, deployment and real UI acceptance pending |
| Broader HA management | Other automation ownership, integrations, configuration, maintenance, security and destructive operations | Not implemented by this change; each capability needs scoped tools, risk/recovery review and tests |

Device-action proposals remain Discord-only in this revision. Do not give the
bot an admin token, shell/file access or a generic authenticated HA request tool
to approximate the future stage: those capabilities could bypass the approval
credential boundary. No blanket authorization for destructive/security changes
or hazardous device actions is implied.

1. Ask House manager to propose a new automation or complete-spec managed edit.
   Proposal tools still cannot approve. Read the exact proposal ID and SHA256.
2. In the House manager local Bot Chat or TUI, invoke the `house-approve` slash
   command with that ID and hash. This is a command, not an LLM tool call.
3. The trusted command handler retrieves the stored pending proposal using a
   separate approval identity, verifies its hash and presents its complete JSON
   and consequences in a native confirmation prompt. Cancel, timeout, unavailable
   UI or missing session/source metadata must not grant approval.
4. Only an explicit confirmation submits that exact hash. A fresh HA policy,
   binding, ownership, base-config and runtime-state check remains mandatory.
5. Read status through `get_home_proposal`. A failed or uncertain operation is
   not retried automatically. Reconcile an uncertain outcome before another edit.

Discord DM approval is retained. Proposals still need the existing authenticated
Discord preview publication and worker readiness; this change adds a way to
approve without replying to the DM, not an offline replacement for Discord.
Only `automation` and `edit` proposals are accepted by the new adapter. Device
`action` proposals retain Discord-only approval and their 900-second lifetime.
New create/edit proposals retain explicit no-expiry; legacy deadlines and
terminal ledger records are unchanged.

## Authorization boundary

The optional HA integration setting `chat_approver_user_id` must identify a
separate active non-administrator user, different from `bot_user_id`. Omit it to
leave the new route absent. Invalid enrollment fails closed at startup.

The authenticated GET/POST path is
`/api/house_manager_general/chat-approvals/{identifier}`. Only that exact enrolled
approver identity may use it, including GET. The existing bot identity, other
users and administrators are rejected. The existing MCP connector retains its
fixed route allowlist and has no approval tool or route.

GET returns the exact stored proposal only when it is awaiting approval, has a
published preview, has no consumed approval, has an allowed kind and passes fresh
validation. It persists a server-generated `interaction_id` bound to the exact
hash and authorized approver; fetching a new preview invalidates the old prompt.
The confirmation interaction expires after 300 seconds; this is NOT the lifetime
of the immutable automation proposal. A fresh prompt can be fetched without
rewriting or expiring a no-expiry proposal. Stale confirmation workers are denied.
POST accepts exactly `sha256`, `interaction_id`, `surface` (`local_chat`) and
`session_id` (bounded audit label). Surface/session are NOT human authentication;
the separate credential and trusted command ingress are the authority. The
request cannot supply an actor ID, payload, approval boolean or timestamp.

The shared manager serializes Discord/chat consumption. Chat evidence and the
pending tombstone are saved together before any mutation. Consumed, uncertain,
expired and completed records are never replayed. Existing native locks, state
preservation and readback verification are reused, not reimplemented.

## Required deployment gates

This is a security/authentication change and needs explicit operator approval
before live enrollment. The operator's subsequent `proceed all` authorized the
reviewed task stages, but cannot replace private authentication or verification.

- Review a separate non-admin approval identity and operator-private token
  enrollment. Never send a token in chat, argv, Git or diagnostic output. Do not
  reuse `HA_MCP_TOKEN` or an administrator credential.
- Keep the approval token confined to trusted plugin execution. Merely putting
  it in the profile environment is NOT sufficient if the model can run shell,
  arbitrary Python, file access, untrusted plugins or equivalent tooling that can
  read or exercise that authority. Review actual profile toolsets, delegated
  capabilities, MCP child environments and process separation before enrollment.
- Hermes authenticates local chat clients, not a distinct biological human.
  An authenticated client with session-control/response rights can invoke the
  command/answer its prompt. This is not protection against a compromised client,
  profile process, cluster administrator or someone with local OS access.
- Keep bot-to-bot messages, cron, arbitrary MCP calls and unsolicited model output
  outside the approval ingress. Do not enable messaging integrations or schedules.
- Review current HA backup/recovery, active automation disruption and the complete
  installed-source diff before a separately authorized HA restart. Source rollback
  requires restoring the previous source and another reviewed restart; preserve
  the ledger, automation definitions and credentials. Do not reverse already
  approved automation changes as a side effect of source rollback.
- Install only reviewed runtime files (including the new `chat.py`), not test
  environments, caches, synthetic state, enrollment or credentials. The persisted
  profile is not overwritten by ConfigMap seed updates.
- Refresh the profile's connector/instructions through the installed supported
  commands and verify plugin registration separately. Do not restart the shared
  Hermes deployment casually; preserve other conversations and manual sync.
- Confirm unauthorized bot-token denial, owner session isolation, cancellation,
  exact preview rendering in both Desktop Bot Chat and TUI, and single-consumption
  behavior before approving a real automation. Local synthetic tests cannot prove
  those live UI and credential boundaries.

## Local verification

From this directory:

    python3 -m unittest discover -s tests_general -q
    python3 -m unittest test_edit_connector test_general_connector_v3 -q
    python3 -m unittest test_chat_approval_plugin test_chat_approval_flow -q
    uv venv --python /usr/bin/python3 .test-venv
    uv pip install --python .test-venv/bin/python 'homeassistant==2026.11.1'
    timeout 120 .test-venv/bin/python tests_general/isolated_edit_runtime.py

The isolated probe runs real HA 2026.11.1 libraries with socket connect, bind and
listen blocked. Only synthetic automation services/config are allowed. It tests
create plus off/on edits through the chat adapter, native persistence, targeted
reload, state/ID preservation and unchanged unrelated runtime/config. No physical
service calls, production configuration or credentials are used.

The original 87 unit tests passed before modification. Final local validation
passed 126 tests: 83 component tests, 17 connector tests, 25 plugin tests and one
command-to-adapter flow test. The real isolated probe passed
with `approval_transport: hermes_command`, both off/on states preserved, stable
ID, unrelated configuration/runtime preserved, and zero device/network calls.
These observations are local only, not a claim of live UI acceptance.

The credential scope, missing/invalid interaction, cancellation and ambiguous
`local` surface refusal cases are tested with synthetic inputs. The workflow test
connects the real command implementation to the real adapter/manager in memory;
only the runtime context and native boundary are synthetic. It does not simulate
a successful modern Bot Chat/TUI runtime when the installed runtime cannot supply
the required provenance. Later runtime-context tests now exercise the downstream
fix and real plugin together. This initial test record remains historical;
private enrollment, deployment and real UI acceptance are still outstanding.

## Operator-private enrollment (helper installed; not activated)

Use an existing active non-admin, non-owner HA user distinct from the model bot,
or create one through the normal HA administrator UI with Administrator disabled.
The helper checks identity and privileges, not whether the account is new.
Sign in as that user and create its own long-lived token under Profile ->
Security. Do not reuse the model bot account or an admin token, and do not
downgrade the operator's normal administrator account merely for enrollment.

Run in a separate private terminal, not through chat:

    kubectl -n hermes exec -it deployment/hermes -c hermes -- /command/s6-setuidgid hermes env HOME=/opt/data HERMES_HOME=/opt/data/profiles/house-manager /opt/hermes/.venv/bin/python /opt/data/house-manager-tools/enroll_chat_approver.py --bot-user-id 31aa5893f45b478b8a3bcc505bf5dc96

Only the hidden prompt receives the token. The helper validates normal HA
WebSocket authentication and `auth/current_user`, rejects the bot/admin/owner
identity and stores the new token in the owning profile's `.env` with mode 0600.
It preserves unrelated bytes and existing command-secret sources, checks effective
key names before prompting and again before writing, and refuses a failed provider
or existing key in dotenv, external or managed sources without disclosing values.
It refuses existing enrollment/credential replacement and writes only IDs/timestamp to
`.chat-approval-enrollment.json`. It does not approve an automation, change HA
settings or enable a plugin. Partial failures require checking private state,
not automatically retrying or rotating credentials.

After private success, read only that non-secret receipt to obtain the approver
ID. Append only `chat_approver_user_id` to the existing HA integration settings
in `/config/house_manager_general.private.yaml`, preserving the other keys/values
without printing or extracting them. Verify actual active/non-admin/distinct
identity at HA startup. Never print or transport the existing Discord token.

Before source activation, obtain fresh current NAS checkpoints through the
reviewed procedures and preserve volume IDs. The last observed HA NAS backup
predates the current custom source and is not a current checkpoint. Back up
reviewed source and current automation/ledger data within their owning runtimes;
rollback must not restore an old ledger or silently undo approved automations.

## Runtime overlay and recovery

`runtime_context/build_bundle.py` packages only a SHA-locked renderer, init helper
and reviewed output digest inventory in an immutable content-addressed ConfigMap.
It does not vendor upstream modules. The credential-free init container uses the
same pinned image as main, verifies its unoverlaid original files, renders five
modules into disposable emptyDir and checks output digests. Main mounts only
those five files read-only; sibling modules, PVC, image and auth settings stay
unchanged. The Application include glob explicitly covers the new ConfigMap.

Tests cover rendering, drift/symlink refusal, scope reset/concurrency, all launch
labels and the real plugin consuming the patched accessor. The earlier
four-module revision passed an actual-image temporary-scratch probe. The current
five-module revision passes 158 local tests, Kubernetes admission dry-run and
full repository verification (21 Applications / 521 resources). Its fresh
actual-image scratch probe was blocked by a tool-approval timeout and was not
retried or bypassed. See `SAFETY-FIX-VERIFICATION.json` for current scope; older
reports are historical. None establishes rollout/UI acceptance. The later
`DUAL-APPROVAL-VERIFICATION.json` supersedes the blocked image-probe observation
and unit-test count, not the historical admission/full-repository results.

Reproduce the non-disruptive current-image check from `house-manager-tools`:

    PYTHONDONTWRITEBYTECODE=1 python3 -m runtime_context.probe_installed_image

It runs as the Hermes user with an explicitly cleared environment, reads only
the fixed public upstream-module allowlist, and writes/removes private scratch
under `/tmp`. Original/output hashes, idempotent init and read-only file modes
must match the locally reviewed bundle. It does not read profiles or credentials,
patch image files, install plugins, restart services or approve proposals.

Rollback removes only the runtime-context init, five main file mounts, associated
volumes and checksum from the reviewed Deployment patch and rolls back once.
The original immutable image then supplies its original modules. Leave unused
immutable ConfigMaps retained until cleanup is separately approved. Disable the
new approval plugin if its required accessor is absent; it fails closed anyway.
Preserve current profile data, enrollment and all existing manual sync policies.
Restore HA source separately if needed, without restoring historical automation
or ledger data. No commit, push, automatic sync or pruning is authorized here.

Official Hermes references:
- https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
- https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/public-api
- https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode

The installed v0.23.2 command dispatch and choice-response authorization were
inspected in public source. Do not substitute model-facing `clarify` or ordinary
shell-command approvals for this exact-hash one-use approval boundary.
