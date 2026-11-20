# Renovate restoration — 20 November 2026

## Scope and publication

The operator approved scoped commits/push/PR creation and manual merges after
exact-commit CI, activation of the existing daily schedule, one initial Job, and
reviewed non-destructive app-scoped deployments. No pruning, force/replace,
storage deletion, retained-artifact cleanup, node upgrades, unrelated schedules,
credential rotation or messaging activation was authorized.

[Setup PR #105](https://github.com/benkim0414/homelab/pull/105) merged as
`202b71b027c240186c9419e4e53db4c0b8876896`. Final PR head
`b8a690e61353823f75473e897c64230f1a9f5572` passed
[CI](https://github.com/benkim0414/homelab/actions/runs/44642076296), as did the
[exact merge revision](https://github.com/benkim0414/homelab/actions/runs/44642288432).
The dedicated task worktree is `.worktrees/homelab-scientist-restore-renovate`.
Other worktrees and primary-checkout changes were preserved.

## Established state and previous runner

Initially there was no live Renovate Application, namespace, CronJob,
SealedSecret or generated `renovate-token` Secret. Dashboard #71 was last updated
on 13 October and still listed subsequently closed/merged PRs and a historical
Immich lookup failure. No open PRs existed.

Historical PRs [#67](https://github.com/benkim0414/homelab/pull/67) and
[#68](https://github.com/benkim0414/homelab/pull/68) introduced the in-cluster
ArgoCD-managed runner and token SealedSecret. Historical bot commits match its
configured bot identity, and the current Actions workflow inventory contains no
Renovate workflow. This strongly supports the former cluster CronJob as the
intended runner, but does not independently prove the execution source of every
historical PR. The [rebuild record](../docs/superpowers/plans/2026-10-14-cluster-rebuild.md)
documents that the recovered controller key could not decrypt old Renovate
ciphertext and Renovate remained excluded. The exact last-run/stopping event is
not established by retained runtime evidence.

## Configuration and local validation

- Official chart `46.447.1`, Renovate `44.255.1`; chart artifact digest
  `sha256:e25f058940e33731713f62c12b5be77a516876388f24204ca5877120a54f39ff`.
- Daily `0 4 * * *`, `Australia/Melbourne`, `Forbid`, enabled; manual ArgoCD sync
  and `automerge: false` preserved. Runner targets AMD64 with 250m/512Mi requests,
  2Gi memory limit, 1800-second deadline and zero Job retries.
- Expanded Kubernetes extraction to Gerrit/Langfuse/Herdr; explicit Hindsight
  control-plane, Langfuse web/worker and Loki tag/digest extraction added.
- Herdr custom runtime remains manual digest selection after approved commit-image
  build/smoke checks. Loki chart remains held at 7.3.0. Existing closed/ignored
  updates were not globally reopened. Retired/offsite resources were not enabled.
- Preserved Immich PG16 exact vector-extension suffix, frozen PG14 rollback and
  migration resources, Hindsight PG17 Bookworm; added conservative Langfuse
  datastore and Gerrit release-line/variant rules.
- Strict selected-version config validation and extraction/rule-engine assertions
  passed (160 dependency records after removing diagnostic duplicate regex
  extraction). Token-free local K3s extraction reports token-required, not a
  successful remote lookup.
- Final repository unit suite: 192 tests, six skipped; Conftest: 5/5; full verifier:
  21 Applications and 520 resources; `git diff --check` passed.

Two validation lessons were corrected before rollout: unignored npm files caused
an initial verifier inventory failure (tools moved under ignored verification
cache), and chart truthiness omitted numeric zero for backoffLimit (string `"0"`
was verified to render integer zero). The selected Helm-values extractor ignores
Loki's separate digest field, so Loki uses a scoped custom manager instead.
The initial live run reported one global-config deprecation warning for Boolean
`dependencyDashboard`; the follow-up changes it to `{ enabled: true }` without
another initial Job or changes to repository proposal policy.

## Reviewed live activation

The operator selected a newly sealed candidate privately. Controller validation
passed without retrieving or displaying token values. Renovate's Secret was
staged through a selective child sync, then verified `Synced=True`, type `Opaque`,
owner `SealedSecret/renovate-token`, key name `RENOVATE_TOKEN`.

Root drift was reviewed. Only `renovate.yaml` was removed from its live exclusion;
legacy Honcho/Flannel exclusions were retained. A root operation selected only
`argoproj.io:Application:renovate` at the reviewed merge revision. It succeeded
and registered only Renovate. Herdr registration and OpenClaw raw-selection drift
were not applied. No bulk root sync occurred.

The complete initial Renovate desired/live comparison consisted of additions:
ConfigMap, CronJob and ciphertext SealedSecret; no existing data volumes, hooks,
RBAC, CRDs or service exposure were changed. Namespace creation was performed by
ArgoCD. Both repository sources were explicitly pinned in source order alongside
chart `46.447.1`; prune/force/replace were disabled. Child sync completed and
reported Synced/Healthy at the exact reviewed revisions. The live schedule,
timezone, concurrency policy, image, deadline and zero backoff were read back.

## Single initial Job and actual GitHub effects

Job `renovate/renovate-initial-20261120`, UID
`5e3e667d-5d09-4507-8096-31ead44cbd74`, ran once on `k3s-05`:

- Started `2026-11-20T00:03:36Z`; completed `2026-11-20T00:05:48Z`.
- Pod `renovate-initial-20261120-jg8c7`: Succeeded, exit 0, zero restarts.
- Runtime image ID:
  `ghcr.io/renovatebot/renovate@sha256:183a671d000c8f20f9dac8c3b1100677c1edb79a0b46bcf8798f1490c785d27c`.
- Repository processing finished `activated` / `done`, exitCode 0; 160 dependency
  records across 73 manager-file records. No auth/lookup error was reported.
- [Dashboard #71](https://github.com/benkim0414/homelab/issues/71) refreshed at
  `2026-11-20T00:05:41Z`; stale problems disappeared and real proposals appeared.
- Prometheus reports Job succeeded=1. Loki counted all 14 structured runner log
  entries in the bounded verification window; raw logs were not published.

The enabled daily schedule is verified configuration; a naturally scheduled
04:00 execution has not yet been observed. No second controlled Job was run.

## Resulting PR review and recovery blocker

| PR | Actual change | CI | Disposition |
| --- | --- | --- | --- |
| [#106](https://github.com/benkim0414/homelab/pull/106) | Langfuse Valkey digest `04b9002` → `fcb69df`; public AMD64 image metadata identifies 8.0.12 → 8.0.13 | Verify success at `c4504402315f43aefa981a65148176a4cf7182f3` | Open; blocked pending recovery/outage review |
| [#107](https://github.com/benkim0414/homelab/pull/107) | Langfuse PostgreSQL digest `2ea8630` → `e754b83`; public AMD64 metadata identifies both as `18.7-1.pgdg13+2`, not a new engine major | Verify success at `f85656bee257f3cc981bb5ae4b825e076c022201` | Open; blocked pending recovery/outage review and exact rebuild assessment |

Both public index manifests retain Linux AMD64/ARM64 support. This is registry
metadata, not target-runtime or recovery validation. Both PR diffs change only
the respective image digest. Neither changes declared hooks/RBAC/storage/auth,
but restarting a persistent datastore still has data/availability effects.

[Valkey 8.0.13](https://github.com/valkey-io/valkey/releases/tag/8.0.13) is a
security release with persistence/replication and crash fixes; do not equate an
unchanged floating tag with identical runtime behavior. PostgreSQL's
[18.7 notes](https://www.postgresql.org/docs/release/18.7/) include index-repair
considerations; no REINDEX or repair was attempted. Identical PG_VERSION strings
do not prove identical image contents or OS packages.

There are no live backup Jobs in namespace Langfuse. Its
[coordinated recovery proposal](../langfuse/BACKUP.md) remains explicitly
unimplemented/untested and requires separate confidential-export, outage and
isolated-restore approval. Initial traces being disposable does not automatically
authorize loss of organization/project/key metadata, stable identities or queue
state. Neither PR was merged or deployed. No speculative rollback, migration,
backup export or recovery attempt occurred.

## Per-application disposition from this completed run

"No update identified" below is scoped to current configured extraction and
constraints, not an unconstrained upstream-current or full live-version claim.
Rate-limited proposals remain in Dashboard #71; limits were not bypassed.

| Application | Status |
| --- | --- |
| Renovate | Deployed and verified at 44.255.1 / chart 46.447.1; initial Job complete |
| Langfuse | PRs #106/#107 opened, CI green, blocked on recovery/outage review; chart/web/worker, ClickHouse and objectstore proposals rate-limited |
| Immich | Server v3.4.2 proposal rate-limited; PG16 variant restriction intact |
| OpenClaw | 2026.11.6 proposal rate-limited; pre-existing live/source drift untouched |
| ArgoCD | Chart 10.18.2 proposal rate-limited |
| Home Assistant | Chart 0.3.92 proposal rate-limited |
| kube-prometheus-stack | Chart 93.4.1 proposal rate-limited; live Prometheus placement/resources preserved |
| Alloy | Chart 1.16.0 proposal rate-limited |
| Tailscale | Operator 1.104.7 proposal rate-limited |
| Hindsight | 1.2.3 chart/API/control-plane and PG17 pgvector 0.8.7 proposals rate-limited; historical bootstrap helper also generates a separate major proposal |
| Gerrit | No update identified within reviewed Gerrit 3.14 / proxy 1.28 Alpine lines; migration gates remain |
| Hermes | No image update identified for tracked v0.23.2 runtime/init/browser/backup references |
| Herdr | Custom runtime intentionally manual/held; Debian build-source proposal rate-limited; missing live Argo Application not activated |
| Loki | Chart deliberately held; no runtime update identified for tracked 3.7.10 |
| kube-vip | No update identified for chart 0.11.2 / explicit runtime v1.3.1 |
| MetalLB | No chart update identified for 0.16.2 |
| Sealed Secrets | No chart update identified for 2.22.0 |
| Longhorn | No chart update identified for 1.13.0 |
| Vaultwarden | No chart/server update identified for 0.46.4 / 1.37.5; backup Python proposal rate-limited, live drift untouched |
| Traefik | Bundled with K3s, not independently upgraded; node proposal remains separate |
| Root apps | Registration only; unrelated drift remains, no bulk sync |

K3s `v1.37.2+k3s1`, CI action/runner updates and the disabled Immich offsite rclone
helper are also proposed/rate-limited. They were not deployed or activated.

## Preservation and health limits

Readback compared all existing Application specs against the pre-activation
snapshot: only root discovery changed and Renovate was added. All Applications
remain manual. Every pre-existing PVC namespace/name/UID/volume binding remained
unchanged, including retained rehearsal/rollback claims. All observed PVCs were
Bound and all five nodes Ready. No cleanup occurred.

Prometheus remains on `k3s-04`, requests 500m CPU / 1536Mi memory, memory limit
2Gi, ready with zero restarts at the spot check. This preserves, but does not
repeat, the earlier sustained capacity acceptance. Active alerts included
Watchdog, intentional OffsiteBackupMissing and the retained failed OpenClaw
recovery integrity Job; retained diagnostic failures were not deleted. The
bounded error query was scoped to Renovate/ArgoCD/Langfuse and is not a complete
cluster log audit. No entire-cluster currency claim is made.
