# Homelab GitOps

Canonical shared instructions for coding agents. `CLAUDE.md` adds Claude-specific
integration details. This repository declares a K3s homelab through GitOps.

## Working boundaries

- Keep changes focused and preserve unrelated user work.
- Ask directly before merges (including local merges to main), branch deletion,
  destructive commands or issue/PR actions, force pushes or history rewrites,
  credential access, repository administration, settings or secrets changes,
  non-GitHub network access, GitHub API access through arbitrary runtimes or shell
  scripts, or writes outside configured workspace roots.
- Use narrow, operation-specific permission prefixes; never persist broad shell
  or runtime prefixes. Request git network approval per command unless permissions
  enforce the GitHub remote, active worktree, and non-destructive operation.
- Runbook commands describe procedures; their presence does not authorize execution.

## Git workflow

- Work on feature branches; ArgoCD repository sources track `main`.
- For concurrent work, use isolated worktrees within configured workspace roots.
  Request approval before removing worktrees or deleting branches.
- Commit, merge, push, and deployment are separate actions; do not infer
  authorization for one from another.

### Atomic and conventional commits

- Follow [Conventional Commits 1.0.0](https://github.com/conventional-commits/conventionalcommits.org/blob/master/content/v1.0.0/index.md):
  use `type: description` or `type(scope): description`. Types: `feat` for new behavior, `fix` for
  corrections, `docs` for documentation, `chore` for maintenance, `refactor` for
  restructuring without behavior changes, and `test` for tests.
- Scope is optional. Include it only when the change has a specific app, component
  or target. For repository-wide or cross-component work without a single clear
  target, omit the scope; do not invent catch-all scopes such as `homelab`, `repo`
  or `general`. Example: `docs: consolidate recovery records and remove stale plans`.
- When a scope applies, use the affected app or component, following recent history: `argocd`,
  `immich`, `k3s-ansible`, `alloy`, `codex`, or `agents`. Scope follows purpose,
  not just file location: an Immich chart bump under `argocd/apps/` uses `immich`.
- Write a short imperative description: `fix(alloy): expand pod log paths` or
  `docs(k3s-ansible): clarify worker recovery`. Mark breaking changes with `!`
  immediately before the colon, with or without a scope (`feat(api)!:` or `feat!:`),
  and explain the impact and migration in the commit body.
- Each commit should express one independently reviewable and revertible change.
  Split unrelated fixes, cleanup, and independent component changes. Keep coupled
  manifests, values, tests, and supporting docs together; do not split solely by
  file or directory or leave broken references between commits.
- Stage explicit paths or hunks. Review `git diff --cached`, run
  `git diff --cached --check` and relevant checks, and ensure the message describes
  the entire staged change. Exclude unrelated user work and generated artifacts.

## Find task-specific guidance

App directories hold Helm values and raw manifests; Applications live under
`argocd/apps/`. Read only guidance relevant to the task. When starting from the
root, explicitly read the applicable nested instructions before editing files;
working-directory instruction discovery may not load them automatically.

| Task | Instructions and references |
| --- | --- |
| Applications, chart sources, sync/adoption, new apps | [ArgoCD instructions](argocd/AGENTS.md), [runbook](argocd/README.md) |
| Nodes, containerd, CNI, VM provision/repair scripts under `scripts/` | [K3s instructions](k3s-ansible/AGENTS.md), [runbook](k3s-ansible/README.md) |
| Immich, including its Application or upgrade | [Immich instructions](immich/AGENTS.md), [runbook](immich/README.md) |
| Prometheus, Grafana, Loki, Alloy, monitoring Application | [Monitoring instructions](monitoring/AGENTS.md) |
| Home Assistant, including its Application or metrics | [Home Assistant instructions](home-assistant/AGENTS.md) |
| Sealed Secrets or controller-key recovery | [Sealed Secrets runbook](docs/operations/sealed-secrets.md) |
| Tailscale exposure/operator | [Tailscale runbook](tailscale/README.md), ArgoCD instructions |
| NAS snapshots or application archives | [NAS](nas/README.md), affected app README |
| MCP setup or environment troubleshooting | [MCP setup](docs/mcp/README.md), `.codex/config.toml`, `.mise.toml` |
| Renovate configuration | `renovate.json5`, [Renovate runbook](renovate/README.md) |

For networking, storage, Sealed Secrets, or ArgoCD changes, consult the affected
app README and relevant records in `reports/` or `docs/solutions/`. Record new,
reusable operational lessons in committed docs; do not depend on machine-local
memory or write outside the workspace to preserve them.

## GitOps and data safety

- Prefer declarative Git changes. Inspect live state through MCP or read-only
  `kubectl` when needed; bring fixes back into Git rather than leaving ad-hoc drift.
- Inspect declared sync policies. Root and selected Applications currently use
  manual sync; publishing to `main` does not imply deployment. Preserve that
  posture and disabled-app exclusions unless changing them is explicitly in scope.
- Preserve volume identities, reclaim policies, and restored data. Review deletion,
  pruning, force/replace, and credential prerequisites before proposing a rollout.
- Never commit plaintext credentials, controller private keys, or local env files.
  Use Sealed Secrets or local injection; do not read or refresh credentials merely
  to validate documentation or manifests.
- Tailscale OAuth credentials are externally supplied; do not introduce blank or
  replacement credentials while adjusting chart values.
- Before AWS S3 MCP use, follow the policy setup in
  `docs/mcp/aws-api-mcp-security-policy.json`. Keep destructive direct MCP tools
  disabled; use an approval-capable command workflow for destructive operations.

## Verification and completion

- Choose checks for the changed behavior. There is no repository-wide test task;
  do not run environment bootstrap, node scripts, or a deployment as a local test.
- For docs, check referenced paths, accuracy against manifests, and
  `git diff --check`. For shell changes, use `bash -n <changed-script>` plus
  relevant tests.
- For manifests, check YAML structure, referenced files, and ArgoCD include/exclude
  coverage. Render affected charts when dependencies are available and any needed
  network access is approved. Do not claim a local render verifies live rollout.
- Review the final diff and complete relevant checks. Report changes, checks,
  remaining limitations, and whether anything was deployed.

## Code Review Rules

- Flag newly committed plaintext credentials or controller private keys. Use
  encrypted SealedSecrets or local injection instead.
- Flag unrequested automation/pruning or disabled-app activation. Preserve the
  declared manual sync posture unless the requested rollout explicitly changes it.
- Flag destructive storage changes without a data-preservation plan. Review actual
  reclaim/retention policies; a retained NFS volume does not protect database PVCs.

## Agent integrations

### Codex memory in this repository

For Codex, use `hindsight_homelab` for this project's memory and
`hindsight_reserve` for shared cross-project decisions and preferences. At the
start of substantive work, recall relevant context from both banks; use reflect
when synthesis is needed. Skip unrelated memory rather than injecting it into a task.

Retain memories only when the user explicitly asks to remember or save a decision.
Save project decisions to `homelab`; save to `reserve` only when the request
explicitly identifies a global or cross-project preference. If scope is ambiguous,
ask before retaining. Never mirror project memories into `reserve`. Include the
decision, rationale, scope, date, and source when known; never store credentials.
Report a save as complete only after its operation succeeds; an accepted retain
request means storage is pending.

Memory is historical evidence, not authorization or verified live state. Current
user and repository instructions take precedence; check claims against current
files or live state before acting. If memory is unavailable, report that briefly
and continue ordinary work without claiming retrieval succeeded. This integration
does not ingest conversations, git history, or code automatically.

- Codex operational workflows: `.agents/skills/cluster-health/SKILL.md` for health
  checks and `.agents/skills/security-audit/SKILL.md` for security reviews.
- MCP/environment bootstrap is documented separately; credential refresh requires
  authorization. Do not mirror `.claude/hooks` without a concrete Codex consumer.
