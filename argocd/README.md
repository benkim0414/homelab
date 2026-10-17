# ArgoCD on K3s

GitOps continuous delivery for the homelab K3s cluster. ArgoCD watches `main`
and compares desired and live state. The root and selected child Applications
currently use manual sync; publishing changes does not automatically deploy them.
Inspect each Application's declared sync policy before planning a rollout.

Operational commands below require task authorization; they are not local tests.

## Architecture

```
GitHub repo (main branch)
    │
    │  push / merge PR
    ▼
┌──────────────┐     ┌──────────────────────────────┐
│   ArgoCD     │────▶│  K3s Cluster                 │
│  (sync loop) │     │                              │
│              │     │  immich        (Helm + raw)   │
│  192.168.0.  │     │  metallb       (Helm + CRDs) │
│    202:80   │     │  sealed-secrets (Helm)        │
│              │     │  kube-vip      (Helm)         │
└──────────────┘     │  tailscale     (Helm)         │
                     └──────────────────────────────┘
```

| Component              | Resources        |
|------------------------|------------------|
| Application controller | 256-512 MB RAM   |
| Server (UI/API)        | 128-256 MB RAM   |
| Repo server            | 128-256 MB RAM   |
| Redis                  | 64-128 MB RAM    |
| ApplicationSet         | 64-128 MB RAM    |

Total: ~640 MB-1.3 GB RAM (fits comfortably on 8 GB Pi nodes).

## Prerequisites

1. **GitHub remote** configured for the repo
2. **Helm** v3 installed locally
3. **MetalLB** deployed (ArgoCD server uses 192.168.0.202)

## Deploy

### 1. Add the ArgoCD Helm repo

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
```

### 2. Install ArgoCD

```bash
kubectl create namespace argocd
helm install argocd argo/argo-cd \
  --namespace argocd \
  --version 10.10.3 \
  -f argocd/values.yaml
```

### 3. Get the initial admin password

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d
```

### 4. Access the UI

Open **http://192.168.0.202** on the trusted LAN. The configured server runs
without TLS because the Tailscale ingress terminates TLS when installed.
Log in with username `admin` and the password from step 3.

### 5. Connect the Git repo

```bash
# If the repo is public, no credentials needed.
# For a private repo, add a deploy key or token:
argocd repo add https://github.com/benkim0414/homelab.git
```

### 6. Apply the Application manifests

```bash
kubectl apply -f argocd/apps/infrastructure.yaml
kubectl apply -f argocd/apps/immich.yaml
```

These Applications register desired configuration from the remote repository;
their current policies require an explicit sync to deploy it. For root App-of-Apps
bootstrap, register `argocd/apps.yaml`, review its selected resources and AppProject,
then explicitly sync the root to create child Applications. Review and sync each
child separately. During a rebuild, defer adoption until Sealed Secrets keys and
application data are restored and the reviewed configuration is published.
Installing ArgoCD alone does not deploy applications. Matching chart versions
and values are necessary for adoption; resource tracking metadata can still
produce an initial difference. See the adoption sequence below and the
[Sealed Secrets runbook](../docs/operations/sealed-secrets.md).

## How upgrades work with Renovate

1. Once activated, Renovate runs daily at 04:00 Melbourne time and opens stable
   chart, image and K3s update proposals. For example, an Immich proposal bumps
   `tag:` in `immich/values.yaml` and/or `targetRevision:` in its Application.
2. You review and merge the PR
3. ArgoCD detects the change on `main`; review the diff and explicitly sync while
   the Application uses manual sync. Automatic deployment applies only if that
   Application's policy is separately changed to enable it.
4. Verify a recent successful PostgreSQL backup before syncing an upgrade. The scheduled CronJob is not a pre-upgrade gate.

Renovate itself is selected by the root and uses manual sync. Review and sync the
root to register it, then review its token prerequisite and child diff before
syncing Renovate without pruning. See the [Renovate runbook](../renovate/README.md)
for dependency coverage, database constraints and activation verification.
K3s proposals update the inventory only; node upgrades require a separately
authorized Ansible operation.

## Adopting existing Helm releases

ArgoCD can adopt resources it did not originally create. Match chart versions, release names, values and raw manifests, then inspect the full generated-to-live diff before syncing. API defaults, generated Secrets, tracking metadata and chart hooks can still produce differences. Adoption is not guaranteed to avoid a rollout merely because the Helm versions match.

> **Note:** For the Tailscale operator, OAuth credentials are passed via `--set-string` at install time and are not in `values.yaml`. After ArgoCD adoption, manage these credentials via a Secret referenced in the Helm values, or use Sealed Secrets.

## Upgrade ArgoCD

ArgoCD manages its own chart through `argocd/apps/argocd.yaml`. Prefer updating
that pin and reviewing/syncing the Application through GitOps. The following
manual Helm procedure is for separately authorized bootstrap or recovery, not
the routine upgrade path. The example version must match `targetRevision` for
`argo-cd` in `argocd/apps/argocd.yaml`; an unversioned Helm upgrade may install a
different chart and is not recovery of the declared Application:

```bash
helm repo update
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version 10.10.3 \
  -f argocd/values.yaml
```

## Uninstall

```bash
kubectl delete -f argocd/apps/immich.yaml
kubectl delete -f argocd/apps/infrastructure.yaml
helm uninstall argocd -n argocd
kubectl delete namespace argocd
```

> **Warning:** Automated pruning removes resources omitted from the desired state during sync. Cascading Application deletion is separately controlled by the resources finalizer and deletion options; disabling automated sync alone does not prevent a cascading delete. Review the actual finalizers and deletion mode before removal.


## Rebuild adoption record — October 2026

These are recorded rollout results, not a new live health assessment. Current
manifests define desired state. All 14 Applications (root plus 13 selected
children) reported Synced/Healthy after adoption; all five nodes were Ready and
seven Longhorn volumes healthy. Root and selected children remain manual.

### Selection and adoption decisions

Honcho, Flannel cleanup and Renovate were initially excluded, leaving 13 child
Applications. Honcho, Nextcloud and Flannel cleanup sources have since been
removed because they are retired. Renovate was excluded during that adoption;
the current root manifest now selects it for a separately reviewed manual rollout.
That selection change is not evidence of live activation. Removing retired
repository sources did not delete cluster resources or data.
Historical configuration is available in Git history.

Adoption preserved Helm release identity, pins, external credentials and volume
identities. Tailscale explicitly uses release name `tailscale-operator` and its
existing external `operator-oauth` Secret. Immich's unrecoverable S3 Secret and
offsite job remain excluded. Database PVs use reclaim policy Delete; manual sync
alone does not prevent data loss through pruning or cascading deletion.

The root and all selected children were synced without pruning. Self-adoption
preserved ArgoCD workloads and credentials. Its LAN and Tailscale URLs returned
HTTP 200. An explicit empty core-API `group` in the Grafana Secret ignore rule
caused a serialization diff; removing it in `8e675c0` and refreshing the root
resolved that diff without resource mutations. Preserve the narrow generated
Secret/checksum ignores and `RespectIgnoreDifferences=true`.

Earlier offline review rendered eight matching installed chart pins and compared
34 chart-generated workloads/services. It found only explicitly rendered API
defaults in three workload specs. That comparison did not cover all Secrets,
hooks, CRDs or tracking metadata; complete ArgoCD diffs were reviewed during
subsequent adoption. Local rendering alone is not rollout verification.

### Flannel cleanup decision

The old privileged cleanup DaemonSet was assessed, left disabled during adoption,
and subsequently removed from the repository with its Application and RBAC. Its failed
API queries become empty active-IP sets; its Running-pod-only comparison also
misses starting attachments. Either can lead to live lease deletion. Read-only
inspection found no orphaned/zero-byte leases on the five rebuilt nodes and no
retained IPAM exhaustion events. This does not establish that exhaustion cannot
recur. Investigate runtime attachment identities before any separately approved
cleanup. See the [March incident](../reports/2026-03-24-flannel-ipam-exhaustion-node14.md).

### Monitoring rollout lessons and results

Prometheus stack chart `92.7.0`, Loki `7.3.0` and Alloy `1.13.1` were rendered
and then deployed with approval. Persistent claims total 34 GiB before Longhorn
replication: Prometheus 20 GiB, Grafana 2 GiB, Alertmanager 2 GiB and Loki 10 GiB.
These were fresh installations, not restores of old monitoring data.

- Use ArgoCD's hook strategy for chart installation. Apply strategy skipped the
  admission-certificate job, leaving the Prometheus operator waiting for TLS.
  A hook sync corrected this without pruning or force replacement.
- Node exporter limits/tolerations belong under `prometheus-node-exporter`, not
  the `nodeExporter` feature toggle.
- Grafana exceeded its former 256 MiB limit and was OOM-killed. Raising request
  to 256 MiB and limit to 768 MiB produced a healthy 3/3 pod with no restarts;
  LAN and HTTPS health checks passed. Initial memory was about 445 MiB, not a
  sustained-load measurement. All 31 Prometheus scrape targets were healthy.
- Loki became 2/2 ready with a healthy 10 GiB volume; gateway, readiness and label
  queries passed. Runtime retention was `168h`, with filesystem delete requests
  and persistent compactor markers. Retention is asynchronous, not a disk quota.
- Alloy initially treated wildcard paths as literal filenames. Enabling
  `file_match` in `loki.source.file` passed validation with deployed v1.20.1 and
  reloaded without rollout. All five collectors became 2/2 ready; Loki queries
  confirmed recent logs from k3s-01 through k3s-05. Ready pods alone had not
  established ingestion.

### Home Assistant and remaining checks

Home Assistant chart `0.3.86` installed fresh with a healthy 5 GiB Longhorn claim.
Its explicit dedicated MetalLB pool and `.204` address are required because the
pool disables auto-assignment. LAN and Tailscale HTTPS returned onboarding
redirects. User onboarding and a replacement metrics token remain required:
decrypting the old token does not make it valid in the new instance. Establish
the monitoring CRDs/operator before dependent ServiceMonitors and custom rules.

Check stale Tailscale registrations before new proxy creation. The user recovered
original Grafana and Longhorn names. Longhorn DNS resolved after rename, but the
post-rename workstation HTTPS check timed out; the earlier suffixed URL passed.
Do not report the renamed endpoint as verified or remove devices without approval.

At rebuild time, Renovate and S3 activation remained dependent on approved
replacement/recovered credentials. For current Renovate activation prerequisites,
see its runbook; S3 remains separately gated. Continue reviewing each app's full
diff before sync; changing manual sync or enabling pruning requires separate
review. See the
[rebuild record](../docs/superpowers/plans/2026-10-14-cluster-rebuild.md) for backup
and controller-key recovery evidence.
