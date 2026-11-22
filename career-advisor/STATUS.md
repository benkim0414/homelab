# Career advisor status

## Fixed native CLI milestone complete

- Worktree: `default-career-advisor-cli`, based on local main
  `260444e18662cf5519842fb1bb53ba7c1b8b771e`.
- Five focused manifest tests passed.
- Full repository verification passed: 22 Applications, 524 resources, including
  schema, policy and secret scanning. This worktree contains Career advisor,
  not the uncommitted Learning coach files in its separate worktree.
- Server dry-run admission passed after creating the new namespace. The first
  combined dry run could not validate namespaced objects because a dry-run
  Namespace does not persist. No validation bypass was used.
- Direct rollout of only `career-advisor/resources.yaml` succeeded. Deployment
  UID `4e344dc7-e178-4a3d-9d29-22676636a91f` is Ready 1/1.
- New 2Gi claim is Bound, UID `f4805c89-7cfe-4592-a413-b0ea7f1715af`, volume
  `pvc-f4805c89-7cfe-4592-a413-b0ea7f1715af`. No existing data or credentials copied.
- Native config commands set `model.default=grok-4.7`,
  `model.provider=xai-oauth`, `toolsets=[clarify]`,
  `platform_toolsets.cli=[clarify]`, `memory.memory_enabled=false`, and empty
  `memory.provider`. Exact selected fields were read back and asserted.
  Fallback providers and MCP servers are absent/empty.
- Native login help works. Pinned public runtime source registers `xai-oauth`
  and its device-code flow with `--no-browser`. Source inspection did not read
  credential files. No agent-started login or inference occurred.
- Default Hermes remains UID `9d4e9fba-b4b1-4b7c-94f6-0b0ce018f896`, generation
  87, Ready 1/1. Learning coach remains UID
  `9d208021-9c6f-44c5-ad5c-0448800a704c`, generation 2, Ready 1/1. These match
  this task's initial live baseline. No command changed either workload.
- No Service, ingress or additional access channel was created.
- Application file prepared locally only. No commit, push, ArgoCD registration
  or root sync was performed.

## Interactive advice and controlled restart

The user reported successful native private-terminal login and provided the
two-turn career advice transcript from the prescribed CLI invocation. The
initial reply supplied three interview preparation topics. Its follow-up turned
the second topic into a pod-debugging exercise. Both replies were nonempty and
the second retained the first turn's context. This is user-supplied execution
evidence, not independent attestation of the provider's internal model identity.

One controlled restart of only Career advisor completed successfully. The pod
UID changed from `418b9598-7048-48d1-9ad6-d185f2ce7b88` to
`6a7c178e-d02e-41c5-b874-2103949eab86`; the replacement is Ready.
The same PVC UID and volume remain Bound. Selected configuration fields were
read back: `xai-oauth / grok-4.7`, clarification-only toolsets, memory disabled,
empty external memory provider, and no fallback providers or MCP servers.
Default Hermes and Learning coach retain their initial task UIDs, generations
and Ready replica counts.

The user supplied the final post-restart CLI reply: a Kubernetes troubleshooting
interview question and a nonempty explanation of what an answer should cover.
No further login was reported or requested. This completes the fixed milestone:
isolated Ready workload, native subscription login, career advice with contextual
follow-up, and another successful reply after one controlled restart.

The sample answer is not a technical correctness benchmark. In particular,
readiness probes do not restart containers; liveness and startup probes can.
No additional acceptance tests or deferred features are being added.

Use the commands and fixed acceptance in [README.md](README.md). Stop on
unavailable model or denied OAuth inference. No API-key fallback is authorized.
Do not expand into custom authentication or response parsing. The official
image's pnpm synchronization warning is present, as with Learning coach.

## Unchanged deferred work

No automatic memory retention, memory bank provisioning, Gerrit publication,
job application submission, email, Discord, desktop connector or cross-agent
sharing was enabled. Historical pilots and safeguards were left untouched.
