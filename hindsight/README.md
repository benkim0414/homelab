# Hindsight shared memory

Hindsight provides a shared global bank named **`reserve`** for explicitly requested
cross-project decisions and preferences. It starts empty. Agent installation and
per-project banks are separate work; no conversation import is enabled here.

## Deployment

| Component | Configuration |
| --- | --- |
| Namespace / ArgoCD Application | `hindsight`, manual sync |
| Hindsight | Official chart and API/UI images `0.10.3` |
| API | One replica, `Recreate`, one internal worker, stable ID `hindsight-api` |
| Model | `openai-codex`, explicitly `gpt-5.6-luna`, no paid API fallback |
| Embeddings / reranking | Local BGE small / MiniLM, 5 GiB Longhorn cache |
| PostgreSQL | pgvector 0.8.1 / PostgreSQL 17 Bookworm, pinned multiarch digest |
| Database | `hindsight-postgres-data`, 20 GiB Longhorn |
| Subscription credentials | `hindsight-codex-auth`, 1 GiB Longhorn |
| API | `https://hindsight-api.<tailnet>.ts.net`, REST and MCP |
| Administration UI | `https://hindsight.<tailnet>.ts.net` |
| Backups | NAS `/k3s-storage/hindsight/backups/scheduled`, 14 successful dumps |

The chart's API Deployment cannot configure a rollout strategy. `api.yaml`
therefore supplies the API and Service while the official chart supplies the UI.
The API uses `Recreate` to avoid overlapping credential owners and RWO mounts.
Single replicas mean upgrades and node failures can temporarily interrupt access.

The existing Longhorn class supplies two storage replicas. Database/auth PVCs have
ArgoCD `Prune=false,Delete=false` annotations, but their underlying class has reclaim
policy **Delete**: direct PVC or namespace deletion can still destroy data. NAS
`Retain` protects only the backup PV. The 20 GiB NFS capacity is not a NAS quota.

## Credentials and trust

Create these three Secrets via the [Sealed Secrets workflow](../docs/operations/sealed-secrets.md).
Only the encrypted manifests belong in `sealed-secret.yaml`, which the Application
already includes. Do not sync until these prerequisites are supplied.

| Secret | Key | Value |
| --- | --- | --- |
| `hindsight-db-credentials` | `POSTGRES_PASSWORD` | Fresh random hexadecimal database password, safe in a connection URL |
| `hindsight-api-credentials` | `HINDSIGHT_API_TENANT_API_KEY` | Fresh random API bearer token |
| `hindsight-ui-credentials` | `HINDSIGHT_CP_DATAPLANE_API_KEY` | Same API token, used server-side by the UI |

The API's tenant extension authenticates both REST and MCP. Do not enable
`HINDSIGHT_API_TENANT_MCP_AUTH_DISABLED` or add a legacy MCP token bypass.
This initial setup uses one trusted-user credential with access to all banks;
bank names and bank-scoped MCP URLs are not authorization boundaries.

The UI proxies administrative requests using its server-side API credential.
**Anyone who can reach the UI can administer the memory service.** Confirm tailnet
access is limited to trusted users before exposing it. There is no public ingress,
Funnel, LAN LoadBalancer, or direct database exposure in these manifests.

The OAuth grant is separate from these static Secrets. It must remain writable
because Hindsight refreshes and atomically replaces tokens. Never seal and remount
a stale OAuth snapshot on every restart. Never share a grant with interactive Codex.
Database backups do not back up this grant; recover it by a fresh login. Treat any
volume backups containing it as credentials, and do not revive old rotating tokens.

## First rollout

These steps require the repository's operation-specific approvals; their presence
is not authorization. Prepare changes on a feature branch, render/review them, and
publish to `main` only through the separately approved Git workflow.

1. Verify capacity, Longhorn health, AppProject permissions, and availability of
   the three pinned images for both ARM64 and AMD64. Check that the two chosen
   Tailscale names are unused and review who can access the UI.
2. Create only `/storage/k3s/hindsight/backups` on the NAS with owner `999:999`, mode
   `0700`, under the existing export. Do not change other directories or exports.
   Verify effective NFS ownership; the backup Job runs as UID/GID 999.
3. Generate/seal the static credentials without printing them, and review the
   resulting encrypted manifests. Do not place plaintext in Git or shell arguments.
4. Bootstrap the namespace and **only** the `hindsight-codex-auth` PVC from the
   reviewed storage manifest. Keep the API stopped until login is finished.
5. Apply `bootstrap-login-pod.yaml` manually. It is deliberately excluded from
   ArgoCD. This temporary ARM64 pod mounts the credential PVC at its normal
   `/home/hindsight/.codex` directory and expires after one hour.
6. Download the pinned official Codex CLI ARM64 binary into a workspace-local,
   ignored staging directory, copy it into the pod, and complete the dedicated login:

   ```sh
   mkdir -p .git/hindsight-validation/codex
   curl -fL https://github.com/openai/codex/releases/download/rust-v0.163.0/codex-aarch64-unknown-linux-musl.tar.gz \
     -o .git/hindsight-validation/codex/codex.tar.gz
   tar -xzf .git/hindsight-validation/codex/codex.tar.gz -C .git/hindsight-validation/codex
   kubectl -n hindsight cp .git/hindsight-validation/codex/codex-aarch64-unknown-linux-musl \
     hindsight-subscription-login:/tmp/codex
   kubectl -n hindsight exec -it hindsight-subscription-login -- \
     /tmp/codex -c 'cli_auth_credentials_store="file"' login --device-auth
   ```

   Approve the displayed device flow in your browser. Do not print `auth.json`.
   Verify the file exists and is owner-only. Hindsight uses
   `HINDSIGHT_API_LLM_CODEX_HOME=/home/hindsight/.codex`; the login pod uses that
   same location naturally, without changing this workstation's Codex home.
7. Remove the temporary login pod with approval and wait for its volume to detach.
   Publish the reviewed repository changes with approval. Sync the root Application
   to register Hindsight, then review and sync Hindsight **without pruning or force**.
   Normal ArgoCD sync runs the PostSync `hindsight-initialize-reserve` hook.
8. Verify the acceptance checks below. Model-name recognition and HTTP health do
   not establish subscription entitlement: retain and reflect must actually work.

Network use during rollout includes image registries, Hugging Face model downloads,
OpenAI login/inference/refresh, the NAS, and Tailscale endpoints. Obtain the required
network approval before performing those operations. There is no fallback to a
billable API provider when subscription limits or authentication fail.

## Agent connections

Use the API endpoint with `Authorization: Bearer <token>` for REST. A safe Python
example reads an injected token rather than putting it in shell command arguments:

```python
import os
from hindsight_client import Hindsight

client = Hindsight(
    base_url=os.environ["HINDSIGHT_API_URL"],
    api_key=os.environ["HINDSIGHT_API_KEY"],
)
result = client.recall(bank_id="reserve", query="What preferences apply to this task?")
```

MCP clients can use `https://hindsight-api.<tailnet>.ts.net/mcp/reserve/` with the
same bearer authentication. Obtain the real hostname from the Ingress status.
Never use the administration UI hostname as an API URL.

For future Hermes project-plus-global recall, install its Hindsight plugin and
select `memory.provider: hindsight`. Its profile-local `hindsight/config.json`
can contain:

```json
{
  "mode": "local_external",
  "api_url": "https://hindsight-api.<tailnet>.ts.net",
  "bank_id": "hermes-unscoped",
  "bank_id_template": "project-{project}",
  "recall_additional_banks": ["reserve"],
  "auto_recall": true,
  "recall_prefetch_method": "recall"
}
```

Supply the API token through the agent's secret/environment mechanism. Explicit
bank mappings are needed for repositories with colliding names. Avoid this dynamic
profile outside a Git project, where the template's empty project placeholder can
resolve to a generic bank. `additional_banks` would mirror writes, so do not put
`reserve` there. Hermes reflect uses only the primary bank.

Save a global decision through a tool explicitly targeting `reserve` only when the
user requests it. Include its scope, date, and source. The bank's mission guides
extraction; it does not enforce user authorization. Keep mandatory rules in
`AGENTS.md`. Other coding-agent connectors need their own tested dual-bank recall
wiring; this deployment does not install them or enable automatic ingestion.

## Acceptance and operations

- All workloads become ready, PVCs bind, and startup downloads finish without OOMs.
  `/health/live` is liveness; `/health` also checks database readiness.
- Protected REST and MCP operations reject absent/wrong bearer tokens. Valid
  credentials work from this machine and an in-cluster client over the intended
  endpoints. Health endpoints may intentionally be unauthenticated.
- The UI works, and browser responses/assets do not disclose the server API token.
- The initializer creates `reserve` with zero memories, preserves an existing bank
  on subsequent syncs, and fails rather than overwriting it on authentication errors.
- Use a separate validation bank: retain a unique harmless fact, wait for extraction,
  recall it from a second client, and reflect over it. Confirm database persistence
  after an API restart and writable OAuth refresh persistence. Leave `reserve` empty.
- Run a manual backup Job, verify its archive, and restore it into a separate test
  database to check the validation fact and bank configuration. Cleanup requires
  explicit approval; never restore over the live database for this test.
- Inspect operation failures, subscription quota/authentication errors, pod restarts,
  API `/metrics`, and backup Job failures. Existing Alloy collects pod logs.

The backup runs at 02:30 Australia/Melbourne, before the NAS's 03:45 snapshot. It
publishes a custom-format dump only after `pg_restore --list` succeeds, then keeps
the newest 14 matching dumps. Failed dumps do not trigger retention. NAS snapshots
do not guarantee a job finished and do not survive loss of the NAS pool.

For recovery, stop clients/API, restore into a fresh PostgreSQL 17/pgvector database
with `pg_restore --exit-on-error --no-owner --no-acl`, verify it, then switch over
through reviewed Git configuration. Obtain explicit approval before replacing any
existing database. Restore static credentials through Sealed Secrets; repeat the
dedicated login if OAuth credentials are unavailable or invalid. Do not downgrade
Hindsight against a migrated schema without a compatible database restore.

## References

- [Hindsight installation](https://hindsight.vectorize.io/developer/installation)
- [Subscription authentication and isolation](https://hindsight.vectorize.io/developer/models)
- [Pinned chart source](https://github.com/vectorize-io/hindsight/tree/v0.10.3/helm/hindsight)
- [Hermes plugin configuration](https://hermes-agent.nousresearch.com/docs/plugins/hindsight)
- [NAS recovery and snapshots](../nas/README.md)
- [ArgoCD deployment workflow](../argocd/README.md)

## Verified rollout — 17 October 2026

Deployed commit `4c97249` through manual root and Hindsight ArgoCD syncs without
pruning or force. Both Applications finished `Synced`, `Healthy`, and `Succeeded`.
The dedicated subscription login succeeded; its temporary bootstrap pod was removed.

- UI: <https://hindsight.tailbd291c.ts.net>
- API: <https://hindsight-api.tailbd291c.ts.net>
- Global-bank MCP: <https://hindsight-api.tailbd291c.ts.net/mcp/reserve/>

REST requests and MCP initialization rejected absent and incorrect tokens with
HTTP 401. Authenticated in-cluster MCP initialization succeeded. MCP's unauthenticated
GET probe intentionally returns 200; use POST initialization to test authentication.
The UI dashboard and 13 linked JavaScript assets loaded without disclosing the API
token. API health and metrics returned 200, and all five PVCs bound.

A workstation client retained a synthetic Amber Heron launch-color fact in
`validation-20261017`; a separate in-cluster client recalled it and reflected the
correct answer using the configured subscription model. Recall still worked after
an API restart. `reserve` remained empty, with zero documents, memories, and failed
operations. Re-running the initializer preserved its existing configuration.

The manual backup Job wrote and verified
`hindsight-20261017T001325393167633Z.dump` on the NAS, SHA-256
`cfc2234ad0b517512ad9ac85244a4072e2ebb93922980340b74d319646a85f2c`.
A separate restore Job restored that archive with `--exit-on-error --no-owner --no-acl`
into `hindsight_validation_20261017`. SQL checks recovered both bank configurations
and two validation memory rows (fact and consolidated observation), with no memories
in `reserve`. The live database was not overwritten.

After explicit approval, the validation bank `validation-20261017`, isolated restore
database `hindsight_validation_20261017`, and both validation Jobs were deleted.
Checks confirmed the test bank and database were absent and `reserve` remained empty.
The backup archive is retained under the normal backup policy. OAuth credentials
persisted across restart and both their file and directory were writable;
expiry-driven token rotation has not yet been observed.
Agent clients still need their own connection configuration and injected API token.
