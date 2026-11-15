# Gerrit learning instance: installation and configuration plan

Date: 2026-11-15 (Australia/Melbourne)
Status: implemented and tested locally; not published or deployed
Scope: isolated personal Gerrit review lab in the existing K3s cluster

## Goal and boundaries

Learn Change-Id, changes, patch sets, inline review, voting, submission and stacked
changes using a new `gerrit-playground` repository. Do not migrate the homelab
GitOps source, change GitHub remotes, or connect CI during the initial installation.

Use one Gerrit instance, private access and persistent data. No Gerrit operator,
HA, external SQL database, public LoadBalancer, SMTP, external AI provider,
automated sync/pruning, scheduled jobs or messaging integrations in phase one.
This plan is not permission to create credentials, expose services, commit, push
or deploy. Obtain approval for the proposed authentication/access design before
implementation and approval for publication and rollout at their respective gates.

## Evidence collected

Read root/app instructions and the [ArgoCD runbook](../../argocd/README.md),
[Tailscale runbook](../../tailscale/README.md), [NAS runbook](../../nas/README.md)
and [verification guide](../../verification/README.md).

Read-only Kubernetes CLI discovery on the plan date found:

- Five Ready nodes, no MemoryPressure, DiskPressure or PIDPressure.
- `k3s-01` through `k3s-04`: ARM64; `k3s-05`: AMD64. No node taints reported.
- `k3s-05`: allocatable memory `15596796Ki`, sampled usage `7017Mi`,
  memory requests `5842Mi`, limits `17Gi` (114%). Requests are not real usage;
  overcommitted limits and unreserved workloads require a fresh capacity check.
- `k3s-04`: sampled usage `2686Mi`, but an existing Hindsight container has a
  `4Gi` limit. Do not choose a node from idle usage alone.
- Tailscale operator Deployment available `1/1`; Tailscale IngressClass present.
- Longhorn disks reported Ready/Schedulable. Default `longhorn` StorageClass uses
  ext4, two replicas, immediate binding and reclaim policy `Delete`.
- No pods/PVCs returned for namespace `gerrit`; this is not a global search for
  Gerrit instances or evidence that the namespace exists.

Public registry inspection of `docker.io/gerritcodereview/gerrit:3.14.6` returned:

- Linux AMD64 manifest: `sha256:7e731f22264ec7d8e17fafa5fd488430690a5c6a0d51d405e5b165e46a74a135`
- Linux ARM64 manifest: `sha256:a7eadd318e495d502580b98254c737963b2c1ccaf26b5c07ce68e2e737debf0e`

These are platform manifests, not the multi-platform index digest. The image was
not pulled or executed. Pin the verified index digest during implementation, or
pin a platform manifest together with an explicit matching architecture constraint.

Upstream support lists 3.13, 3.14 and 3.15 active, but the releases overview still
labels 3.15 in development. Use supported 3.14.6 as the initial candidate, not a
claim that it is the newest release. Recheck support, patch/security notes and
exact image before implementation. Unversioned documentation may describe newer
features; validate all configuration against the selected release's documentation.

## Proposed architecture

- Namespace `gerrit`; ArgoCD Application `gerrit`, raw manifests on `main`.
- Single-replica StatefulSet with a separately named persistent claim. Explicit
  retention, no cascading deletion finalizer on the new Application, no prune,
  force or replace. Never run two Gerrit writers against the same site.
- Gerrit container plus a small pinned authenticating reverse-proxy sidecar.
  Gerrit HTTP listens on IPv4 loopback only; Service targets the proxy, never
  Gerrit's backend HTTP port. No backend HTTP listener on the Pod IP.
- ClusterIP Service; proposed Tailscale HTTPS name `gerrit`. Check name/device
  collisions and existing ACL access before creating a proxy. Do not change
  Tailscale OAuth credentials or broaden ACLs as part of installation.
- Web and initial Git transport over HTTPS through the same authenticated proxy.
  Do not expose SSH initially. A later localhost-only kubectl port-forward to
  Gerrit's SSH port 29418 can teach SSH without allocating a persistent endpoint;
  explicitly document the temporary host/port rather than misleading clone links.
- No privileged containers, host paths, host networking or Kubernetes API access.
  Disable service-account token automount. Verify intended UID/GID and volume
  permissions using the pinned image; do not apply recursive ownership changes
  to unrelated storage. Start with dropped capabilities and no privilege
  escalation; assess writable paths before promising read-only root filesystems.
- Ingress NetworkPolicy permits only the intended Tailscale proxy traffic to the
  authenticating proxy. Verify actual source labels/IPs and K3s enforcement.
  Probe traffic and approved diagnostic access must be accounted for explicitly.

## Authentication and project permissions

Recommended low-dependency lab choice, pending operator approval:

1. Proxy-managed HTTP Basic authentication over Tailscale HTTPS, with Gerrit
   `auth.type=HTTP`. An operator creates a new lab credential privately; deliver
   only encrypted SealedSecret ciphertext or an approved local Secret injection.
   Do not reuse other applications' credentials or put values in chat/arguments.
2. Proxy validates every request, including Git smart HTTP and REST, and overwrites
   Gerrit's configured identity header with its authenticated username. Strip any
   client-supplied identity/display-name/email headers; restrict trusted proxy
   addresses to loopback where supported by the selected release. Backend is
   loopback-only regardless of header-source configuration support.
3. Verify exact selected-release Git HTTP authentication settings: proxy password
   authentication and Gerrit-issued Git tokens are different mechanisms. Phase one
   intends proxy authentication end-to-end; prove clone/fetch/push through it.
   Do not create a bypass route to make a token workflow work.
4. Restrict initial proxy allowlist to the intended operator account. The first
   registered user normally becomes administrator; bootstrap privately before
   admitting any second account. Confirm the actual administrator membership.
5. Decide the operator username and commit email privately before bootstrap.
   With SMTP disabled, use a reviewed trusted-proxy email mapping supported by
   the pinned release, or its documented administrative email setup. Verify commit
   author email matches the account; do not solve failures by disabling validation.
6. Create `gerrit-playground` on branch `main`. Give a non-admin lab identity/group
   repository-scoped upload, Code-Review +2 and Submit rights. Allow uploader
   self-approval for this repository only. Do not weaken global submit rules.
7. Require Code-Review +2 and no unresolved review threads for submission; validate
   the selected release's exact submit-requirement expressions. Do not require a
   nonexistent CI `Verified` vote. Keep direct updates to `refs/heads/main` denied
   for the ordinary lab identity, but permit initial seeding through the admin.

Basic authentication logout/account switching has browser limitations. If two
identities are useful later, use separate browser profiles and credentials; do
not enable DEVELOPMENT_BECOME_ANY_ACCOUNT. OAuth/SSO is a separate enhancement,
not a prerequisite or an implicitly approved authentication change.

## Resource and storage proposal

Initial Gerrit budget: CPU request 500m, limit 2; memory request 2Gi, limit 4Gi;
JVM maximum heap 2Gi, leaving native/index/cache headroom. Budget the proxy
separately (initially 50m/64Mi request, 200m/128Mi limit) and include the extra
Tailscale proxy in capacity review. These are trial values, not measured needs.

Prefer worker placement, provisionally `k3s-05` with explicit AMD64 compatibility.
Before approval, review current peak usage and existing requests/limits, including
rehearsal workloads. Do not delete or move another task's pods to make room. Hold
rollout or propose separate resizing/placement if adequate headroom is uncertain.
Verify ARM64 startup before proposing `k3s-04` as an alternative; image manifest
availability alone is not runtime validation.

Allocate a proposed 10Gi RWO site claim. Prefer a new Gerrit-scoped StorageClass
matching reviewed Longhorn parameters but with reclaim policy `Retain`; do not
modify the shared default or reuse unrelated recovery classes. Include this
cluster-scoped resource explicitly in Application/AppProject and verifier review.
Retain claim identity across restart, rollout and scale-down. Account for two
replicas and snapshot/backup growth when checking available disk capacity.

Map all mutable Gerrit site paths after inspecting entrypoint/init behavior:
repositories including All-Projects/All-Users, configuration/generated secrets,
SSH host keys, plugin data, H2 state where used, and indexes/caches as appropriate.
Keep declarative nonsecret configuration separate from generated sensitive state;
never overwrite an existing initialized site on every startup. Use an idempotent,
version-checked initialization path; no automatic plugin downloads at runtime.

## Implementation sequence and deliverables

1. Confirm access/auth proposal, initial username/email and practice-only scope.
2. Inspect pinned image Dockerfile/entrypoint, Java version, plugin inventory,
   initialization flags, UID/GID, health endpoints and upgrade behavior. Pull and
   exercise a disposable site locally where supported, without real credentials.
   Select only necessary bundled plugins (e.g. Gitiles for browsing); no AI,
   flows, webhook, external CI or outbound messaging integration.
3. Add `gerrit/AGENTS.md` and `gerrit/README.md` with ownership, bootstrap, safe
   credential provisioning, transport, backups, restart and recovery procedures.
4. Add namespace, config, StatefulSet, named PVC/new StorageClass, Service,
   NetworkPolicy and Tailscale ingress under `gerrit/`. Add encrypted auth material
   only after approved provisioning. Set canonical HTTPS URL and reverse-proxy
   scheme correctly. No public NodePort/LoadBalancer.
5. Add `argocd/apps/gerrit.yaml` with an explicit raw-file include glob, the correct
   project/destination and manual sync. Root `argocd/apps.yaml` already includes
   `*.yaml`; do not broaden discovery or activate unrelated apps. Check live
   AppProject permissions without dumping repository credential Secrets.
6. Validate all raw-file coverage and account for verifier inventory/config changes
   required by the new Application/StorageClass. Preserve policy safeguards.
7. Run `git diff --check` and the full repository verification workflow (bootstrap,
   tests, policies and renderer per the verification guide). Offline is partial.
   Rehearse initialization/restart and proxy negative tests with disposable state.
8. Present complete changes and prerequisite results. Commit/push only when asked;
   require successful Verify CI for the exact published revision before rollout.
9. Review root drift separately; register only Gerrit, not all pending children.
   Review full child diff, admission prerequisites, exposure, storage retention and
   auth references. Sync only the approved exact revision, without prune/force.
10. Bootstrap the account/project, execute acceptance tests and record real results
    in the runbook. Operator performs private login/credential entry as required.

## Acceptance tests (must execute before claiming working)

- Exact intended image and revision running; PVC Bound and Longhorn volume healthy.
- Startup probe tolerates initialization/indexing; readiness checks actual serving
  state. Restart/liveness settings do not cause initialization loops.
- HTTPS certificate, canonical redirects, login and project/source browsing work.
- Missing/wrong proxy credentials fail; spoofed identity headers cannot change
  user; direct Pod-IP backend HTTP is unreachable. Unapproved access paths fail.
- Normal lab identity clones, installs commit-msg hook and pushes a review to
  `refs/for/main`. Main remains unchanged until submission; direct main push denied.
- Inline comment, amended commit and second patch set retain the same Change-Id;
  patch-set comparison works. Resolve thread, vote +2 and submit successfully.
- Fresh clone/fetch sees submitted content. Two dependent changes can be reviewed,
  revised/rebased and submitted in order. Record actual change URLs/IDs.
- Controlled pod restart preserves account, repository, comments, votes and patch
  sets; no unexpected reinitialization. Observe memory/restarts after startup and
  review actions, not merely initial Ready.
- Produce one consistent backup and restore into isolated disposable storage;
  prove review metadata and repository history survive. Never test by replacing
  the live volume. Failure leaves lab marked experimental with disposable data.

## Backup, recovery and uninstall

Phase one uses an explicitly requested manual cold backup, not a new CronJob.
Before stopping the single replica, verify PVC retention/ownership and volume
reclaim policy. Observe normal shutdown and detached/unused data before backing
up. Preserve the full site plus pinned image/plugin/config versions; protect
secret material with approved encryption/access controls. Longhorn replicas are
not backups. NAS snapshots do not automatically cover Longhorn site data.

Select a dedicated NAS archive destination and verify permissions/free capacity
before any write; do not reuse or alter existing recovery sets. No automatic
retention deletion. Future scheduled backups require separate approval.

For initialization failure, retain logs safely and preserve the failed PVC for
inspection; do not delete/reinitialize it to obtain a green rollout. For upgrades,
checkpoint first: image downgrade alone may not undo site schema changes. Recover
with the matching complete site backup into a new retained claim after approval.

Uninstall is separately authorized: stop access/workload, preserve/export the site
and verify backup, then review Application deletion mode and each resource.
Never delete the namespace, PVC, PV, Longhorn data or Tailscale devices as a casual
cleanup step. Retain recovery data until the operator approves its removal.

## Verification status and remaining gates

The operator approved proceeding with the plan on 15 November 2026. That approval
was applied to implementation and the private HTTP-auth design, retaining separate
publication and rollout gates. The operator subsequently supplied encrypted auth
and authorized an atomic implementation commit. No live cluster writes or pushes
were performed; publication and rollout remain separate gates.

Completed: repository/upstream discovery, public image-platform inspection,
scoped live capacity/storage/Tailscale checks and live default AppProject review.
No Secret values read. Added the single-instance manifests, private credential
sealing helper, generated-config checks, runbook and Gerrit regression coverage.

Local validation: repository suite ran 91 tests with six pre-existing optional/
environment skips; all executed tests passed. All five policy tests passed. Full
repository verifier passed with 20 Applications and 482 resources, including the
operator-generated authentication SealedSecret. Whitespace and local doc links
passed. Actual kubeseal 0.41.2 encryption using the controller's public certificate
also passed with synthetic credentials only, without a cluster write. The operator
then privately generated the real authentication ciphertext; its resource identity
and encrypted field set were verified without displaying values. The helper now
preflights public-certificate access and gives stage-specific, credential-free
errors and local password-validation retries.

Real-image rootless rehearsal passed in
`verification/cache/gerrit-probe-09/result.json`: authentication and spoof rejection,
first-account administrator and non-admin separation, WebUI HTML/Gitiles,
non-admin Git clone/push, direct-main denial, two patch sets, unresolved comments,
self-approval/submission, two stacked changes revised/rebased/submitted, normal
shutdown/restart persistence and isolated complete cold-site backup/restore.
The bounded scope recorded memory peak 932077568 bytes and zero OOM events; this
small synthetic run is not a cluster sizing guarantee. Kubernetes CNI/fsGroup,
tailnet TLS/ACLs, interactive browser behavior and NAS backup remain live checks.

The protected-file tool blocked creation of `gerrit/AGENTS.md` after its approval
prompt timed out. It was not retried or bypassed; that planned deliverable remains
omitted pending explicit protected-file approval. Existing repository instructions
and the application runbook still apply.

Remaining gates: publish approval and exact-revision CI; refreshed peak capacity;
live storage retention/
ownership and tailnet-name/ACL verification; complete scoped ArgoCD diff and
rollout approval; live acceptance and an actual deployed-site NAS backup/restore.
No full cluster-health, Grafana alerts or Loki log audit was performed.

## Upstream references

- [Container images and training/production caveats](https://github.com/GerritCodeReview/docker-gerrit)
- [Supported versions](https://www.gerritcodereview.com/support.html)
- [Release overview](https://www.gerritcodereview.com/releases-readme.html)
- [3.14 release notes](https://www.gerritcodereview.com/3.14.html)
- [Authentication/configuration](https://gerrit-review.googlesource.com/Documentation/config-gerrit.html)
- [Reverse proxy configuration](https://gerrit-review.googlesource.com/Documentation/config-reverseproxy.html)
- [Review walkthrough](https://gerrit-review.googlesource.com/Documentation/intro-gerrit-walkthrough.html)
- [Backup and consistency](https://gerrit-review.googlesource.com/Documentation/backup.html)
- [Kubernetes operator, deferred](https://github.com/GerritCodeReview/k8s-gerrit/blob/master/Documentation/operator.md)
