# House manager standing permissions — 2026-11-22

## Authorization and scope

The operator explicitly selected the recommended standing routine-HA permission
scope in this conversation. See
[the permission contract](../hermes/profiles/house-manager/STANDING-PERMISSIONS.md).
Hazardous physical actions, credentials/security/exposure, destructive data/storage
operations and unrelated services remain gated. The initial standing-permission
approval did not itself authorize Git publication; later publication authority
is recorded below.

Worktree: `.worktrees/homelab-scientist-house-manager-permissions`, based on
`074c76df1dafed3ca3b42086a76ea0cab7554343`. Initial live activation was performed
without commits or pushes. The operator subsequently authorized atomic commit
and merge; publication is separate from deployment.

## Local validation

- HA policy/runtime suite: 136 tests pass.
- Connector suites: 33 tests pass, including real-engine receipt/readback tests.
- Broker: 20 tests pass, including local synthetic HTTP/WebSocket exchanges.
- Isolated real HA 2026.11.1: standing create/edit and owned enable/disable pass,
  exact identity/unrelated definitions preserved, off state preserved on edits,
  zero physical-device/network calls and no independent approval worker required.
- Repository unit suite: 226 cases pass with 26 dependency-gated skips. The one
  UNIX-socket test passes separately using a short `/proc/<parent>/fd/<fd>` alias
  to the same approved scratch directory. The unsplit run exceeds AF_UNIX path
  length in this profile; using the alias for the entire suite changes unrelated
  path-sensitive Langfuse fixtures, so only the socket case uses it.
- Conftest: 9/9 pass. Full verifier: 23 Applications / 537 resources pass.
- Strict server dry-run passes for all eight broker resources.
- Source installer check-only mode verifies exact live baseline HA module and
  connector hashes. No credentials are printed, changed or copied by it.

Review found and corrected retained-heating fan activation, hazardous-domain and
proxy classification, native-extra preservation on standing edits, Discord poll
race, contradictory state receipts, normalized optional defaults and Boolean
constant type confusion. Standing routine actions require registry-supplied direct
platforms (LIFX, SmartThings, Dyson local), complete native shape and fresh policy
and binding checks. A Hot + Cool fan is not treated as persistently safe merely
because its fan attributes omit heating modes. Direct integration trust is a
bounded assumption, not proof that unrelated HA automations have no downstream
effects.

## Live broker activation

Applied only the new broker's eight resources, with NetworkPolicies before its
Deployment. No ArgoCD sync, prune/force/replace, app upgrade, HA restart or volume
change occurred in this stage. The runtime uses the existing pinned Hermes image,
a non-root standalone process and no HA credential stored in the broker.

- Deployment `hermes/ha-operations` rolled out and read back available 1/1.
- Pod `ha-operations-5c7475f9f6-mqftl`: Running/Ready, zero restarts, on `k3s-05`.
- Chose `k3s-05` because the existing HA/Hermes node `k3s-03` was at 96% observed
  memory use; no workload was moved or resized.
- All declared fields of all eight resources read back exactly.
- Impersonated service-account checks confirm get/patch only exact HA StatefulSet
  and get exact HA pod; Secret access, exec, delete, other workloads/pods and the
  Hermes namespace's pods are denied.

This is not authenticated broker acceptance or proof of HA-side standing activation.
The broker validates the existing bot through HA on every request and fails closed
when HA is unavailable. Restart requires a fresh native configuration-check result,
rollout prerequisites and exact resource-version/UID tests. A restart annotation
receipt is never rollout success. Pod-wide NetworkPolicy is not per-profile
cryptographic identity; transport reuses existing in-cluster HTTP trust.

## HA/profile activation and acceptance

Installed the tested HA component as 0.5.0 and enabled the non-secret standing
setting. The first installer attempt incorrectly appended a block YAML setting
to an inline mapping. It failed before any HA restart. While the old healthy
process remained running, removed exactly that suffix and atomically inserted
the Boolean inside the original inline mapping, preserving every other field,
owner and mode. Readback parsed successfully. The installer now validates both
flow/block forms before any writes. Publication review also pinned its original
source baseline so a later commit cannot change its replacement guard; four
installer regression tests pass. No
credential value was displayed or changed.

All installed HA source hashes were read back against the tested candidate
before the normal StatefulSet restart. HA returned Ready with zero pod restarts
and the original claim/volume identity. Source recovery copy:
`/config/.house-manager-standing-backups/20261122T093443Z/source`.
Its ledger observation must never be restored over newer receipts.

Installed the connector and instructions under the existing house-manager
profile. Both read back exactly; the original connector/instructions are at
`/opt/data/profiles/house-manager/.house-manager-standing-backups/20261122T093700Z`.
Changed only the connector's explicit 12-tool filter and its argument list
through the profile-scoped Hermes CLI. Added Python `-B`, also changing the
connector launch inputs for fresh sessions. No shell/file/code toolset,
administrator identity, provider/model change, approval bypass, new credential,
memory save or messaging change was introduced. Existing chats are not rewritten.

Authenticated native MCP acceptance, using normal configured credential loading:

- All 12 selected tools registered; HA reports `standing_permissions: true`,
  HA 2026.11.1 and the independent approval adapter ready.
- Native config check returned `valid: true`; sanitized diagnostics and fixed
  workload health succeeded. Six unavailable and twelve unknown entities were
  observed at that instant; no device remediation is claimed.
- Unauthenticated broker request received 403. The Hermes source reached the
  broker's exact pod IP/port; the browser/non-Hermes source was refused.
- Invoked `restart_home_assistant` once through native MCP. The broker returned
  verified config-check/annotation evidence and explicitly did not claim rollout
  completion. Subsequent Kubernetes rollout and authenticated health confirmed
  Ready, generation observed and revision converged.
- Compared the exact pre/post StatefulSet specs: only the broker restart timestamp
  annotation changed. Workload UID stayed fixed, pod UID changed as expected, and
  claim UID/volume identity stayed fixed. New pod restart count was zero.
- Actual returned inventory, evaluated through the exact tested policy without
  executing any action, accepts an ordinary light routine for standing authority
  and requires approval for Hot + Cool activation.

There were two normal HA restarts: one to load the new component and one to test
the broker. No image upgrade, storage change, ArgoCD sync or production
automation/device-control mutation occurred. The source and manifests were
uncommitted at the initial activation stage, before the separately authorized
atomic publication and merge.

## Remaining limitations and rollback

Full dashboard/helper/integration editing is not implemented by the exposed
interface. Those mutations remain unexposed rather than using a generic privileged
proxy/admin token. Safe native capability implementation is an engineering gap,
not a request to repeat the operator's standing authorization.

Start a fresh House manager conversation for the new prompt/tool snapshot.
The successful calls above used native MCP registration/handlers without an
inference request. The operator subsequently supplied a fresh-chat response
reporting a valid check at `2026-11-22 11:26:55 UTC`, healthy workload, enabled
managed routines and one unavailable/unmanaged routine, with no changes made.
This is operator-reported read-only chat acceptance, not an independently
observed UI test or proof of a production automation edit through that UI.
The existing image reports pnpm/install-sync and Langfuse process-environment
warnings. They were not changed or treated as failure of the tested HA tools.

For authority rollback, set only the HA `standing_permissions` Boolean false
using a mapping-aware atomic edit, validate, then normally restart HA. Keep the
0.5.0 source/receipts rather than blindly downgrading or restoring old ledgers.
Restore the profile's original seven-tool filter and instructions through the
supported CLI/protected backup, preserving unrelated settings and credentials.
Disable the two broker-facing tools before stopping the broker. A stateless
broker stop does not require touching HA data. Review removal of restart
annotations separately: reverting a template annotation can itself restart HA.
