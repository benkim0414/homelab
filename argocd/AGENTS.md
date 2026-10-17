# ArgoCD instructions

Use [the runbook](README.md) for bootstrap, adoption history, and operational
procedures. Inspect manifests for current desired state rather than treating
historical rollout notes as live status.

## Application changes

- Use a Helm source plus this repository with `ref: repo` for `$repo` value files;
  add a repository path source when raw manifests are needed. Not every app has
  three sources. Preserve repository revisions on `main` and existing chart pins.
- Raw manifests must be covered by the Application's `directory.include` glob.
  Check coverage whenever adding storage, SealedSecrets, rules, or ingresses.
- Renovate is selected by the root and uses manual sync. Flannel cleanup is
  retired; do not reintroduce its unsafe lease-deletion automation. Review
  `apps.yaml` selection as well as child Applications when adding an app.
- For a new app, add its values/raw manifests and Application together. Check its
  AppProject, namespace, chart identity, value-file paths, and raw-file selection.
- ArgoCD manages itself through `apps/argocd.yaml`, including its Tailscale ingress.
  Self-management does not imply automated sync. Preserve manual sync policies;
  introducing automated sync or pruning requires explicit rollout review.
- Adoption must preserve Helm release identity, chart versions, external Secrets,
  and data volumes. Keep `helm.releaseName: tailscale-operator` for Tailscale.
  Review a complete generated-to-live diff before proposing a sync; matching
  chart versions alone does not guarantee a rollout-free adoption.

## Review and verification

- Use `apps/immich.yaml` as a pinned-chart example, but verify chart/image
  compatibility with [Immich instructions](../immich/AGENTS.md).
- For generated Secrets, narrowly ignore only generated data fields and dependent
  workload `checksum/secret` annotations. Preserve `RespectIgnoreDifferences=true`;
  see `apps/monitoring.yaml`. Do not hide unrelated drift or export secret values.
- Read [monitoring instructions](../monitoring/AGENTS.md) for monitoring changes.
- Check every `$repo` value path, raw manifest glob, chart pin, and AppProject.
  Render locally when possible; remote chart retrieval needs network approval.

## Code Review Rules

- Flag new raw manifests omitted from their Application include glob or blocked by
  root discovery. Update selection deliberately; keep disabled apps excluded unless
  activation is requested.
- Flag chart recovery commands that omit or differ from the Application pin. Use
  its declared version unless an upgrade is explicitly in scope.
- Flag removal/pruning plans that assume manual sync protects data. Registration,
  sync, pruning, and deletion are distinct: review finalizers and deletion mode,
  and preserve database PVCs whose backing volumes use reclaim policy Delete.
