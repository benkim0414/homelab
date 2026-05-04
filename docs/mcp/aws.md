# AWS MCP

This repo configures two AWS Labs MCP servers:

- `aws_iam` uses `awslabs.iam-mcp-server` for IAM users, roles, groups,
  policies, access keys, and policy simulation.
- `aws_s3` uses `awslabs.aws-api-mcp-server` for regular S3 and S3API commands.

The dedicated AWS S3 Tables MCP server is not configured because it targets S3
Tables, not normal S3 buckets and objects.

## Credentials

Both servers use the local AWS profile:

```bash
AWS_PROFILE=homelab
AWS_REGION=ap-southeast-2
```

Keep AWS credentials outside this repository. Configure or refresh the profile
with the AWS CLI or your local credential provider.

## Destructive Operation Guard

The Codex IAM MCP entry enables IAM writes with `--allow-write`, then disables
destructive IAM tools in `.codex/config.toml` where Codex can disable individual
MCP tools. The Claude-style `.mcp.json` IAM entry stays read-only because that
config does not provide a per-tool deny mechanism.

AWS API MCP exposes a generic `call_aws` tool, so S3 destructive command
blocking is handled by the AWS API MCP security policy.

Install the tracked policy locally:

```bash
mkdir -p ~/.aws/aws-api-mcp
cp docs/mcp/aws-api-mcp-security-policy.json ~/.aws/aws-api-mcp/mcp-security-policy.json
```

The policy blocks common destructive S3 and S3API commands while allowing
non-destructive reads and non-delete writes. AWS API MCP policy matching is
exact command-name matching, not wildcard or argument-aware matching, so AWS IAM
permissions on the `homelab` profile remain the primary enforcement boundary.

## Local File Access

`aws_s3` keeps `AWS_API_MCP_ALLOW_UNRESTRICTED_LOCAL_FILE_ACCESS=workdir`, which
restricts file operations to the AWS API MCP server's default workdir. This
supports explicit S3 file operations without giving the MCP server broad
filesystem access.
