# Bounded, honest session-start health checks

The repository's session-start hook provides a quick diagnostic, not a full
health assessment. See the [hook](../../../.codex/hooks/cluster-session-start.sh),
[hook registration](../../../.codex/hooks.json) and
[stubbed checks](../../../.codex/hooks/cluster-session-start.test.sh).

## Maintenance rules and limits

- Keep queries read-only. Wrap calls in a timeout when the local `timeout`
  executable is available; `KUBECTL_TIMEOUT` defaults to `5s` per call. Without
  that executable, the current wrapper has no external timeout.
- Report a failed query as unknown rather than a clean zero. Tooling, VPN, DNS
  or API access failure does not establish a cluster failure.
- Consider readiness and displayed container status as well as pod phase.
  A pod can have phase Running while a container is in CrashLoopBackOff.
  Completed/Succeeded Jobs are excluded from the unhealthy count.
- The ArgoCD summary counts OutOfSync/Degraded only. It does not replace checking
  ComparisonError conditions, manifest generation or full application diffs.

The local shell test substitutes `kubectl`; it covers unhealthy pod counting,
ArgoCD counting and unavailable-query reporting without cluster access. Keep
these failure cases when changing the hook. Implementation belongs in the
script and test rather than duplicated documentation snippets.

## Investigation handoff

Use the [cluster-health skill](../../../.agents/skills/cluster-health/SKILL.md)
for structured diagnostics. Classify findings into repository corrections,
separately approved live recovery, or observations before acting. Separate old
completed Jobs from current failures and local access problems from node issues.
Use explicit SSH configuration and targeted node probes when cluster evidence
points to a node-local problem. Historical health measurements are not a current
baseline, and old unresolved timeout/datasource findings require fresh evidence.
