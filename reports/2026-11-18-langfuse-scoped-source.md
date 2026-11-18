# Langfuse scoped-source rollout and safety findings

Verified on 2026-11-18; storage/settings sample at 12:44 AEDT. This supersedes the
initial key-only diagnosis in the earlier [rollout record](2026-11-18-langfuse-rollout.md).

## Approved and applied

The operator approved a read-only mount of the existing `hermes-langfuse` Secret
and a native command-secret source for only cluster default and house-manager.
Created and read back `ConfigMap/hermes-langfuse-key-source`; server dry-run and
post-patch comparison proved the Deployment changed only by two read-only volumes
and two mounts. Its Recreate rollout completed. Main/init images, probes,
resources, existing volume references, manual sync and provider settings were
not changed. Live Hermes remains v0.22.2. PVC UID and PV binding match the recorded
pre-change baseline; Longhorn reports attached/healthy with two replicas.

The helper reads only the two projected files as application UID/GID 10000,
validates bounded ASCII values, and emits an all-or-nothing map through the
framework's captured credential IPC. Never execute it directly as a diagnostic:
its stdout contains credentials. No values are written into ConfigMaps or profile
configuration. The supported `hermes config set secrets.command` path was used;
there were no previous command sources or explicit source-order lists to replace.
Settings backups are under
`/opt/data/langfuse-scoped-source-backup-20261118T012001Z-c5359f45`.
Only task-owned backup permissions were restored to 0600/0700 after recreation.

## Potential credential disclosure during verification

The initial helper supplied only the two keys. A bare-Python probe first omitted
normal external-source hydration; inspection showed that
`hydrate_profile_secret_sources(home)` must precede `build_profile_secret_scope()`.
After adding normal hydration, the first SDK authentication attempt returned
`UnauthorizedError`, before any setup observation was created.

Inspection of the pinned catalog plugin at
`c2a95963c442f3f23e4bc6fe0da898e1dd1fb63d` then exposed the incomplete diagnosis:
`_build_client()` uses `_secret()` for BASE_URL, ENV and SAMPLE_RATE as well as
credentials. Its separate `_env()` status helper returning the pod's private URL
was not evidence of the effective SDK destination. A missing scoped BASE_URL
selects `https://cloud.langfuse.com` even when the pod environment has a private
URL. The first authentication probe may therefore have transmitted the
self-hosted project's ingestion key pair to Langfuse Cloud. No packet-level
request-destination capture was collected; treat the pair as potentially
disclosed, not as proven safe. No user prompt/tool content was supplied by this
probe, and it failed before creating an observation.

The operator was notified immediately after the constructor issue was identified.
Both plugins were temporarily disabled through the supported CLI. No key was
printed, copied between profiles or rotated. Recommend privately replacing and
revoking this `hermes-cluster` project key pair; this is not permission to rotate
inference-provider credentials or any of the six server-bootstrap secrets.
Rotation requires explicit approval and a reviewed private ciphertext replacement
workflow; the existing no-overwrite client helper must not be blindly rerun.

## Corrected source and verified private export

The source now atomically supplies both keys plus these fixed scoped settings:

- BASE_URL: `http://langfuse-web.langfuse.svc.cluster.local:3000`
- CAPTURE: `metadata`
- ENV: `homelab-cluster`
- SAMPLE_RATE: `1`

Regression contracts require these settings to match the Deployment. The probe
now checks `_secret(BASE_URL)` against the exact internal URL, and checks scoped
sampling, before constructing any SDK client or making any network call. It does
not substitute global credential fallbacks. Both scopes passed these checks.
The updated live ConfigMap was read back exactly.

Both scoped SDK clients authenticated to project `hermes-cluster` and exported
clearly labelled zero-model setup spans. Supported v2 observations readback,
bounded by exact trace IDs and time windows, found one observation for each with
empty input/output and matching setup-purpose/profile metadata:

| Profile | Actual setup trace ID |
| --- | --- |
| default | `cf5f94f85b62ceb59ecbddc4b96994ad` |
| house-manager | `88c0a441d027b36edefdeff5a607c600` |

These are genuine SDK export/readback checks, not real Hermes model/tool turns.
No generation/tool privacy acceptance, trace restart persistence or outage
acceptance is claimed. Keep the shared SDK resource manager alive until all
same-project probes finish; shutting the first client down can stop later probes.

## Remaining activation and capacity blocker

Re-enabling default succeeded. House-manager re-enablement was refused with
`Errno 28: No space left on device` while the package manager cloned a new managed
environment. Its failure did not enable the profile. At that failure, settings readback showed default enabled and house-manager
disabled. Subsequently paused default with the supported native
`hermes config set plugins.enabled` operation, removing only Langfuse from its
enabled list without another environment build. Final readback confirms both
profile activations are paused; both source configurations are retained.
All other provider/settings values match the pre-source backups. No repeated
activation retries, environment deletion or storage expansion was performed after
identifying the capacity failure.

The 10Gi Hermes filesystem had 936792064 bytes (about 0.87 GiB) available and
515185 free inodes. Five root managed-environment directories occupied about
8.19 GiB. This is Hermes package-manager working/retained environment storage,
not a Langfuse datastore or VM CPU/RAM shortage. Failed staging cleanup left
some free space, but another full environment build does not fit.

`hermes-data` remains Bound at 10Gi with its original UID/PV; reclaim policy is
Delete, so deletion/recreation is not a recovery option. StorageClass allows
expansion; all five Longhorn nodes allow scheduling, with observed available
capacity ranging from 79.8 to 405.4 GiB. Proposed next step is explicitly approved
in-place expansion to 20Gi without deleting data, followed by house-manager
activation and a final fresh-window restart. Alternatively, audit managed
references and obtain approval before removing any unreferenced environments.
Do not assume every old environment is disposable: some may be active or rollback
references. In-place growth cannot be undone by shrinking this filesystem.

Until storage remediation, private key rotation and final activation/restart are
resolved, do not present browser tracing as fully accepted or resume chats for
acceptance testing. Desktop enrollment remains pending. The pod is Ready, but
that does not prove sufficient free space for package operations or session writes.

## Local validation and publication

Updated full suite: 144 tests, OK with six skips. Full verifier: 21 Applications /
520 resources. Initial standalone policy check: five passed. Helper and mount
contracts cover projected symlinks, all-or-nothing failures, bounded reads,
unsupported-argument suppression, read-only access, source/ConfigMap equality,
manual selection and all scoped constructor settings.

Changes remain local/uncommitted in the task worktree. The approved live changes
were direct, narrowly reviewed operations, not a broad ArgoCD sync. New helper
selection is prepared in the local Application; it is not yet published on main.
Do not sync the whole pending Hermes Deployment: its unrelated v0.23.1 upgrade
and other drift remain deliberately unapplied. No commit, push, source prune,
force/replace operation, provider change or schedule/messaging enablement occurred.

## Subsequent explicit approvals

The operator approved in-place expansion of the existing `hermes-data` claim from
10Gi to 20Gi, preserving identity/data, and confirmed a fresh idle window for
activation and restart. The operator separately approved preparation/guidance of
a private replacement/revocation workflow for only the Langfuse project pair.
Neither approval authorizes server-bootstrap or inference-provider rotation.

The declarative claim now requests 20Gi. The verifier's exact `storage-resize`
exception covers only `/PersistentVolumeClaim/hermes/hermes-data` against the
10Gi base and links to this approval record; other storage guards remain active.
Remove that exception once the comparison base already contains 20Gi, as the
verifier deliberately rejects stale/unmatched exceptions. Expansion is not a
shrinkable rollback; on failure preserve the claim and inspect CSI/Longhorn rather
than deleting/recreating it. Live expansion results will be recorded separately.

### Verified in-place expansion

The new capacity contract was exercised RED at 10Gi, then GREEN at 20Gi. Full
manifest verification passed with the exact approved resize exception. A guarded
server dry-run proved only `spec.resources.requests.storage` changed; the actual
patch requested 20Gi and readback retained the recorded original UID/PV.
Kubernetes then reported capacity 20Gi. Inside the still-running pod, the mounted
filesystem reported 19.58 GiB total and 10.71 GiB available, confirming online
filesystem growth rather than merely a requested size. No environments or data
were deleted; no image/provider/VM resources changed. Both tracing activations
remain paused pending private replacement key entry and final activation/restart.

### Private rotation preparation verified

Added `langfuse/rotate-hermes-client.py` and eleven fake-fixture regression tests.
It reuses the existing private project verifier and strict sealer in empty private
staging, validates both ciphertext identities/keysets, preserves the old
ciphertext in ignored owner-only cache, detects changed/symlink/nonregular targets,
and publishes by atomic rename. Concurrent helper instances serialize via a
directory lock; unrelated writers must not edit during the final stat/rename
interval, which is not OS-level compare-and-swap.

Parent review and execution verified the full fake-input rotation path with the
actual kubeseal binary/controller; only the fake-key project HTTPS check was
mocked. Temporary fixtures were discarded without touching the production target.
Read-only production ciphertext identity/scope/keyset preflight passed; no payload
was displayed and it was not replaced. Cache exclusion was checked. Updated full
suite passed 156 tests with six skips; full verifier passed 21 Applications /
520 resources. The helper's help and diff-whitespace checks passed.

The operator must now create/enter the replacement pair privately and revoke the
old potentially disclosed cluster pair while tracing is paused. No replacement
pair has been entered, no production ciphertext rotated, and no key revoked by
this preparation. After private entry, review/apply only the client SealedSecret
and complete activation/restart with a current idle confirmation. The initial
server-bootstrap secrets and inference-provider authentication remain out of scope.

## Replacement applied and cluster profiles activated

The operator ran the private rotation helper successfully and reported backup
`verification/cache/rotation-7a82078603af25e878ddf1213c252268/previous-ciphertext.yaml`.
Read-only validation confirmed strict identity/keyset, 0600/0700 modes, the backup
matching previous HEAD ciphertext and only encrypted values changed. Full local
unit/manifest checks passed with the replacement present.

Reviewed and applied only the SealedSecret's two encrypted fields using an
optimistic-concurrency JSON patch after server dry-run. Readback retained its UID,
matched the replacement ciphertext, and confirmed the controller observed the new
generation with Synced=True. Generated Secret metadata changed under the expected
SealedSecret owner. No plaintext Secret values were fetched or displayed.

After the clarification form timed out, the operator replied `yes`; this was
explicitly interpreted as confirmation that the old pair was revoked and Hermes
was idle for activation/restart. Revocation is operator-confirmed, not independently
checked by decrypting or reusing the old credentials.

Both profiles enabled successfully through the supported plugin CLI with
`--no-allow-tool-override`. The final Recreate restart completed, and both scoped
SDKs authenticated to the private `hermes-cluster` project and exported new
clearly labelled no-model setup spans. Supported v2 observations readback found
one observation for each, with empty input/output and expected purpose/profile
metadata:

| Profile | Replacement-key post-restart trace ID |
| --- | --- |
| default | `1e5789cd3243fffeb477a5f311999715` |
| house-manager | `e3dcea5f0e4cc9e09aedae4b2d6c1c90` |

Final settings comparison against the pre-source backups matched exactly after
adding only the approved command source. Both enable flags and false tool-override
permissions were read back. Task-created settings backups were restored/read back
at 0600/0700 after startup. Available data filesystem space was 9.14 GiB. The
original PVC/PV remained Bound at 20Gi, Longhorn healthy, and the exact original
v0.22.2 image remained available. Private Langfuse health returned OK/4.77.0.

Cluster credential enrollment/activation is complete. Real model/generation/tool
privacy, trace persistence through server restart and outage acceptance are still
pending; the setup-span checks are not substitutes for those tests. Desktop
enrollment is also pending. Changes remain local/uncommitted; no broad ArgoCD
sync, core upgrade, environment deletion, provider change or schedule enablement
was performed.

## Git publication and resize-exception retirement

The operator authorized commit, push, PR creation and merge after checks, without
a broad sync or core upgrade. [PR #97](https://github.com/benkim0414/homelab/pull/97)
published the reviewed scoped source, replacement ciphertext, 20Gi claim and
supporting tooling/evidence. PR verification passed; it merged as
`1ad9a43800526a66870b2f750055d7e711bfc042`.

That merged baseline already contains 20Gi. Re-running verification against it
correctly rejected the now-unmatched one-time resize exception (RED). The follow-up
removes only that exact exception and records publication; general storage
guards remain unchanged. Historical local/uncommitted statements above describe
the earlier rollout phase and are superseded by this publication record. No
cluster write, Application sync or deployment is part of publication/cleanup.
