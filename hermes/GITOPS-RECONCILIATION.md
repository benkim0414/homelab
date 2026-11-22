# Hermes GitOps reconciliation — 22 November 2026

Verified at `2026-11-22T06:18:08Z` after the user explicitly authorized Application
path reconciliation and specialist registration/adoption. This operation is
separate from the directory reorganization and its publication.

## Revision and result

Reviewed main revision: `074c76df1dafed3ca3b42086a76ea0cab7554343`.
Both the PR checks and the main-commit `Verify` checks succeeded. Main was
checked before the selected syncs and remained at that revision afterward.

| Application | Source path | Verified state |
| --- | --- | --- |
| `hermes` | `hermes/profiles/house-manager` | Synced / Healthy |
| `learning-coach` | `hermes/profiles/learning-coach` | Synced / Healthy |
| `career-advisor` | `hermes/profiles/career-advisor` | Synced / Healthy |

All three Applications retain `targetRevision: main`, manual sync, no cascading
finalizer and their original namespaces. Reconciliation is not automatic rollout.

## Review and exact operations

1. Reviewed the published raw declarations, Application specs, root selection,
   default AppProject permissions, selected resource identities and storage
   preservation conditions. No image, database or runtime upgrade was involved.
2. Recorded public Deployment/Pod/PVC identities and existing Application specs.
   Server dry-runs for all three selected Application objects succeeded. The
   existing Hermes Application differed only in source path. Specialists were
   new Application objects adopting already-running resources.
3. Compared each specialist's complete current spec with server dry-run apply
   output for its namespace, claim and Deployment: no spec changes. A further
   tracking-metadata dry-run likewise predicted no spec changes.
4. Submitted a revision-pinned selective root sync for only the three Application
   objects. Its operation succeeded and its result lists exactly those targets.
   Existing root exclusions were not changed. No full root sync was performed.
5. Hermes immediately became Synced/Healthy after resolving the new source path;
   no Hermes child-resource sync was needed.
6. Submitted revision-pinned apply-strategy syncs for each specialist. Each
   succeeded for exactly its namespace, claim and Deployment. Pruning was false;
   force and replacement were explicitly disabled. No hook resources exist in
   these specialist manifests. No automatic retry was requested.
7. Read back source revision, selected paths, status, tracking annotations,
   operation results, workload identities and bounded configuration fields.

The normal ArgoCD CLI had no usable session. Core-mode access also failed with
local configuration and service-account limitations. No login, credential
refresh, privilege change or authentication workaround was performed. The
operation used the existing Kubernetes-authorized Application operation workflow.
A CLI-generated diff was therefore unavailable. Published-source comparisons,
server dry-runs, controller comparison results and exact operation results were
used instead. No decrypted Secret or private authentication/session content was
read, copied or printed.

## Preservation evidence

| Workload | Deployment UID | Pod UID | Claim UID |
| --- | --- | --- | --- |
| Default Hermes | `9d4e9fba-b4b1-4b7c-94f6-0b0ce018f896` | `af98e2a3-0997-48b5-96bb-1632a3d46d6e` | `d4c53ad4-a9a2-4d28-91a9-0c4e3c884383` |
| Learning coach | `9d208021-9c6f-44c5-ad5c-0448800a704c` | `852cc46d-13bd-48ed-9f5f-21e7c6791437` | `6fae088c-2245-47aa-82ba-cf48ce7dc8f6` |
| Career advisor | `4e344dc7-e178-4a3d-9d29-22676636a91f` | `6a7c178e-d02e-41c5-b874-2103949eab86` | `f4805c89-7cfe-4592-a413-b0ea7f1715af` |

These identities and the bound volume names are unchanged from preflight. All
three workloads remain Ready; their pod restart counts remain zero. The browser
Deployment/Pod and legacy Herdr claim in namespace `hermes` also retain identity.
Short-lived scheduled backup/recovery Job pods were excluded from restart
comparison because normal Job-history cleanup occurred during observation.
No backup or recovery Job was started by this operation.

ArgoCD adopted the specialists using top-level `argocd.argoproj.io/tracking-id`
annotations, not instance labels. The annotations increased each specialist
Deployment generation from 2 to 3 without replacing pods or changing their
restart counts. Default Hermes generation remains 87; browser generation remains
8. Do not interpret an adoption generation increment alone as a pod rollout.

Bounded settings readback confirms:
- Learning coach: `openai-codex / gpt-6.1-sol`.
- Career advisor: `xai-oauth / grok-4.7`.
- Both retain `clarify` for default and CLI toolsets, with no configured fallback
  provider or MCP server.

No new inference, login, memory retention, publication, messaging or job-submission
test was performed. Prior interactive acceptance remains separate evidence.

## Deliberately untouched

The root `apps` Application remains Healthy / OutOfSync. Its remaining reported
child differences are `herdr`, `hindsight`, `immich`, `kube-prometheus-stack` and
`openclaw`. All unrelated existing Application specs are unchanged from baseline.
No attempt was made to reconcile unrelated workloads, repair Renovate health,
change exclusions, enable automation or remove resources merely to make the root
green. These are outside this task.

## Operational lessons

- A directory move can temporarily show all old resources as requiring pruning
  until the live Application source path is reconciled. Never prune to fix that.
- Review and sync only selected child Application objects when the root contains
  unrelated drift. Recheck their resolved revisions before child adoption.
- Check original Pod UIDs, restart counts and PVC/volume identities after adoption.
  Tracking metadata can increment Deployment generation without a restart.
- Use the supported Kubernetes Application operation workflow when configured
  CLI authentication is unavailable. Do not extract tokens or weaken RBAC.

The local baseline and readback JSON files under `verification/cache/` contain
only public reconciliation metadata. They are ignored diagnostic artifacts, not
credentials or a new runtime subsystem. This record is prepared locally; no new
commit or publication was performed as part of the live reconciliation.
