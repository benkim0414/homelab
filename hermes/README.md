# Hermes profiles

This directory groups the repository configuration for three Hermes roles.
Here, "profile" means repository organization, not a shared Hermes process,
credential store, session database or persistent volume.

| Role | Repository directory | ArgoCD Application | Runtime namespace |
| --- | --- | --- | --- |
| House manager / existing default Hermes | [profiles/house-manager](profiles/house-manager/README.md) | `hermes` | `hermes` |
| Learning coach | [profiles/learning-coach](profiles/learning-coach/README.md) | `learning-coach` | `learning-coach` |
| Career advisor | [profiles/career-advisor](profiles/career-advisor/README.md) | `career-advisor` | `career-advisor` |

Applications remain under `argocd/apps/`. Each selects only its own profile
manifests. House manager retains its existing split manifest files and tools;
the specialists each retain `resources.yaml`. This avoids changing generated
ConfigMaps, checksums or live resources merely to standardize filenames.

## Preserved runtime boundaries

The directory reorganization does not rename Kubernetes resources, namespaces,
claims, Secrets or Applications. It does not change image pins, provider/model
selection, tool permissions, manual sync policies or credential custody.
House manager remains the existing default Hermes deployment with its existing
integrations. The two specialist workloads retain their independent state and
native CLI access. No native runtime profiles are created or merged here.

Specialist memory integration, Gerrit publication, job submission, messaging,
desktop delegation and additional channels remain deferred. Existing House
manager capabilities are neither removed nor granted to the specialists.

[shared/](shared/README.md) is reserved for genuinely shared repository material.
There is no new shared runtime asset. The runtime-context overlay remains under
House manager's `tools/runtime_context/` because it is specific to that role.

## Source migration

- `hermes/<existing file>` moved to `hermes/profiles/house-manager/<same file>`.
- `hermes/house-manager-tools/` moved to `hermes/profiles/house-manager/tools/`.
- `career-advisor/` moved to `hermes/profiles/career-advisor/`.
- Completed Learning coach files were imported from its original task worktree
  into `hermes/profiles/learning-coach/`. The original worktree is untouched.

The profile status records describe their original acceptance observations.
Historical evidence retains original paths and identifiers. Repository directory
names do not change paths inside containers or records of previous operations.

The reorganization itself did not perform live rollout or sync. Subsequently,
the user authorized scoped GitOps reconciliation. All three Applications were
verified Synced/Healthy at the published layout revision, with original pods and
claims preserved. See [the reconciliation record](GITOPS-RECONCILIATION.md).

Future reconciliation still needs its own authorization and complete diff review
without pruning, force or replacement. Preserve all existing claim identities.
