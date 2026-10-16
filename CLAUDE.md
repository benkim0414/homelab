# Claude instructions

@AGENTS.md

`AGENTS.md` is canonical for shared repository rules. Follow its routing table
and read applicable nested `AGENTS.md` files for affected components, including
cross-directory edits. Do not maintain a second copy of shared conventions here.

## Claude integration

- Claude MCP servers are configured in `.mcp.json`; use the configured Kubernetes,
  Grafana, and ArgoCD tools for relevant read-only inspection.
- `.mise.toml` loads `.env.local`. Follow `docs/mcp/README.md` for environment
  setup; do not unlock the vault or refresh secrets without authorization.
- `.claude/settings.json` configures the session-start hook under `.claude/hooks/`.
  Claude operational commands live in `.claude/commands/`.
- Optional local context may exist at
  `~/.claude/projects/-home-benkim0414-workspace-homelab/memory/MEMORY.md`.
  Committed runbooks and `docs/solutions/` remain the portable source of lessons.
  Missing local memory must not block work; preserve new lessons in the repo.
