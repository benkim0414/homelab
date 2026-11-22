# Profile directory reorganization

## Scope

Repository layout only. House manager, Learning coach and Career advisor live
under `hermes/profiles/`. Application files remain under `argocd/apps/` and
retain manual sync. No native runtime profile, workload, claim, credential,
provider/model, permission or access channel was changed by this task.

House manager keeps split manifests to preserve generated content and checksums.
The runtime-context overlay stays with House manager tools; no shared runtime
component was introduced. `hermes/BACKUP.md` is a compatibility pointer for
existing monitoring alert links, so alert resource annotations remain unchanged.

The accepted Learning coach files were imported from the separate
`default-learning-coach-cli` worktree. They were not on main at the task base.
The source worktree and the large historical career-learning worktree were not
modified. No private session or authentication file was read or copied.

## Verification

Base commit: `b6a310712c0a996071281a4fdd6b84ba5ef0ad27`.

- Full repository verification: 23 Applications, 529 resources passed, including
  schema/policy/secret scanning and comparison against the base commit.
- The rendered change summary contains only Application path changes for
  `hermes` and `career-advisor`, plus the imported Learning coach Application,
  namespace, claim and Deployment. No existing workload or storage resource
  changes were reported.
- All 19 relocated House manager YAML files, including the plugin manifest,
  match their base Git blobs byte-for-byte. The 30 Kubernetes resource documents
  from its top-level manifests are identical. All seven historical JSON files
  also match their original bytes.
- Career advisor manifest matches its base Git blob byte-for-byte. Learning
  coach manifest matches the accepted source worktree byte-for-byte.
- Existing `hermes` and `career-advisor` Applications differ only in source path.
- Repository unittest discovery: 227 tests ran, OK with 26 skipped for optional
  tooling, public-source fixtures or an already completed migration.
- House manager general tool suite: 90 tests passed after relocation.
- House manager connector/plugin/runtime-context suites: 78 tests passed using
  the existing CI downloader's hash-pinned public upstream fixtures. No cluster
  source or private runtime state was captured.
- Browser generator exercised by the implementation agent in a temporary tree;
  generated manifests matched the existing bytes.
- Renovate extraction checker JavaScript syntax and Git whitespace checks passed.
  A new full Renovate extraction run was not performed.

Initial tool discovery lacked ignored `runtime_context/.test-state/installed`
fixtures (22 errors). The existing CI downloader's `--upstream` mode supplied
the exact hash-pinned public files, and those suites then passed. No live source
capture, package installation in a workload or expanded acceptance was needed.

Independent review found one obsolete CI working directory. It now points to
`hermes/profiles/house-manager/tools`. A regression test reproduced the failure
before the correction and passes afterward. Renovate extraction assertions now
also cover both specialist image/digest declarations. The active backup alert
links resolve through the compatibility page without changing alert manifests.

## Delivery boundary

Implementation was prepared on `default-hermes-profile-layout`. The user then
authorized one atomic commit and merge. Publication does not authorize cluster
apply, restart or ArgoCD sync; none is included in this reorganization.
Review reconciliation separately. In particular, registering Learning coach in
Git is distinct from its already completed direct deployment.
