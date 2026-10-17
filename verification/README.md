# Verify

Verification runs locally and in GitHub Actions using the same entry point. It
checks the repository's declared deployment configuration without connecting to
Kubernetes, ArgoCD, a credential store, or the local mise environment.

## Run

Use a dedicated task worktree as required by the root instructions. The supported
environment is Linux x86_64 with Python 3.12 or newer, venv, Git and Bash.
Bootstrap downloads pinned tools from GitHub/get.helm.sh and a hash-locked PyYAML
package from PyPI. Obtain network authorization when required by repository rules.
Caches, isolated tool homes, the virtual environment and reports stay under this
worktree's `verification/` directory and are ignored by Git.

```bash
python3 verification/bootstrap.py
verification/venv/bin/python -m unittest discover -s verification/tests -v
verification/cache/bin/conftest verify --policy verification/policy
verification/venv/bin/python scripts/verify.py --all --base main
```

`--base` accepts an existing local Git commit. The verifier renders that commit
from Git objects without checking it out or executing its scripts. It compares
that desired state with the candidate checkout. Without `--base`, it validates
all selected Applications and reports their resources as additions.

For a network-free structure check, run `scripts/verify.py --offline` with a Python
that has the pinned PyYAML dependency installed. This mode returns **2**, reports
`partial`, and never satisfies the full CI check. Normal verification returns 0
only on success and 1 on failure.

The candidate includes existing tracked and non-ignored untracked files, allowing
checks before staging, including deletions and renames. Reports identify HEAD;
local edits are not represented by that commit until committed. CI uses the
checked-out candidate (GitHub's merge commit for pull requests), and compares it
with the PR base or previous main commit. Manual workflow runs compare against
the merge base with `origin/main`.

## Coverage

- Root Application discovery, multi-document child files, projects, destinations,
  exact chart versions, `$repo` value paths and supported directory globs.
  Applications emitted by other raw sources or charts must be included in root
  discovery; otherwise verification fails rather than leaving their sources unchecked.
- HTTP/OCI Helm charts with release names, namespaces and ordered values from the
  Applications. When set, `valuesObject` replaces inline `values`,
  matching ArgoCD. A second render supplies served CRD APIs declared by selected
  charts, including APIs needed by dependent charts. Unsupported source/Helm
  options fail rather than disappear.
- Selected raw manifests and an explicit inventory of excluded recovery, disabled
  and example manifests. New unclassified manifests and activation of excluded
  files fail.
- Strict Kubeconform validation against the declared K3s Kubernetes version.
  Built-in schemas come from a pinned upstream commit; the CRD resource itself
  uses the matching Kubernetes version's official apiextensions OpenAPI schema.
  Custom schemas are derived
  from the rendered chart CRDs plus the versioned external HelmChartConfig CRD.
  Unknown schemas or unavailable downloads fail rather than silently skip.
- Conftest policies preserve manual sync, block force/replace options and committed
  Secret payloads, preserve Tailscale release identity and monitoring's narrow
  generated-secret ignores. Change-aware checks flag storage removal, identity,
  claim-template and retention changes, and PVC resizing for migration review.
- Gitleaks scans candidate file contents with redacted output, including files
  outside Application paths. Only well-formed SealedSecret ciphertext values are
  filtered from its scan copy; surrounding content remains scanned. One exact
  Hindsight URL expression has a documented false-positive allowlist.
- Actionlint validates the CI workflow. The final `Verify` job requires its
  prerequisite to succeed; failure, cancellation and skipped prerequisites fail.

Summaries in `reports/summary.md` and `reports/summary.json` contain resource
identities and change categories, never raw rendered manifests or Secret values.
GitHub Actions publishes the Markdown in its job summary and uploads only these
two sanitized files as an artifact, retained for seven days, without PR-comment
write permissions. Tool stderr is withheld where it could contain sensitive values.
Secret findings report only rule, file and line. Temporary rendered files are
removed at the end of each operation.

`config.json` records tool versions, the schema commit, excluded files, narrow
normalization rules and exact policy exceptions. Exceptions require `rule`,
`resource`, `reason` and an existing repository `document` describing the migration.
They must match a violation; stale entries fail. Exceptions and policy changes
need explicit review alongside any rollout that changes these safeguards.

## Limits and rollout

CI compares desired configurations; it does not inspect live drift, admission,
external Secret validity, backup success, image architecture support, database
migration compatibility, or application behavior. Helm's available APIs may differ
from the live cluster; API prerequisites remain part of pre-sync review. CRD CEL
and other server-side validations require an authorized live check. Traefik's
embedded values are parsed but its K3s-managed chart is not rendered. New Helm dependencies are downloaded using the declared
chart pins; rendered packages are checked for matching names and versions. Chart versions
are pinned; upstream republishing of an identical version is not prevented by this
layer. GitHub dependencies and Helm downloads must remain available for a clean run.

First establish a passing complete baseline and representative PR runs. Then,
with separate approval for repository settings, require the stable `Verify` status
on `main`, require pull requests and up-to-date branches, and restrict bypasses.
This workflow does not configure repository protection. The pre-sync gate is a
manual procedure, not an ArgoCD authorization control. Follow the
[pre-sync checklist](../argocd/README.md#verification-before-manual-sync) before
deployment.

Research references:

- [ArgoCD Helm inputs and precedence](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
- [ArgoCD multi-source behavior](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/)
- [Kubeconform schema validation and limits](https://github.com/yannh/kubeconform)
- [Conftest policies](https://www.conftest.dev/)
- [ArgoCD server-side diff limitations](https://argo-cd.readthedocs.io/en/stable/user-guide/diff-strategies/)
- [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use)
