# Renovate

Renovate is selected by the root Application in `argocd/apps.yaml`. Its Application
uses the pinned official Renovate Helm chart and manual sync. Publishing these
manifests does not establish that Renovate is running. Review root drift, align
only its discovery selector when needed, and register only the Renovate child
through a resource-selective operation. Do not bulk-sync unrelated pending
children. Review and sync Renovate separately after verifying its token
prerequisite. Neither sync should use pruning or force replacement.

## Update detection decisions

`renovate.json5` is repository policy; the chart's config selects this repository
and requires that policy to exist. The CronJob runs daily at 04:00 in
`Australia/Melbourne`, including daylight saving changes, and uses
`concurrencyPolicy: Forbid` to prevent overlapping runs. Repository policy has no
monthly update windows, ignores unstable releases, separates major upgrades from
minor/patch proposals, and explicitly disables automerge. Normal Renovate PR
limits can spread an initial backlog across multiple daily runs; inspect the
Dependency Dashboard for pending updates and lookup failures.

| Dependency | Detection and review |
| --- | --- |
| Helm charts | ArgoCD sources under `argocd/`, including OCI charts and Renovate itself |
| Runtime and backup images | Kubernetes manifests in app directories, including Gerrit and Langfuse; existing digests remain pinned |
| Helm runtime overrides | Helm-values extraction plus scoped Hindsight control-plane and Langfuse web/worker regex managers; explicit overrides must be reviewed with chart proposals |
| Herdr | Extracted for inventory but updates disabled: build/smoke-test an approved commit image and select its digest manually for init and runtime containers; there is no latest-tag policy |
| Immich, kube-vip and Vaultwarden values tags | Custom regex managers provide the image repository omitted from values |
| K3s | Custom regex manager tracks `k3s_version` in the Ansible inventory through `k3s-io/k3s` GitHub releases, including `+k3s` revision updates |

Chart and image changes are grouped per app for Immich, Hindsight, kube-vip and
Vaultwarden. Unrelated infrastructure and monitoring charts get independent PRs.
Hindsight PostgreSQL updates have their own group, covering both the database and
backup image/digest. Immich database and backup images remain in the Immich group.
Grouping provides a joint review, not proof that two versions are compatible.

Immich has completed its PostgreSQL 16 cutover; see the
[migration runbook](../immich/migration/README.md). Active database and backup
images track PostgreSQL 16. The retained PostgreSQL 14 rollback workload and
manual migration manifests remain frozen.

Database rules preserve Immich PostgreSQL 16 with its exact VectorChord/pgvectors
extension suffix, and Hindsight PostgreSQL 17 with the Bookworm suffix. Engine
major, extension-variant and OS-variant migrations require a separate plan and
policy update. Proposals must keep database and pg_dump images aligned and verify
a recent successful backup before rollout. Current allowed tags can legitimately
produce no version update; inspect the dashboard rather than assuming a pin is
untracked.

Langfuse PostgreSQL remains on major 18 without an OS-variant switch, Valkey on
8.0, ClickHouse on 26.8, and SeaweedFS on major 4. Database proposals are separate
from Langfuse chart/web/worker proposals. Gerrit proposals stay on 3.14 and its
proxy on 1.28 Alpine; review declared site version/config regeneration, Java,
Gitiles, schema/reindex and cold-site recovery before deployment. Langfuse
rollouts require its documented coordinated recovery/disposable-data review.
These constraints propose updates, not permission to migrate data.

Loki's chart remains deliberately held at 7.3.0; runtime images remain tracked
separately. See the [Loki upgrade gates](../monitoring/UPGRADE-loki-3.7.md).
Respect closed/ignored updates; do not set a global recreate policy or recheck
all dashboard entries to bypass those decisions.

K3s upgrades are separate proposals; review the
[K3s runbook](../k3s-ansible/README.md), supported upgrade path and version skew
before an independently authorized node upgrade. Traefik comes bundled with K3s
and has no independent chart pin here. A merged inventory version does not run
Ansible or upgrade nodes.

Example manifests are excluded. Recovery helpers and manifests excluded from
ArgoCD, such as Immich's offsite backup job, may still have their image pins
tracked; updating a pin does not activate those resources. Preserve their
separate activation and credential requirements.

Review proposed chart and server image versions together; a chart's appVersion
label does not override an explicitly pinned image. An earlier stale Vaultwarden
pin caused client login compatibility problems. Review release notes and app
runbooks before merging any upgrade, then review the ArgoCD diff and explicitly
sync that app. Renovate updates Git; it does not deploy cluster workloads.

The chart pin was verified against the
[official release](https://github.com/renovatebot/helm-charts/releases/tag/renovate-46.447.1).
It runs Renovate 44.255.1. Use that same version for configuration/extraction
validation. Runs use the AMD64 worker, bounded memory, a 30-minute deadline and
no automatic Job retry. Investigate a failed run before authorizing another.

### Failure reporting

The self-hosted runner sets `exitCodeForErrors: true` and JSON info logs.
Renovate 44.255.1 otherwise logs a repository `external-host-error` with an
internal exitCode of 7 but can still exit the process with 0. Kubernetes then
marks the Job successful even though lookup/update processing did not complete.
Do not disable host-error detection or ignore a dependency to manufacture success.

Reproduce the native behavior with an isolated, credential-free synthetic Git
fixture and the reserved `.invalid` registry (no GitHub writes):

```bash
python3 renovate/check-error-exit.py /absolute/path/to/pinned/renovate
```

This must observe repository error 7 in both cases, process exit0 with the option
disabled and process exit7 with it enabled. The normal repository unit tests also
guard the declared error/logging option, schedule and zero-retry contract.
An actual failed run now becomes a failed Kubernetes Job; inspect the existing
`KubeJobFailed` Prometheus rule as well as structured repository results. Preserve
failed Jobs/log evidence and investigate before a separately authorized run.

## GitHub Token

The CronJob expects a Kubernetes Secret named `renovate-token` in the `renovate` namespace with a `RENOVATE_TOKEN` key. Do not commit a plaintext Secret.

With explicit authorization, create the SealedSecret using an approved GitHub
token. Follow the [Sealed Secrets runbook](../docs/operations/sealed-secrets.md).
Prepare a restricted local env file containing `RENOVATE_TOKEN` outside tracked
files; do not put the token in shell arguments or history. Replace the example
input path below:

```bash
kubectl create namespace renovate --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic renovate-token -n renovate \
  --from-env-file=path/to/local-renovate-token.env \
  --dry-run=client -o yaml \
  | kubeseal \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      --format yaml > renovate/sealed-secret.yaml
```

Commit `renovate/sealed-secret.yaml` after confirming it contains only encrypted data.

## Validation

Before first activation, check the existing SealedSecret's synchronization status
and the generated Secret's metadata/key names using an approved workflow. Do not
print or decode the token to validate manifests. The encrypted file's presence
does not prove the controller can decrypt it or that its GitHub token is valid.
If recovery or rotation is needed, obtain separate credential authorization.

Validate repository policy with `renovate-config-validator --strict renovate.json5`.
A local Renovate extraction check should use `--platform=local --dry-run=extract`
and an explicit `RENOVATE_CONFIG_FILE` pointing to this repository's
`renovate.json5`; inspect extracted charts, images, K3s and grouping/compatibility
rules. Local extraction does not establish registry availability, token validity
or a successful GitHub run. External lookups and tool downloads require network
approval under repository working agreements.

Keep validation dependencies under ignored `verification/cache/`, not an
unignored top-level npm directory (the repository verifier inventories untracked
files). With Renovate 44.255.1 installed under
`verification/cache/renovate-tools`, run:

```bash
verification/cache/renovate-tools/node_modules/.bin/renovate-config-validator --strict renovate.json5
LOG_FORMAT=json LOG_LEVEL=debug RENOVATE_CONFIG_FILE="$PWD/renovate.json5" \
  verification/cache/renovate-tools/node_modules/.bin/renovate \
  --platform=local --dry-run=extract > verification/cache/renovate-extract.jsonl
node renovate/check-extraction.mjs verification/cache/renovate-extract.jsonl \
  verification/cache/renovate-tools/node_modules
```

The assertion script exercises the selected version's actual rule matcher,
including image/digest extraction, database variants and disabled proposals.
Local extraction without a token reports a GitHub-token-required skip for K3s;
that is not an authenticated lookup result. Loki uses a scoped regex because
this version's Helm-values extractor ignores its separate `digest` field.

After an approved rollout, confirm the CronJob and its timezone, then inspect the
latest run (wait for the scheduled run, or obtain approval for a one-off Job):

```bash
kubectl get cronjob -n renovate
kubectl get jobs -n renovate --sort-by=.status.startTime
kubectl logs -n renovate job/<job-name>
```

Confirm the Job completes, lookup/authentication errors are resolved, and the
GitHub Dependency Dashboard and expected update proposals appear. Do not treat
an empty PR list as proof that all apps are current. Record local validation and
live rollout results separately.
Inspect the structured `Repository finished` result and process termination in
addition to Job status. Retain raw logs privately and report only projected
error category, affected public package/host, exit code and outcome. A natural
schedule firing is not proof that repository processing succeeded.
