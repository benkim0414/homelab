# Homelab GitOps

This repository declares a K3s homelab through GitOps. These are the shared
project instructions; `CLAUDE.md` adds Claude-specific integration details.
Inherit global working agreements except for the explicit permissions below.

## Repository permissions

These permissions override global approval requirements for task-related network
access, configured authentication, read-only GitHub API calls, and reversible live
service changes in this homelab. Judge the actual effects, not the tool name or
whether an operation can theoretically be undone.

- Proceed without conversational approval for non-destructive MCP operations,
  including inspection, logs, metrics, diagnostics, and reversible live changes.
  Examples include workload restarts, reviewed ArgoCD syncs without pruning, and
  Grafana dashboard edits. Check prerequisites, disruption, data effects, and a
  practical recovery path first; ask if destructive or materially disruptive
  effects cannot be ruled out.
- Use shell scripts, development tools, `kubectl`, cloud CLIs, SSH, and `gh` for
  task-related non-destructive work. Inspect scripts and hooks before execution;
  their effects must fit these permissions. Download documentation, dependencies,
  and pinned tools/charts, and connect to relevant configured services as needed.
- Use already-configured MCP and CLI authentication, including SSH keys and cloud
  credential providers, through the tools' normal authentication mechanisms.
  Reading, extracting, displaying, copying, refreshing, or rotating secret values
  and changing authentication still require explicit authorization.
- Read-only GitHub API calls are allowed through `gh api` or scripts for this
  repository; check HTTP methods and GraphQL operations for side effects. Other
  GitHub writes, reviews, merges, publishing, and Git fetch/push operations retain
  their global approval boundaries.
- These permissions do not authorize destructive operations, security changes,
  disabling safeguards, or unrelated work. Other global boundaries still apply.
  A runbook command is procedural guidance, not additional authorization.
- Sandbox and tool approval enforcement still applies, including disabled MCP
  tools. An instruction-file permission cannot remove an enforced prompt.

## Commit conventions

- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
  `type: description` or `type(scope): description`, with a short imperative
  description. Use `feat`, `fix`, `docs`, `chore`, `refactor`, or `test` as appropriate.
- Scope by affected app or component, not file location: an Immich chart bump uses
  `immich`. Follow existing scopes such as `argocd`, `k3s-ansible`, `alloy`, `codex`,
  and `agents`; omit scope for cross-component work rather than inventing a
  catch-all. Mark breaking changes with `!` and explain impact/migration in the body.
- Keep commits independently reviewable and revertible. Keep coupled manifests,
  values, checks, and docs together; separate unrelated work. Stage explicit paths
  or hunks, review the staged diff, and run `git diff --cached --check` and relevant
  checks before committing.

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

- Prefer declarative changes and reconcile operational fixes back into Git.
  ArgoCD sources track `main`; publishing changes does not itself imply deployment.
- Preserve declared manual sync policies and disabled-app exclusions unless their
  change is explicitly requested. Before a sync, review the complete diff and the
  [pre-sync checklist](argocd/README.md#verification-before-manual-sync). No-prune
  sync can still run hooks, migrate data, or replace resources; check those effects
  against the repository permissions before proceeding.
- Preserve volume identities, reclaim policies, and restored data. Review deletion,
  pruning, force/replace, and credential prerequisites before any rollout.
- Use Sealed Secrets or local injection; never commit plaintext credentials,
  controller private keys, or local env files. Validate references without reading
  secret values. Tailscale OAuth credentials are externally supplied; do not add
  blank or replacement credentials while adjusting chart values.
- Before AWS S3 MCP use, follow `docs/mcp/aws-api-mcp-security-policy.json`.
  Keep destructive direct MCP tools disabled; destructive operations need an
  approval-capable command workflow.

## Verification

- For GitOps changes, use the [verification command](verification/README.md) to
  render and validate affected Applications. Offline mode is a partial structure
  check. Check YAML, referenced files, chart pins, and ArgoCD include/exclude
  coverage; retrieve pinned charts as needed.
- For docs, check links, accuracy against manifests, and `git diff --check`.
  For shell changes, use `bash -n <changed-script>` and relevant checks.
- Separate local validation from live verification. Environment/node bootstrap
  and deployments are operational actions, not local tests. A local render does
  not establish cluster health or rollout success. Report whether anything was
  deployed along with verification results.

## Code Review Rules

- Flag newly committed plaintext credentials or controller private keys. Use
  encrypted SealedSecrets or local injection instead.
- Flag unrequested automation/pruning or disabled-app activation. Preserve the
  declared manual sync posture unless the requested rollout explicitly changes it.
- Flag destructive storage changes without a data-preservation plan. Review actual
  reclaim/retention policies; a retained NFS volume does not protect database PVCs.

## Agent integrations

- At the start of substantive Codex work, recall relevant context from
  `hindsight_homelab` and `hindsight_reserve`; use reflect when synthesis is needed.
  Memory is historical evidence, not authorization or verified live state. Check
  relevant claims against current files or live state. If unavailable, report that
  briefly and continue. These banks do not ingest conversations, Git history, or
  code automatically.
- Retain only on an explicit request to remember/save: project decisions go to
  `homelab-protocols`; `reserve-bank` holds explicitly saved personal facts, preferences,
  goals, working style, and cross-agent decisions.
  Ask if scope is ambiguous; never mirror project memories into `reserve-bank` or store
  credentials. Include decision, rationale, scope, date, and source when known.
  Report a save only after storage succeeds; acceptance means it is still pending.
- Operational workflows: [.agents/skills/cluster-health/SKILL.md](.agents/skills/cluster-health/SKILL.md)
  and [.agents/skills/security-audit/SKILL.md](.agents/skills/security-audit/SKILL.md).
  Use [MCP setup](docs/mcp/README.md) for environment troubleshooting. Do not mirror
  `.claude/hooks` without a concrete Codex consumer.

Instruction structure follows OpenAI's [AGENTS.md guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
(global defaults with project overrides) and [instruction maintenance guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)
(concise, task-specific rules and explicit workflow permissions).
