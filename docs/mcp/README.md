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

## Quick Checks

```bash
command -v mise npx
mise exec -- uvx --version
mise exec -- kubectl config current-context
mise exec -- aws sts get-caller-identity --profile default
```

Restart Codex after changing `.codex/config.toml` or after installing missing
tools so the MCP client starts the servers again.
