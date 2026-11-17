# Langfuse live preflight — 2026-11-18

## Scope and status

Resumed the existing `homelab-scientist-langfuse` worktree after the operator
reported restored networking. This report supersedes only the connectivity
blocker in [the preparation record](2026-11-17-langfuse-preparation.md). No
Langfuse resources, application credentials, agent plugin settings, networking,
kubeconfig, TLS policy, Git commits or GitHub state were changed.

The initial owner credentials still need private operator setup. Capacity and
Git publication questions were presented but timed out without an answer; no
approval is inferred. Existing approval for private deployment/new credentials,
metadata-only enrollment and disposable telemetry remains the intended scope.

## Connectivity — verified

- `ip route get 192.168.0.11`: via `192.168.86.1`, device `wlp192s0`, source
  `192.168.86.104`. The route was established outside this task, not by this agent.
- Authenticated kubectl `/version`: `v1.36.5+k3s1`.
- Ordinary kubectl node list: all five nodes Ready; k3s-01 through k3s-04 ARM64,
  k3s-05 AMD64.
- Kubernetes MCP `resources_list` for Node: succeeded and returned all five Ready
  nodes with the same architecture/version observations. No MCP restart or
  configuration change was required.

## Health and capacity — observed, not rollout acceptance

- All five nodes: MemoryPressure, DiskPressure and PIDPressure False.
- Sample usage from `kubectl top nodes`: memory about 59%, 69%, 70%, 37% and 50%
  for k3s-01 through k3s-05 respectively. These are point-in-time samples.
- k3s-05 allocatable: 3800m CPU and 15596796 Ki memory. Existing requests:
  2200m CPU / 7954 Mi memory. The planned AMD64 web, worker and ClickHouse add
  1000m CPU / 4096 Mi, leaving 600m CPU and about 3181 Mi not requested at the
  observation time.
- Existing k3s-05 limits already total 373% CPU and 142% memory of allocatable.
  Requested-resource fit does not guarantee simultaneous limit consumption.
  Approval of the non-HA capacity budget remains pending; do not shrink memory
  or move databases to NFS merely to obtain a green scheduler result.
- Proposed data claims remain 65 GiB, nominally 130 GiB with the observed two
  Longhorn replicas before overhead. All five Longhorn disks Ready/Schedulable;
  observed available bytes ranged from 88709529600 to 449105100800. StorageClass
  reclaim policy is Delete; no new claims were created.
- All listed PVCs Bound. Attached Longhorn volumes reported healthy; detached
  recovery/rehearsal volumes reported unknown, not proof of data failure.
- Of 126 observed pods, two existing diagnostic/recovery pods were Failed:
  `hermes/hermes-network-control` and
  `recovery-openclaw-20261112221724/integrity-check-6957f`. No container was flagged
  by the greater-than-five-restarts or CrashLoopBackOff check. Nothing was removed
  or restarted to clean up these observations.
- ArgoCD listed existing Applications Healthy, with some OutOfSync including
  root apps, hermes, immich, monitoring, openclaw and vaultwarden. These existing
  differences must not be swept into a broad sync for Langfuse.
- Namespace `langfuse` does not yet exist. No existing Langfuse data was adopted.
- Tailscale operator and Sealed Secrets controller each 1/1 available. Grafana
  alerts and Loki logs were not queried as part of this scoped preflight.

## Actual Hermes version changes the enrollment procedure

Live Deployment image:
`nousresearch/hermes-agent:v0.22.2@sha256:36099926da316742423544e055d4734777105ffe6341873af5459b957d0c2919`.
The installed CLI reports v0.22.2, upstream `d923a5eb`, Python 3.14.7.

This differs from the repository's already-pending v0.23.1 declaration. Do not
sync the entire Hermes Deployment for tracing; that would silently include an
unrelated core upgrade. Preserve the live image and apply only reviewed tracing
fields when prerequisites are ready, with the matching fields declared in Git.

Initial expectation of a bundled plugin at this older version was checked and
rejected by live evidence: no bundled Langfuse plugin or SDK is present. Its
actual catalog contains `langfuse` 2.0.0 at
`c2a95963c442f3f23e4bc6fe0da898e1dd1fb63d`, requires Hermes >=0.21.7, and that
exact plugin's upstream pyproject pins `langfuse==4.15.2`. The v0.23.1 catalog pin
recorded during planning is not the live pin. No plugin was installed/enabled.

Profiles default and existing house-manager were listed. Their observed selected
models remain grok-4.7 and gpt-6-luna respectively; neither was changed. No model
request or device-control tool ran. A profile CLI reporting gateway stopped is
not sufficient evidence about the browser/backend session-owner process.

The actual executable is `/opt/hermes/bin/hermes`. `s6-setuidgid` was absent from
PATH, so read-only CLI inspection used Python to clear supplementary groups and
drop GID/UID to 10000 before exec. This worked for version/profile/plugin help
commands without inspecting credentials. The actual installer supports
`--ref COMMIT_SHA`, `--yes-deps`, `--no-enable`; persistence/dependency behavior
still needs review before installation into the existing PVC profile.

## Private provisioning tooling — ready, not used for real credentials

- Matching `kubeseal` 0.41.2 downloaded to
  `verification/cache/bin/kubeseal` from the public release, verified against its
  published SHA-256 checksum. No global tool/authentication configuration changed.
- Public sealing certificate fetch succeeded using the configured controller.
  No controller private key or existing Secret value was read.
- The real binary and public certificate were exercised through the helper's
  strict output validator using explicitly fake input; ciphertext was discarded.
  Compatibility passed. This is not infrastructure credential provisioning.
- Operator-private next step from the task worktree:

  `PATH="$PWD/verification/cache/bin:$PATH" python3 -B langfuse/seal-bootstrap.py`

  Choose the owner email/password privately and save the password in the approved
  vault. Do not paste credentials into chat. The helper outputs only encrypted
  manifests, refuses existing destinations, and needs no plaintext credential file.

## Local revalidation

After connectivity restoration and plugin-version investigation:

- Langfuse-specific unittest discovery: 23 tests, all passed.
- Full repository verifier: passed, 21 Applications / 512 resources.
- Updated runbook shell examples: Bash syntax passed; local documentation links
  resolve; `git diff --check` passed.
- The preceding complete suite remains documented in the preparation record:
  117 tests, OK with six explicit skips. No assertion here treats skipped checks
  as successful live acceptance.

## Bootstrap diagnostic correction

The operator's first interactive bootstrap returned the generic sanitized error.
No application ciphertext files were present afterward. The original failure
cannot be attributed conclusively without the discarded input/failure stage;
no password or credential was requested for diagnosis.

The helper required a 20-character owner password but did not disclose that in
its prompt, and all validation failures had the same generic message. The prompt
and help now state the minimum. Controlled, allowlisted reason codes distinguish
email validation, password length/mismatch/characters, existing destinations,
kubeseal failure, output validation, timeout and missing executable cases without
echoing input values, exception text or raw subprocess output. No password rule
was weakened and no existing ciphertext was overwritten.

The new diagnostic regression tests were observed failing before the change and
passing afterward. The complete updated CLI flow was then exercised against the
real kubeseal/controller using explicitly fake input and a disposable cache-only
directory: all six ciphertext files validated, then fixture files were discarded.
No application credentials were provisioned by that test. Final full suite:
119 tests, OK with the same six skips. Full verifier passed again for 21
Applications / 512 resources; `git diff --check` passed.

## Private bootstrap completed and capacity approved

The operator reran the corrected private helper and reported success. Local
readback confirmed exactly six infrastructure SealedSecret manifests with the
expected namespace/name identities, encrypted key sets, protection annotations
and 0600 permissions. No ciphertext values or plaintext credentials were
displayed. The original owner-input failure remains unproven; the successful
retry does not establish its cause.

Revalidation with the real ciphertext files: 119 tests, OK with six skips;
full repository verifier passed for 21 Applications / 518 resources;
`git diff --check` passed. No manifests have been applied to the cluster.

The operator explicitly approved the proposed non-HA capacity budget. The
separate publication-scope question timed out without an answer; commits,
pushes, PR creation/merge and deployment have not proceeded.

## Publication and rollout authorization

After the six ciphertext manifests and capacity approval were verified, the
operator explicitly authorized committing/pushing the task branch, opening and
merging its PR after CI passes, and the reviewed no-prune rollout. The approval
also requires preserving live Hermes v0.22.2; the pending v0.23.1 upgrade is not
part of this deployment. No earlier timed-out prompt is treated as approval.

## Remaining gates

1. Commit/review/publish under the now-approved scope. Capacity, publication
   authorization and infrastructure bootstrap gates are complete.
2. Preserve the six existing ciphertext files; do not regenerate them. Verify
   successful controller unsealing after the approved deployment.
3. Publish/review the intended main revision and green CI; review root registration
   separately from the child deployment, with no pruning or unrelated sync.
4. Deploy Langfuse, verify stores, hook, migrations, valid HTTPS and private login.
5. Create cluster/desktop projects and private keys; seal/inject them through the
   approved process. Enroll only the four selected profile instances using their
   actual plugin generation without core/provider changes.
6. Verify real root/generation/tool traces, metadata-only content, persistence,
   outage behavior and CNI enforcement before declaring the task complete.
