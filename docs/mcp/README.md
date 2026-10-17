# MCP Connections

This repo configures Codex MCP servers in `.codex/config.toml`.

## Local Bootstrap

Install the repo-declared tools and refresh local secrets before starting Codex:

```bash
mise install
mise run secrets
```

`mise install` provides:

- `uv`, used by the Grafana and AWS MCP servers through `mise exec -- uvx`
- `kubectl`, required by the Kubernetes MCP server
- `aws-cli`, useful for validating the local `default` AWS profile used by AWS
  MCP servers

`mise run secrets` refreshes `.env.local`, which `.mise.toml` loads into the
Codex process environment.

## Configured Servers

| Server | Startup | Required local state |
| --- | --- | --- |
| `kubernetes` | `npx -y kubernetes-mcp-server@latest` | `kubectl` on `PATH` and a valid kubeconfig |
| `grafana` | `mise exec -- uvx mcp-grafana` | `GRAFANA_URL` and `GRAFANA_SERVICE_ACCOUNT_TOKEN` |
| `argocd` | `npx -y argocd-mcp@latest stdio` | `ARGOCD_BASE_URL` and `ARGOCD_API_TOKEN` |
| `aws_iam` | `mise exec -- uvx awslabs.iam-mcp-server@latest --allow-write` | Local AWS `default` profile |
| `aws_s3` | `mise exec -- uvx awslabs.aws-api-mcp-server@latest` | Local AWS `default` profile and AWS API MCP policy |
| `hindsight_homelab` | HTTPS MCP `/mcp/homelab/` | Tailscale access and `HINDSIGHT_API_KEY` |
| `hindsight_reserve` | HTTPS MCP `/mcp/reserve/` | Same token; shared global memory |

## Codex memory

The two Hindsight connections are scoped to this trusted repository through
`.codex/config.toml`. No user-level Codex configuration or other agents are modified.
Both expose only `recall`, `reflect`, and `retain`. Codex consults both banks for
relevant context, following the memory instructions in the root `AGENTS.md`.
Only explicit user requests trigger saves: project decisions go to `homelab`, and
explicitly global decisions go to `reserve`. There are no ingestion hooks or imports.

Supply `HINDSIGHT_API_KEY` in `.env.hindsight.local`, an owner-only (`0600`)
gitignored file, using the existing Hindsight API token. `.mise.toml` loads it
separately from `.env.local`, so `mise run secrets` does not overwrite it. Obtain
credential-access approval before retrieving the Kubernetes Secret; do not print
the token, place it in command arguments, or commit it. After rotation, replace
only this local token and restart Codex from the repository with `mise exec -- codex`.
The file must contain a single `HINDSIGHT_API_KEY=<token>` assignment.

The bank-scoped URLs are routing conveniences, not authorization boundaries:
the token has access to every bank. No additional OAuth login is needed for these
MCP connections. The server's separate subscription login is unrelated.

After initial setup, restart Codex and use `/mcp` to confirm both Hindsight servers
are connected. If either fails, check Tailscale connectivity, the token's presence
in the launching process, and whether the corresponding bank exists. A 401 means
authentication failed; an unavailable bank requires the reviewed bank initializer
to run. Continue ordinary work if memory is unavailable. An accepted `retain`
response means asynchronous storage is pending, not yet verified complete.

This explicit-save setup uses the direct MCP path supported by
[Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), instead of the
automatic retention installed by the
[Hindsight coding-agent package](https://hindsight.vectorize.io/sdks/integrations/coding-agents#-codex-cli).

## Quick Checks

```bash
command -v mise npx
mise exec -- uvx --version
mise exec -- kubectl config current-context
mise exec -- aws sts get-caller-identity --profile default
```

Restart Codex after changing `.codex/config.toml` or after installing missing
tools so the MCP client starts the servers again.
