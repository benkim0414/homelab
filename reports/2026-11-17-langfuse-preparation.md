# Langfuse preparation — 2026-11-17

## Outcome

Local implementation and validation completed in
`/home/benkim0414/workspace/homelab/.worktrees/homelab-scientist-langfuse`, branch
`homelab-scientist-langfuse`, based on `b8ae11c081d71e75c7231a84882a14326faeb893`.
Nothing was committed, pushed, deployed or enabled in an existing Hermes profile.
No real application credentials were generated or read.

Live completion is blocked, not accepted: both configured kubectl and Kubernetes
MCP cannot reach `192.168.0.11:6443` (`no route to host`). Read-only investigation
found this workstation on `192.168.86.0/24`, no advertised homelab subnet route,
and a down Docker bridge claiming `192.168.0.0/20`. The existing Hermes tailnet
HTTPS endpoint returned HTTP 302 and the tailnet suffix was confirmed as
`tailbd291c.ts.net`; this does not establish Kubernetes API reachability.
The operator elected to reconnect/restore routing. No network settings changed.
The final time-bounded Kubernetes version read still failed with the same route
error after local validation.

## Approved scope

The operator approved a tailnet-only `langfuse` service, creating and sealing new
server credentials, arranging owner login privately, metadata-only tracing,
workstation profiles `homelab-scientist` and `default`, and cluster default plus
existing `house-manager`. Initial traces may be disposable; no backup schedules
are authorized. No changes to inference providers/models, OAuth, memory banks,
MCP filters, messaging or schedules were made.

## Implemented artifacts

- `argocd/apps/langfuse.yaml`: pinned official chart 2.2.4, repository sources on
  main, explicit raw selection, manual sync and no cascading-delete finalizer.
- `langfuse/values.yaml`: Langfuse 4.77.0, stable Secret references, private API,
  PostgreSQL, persistent standalone Valkey, no AI gateway or cluster operators.
- `langfuse/clickhouse.yaml`: nonclustered ClickHouse with protected Longhorn PVC.
- `langfuse/objectstore.yaml`: minimal raw SeaweedFS, protected PVC, persistent
  filer metadata, no token/extra capabilities, bounded idempotent bucket hook.
- `langfuse/network-policy.yaml`, `namespace.yaml`, `tailscale-ingress.yaml`:
  namespace isolation and narrow client/web access, no public exposure.
- `langfuse/seal-bootstrap.py`: operator-only private-terminal bootstrap, no
  credential arguments/plaintext files, strict sealing identity validation,
  symlink/overwrite guards and tested publication failure handling.
- `scripts/hermes-langfuse-desktop.sh`: profile-safe launch environment with the
  private URL, metadata capture, sample rate 1 and source/service attribution.
- Hermes Deployment env, raw include selection and narrow web-only egress rule.
  Client Secret is a required pre-rollout prerequisite, not a generated placeholder.
- Static/real-chart/bootstrap/launcher/bucket-hook tests, the operating runbook
  and links from the existing repository/Hermes READMEs.
- A minimal null-empty-Secret report sanitizer fix and regression in the existing
  verifier. Nonempty Secret payload redaction is preserved.

## Evidence-driven corrections to the plan

The bundled SeaweedFS all-in-one chart unconditionally renders an SFTP Secret,
including random passwords and an upstream SSH private-key literal, even with
SFTP disabled. It also defaults to cluster-wide pod-write RBAC. Both were rejected:
the bundled store is disabled and the same SeaweedFS image is declared through
minimal raw resources. No scan exception or broad drift ignore was added.

Valkey now uses Recreate and explicit Argo PVC protection. PostgreSQL selects the
existing no-token application ServiceAccount. An explicit string media-size
setting prevents Helm scientific notation from failing a schema roundtrip.
`mediaUpload.enabled=false` does not enforce a server-side media ban in this
chart; client metadata capture is the privacy control, not that values flag.

All six images were independently checked against anonymous registry manifest
indexes. SHA-256 hashes matched Docker-Content-Digest, AMD64/ARM64 entries exist,
and all runtime/init/hook uses are now digest-pinned. This is registry identity
and architecture evidence, not image-signature verification or runtime testing.

## Local validation — actually executed

- Baseline: 91 tests, OK, 6 skips.
- Final unittest discovery: 117 tests, OK, 6 skips.
- Conftest policy tests: 5 passed, 0 failures, 0 exceptions, 0 skipped.
- Full `scripts/verify.py --all --base main`: passed, 21 Applications,
  512 resources. Schema, policy, source-selection and redacted secret-scan checks
  ran through the repository entry point.
- `bash -n scripts/hermes-langfuse-desktop.sh`: exit 0.
- `git diff --check`: exit 0.
- Real-chart tests prove deterministic repeated renders, no generated credential
  payloads/cluster operators, four Longhorn data claims, private web selectors,
  stable Secret references and immutable workload image references.
- Bootstrap tests use fake credentials and mocked kubeseal only. Launcher tests
  execute the real script with a stub Hermes. Bucket-hook tests execute its shell
  with a stub store, proving idempotence and post-create failure detection. None
  of those stubs are live application evidence.

Unittest skips: Prometheus alert evaluation needs promtool; four aiohttp browser
integration cases run in the browser image; the existing Immich cutover test is
already retired after committed cutover. These are not Langfuse acceptance passes.

## Not verified / remaining gates

- Live node architecture, pressure, allocatable/requested headroom, Longhorn
  disk capacity/health/reclaim policy and current resource ownership.
- Six infrastructure ciphertext manifests and the `hermes-langfuse` client
  ciphertext. They do not exist yet; run the approved private-terminal sealing
  workflow after API access/controller availability is restored. Never publish
  plaintext placeholders or sync the Hermes Deployment with a missing Secret.
- Git publication/CI and reviewed main revision; commit/push still require
  authorization. No local GitOps render is a substitute for that review.
- Actual chart/data-store startup, UID/filesystem behavior, bucket hook execution,
  migrations, valid HTTPS readiness and owner login.
- Creating separate cluster/desktop Langfuse projects and private ingestion keys.
- SDK installation/plugin enablement for the four approved profile instances,
  actual native/browser UI backend enrollment, real root/generation/tool traces,
  profile/source attribution and metadata-only content checks.
- Persistence after web restart, bounded backend-outage behavior and real CNI
  enforcement/denial checks. No trace IDs or live success claims are available.

Resume from the capacity/credential gates in [the runbook](../langfuse/README.md)
once cluster access is restored. Preserve the worktree and all unrelated branches.
