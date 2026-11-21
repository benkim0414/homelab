# Renovate scheduled-run reliability — 2026-11-21

## Outcome

Renovate's repository-error exit propagation is corrected and deployed. A fresh
controlled cluster run completed repository processing, refreshed Dashboard #71
and created two unique update PRs with no warning/error events. The existing daily
schedule remains enabled. App upgrades and Langfuse recovery remain separate work;
no dependency-update PR was merged or deployed during this repair.

The operator explicitly authorized the remaining Renovate diagnosis, correction
and controlled verification without additional conversational approval. Existing
boundaries on credentials, pruning, force/replace, storage and unrelated schedules
were preserved.

## Historical failure and evidence limits

The first naturally scheduled Job `renovate/renovate-29919900` fired at
`2026-11-20T17:00:00Z` (04:00 Melbourne on 21 November). Kubernetes marked it
successful and its container exited0, but its Renovate repository summary reported
`result=external-host-error`, `exitCode=7`. It did not refresh the Dashboard or open
new PRs. The public package associated with the host error was
`ghcr.io/immich-app/immich-server`, datasource/host type `docker`.

The retained info log does not contain an underlying HTTP status, DNS/transport
code or detailed remote cause. Do not label this as a 429, invalid token, DNS
failure or a fixed network defect without evidence. The same dependency resolved
successfully in the fresh run; the host failure is not currently reproducible.
No credential rotation, registry-auth change, ignored-package rule, abort/error
suppression or speculative networking change was used to make it pass. Historical
Job status was not rewritten. Raw logs remain private in ignored task evidence.

## Root cause of false success and regression proof

Pinned Renovate 44.255.1's
[global worker](https://github.com/renovatebot/renovate/blob/44.255.1/lib/workers/global/index.ts)
propagates the repository result's error code only when the self-hosted option
`exitCodeForErrors` is enabled. Otherwise this warning-level repository failure
can produce process exit0. This is distinct from the remote registry failure.

Set `exitCodeForErrors: true` in the runner ConfigMap, not repository policy.
CronJob logs now default to JSON/info, retaining Forbid concurrency, zero Job
retries, 1800-second deadline and all normal proposal controls. No shell wrapper
or error-hiding policy was introduced.

The real pinned Renovate CLI was exercised using
[check-error-exit.py](../renovate/check-error-exit.py), an isolated synthetic Git
repository, a reserved `.invalid` image registry and an allowlisted environment
without platform credentials:

| Native repository result | Option | Actual process exit |
| --- | --- | --- |
| external-host-error / 7 | false | 0 |
| external-host-error / 7 | true | 7 |

Both cases executed the actual Renovate lookup/global-worker error path; these
are not fabricated registry responses. No GitHub writes occurred in the fixture.
New repository unit contracts guard the global option, structured logging,
schedule and no-retry posture.

The existing live Prometheus `KubeJobFailed` rule covers all namespaces:
`kube_job_failed{job="kube-state-metrics", namespace=~".*"} > 0`, warning after 15m.
With error propagation enabled, a repository error no longer hides behind a
successful process exit. The rule's definition/coverage was verified; no deliberate
failing cluster Job or notification-delivery test was injected. No new alert,
notification integration or schedule was enabled.

## Publication and reviewed deployment

[PR #110](https://github.com/benkim0414/homelab/pull/110) final head
`83a16274d6847da1c1b31d0ccd5a617572951340` passed exact-commit
[Verify CI](https://github.com/benkim0414/homelab/actions/runs/44837726117).
It merged as `5ab77b60e4ae2226592ca23d44d2857864af06ae`, whose
[main CI](https://github.com/benkim0414/homelab/actions/runs/44837928715) also passed.

Local validation passed strict selected-version global config validation,
Conftest 5/5, full repository verification (21 Applications / 520 resources),
188 unit tests with 27 optional skips, diff checks and the native failure fixture.
Those optional local skips are not claimed as exercised tests; required GitHub
verification ran separately and passed.

Reviewed the complete local generated/live resource comparison and Argo resource
inventory: ConfigMap adds only the error option; CronJob adds only LOG_FORMAT and
LOG_LEVEL; SealedSecret spec is identical. Remaining standalone-render differences
were documented API defaults, tracking/last-applied metadata and status, not
permission to remove live ownership. No hooks, storage, RBAC, exposure, images or
credentials change.

A single resource-selective Renovate operation applied only ConfigMap and CronJob,
with revisions in source order:
`[46.447.1, 5ab77b60e4ae2226592ca23d44d2857864af06ae, 5ab77b60e4ae2226592ca23d44d2857864af06ae]`.
Prune/force/replace were disabled. It completed Succeeded and Renovate returned
Synced/Healthy. An immediate JSONPath read initially encountered the old one-entry
env list; subsequent verification-only readback confirmed the completed change.
No second sync was submitted to repair that timing assertion.

## Fresh controlled cluster run

After verifying no active Renovate Job, created `renovate-verify-20261121` from
the corrected CronJob. Only that Job used JSON/debug for private diagnosis; the
declared daily template remains JSON/info. The run used image
`ghcr.io/renovatebot/renovate:44.255.1` with zero retries.

- Job start `2026-11-20T23:38:39Z`; completion `2026-11-20T23:40:46Z`.
- Pod `renovate-verify-20261121-gdmrf`: container exited0, Completed, zero restarts.
- Repository result `done`, status `activated`, exitCode0, processing 115872ms.
- Structured log severity: 1552 debug, 10 info, zero warnings/errors/fatals.
- Real GHCR request statistics recorded 118 requests; the Dashboard again lists
  the Immich server proposal v3.4.1 → v3.4.2 without lookup problems.
- [Dashboard #71](https://github.com/benkim0414/homelab/issues/71) refreshed at
  `2026-11-20T23:40:41Z`; no repository-problem, lookup-failure or config-migration
  section remained in that readback.
- [PR #111](https://github.com/benkim0414/homelab/pull/111): ClickHouse
  26.8.42.13 proposal. It remains open, subject to Langfuse recovery gates.
- [PR #112](https://github.com/benkim0414/homelab/pull/112): PyYAML 6.0.4 proposal.
  It remains open for normal dependency review. Both new PR Verify checks passed
  at the inspected heads; this does not authorize deployment.
- Debug/info event streams each log PR creation, so raw creation-event counts
  duplicate PR numbers. GitHub readback confirmed exactly two unique new PRs.
- Prometheus reports the new Job succeeded=1. Loki counted all 1562 structured log
  entries for the exact Pod in the bounded verification window. No raw logs or
  credential values were published.

The first post-fix controlled run is verified; the next naturally scheduled run
has not yet occurred. This is not a guarantee that public registries never fail.
The correction makes future such repository failures visible as failures rather
than silently accepting incomplete processing.

## Preserved state

CronJob UID remains `4d3bd0b6-6e49-4d58-9847-6ad6ec3a8cf1`, schedule
`0 4 * * *`, timezone `Australia/Melbourne`, suspend=false, concurrency Forbid.
All Application specs and manual policies match the pre-repair snapshot. Every
original PVC UID/volume binding is unchanged. Prometheus remains on k3s-04 with
500m/1536Mi requests and a 2Gi limit. No root sync, app deployment, volume/recovery
artifact cleanup, authentication change or additional automation occurred.

Renovate repair work is complete at this verification point. Queued/rate-limited
updates, review/CI/recovery gates and separately reviewed manual app deployments
remain the intended ongoing workflow—not an uncompleted runner restoration.
