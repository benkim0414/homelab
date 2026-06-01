---
title: Codex Session Hook Health Checks
date: 2026-06-01
category: developer-experience
module: Codex local configuration
problem_type: developer_experience
component: tooling
severity: low
applies_when:
  - "Maintaining repo-local Codex hook configuration"
  - "Adding startup diagnostics that call cluster tools"
  - "Keeping agent startup checks useful without making sessions brittle"
tags: [codex, hooks, kubectl, startup-checks, developer-experience]
---

# Codex Session Hook Health Checks

## Context

The repo emitted this warning at Codex startup:

```text
⚠ `[features].codex_hooks` is deprecated. Use `[features].hooks` instead.
```

The repo also had a `SessionStart` hook in `.codex/hooks.json` that ran
`.codex/hooks/cluster-session-start.sh` on startup and resume. The hook was
useful because it surfaced cluster context before GitOps work, but its health
signal was too optimistic: it counted only pods whose phase was not
`Running` or `Succeeded`, so common container failures like `CrashLoopBackOff`
could be missed when the pod phase stayed `Running`.

## Guidance

Keep the session-start hook, but make it bounded and honest:

- Use `[features].hooks = true` in `.codex/config.toml`.
- Keep hook commands read-only.
- Wrap cluster queries in a short timeout so Codex startup does not hang when
  kubeconfig, DNS, VPN, or the API server is unavailable.
- Report failed cluster queries as `unknown`, not `0`.
- Count unhealthy pods from the tabular `kubectl get pods -A --no-headers`
  output by considering both phase and readiness.

The key config change is intentionally small:

```toml
[features]
hooks = true
```

The hook script now centralizes `kubectl` invocation:

```bash
KUBECTL_TIMEOUT=${KUBECTL_TIMEOUT:-5s}

kubectl_read() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "${KUBECTL_TIMEOUT}" kubectl "$@"
  else
    kubectl "$@"
  fi
}
```

The unhealthy pod count treats non-running phases and not-ready running pods as
unhealthy, while ignoring completed work:

```bash
UNHEALTHY=$(printf '%s\n' "${UNHEALTHY_RAW}" | awk '
  function ready_ok(value) {
    split(value, parts, "/")
    return parts[1] == parts[2] && parts[2] != "0"
  }

  $4 == "Completed" || $4 == "Succeeded" { next }
  $4 != "Running" || !ready_ok($3) { count++ }
  END { print count + 0 }
')
```

For regression coverage, add a small shell test that stubs `kubectl` instead
of depending on a live cluster. The test should cover at least two cases:

- A `CrashLoopBackOff` pod and a `Pending` pod are counted as unhealthy.
- Unavailable `kubectl` reports `unknown (kubectl unavailable)` for pod and
  ArgoCD checks.

## Why This Matters

Startup hooks are valuable only if they are fast and trustworthy. A hook that
hangs makes every Codex session feel broken. A hook that reports failed queries
as `0` or misses `CrashLoopBackOff` gives false confidence before making
GitOps changes.

Treating the hook as a small tested tool keeps the startup signal useful
without turning it into a dependency on live cluster availability.

## When to Apply

- When a Codex feature flag deprecation points at a repo-local config key.
- When hook output summarizes cluster or deployment health.
- When a hook runs automatically on startup, resume, pre-tool, or pre-commit
  events.
- When a health check depends on tools that may be unavailable locally.

## Examples

Before:

```bash
UNHEALTHY_RAW=$(kubectl get pods -A --no-headers \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  2>/dev/null || true)
```

This can miss failing containers and silently collapse query failure into a
clean count.

After:

```bash
if UNHEALTHY_RAW=$(kubectl_read get pods -A --no-headers 2>/dev/null); then
  # Count phase and readiness problems.
else
  UNHEALTHY="unknown (kubectl unavailable)"
fi
```

This separates "no unhealthy pods" from "the check could not run."

## Related

- `.codex/config.toml`
- `.codex/hooks.json`
- `.codex/hooks/cluster-session-start.sh`
- `.codex/hooks/cluster-session-start.test.sh`
