# Staged application rollout — 2026-11-12

This is live verification, separate from the earlier candidate/CI review at
`b0f2968c34d651ee006adf9dec4150b389c8eb17`. The operator requested staged upgrades
until current, preserving existing safety boundaries. Subsequent follow-ups on
2026-11-13 authorized the specifically described recoveries, maintenance and
protected monitoring admission checkpoint. No bulk root sync, pruning,
force/replace, unrestricted credential access or new schedules is authorized.

## Latest checkpoint summary (2026-11-13)

- Verified deployed runtimes in this record: Alloy1.21.3, MetalLB0.16.2,
  Tailscale1.104.4, kube-vip1.3.1, SealedSecrets0.41.2, ArgoCD3.6.1,
  OpenClaw2026.11.3, Vaultwarden1.37.5 and HomeAssistant2026.11.1.
- Home Assistant memory limit1Gi was published in7d63da5 and exact-SHA CI passed
  before its scoped rollout; new pod/readiness/scraping checks passed. Vaultwarden
  retains excluded generated-Secret drift; OpenClaw retains unrelated bootstrap
  drift. Authentication/client/device acceptance is not inferred from readiness.
- Hermes clone SQLite migration passed, but actual config/s6/browser/session-owner
  gates remain. Monitoring crypto/runtime tests passed; real Secret capture and
  rollout remain held for outstanding preflights/custody and data recovery.
- Immich paired-media checkpoint placement is unselected. Hindsight execution was
  explicitly denied and was not retried. Their old production versions remain.
- This is not an all-apps-latest declaration. Sections below preserve chronological
  observations; later corrections explicitly supersede earlier hypotheses/gates.

## Alloy — deployed and verified

- Live Application chart source changed 1.13.1 -> 1.15.0, matching published Git.
  Manual sync policy remained unchanged. All Git sources resolved to the exact
  CI-passing commit above before the operation.
- Complete ArgoCD managed-resource diff reviewed: seven identities, unchanged
  PodLogs CRD, configuration, permissions, Service spec and log pipeline. Only
  version labels and Alloy/config-reloader images changed. No hooks/removals.
- ArgoCD MCP read authentication succeeded, but its `argocd-mcp` account denied
  application sync. The MCP tool also serialized syncOptions in an incompatible
  request shape. No MCP role/token/authentication setting was changed.
- The existing, repository-approved Kubernetes CLI identity submitted an ArgoCD
  Application operation with exact source/revision arrays, `prune: false`,
  `dryRun: false`, hook strategy `force: false`, and retry limit zero. This was
  not a direct image patch or a change to the app's sync policy.
- The first rollout-status command returned before ArgoCD changed the DaemonSet
  template, so it was not accepted as evidence. Verification then waited for the
  exact new template image followed by rollout completion and operation success.
- Final Application status: Synced/Healthy, operation Succeeded. All five node
  pods Ready with `docker.io/grafana/alloy:v1.21.3` and config-reloader v0.94.2
  pinned to its chart-supplied digest.
- Loki metric queries confirmed recent monitoring logs from all five nodes and
  additional argocd/kube-system workload streams. Restarted collectors replayed
  historical files; Loki rejected stale/out-of-order entries during startup.
  Per-node final 30-second log summaries showed zero error/stale-rejection lines.
  No Loki timestamp safeguards were relaxed to admit historical replay.

## MetalLB — deployed and verified

- Live Application chart source changed 0.16.1 -> 0.16.2; manual policy unchanged.
- Candidate nonsecret resources passed client-side apply server dry-run through
  kubectl diff (exit 1 for expected differences, no admission errors).
- Both packaged webhook Secret templates contain only metadata, no data or
  stringData. Live secret values were not fetched.
- Complete semantic review covered 46 nonsecret resources and all 13 CRDs.
  The only existing-field schema tightening limits FRRConfiguration routers to
  50; there are no live FRRConfigurations or BGP resources. RBAC, webhook scope,
  pools, Services and ConfigMap contents remain unchanged. A nonsecret speaker
  exclusion ConfigMap's projection mode changes from 0400 to 0444, not a Secret
  projection or privilege change. Other schema additions are optional and unused.
- Submitted the reviewed exact-revision no-prune ArgoCD operation through the
  configured Kubernetes identity. Final operation Succeeded, Synced/Healthy.
  Controller and status-cleaner Deployments Ready; speaker and FRR DaemonSets
  each 5/5 Ready with MetalLB 0.16.2, FRR-k8s 0.0.27 and FRR 10.6.2.
- All six L2 service announcements persisted. Direct LAN checks matched the
  baseline: Traefik's bare-IP route returned its existing HTTP 404; Immich,
  Vaultwarden, Grafana, Home Assistant and Longhorn returned HTTP 200. This
  checks basic connectivity, not authenticated functional flows.
- Final 60-second error-level log counts were zero for all 12 active pods.
- Local kubectl diff lacks ArgoCD-injected tracking annotations; its apparent
  annotation removals are tooling noise, not an approved ownership change.
  Deployment must remain through ArgoCD with normal tracking injection.

## Tailscale — deployed and verified

- Complete generated-to-live nonsecret diff reviewed and server dry-run passed:
  only operator/proxy image changes, plus local-diff tracking annotation noise.
  Existing OAuth Secret references, privileges and exposure were preserved;
  credential values were not accessed. No hooks or removals.
- Live chart source changed 1.104.1 -> 1.104.4, preserving manual sync.
  Exact-revision no-prune operation Succeeded; Application Synced/Healthy.
- Operator and all 11 managed proxy StatefulSets completed their rollouts and
  actual Ready pods run 1.104.4. Operator readiness alone was not treated as
  proof that the managed proxies had upgraded.
- Anonymous Docker Hub manifest checks returned HTTP 404 for both
  tailscale/k8s-operator:v1.104.6 and tailscale/tailscale:v1.104.6.
  This deploys the latest published stable chart/container target reviewed here,
  not the separately newer 1.104.6 application release.

## kube-vip — deployed and verified

- Complete six-resource live diff reviewed and server dry-run passed: only
  image/chart labels, not RBAC, capabilities, networking or lease settings.
  Preserved VIP 192.168.0.10, eth0, plndr-cp-lock, 15/10/2-second timers,
  disabled Service/egress modes and maxUnavailable=1.
- Authenticated, TLS-verified API /readyz calls succeeded through the VIP and
  each direct control-plane endpoint (.11, .12 and .13). The configured CLI
  already uses .11, independently of the VIP. Previous DaemonSet revision 1
  was available for template rollback without node, lease or data deletion.
- Live chart source changed 0.11.1 -> 0.11.2; exact-revision no-prune operation
  Succeeded. All three actual pods Ready on ghcr.io/kube-vip/kube-vip:v1.3.1;
  Application Synced/Healthy, manual policy preserved.
- During the natural rolling restart, leadership moved k3s-01 -> k3s-02 and
  leaseTransitions increased 2 -> 3. All 19 sampled VIP /readyz requests over
  the approximately 23-second observed operation succeeded. Sampling does not
  prove the absence of sub-sample interruptions; no additional failure was induced.

## Final live health

- All four upgraded Applications: Succeeded, Synced/Healthy, prune false and
  manual sync retained. All source revisions match the CI-passing SHA above.
- Final Kubernetes inspection found no active non-terminating unready pods and
  no unhealthy Applications. All five nodes Ready. Root apps remains OutOfSync;
  it was not bulk-synced and disabled apps/schedules were not activated.
- Live JSON evidence and detailed diffs are local ignored verification artifacts
  under verification/reports/. This report is an uncommitted workspace artifact;
  no new commit or push was made during this rollout phase.

## Initially pending authorization/recovery gates

A clarification requested explicit approval for one-off pre-upgrade backups,
isolated migration/restore rehearsals and necessary app maintenance, plus ArgoCD's
finalizer permission and monitoring's named admission Secret migration. The form
timed out with no answers; **no approval was inferred**. Stateful migrations and
those security/destructive-at-object-level effects remain held.

Read-only backup inspection still found no current-source Longhorn Backup CR for
OpenClaw or Home Assistant. Scheduled Hindsight/Immich/Vaultwarden backup Jobs and
Hermes nightly NAS backup were successful. Job or Backup completion does not
establish a target-version rehearsal or full restore. No backup/restore or
credential removal was performed in this phase.

The following were the initial holds, superseded as noted in the next section;
they are not claims that all applications are latest:

- OpenClaw/Home Assistant: establish complete pre-upgrade recovery coverage.
- Hermes/Immich/Hindsight: isolated sanitized restore/migration rehearsals and
  app-specific recovery/maintenance gates; Hindsight target remains held in Git.
- Vaultwarden: complete-data restore and full server/client compatibility path.
- Argo CD: explicit finalizer-permission approval and initialization-hook review.
- Monitoring stack: explicit named admission-Secret migration/scoped-delete
  permission approval and Grafana recovery. Loki's candidate chart still renders
  runtime 3.6.11; a real runtime upgrade needs additional review, not a chart-label
  claim or an unreviewed 3.7.x image override.
- Sealed Secrets: operator confirmation that controller healing will not revert
  intentional generated-Secret overrides. Synced=True alone is insufficient;
  Secret/controller-key values were not read to try to bypass this question.

## Phase 2 — operator approval on 2026-11-13 AEDT

The operator answered "Approve" to the explicit request for (1) one-off backups,
isolated recovery/migration rehearsals and necessary app maintenance, (2) Argo CD's
reviewed finalizer permission and monitoring's named admission-Secret migration
and scoped delete permission, and (3) Sealed Secrets reconciliation of generated
Secrets to declared contents. This supersedes the unanswered form, not the
requirement that actual compatibility and recovery tests pass. It does not approve
unrelated credentials access, automatic schedules, root bulk sync or data deletion.

### Sealed Secrets — deployed and verified

- Latest upstream controller release independently rechecked as v0.41.2.
  Eleven-resource nonsecret live diff and server dry-run reviewed: image/version
  labels only, with unchanged RBAC, volumes and exposure. No hooks/removals.
- Live chart source 2.20.0 -> 2.22.0, exact published Git revision above; no-prune
  operation Succeeded, Application Synced/Healthy and actual new pod Ready on
  docker.io/bitnami/sealed-secrets-controller:0.41.2. The old terminating pod was
  not counted as an active target-version replica.
- All eight SealedSecrets remain Synced=True; the new controller's metrics report
  eight unseal requests. Existing two controller-key object UIDs unchanged. Only
  their metadata was inspected; no controller-key values were read/exported.
- Recent controller-log inspection emitted only an aggregate error count, not
  raw logs. No controller-key rotation or authentication change was performed.

### Vaultwarden — fresh backup and full archive restore check passed

- Created one-off Job vaultwarden-preupgrade-20261112215611 from the reviewed
  backup specification after verifying the live backup script matches Git and
  there is no active scheduled backup. Production source mounted read-only.
  BACKUP_KEEP=0 disabled archive deletion for this run; schedule unchanged.
- Capacity preflight: source 6,504,097 bytes; backup filesystem free
  206,148,993,024 bytes. The Job completed successfully and verified SQLite
  integrity and required archive contents before atomic publication.
- Archive: vaultwarden-20261112T215612478069Z.tar.gz, 921,932 bytes.
  SHA-256: 013cabea34127ea0eb5a9e6d980e4ce6bba0df4fb77226f44359011156e39fa8.
  Stored in the existing protected NAS backup directory; no payload was displayed.
- Isolated restore Job vaultwarden-restorecheck-20261112215721 completed with
  the archive mounted read-only and restored data on disposable emptyDir storage,
  no production data claim, no service-account token and a deny-all ingress/egress
  NetworkPolicy selecting only this test. Archive checksum verified, all 183
  members restored, SQLite integrity_check returned ok, signing-key presence
  verified without reading/displaying its value, and the one referenced attachment
  was opened/read successfully without displaying its name or contents.
- After recording the result, removed only the disposable restore Job and its
  test-only NetworkPolicy. Read-back confirmed both objects and their pod absent;
  restored emptyDir data was discarded. Production data and NAS archive retained.
- This is an online backup and full archive/integrity test, not a target-version
  startup/migration or authenticated login/decrypted-attachment test. A final
  write-frozen checkpoint and client/server compatibility gates still apply.
- Independent read-only reviews of the remaining migration/recovery paths are
  running. No other production application was upgraded in this phase yet.

### Loki — recovery hazard confirmed, production upgrade held

- Independent review recommends isolated restored-data testing for runtime 3.7.9;
  native configuration validation is not a completed recovery/load rehearsal.
- Parent verified live StatefulSet retention is Delete/Delete and the
  storage-loki-0 PVC has a StatefulSet owner reference. Scaling to zero is unsafe
  until retention safeguards and actual owner-reference reconciliation are
  separately reviewed and verified. No scale-down or storage-policy change made.
- Reviewer found no usable current durable Loki backup; restored-data replay,
  512Mi memory behavior and retention recovery remain untested. Do not substitute
  chart appVersion metadata for an actual runtime upgrade or bypass the gate.
- Detailed local review was actually written under the original checkout at
  /home/benkim0414/workspace/homelab/verification/reports/loki-review/REVIEW.md,
  not under the upgrades worktree. Parent located/read the exact artifact and
  independently confirmed the critical live retention finding.

### Argo CD — deployed and live-verified

- Final 45-resource review passed; no durable storage migration/removals.
  Rechecked successful Verify for exact main SHA b0f2968 above and direct API
  readiness. Captured 37 old-live nonsecret recovery resources, excluding CRDs,
  Secrets and hooks; no secret export performed.
- Updated only argocd child chart descriptor 10.10.3 -> 10.18.0. Submitted the
  full exact-revision hook sync, prune=false, hook.force=false, retry limit zero,
  preserving existing manual/SSA policy. An initial guard stopped before any
  operation because reviewed old hook lifecycle objects carried requiresPruning;
  inspection confirmed only the three named Redis hook RBAC/ServiceAccount
  objects. The guard was narrowed for these reviewed before-hook-creation
  objects only; normal-resource removal remained prohibited.
- Final operation Succeeded, Synced/Healthy. Redis PreSync ServiceAccount,
  Role, RoleBinding and Job all Succeeded. Redis auth-preserving hook behavior
  was reviewed; credentials were not read/rotated.
- Actual controller/server/repo-server/ApplicationSet and copyutil init images
  are v3.6.1, all Ready; Redis remains 8.6.4-alpine and Ready.
  Tailscale UI and /api/version returned HTTP 200, latter reporting v3.6.1.
  No Application comparison conditions appeared. Existing operator login was
  not exercised and no private login/session credentials were accessed.
- Subsequent new-server-side comparison flagged only MetalLB's nonsecret FRR
  startup ConfigMap OutOfSync while Healthy. Parent confirmed its desired/live
  data and labels match exactly; a read-only exact-diff diagnosis is pending.
  No blanket sync, ignore rule, comparison toggle or drift-masking applied.

### OpenClaw, Home Assistant and Grafana — cold backup/restore integrity

- Read-only capacity Job mounted the existing Longhorn NAS backup export:
  206,148,993,024 free bytes, sufficient for conservative source logical sizes
  plus reserve. Configured NAS SSH file was unavailable; no host-key checking
  was bypassed. NFS capacity/target availability do not verify ZFS pool health.
- Sequential guarded maintenance verified manual sync/no HPA or competing
  jobs/leases, source identities/healthy volumes, and Retain policy for HA.
  A watch was established before each scale-down; all application/sidecar
  containers exited 0, all consumers disappeared and normal detach completed
  before new snapshots/full NAS backups. Finally resumed the same original
  workload UID and waited for rollout readiness. No force detach/deletion,
  retention deletion or schedule activation.
- Durable Completed full backups, with source volumes/error checks read back:
  oneoff-openclaw-20261112221139;
  oneoff-home-assistant-20261112221408;
  oneoff-grafana-20261112223223.
- Created separate recovery namespaces with deny-all policies, fresh Longhorn
  restore classes/claims using Retain reclaim, and fixed integrity-only Jobs.
  No copied application was started in Kubernetes. Original claims were not
  mounted by the test Jobs. Source backup snapshots remain untouched.
- HA restored required config paths and one SQLite DB passed integrity_check.
  OpenClaw's initial validator failed because its bundled Python SQLite lacked
  octet_length(). Rechecked with Python 3.13 / SQLite 3.46.1, first asserting
  actual octet_length support: nine databases and required state/capture paths
  passed. No replacement SQL function, database repair or production edit used.
  Grafana's full restored data/required grafana.db passed SQLite integrity too.
- Trusted read-only export helpers copied only restored OC/HA state opaquely
  into owner-only local rehearsal archives (directory 0700/files 0600), without
  displaying payloads. Helpers were removed and absence read back; source and
  restored claims preserved. Application-startup tests are still pending.
- Independently exercised a local rootless network namespace with only lo;
  internet, NAS, node API and cluster API connections all returned ENETUNREACH.
  A public-image runtime preparation worker is testing official-image execution
  without Docker or any host credential/home/socket binding. This is not yet
  evidence of target-version application startup/migration success.
- Original OpenClaw/HA/Grafana replicas were restored to one Ready each. HA LAN
  GET returned HTTP 200. Unauthenticated OpenClaw Tailscale GET returned 403;
  readiness is healthy, but authenticated UI acceptance is not established.
- Remaining monitoring gates still include Prometheus/Alertmanager recovery,
  protected admission Secret/CA recovery and actual Grafana target-version
  rehearsal. Other stateful migration gates remain open; not all apps are latest.

### Actual offline OpenClaw/HA startup rehearsals — passed, limited scope

- Verified official linux/amd64 image bundles and original entrypoints were run
  against independent writable copies of opaque restored baselines, never live
  claims. Rootfs read-only, cleared host environment, separate user/net/PID/etc.
  namespaces, no external interface/ports, scoped cgroup memory/CPU/task limits.
  Home Assistant ran its real /init without arguments as PID 1, not the previous
  diagnostic replacement service. No model turn, auth refresh or integration
  installation was requested; no credential/grant values were displayed.
- Both OC versions reached startupz HTTP200/ok/started and remained ready during
  a bounded settled-startup observation. Both exited cleanly and all nine DBs
  passed integrity checks using their actual image's Node SQLite 3.53.4.
  Target schema user_versions changed 25 -> 27 and 20 -> 22; this is actual
  restored-state migration evidence, not config validation alone. No OOM events
  under the existing 4Gi limit. Checked nonsecret model/runtime/thinking/plugin/
  tool/auth-mode settings preserved relative to the original baseline.
- Both HA versions reached HTTP200, retained HTTP401 on unauthenticated /api/,
  exited cleanly and retained valid recorder SQLite schema 53. Both hit the
  512Mi cgroup ceiling with reclaim events but no OOM; do not claim memory
  headroom. Native test is amd64, not a full ARM/device/client qualification.
- Nonsecret copied config-entry metadata showed the expected HACS -> Marketplace
  migration, all other configured-domain counts preserved and zero disabled
  entries. Two custom-component directories preserved; no www JS cards or YAML
  automations found in this copy. No auth/session/grant files were inspected.
- Offline HA errors occurred in both versions. The single additional target
  ConfigEntryError refers to mobile_app notify; exact public source changed
  notify setup from returning false to raising ConfigEntryError on that same
  failed platform setup. Network/device-dependent functionality is not proven
  by this disconnected rehearsal; no raw application logs were published.

### OpenClaw 2026.11.3 — deployed with scope preserved

- New full cold checkpoint oneoff-openclaw-20261112225752 Completed after observed
  exit 0. Original remained stopped until the reviewed Argo operation began,
  avoiding a write gap between checkpoint and migration. Actual namespace/PVC
  and workload identities preserved; no data restored over production.
- Live child source excludes undeployed backup infrastructure. Repo-wide render
  would add unsuspended backup/recovery CronJobs and RBAC; these were NOT applied.
  Existing bootstrap ConfigMap also differs by an unrelated Codex -> Grok seed
  default, so it was left unchanged rather than treating published drift as
  permission to alter provider defaults.
- Because the current child has no hooks, submitted an exact-SHA, prune=false,
  force=false Argo sync selecting ONLY apps/Deployment openclaw/openclaw. Source
  include/exclusions and manual policy unchanged; verified zero CronJobs afterward.
- Operation Succeeded, actual gateway/init images at reviewed 2026.11.3 index
  digest, deployment 1/1 Ready on k3s-05 with zero restarts and Healthy. Runtime
  /app/package.json independently reports 2026.11.3. Selected live nonsecret
  model/runtime/tool/plugin/auth-mode/cron/browser/update/heartbeat settings match
  the original baseline; no gateway-token/grant values were read or rotated.
- Application intentionally remains OutOfSync ONLY for openclaw-bootstrap;
  runtime version is upgraded, unrelated bootstrap-provider drift remains held.
  No authenticated model turn/device-pairing acceptance was performed.

### Follow-up operator questions — unanswered, not inferred

- Requested confirmation of HA client browser minimums and post-rollout existing
  login/device acceptance, specific protected encrypted monitoring admission
  Secret/CA backup permission, and permission for remaining app-scoped Git
  commits/pushes to main with exact-SHA CI before deployment.
- The form timed out with empty answers. These additional items remain
  unconfirmed; earlier one-off backup/rehearsal/maintenance and specifically
  reviewed migration approvals remain in force. No Git commit/push or admission
  Secret value backup was performed based on the unanswered questions.
- Independent public-image Vaultwarden runtime preparation is running; it may
  not access actual restored data or change production. Its eventual empty-data
  fixture tests must not be reported as target-version full-state recovery.

### MetalLB comparison diagnosis corrected and reconciled

- Supersedes the earlier Server-Side Diff hypothesis: MetalLB has no SSA/SSD
  enablement. The actual cause is repo-server Helm 4.3.1 versus verifier Helm
  3.19.0 rendering of the chart's frr.conf `|+` scalar. Filtered current Argo
  target and independent Helm-4 rendering contain one additional trailing LF:
  213 UTF-8 bytes instead of 212. No FRR command changes.
- Parent independently re-read only this ConfigMap through the filtered Argo
  API, confirmed the live/hash/target byte difference, exact main SHA and that
  the sole drift was this one resource. No broad Secret/resource response used.
- Existing task/repository permissions cover this reviewed nondestructive
  follow-up. Submitted a normal ConfigMap-only Argo operation at exact reviewed
  chart/Git revisions, prune=false, force=false, unchanged sync policy. No Git
  write, restart, force-conflicts override or comparison-ignore change.
- Read-back: operation Succeeded, Application Synced/Healthy, ConfigMap UID
  preserved, data and last-applied match the actual 213-byte target. FRR DaemonSet
  spec/generation and all five pod UIDs/restart counts unchanged; 5/5 Ready.
- Detailed verified analysis: verification/reports/metallb-post-argocd-diff.md.
  Actual follow-up evidence: verification/reports/metallb-cosmetic-reconcile-result.json.
  Future live reviews must account for the actual repo-server renderer; matching
  an older local render alone cannot establish current target equivalence.

### Vaultwarden — real-data startup/migration rehearsal passed, not deployed

- Independently exercised the prepared official 1.37.1 and 1.37.5 runtimes
  against separate writable copies of the verified 183-member full archive.
  The original archive remains byte-verified and protected as mode 0600 under
  the task's mode-0700 private cache; no credential-bearing payload was printed.
  A temporary read-only NAS export Pod/NetworkPolicy was removed and absence
  verified. No production Secret values or launcher session caches accessed.
- Original image entrypoint /start.sh, image root read-only, user/network/PID
  isolation and cleared inherited environment were retained. Actual user-cgroup
  limits: 1Gi memory, no swap, one CPU, 128 tasks. These are diagnostic settings;
  the production StatefulSet has no declared resource limits.
- Copied config sanitizer omitted the admin credential, replaced signing keys
  ONLY in disposable working copies, disabled SMTP/sendmail/push/SSO/external
  2FA and signup/invitation paths, and used a loopback fixture domain. Production
  signing keys/configuration were untouched. All 15 persisted numeric fields
  were preserved; repeated both tests with the 35 allowlisted nonsecret live
  ConfigMap environment entries, including actual database/cron settings.
  Fixture overrides deliberately limit auth/outbound configuration coverage.
- Both versions returned HTTP200 from /alive, / and /api/config, remained ready
  during a bounded observation, and exited 0 without forced termination. Network
  namespace had no external routes; Internet/NAS/node/API connection attempts
  failed. No OOM events; no remaining Vaultwarden sandbox processes confirmed.
- After shutdown SQLite integrity was ok for both copies. Counts stayed at
  one user, 263 ciphers, one attachment, zero sends. Referenced attachment bytes
  matched the baseline. Target schema migrated from 20260505120000 to
  20261007120000; the old-version control retained 20260505120000. This establishes
  actual restored-data migration, not authenticated client/session compatibility.
- Generated-to-live review confirms the chart candidate changes image/labels/
  checksum annotations, without workload/storage/service configuration changes.
  Normal Argo tracking must be retained. The chart-generated optional Secret was
  excluded from payload inspection: do not infer its live contents or authorize
  credential overwrites from a nonsecret diff.
- Production remains unchanged on 1.37.1, pod Ready with zero restarts; Tailscale
  /alive, / and /api/config return HTTP200. Existing-client/proxy compatibility
  and authenticated acceptance remain unverified; the runbook requires those
  checks and a fresh full cold checkpoint before the eventual production cutover.
  No new Git commit/push, chart-descriptor patch or production sync in this phase.
- Sanitized detailed evidence: verification/reports/vaultwarden-1.37.1-real-state-rehearsal.json
  and verification/reports/vaultwarden-1.37.5-real-state-rehearsal.json. Private
  restored state/raw logs are deliberately excluded from Git and report payloads.

## Further staged execution — operator approved proceeding with recommendations

The operator subsequently requested "proceed all as recommended" after the
specific outstanding Home Assistant/client acceptance, protected encrypted
monitoring admission-Secret/CA backup, and reviewed app-scoped publication
requirements were explained. Those approvals are no longer held for an empty
form. They do not establish actual client compatibility or permit plaintext
credential output, broad Secret access, schedules, pruning or bulk root sync.

### Vaultwarden 1.37.5 / chart 0.46.4 — deployed

- Clean exit 0, normal detach and full NAS checkpoint
  `oneoff-vaultwarden-20261112234819` Completed. Original remained stopped between
  checkpoint completion and the reviewed image migration; no write gap.
- Scoped normal Argo sync selected only the main StatefulSet, ConfigMap, Service
  and ServiceAccount. No Secret/SealedSecret payloads or backup schedules synced.
  Exact chart/Git revisions were 0.46.4 and b0f2968c34d651ee006adf9dec4150b389c8eb17.
- Operation Succeeded; actual binary reports 1.37.5, the running image index
  matches the independently verified 1.37.5 pin, pod Ready with zero restarts;
  /alive, / and /api/config return HTTP200 over existing Tailscale HTTPS.
- Workload/PVC UIDs unchanged. Comparison to the retained actual old-image
  ControllerRevision proves the pod spec changed only by the image. Existing
  config/admin Secret references, storage and exposure preserved.
- The first postcondition script stopped on raw dictionary equality because
  Argo's Go API omits empty core API groups (and false booleans). Canonical API
  identity/default-aware read-back confirmed exact intended selection/revisions;
  this was a verifier representation error, not a failed production migration.
  No second sync, downgrade or data overwrite was used to resolve it.
- Application Healthy but OutOfSync for the excluded chart-generated Secret
  `vaultwarden`. Its contents were not inspected or overwritten. Existing-client
  login/2FA, sync, controlled write and attachment acceptance remain with operator.

### Home Assistant 2026.11.1 / chart 0.3.91 — deployed; memory gate resolved

- Clean exit 0, normal detach and new full NAS checkpoint
  `oneoff-home-assistant-20261112235200` Completed immediately before cutover.
  Selected nonsecret app resources only; existing token/authentication preserved.
  Initial operation Succeeded and Application Synced/Healthy. No claim replacement.
- Initial 512Mi pod later became unready under sustained memory pressure and
  underwent one liveness-triggered restart (exit137/reason Error). OOM metric
  increase was zero. Diagnostic Python version-command timeout may have added
  pressure, but was not established as sole cause; no leftover version process.
  Other production rollouts were paused rather than treating initial Ready as
  final acceptance or downgrading against migrated configuration.
- Reviewed node headroom and published only the app memory limit 512Mi -> 1Gi,
  plus the operational README. Requests remain 256Mi; image, probes, config,
  auth/proxy settings and storage unchanged. Full local verification passed:
  19 Applications / 472 resources. Reviewed staged diff/whitespace and published
  `7d63da5c4fe4ea7c1549a1c731cf1a8ab9a29175`; remote read-back matches.
  Exact-SHA Verify run 43333720665 completed successfully before deployment.
- Re-reviewed live diff: only the memory-limit field is semantic; usual standalone
  tracking noise and unsupported Helm-test Pod were not applied. A StatefulSet-only
  no-prune/no-force sync at that exact SHA Succeeded; read-back proves complete
  spec equality except the one memory-limit field, with workload/PVC UIDs intact.
- New pod remained Ready, restart0, HTTP200 at both LAN/Tailscale entry points
  throughout a three-minute sampled window and was rechecked after 325 seconds
  running. Latest sample 556Mi is above the previous cap; authenticated Prometheus
  target up=1 on the new pod endpoint. Fresh Application read-back Synced/Healthy
  supersedes the early Progressing snapshot in the memory-rollout receipt.
- A Roborock coordinator error also exists in logs strictly before cutover (count
  query only; no raw logs exported). This does not prove all integration/device
  functionality. Owner login/dashboard/device acceptance remains required.
- Last cluster read-back found no nonhealthy Applications. All pending stateful
  recovery/migration gates still apply; this is not an all-apps-latest declaration.

### Hermes actual checkpoint clone — SQLite gate passed, no production rollout

- Restored Completed checkpoint `hermes-20261112-170001-7b9ffbab` to a distinct
  10Gi/two-replica Longhorn volume and static Retain PV/PVC in
  `hermes-rehearsal-20261113`. Namespace deny-all policy was created before Jobs;
  resources were created with collision checks, not applied over existing objects.
- Target-image integrity and library-migration Jobs both completed. They bypassed
  s6/gateway/dashboard/browser, loaded no restored config/plugins, used an empty
  Hermes home and a no-socket/no-subprocess Python audit guard. Conventional
  credential files were unlinked only on the clone, without reading them; this
  is not a general secret scrub or permission to start an agent on copied state.
- Actual restored database integrity passed before/after schema31 -> 33; counts
  stayed at 10 sessions and 61 messages. Only counts/schema were reported, not
  transcript values. Production PVC UID/volume identity read-back unchanged.
  Detailed receipt: verification/reports/hermes-clone-migration-result.json.
- Synthetic source tests also confirmed config50 -> 53, including the v53 stale
  clarify-timeout change 3600 -> 90. The README's schema52-only description was
  corrected. Actual persisted config, full image/s6/browser sandboxing, session
  owner/client attachment and fresh cutover checkpoint remain gates.

### Monitoring admission encryption review — blocked before Secret access

- Independent review reproduced a certificate verifier accepting a matching CN
  without SAN. Initial claims of strict SAN verification were therefore not valid;
  no production Secret was accessed and no backup/recovery RBAC was created.
- Parent disabled Common Name fallback explicitly. Regression tests for missing/
  wrong SAN, expired certificates and a proper CA-signed leaf, plus execution in
  the pinned Python3.13 runtime and regenerated embedded-worker manifests, remain
  required before capture. Do not weaken verification if live material is rejected.
- Other runtime preflights remain: exact context/cluster identity, collisions and
  effective SA privileges, additive NetworkPolicies/CNI, allowed API reachability
  and denied egress to an independently confirmed listening endpoint. Only named
  GET permissions are reviewed for backup; recovery writer and namespace-wide
  Secret CREATE permissions remain inactive, the latter unapproved.
- Off-host ciphertext destination and separate identity custody still need an
  operator-selected location. No key or payload was printed or committed.

### Immich and Hindsight follow-up — real blockers separated from assumptions

- Immich official image synthetic PG16 migration fixtures passed: baseline96 ->
  target104 migrations, target repeat0, invalid indexes0, and separate old-version
  dump recovery96. These are not populated-data/full-runtime acceptance results.
  Production remains3.2.0; preserve the completed PG16 cutover and all claim IDs.
- Whole Immich media measures153.33GiB. Same NAS free191.80GiB would nominally
  leave38.47GiB after another full copy, before reserve/growth. No duplicate copy
  was attempted there. NAS SSH remains blocked by unestablished host trust; no
  host-key bypass, authentication change or shared-dataset rollback attempted.
- Parent confirmed independent workstation storage is Btrfs with approximately
  1.7TiB free and rsync available; NFS mount helper was not found. This is a
  possible separately selected checkpoint path, not an executed/readable mount,
  protected media snapshot or paired write-frozen checkpoint.
- Hindsight1.2.1 MIT/local-reranker correction was independently verified against
  tagged LICENSE/config source and added to the upgrade runbook. No mandatory
  hosted Hindsight subscription was established. Explicit MiniLM and existing
  Codex model/grant ownership stay unchanged; no fallback or grant copying.
- Seven offline Hindsight contract tests passed, but the PostgreSQL sandbox
  command was explicitly user-denied by the execution gate. Parent confirmed
  that exact denial in the completed task transcript. No retry, rephrasing or
  alternative path to the denied execution; no DB/runtime rehearsal proof.
  Production remains0.10.3 and requires the operator to resolve that denial.

### Monitoring SAN regression fixed; credential-free ARM64 preflight passed

- Source/manifest hashes independently matched the final test receipt. All22
  dummy tests passed on hostPython3.14 and pinned OCI Python3.13.18/OpenSSL3.0.22
  with age1.3.2. Proper CA-signed SAN leaf accepted; missing/wrong SAN and expired
  leaf rejected. Deliberate disposable CN-fallback mutation fails the missing-SAN
  regression. Prepared identity was not used for fixture tests or mounted there.
- Hardened client checks ownership/modes, symlinks/hardlinks and artifact/receipt
  collisions before exec. Embedded worker in regenerated public manifests matches
  the reviewed source; no recovery writer or namespace-wide CREATE grant enabled.
- Normal documented strict-checking node SSH failed because the configured key
  path/host trust is unavailable. No key, host-trust, privilege or authentication
  change attempted. Firewall chains could not be inspected; zero captured chains
  on that failed command are NOT evidence of absent network-policy enforcement.
- Separately created17 public-only temporary ConfigMap/NetworkPolicy/Pod objects
  for ARM64 preflight. No ServiceAccount/RBAC or production volume/Secret was
  created/mounted; token automount and service links disabled. Native arm64 age
  1.3.2, Python3.13.18 and OpenSSL3.0.22 executed onk3s-01. API VIP and all three
  reviewed backend endpoints accepted CA-validated TLS connections without auth.
- The outside-allowlist Vaultwarden LAN endpoint was independently confirmed
  listening from the workstation and denied from the preflight pod. This proves
  that one tested flow was blocked, not universal confinement or authenticated
  API access. Node-local exceptions/additive policies/effective backup SA grants
  still require reviewed checks before protected capture.
- Cleanup deleted only this attempt's recorded UIDs, pod before its mounts, and
  read-back confirmed every created object absent. Receipt:
  verification/cache/monitoring-recovery/arm64-preflight-receipt.json.
- No actual admission Secret GET, private backup-identity contents read by parent,
  production checkpoint capture, admission hook or monitoring rollout occurred.
  Off-host destinations/separate key custody remain operator decisions, not a
  default inferred from the unanswered form.
