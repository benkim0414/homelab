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

1. Renovate detects a new Immich version and opens a PR bumping `tag:` in `immich/values.yaml` and/or `targetRevision:` in `argocd/apps/immich.yaml`
2. You review and merge the PR
3. ArgoCD detects the change on `main`; review the diff and explicitly sync while
   the Application uses manual sync. Automatic deployment applies only if that
   Application's policy is separately changed to enable it.
4. Verify a recent successful PostgreSQL backup before syncing an upgrade. The scheduled CronJob is not a pre-upgrade gate.

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


## Rebuild adoption review — 15 October 2026

At the initial review, no Applications were installed in the rebuilt cluster. The
root selected all 16 child Applications. Honcho, Flannel cleanup and Renovate
are now excluded at the user's request,
leaving 13 selected Applications. Monitoring (Prometheus/Grafana, Loki and Alloy)
and Home Assistant are approved for the initial selection. The root and every
selected child now use manual sync for adoption; registering them will not
automatically deploy their workloads. Repository sources explicitly track `main`.

### Adoption preparation and remaining review

| Finding | Effect | Required preparation |
| --- | --- | --- |
| Initial application selection | Monitoring and Home Assistant are approved; Renovate credentials are unavailable | Prepared: exclude Renovate, Honcho and Flannel cleanup; retain monitoring and Home Assistant for manual review/sync. |
| Immich includes `s3-sealed-secret.yaml` and `offsite-backup-cronjob.yaml` | Attempts to decrypt an unrecoverable Secret and schedules a job without working credentials | Prepared: both are excluded until replacement S3 credentials are configured |
| Root and selected children use manual sync | Each deployment requires an explicit sync | Prepared: automated sync/pruning removed; enable automation per app only after reviewing the diff |
| Tailscale release is installed as `tailscale-operator`, Application is `tailscale` | Release identity differs from default ArgoCD rendering | Prepared: chart source explicitly sets `helm.releaseName: tailscale-operator` |
| Tailscale uses the existing `operator-oauth` Secret | Chart rendering without credentials omits the Secret; it remains an external prerequisite | Keep that Secret intact, verify its external backup and decide how it will be managed before adoption; do not pass blank OAuth values |
| ArgoCD and Longhorn include Tailscale ingresses absent from the live cluster | Creates new proxy resources and tailnet registrations | Defer those raw ingresses or separately approve their creation and name recovery |
| Database PV reclaim policy is `Delete` | Deleting a database PVC can remove its underlying Longhorn data | Review PVC/StatefulSet diffs carefully and do not use force/replace or prune data claims during adoption |
| Monitoring and Home Assistant chart versions | Previously used wildcard versions | Prepared: pinned and rendered the four selected charts; runtime validation remains pending |

Nextcloud has no child Application under the current root directory and is not
selected. Excluding an optional app from root discovery is a deployment choice;
it does not delete the app's source files or existing data.

### Verified comparison and limits

The eight pinned chart versions match the live Helm releases. Offline rendering
and read-only comparison covered 34 chart-generated Deployments, DaemonSets,
StatefulSets and Services. All existed under the expected names. Three workload
specs differed only in explicitly rendered zero/false defaults omitted from the
live API representation (probe delays and Immich host namespace flags).
This is a provided-field comparison, not a complete ArgoCD diff: it does not
prove equality of generated Secrets, hooks, CRDs, tracking metadata or all
controller-managed fields. Live credential values were not exported for review.

Server-side dry runs accepted PostgreSQL, the Immich NFS PV/PVCs, Vaultwarden's
backup PV/PVC, MetalLB address pools/advertisement and Traefik HelmChartConfig.
Both live application SealedSecrets report synced. Only the two approved NAS
backup CronJobs and the two restored application Tailscale ingresses currently
exist; offsite backup, ArgoCD/Longhorn ingress and optional workloads are not live.
The namespace's Application tracking label key is `argocd.argoproj.io/instance`,
which differs from Helm's `app.kubernetes.io/instance`; preserve that distinction.

### Proposed adoption sequence

1. Review the prepared initial selection, exclusions and manual
   child sync policies above. Keep the infrastructure AppProject available before
   creating Applications that reference it. Use explicit `main` revisions for
   this repository rather than depending on the remote default branch.
2. Review and commit those changes, then request push/merge approval. Publishing
   code does not itself require applying the root to the currently unmanaged cluster.
3. After the reviewed revision is on `main`, obtain approval to register the
   manual Applications. Inspect their complete ArgoCD diffs before syncing.
4. Adopt one app at a time without pruning: establish Sealed Secrets and
   credential prerequisites, then review networking, storage, Tailscale and
   restored applications. Adopt ArgoCD itself last and verify API/UI access.
5. Confirm database volumes remain healthy, both HTTPS apps work and scheduled
   backups remain configured. Enable automation and pruning per app only after
   separate review of the resulting desired resource set.

The review initially changed documentation only. The root discovery filter now
excludes Honcho, Flannel cleanup and Renovate, while retaining their Application
and source files. The selected Applications and root are manual, Immich offsite
backup manifests are excluded, and Tailscale release identity is explicit. No
Applications, credentials, tailnet devices or workloads were created, synced,
deleted or reconfigured. Selection and chart rendering review are complete;
complete live diffs, runtime validation and rollout approval remain pending.

### Flannel cleanup assessment

Read-only inspection on all five rebuilt nodes found lease counts of 14, 11, 11,
14 and 4 respectively. There were no zero-byte leases or lease container IDs
absent from the local containerd sandbox list. All nodes were Ready, and retained
events contained no CNI/IPAM exhaustion errors. This is a snapshot of the current
cluster, not proof that orphaned leases cannot recur.

The March incident involved exhausted IPAM state after ungraceful pod termination
on the old nodes. Those disks have been reimaged, and `.14` now uses NVMe. The
existing DaemonSet is not running and is now excluded from root discovery.
Any replacement requires separate review:

- Its API query uses `|| true`; failure produces an empty active-IP set and the
  loop then deletes all nonempty lease files, including potentially live leases.
- Restricting the query to Running pods omits pending/starting attachments.
- It runs privileged with host filesystem access across both architectures, while
  its image is documented as an ARM64 digest and Kubernetes 1.31-era tooling.

The [CNI host-local documentation](https://www.cni.dev/plugins/current/ipam/host-local/)
describes the per-host allocation database. The
[CNI specification](https://github.com/containernetworking/cni/blob/main/SPEC.md)
defines garbage collection using valid attachment identities; a Running-pod-IP
list is not equivalent. Runtime/plugin GC support in this exact K3s build was not
verified, and no lease files were changed during this assessment.

The user approved excluding the old automated cleanup job. Its Application was
extracted from `infrastructure.yaml` into `argocd/apps/flannel-ipam-cleanup.yaml`
and excluded by the root discovery filter alongside Honcho. The DaemonSet and
RBAC source files remain available. Monitor for sandbox/IPAM errors and increasing
lease use, and investigate any recurrence before performing targeted cleanup.

### Monitoring and Home Assistant chart review

Reviewed official Helm indexes and downloaded archives on 15 October 2026.
All four archive SHA256 digests matched their index entries. Selected stable pins:

| Application | Chart version | Rendered main image |
| --- | --- | --- |
| kube-prometheus-stack | 92.7.0 | Prometheus Operator v0.94.1; Grafana 13.2.4-distroless |
| Loki | 7.3.0 | grafana/loki:3.6.11 |
| Alloy | 1.13.1 | grafana/alloy:v1.20.1 |
| Home Assistant | 0.3.86 | home-assistant:2026.10.1 |

Sources: [Prometheus stack release](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-92.7.0),
[Loki release](https://github.com/grafana/helm-charts/releases/tag/helm-loki-7.3.0),
[Alloy release](https://github.com/grafana/helm-charts/releases/tag/alloy-1.13.1),
[Home Assistant release](https://github.com/pajikos/home-assistant-helm-chart/releases/tag/home-assistant-0.3.86).
The downloaded chart defaults determine rendered image tags; Loki's appVersion
is 3.6.12 but its default Loki image is explicitly 3.6.11.

All four charts render with repository values and Kubernetes version 1.36.5.
Rendered resources preserve Longhorn storage: Prometheus 20Gi, Grafana 2Gi,
Alertmanager 2Gi, Loki 10Gi and Home Assistant 5Gi. These are fresh optional
installations, not restores of historical monitoring or Home Assistant data.

Rendering exposed two existing value issues, now corrected:

- Node exporter resource limits/tolerations belong under `prometheus-node-exporter`,
  not the feature toggle `nodeExporter`; the rendered DaemonSet now has the intended
  64Mi memory limit and control-plane toleration.
- Home Assistant now explicitly requests its dedicated MetalLB pool and `.204`
  address. That pool disables automatic assignment, so a LoadBalancer type alone
  did not select it.

Validation covers chart rendering and generated configuration, not container
startup or image architecture availability. Install the monitoring CRDs/operator
before syncing Home Assistant's ServiceMonitor or custom monitoring rules.
Home Assistant's retained encrypted metrics token must match a token in the new
Home Assistant instance; successful decryption alone does not make an old token
valid for a fresh installation. Confirm or replace it before expecting metrics.
Loki retains logs for the approved seven days (`168h`) on its 10Gi volume.
Compactor retention is enabled with filesystem delete-request storage and
persistent markers under `/var/loki/compactor`. Expired chunks are removed
asynchronously; retention does not impose a hard disk-usage ceiling. See the
[official retention configuration](https://grafana.com/docs/loki/latest/operations/storage/retention/). Monitoring and Home Assistant Tailscale ingresses
will create new proxies/devices when synced and still require diff/name review.

### Adoption progress and monitoring diff review

The manual root, Sealed Secrets, MetalLB, kube-vip, Traefik, Tailscale, Immich,
Vaultwarden and Longhorn Applications have now been synced without pruning.
All report Synced/Healthy. Existing application pods and database volumes remained
healthy. Vaultwarden's reviewed backup validation improvement is deployed.
ArgoCD self-adoption and Home Assistant have subsequently been synced; see below.

After the user removed the stale Longhorn tailnet device and renamed the new
proxy, the ingress advertises `https://longhorn.tailbd291c.ts.net`. DNS resolves
that name, but the post-rename workstation HTTPS check timed out. The earlier
suffixed URL had passed HTTPS verification. Resolve stale tailnet names before
creating replacements; do not delete devices without approval.

The live ArgoCD comparison for monitoring is error-free and consists solely of
new resources: 112 for kube-prometheus-stack, 12 for Loki and 7 for Alloy. No
existing resources are changed or removed by these comparisons. The stack adds
Prometheus CRDs/operator, admission webhooks, Prometheus/Alertmanager, Grafana,
exporters, scrape monitors/rules, Longhorn storage and the Grafana Tailscale ingress.
Loki adds single-binary logging with seven-day retention; Alloy adds its log
collector DaemonSet and PodLogs CRD. Runtime operators will create additional
Pods/PVCs not represented by these rendered-resource counts.

The five nodes are Ready with roughly 6–36% observed memory usage before this
installation. This is a point-in-time capacity observation, not a load test.
The reviewed persistent volumes total 34Gi for monitoring (20Gi Prometheus,
2Gi Grafana, 2Gi Alertmanager, 10Gi Loki), before Longhorn replication.

The user confirmed the old `grafana` Tailscale device was removed or renamed
before first sync so the new proxy can claim that exact name. The approved
Prometheus stack sync created the operator, Prometheus, Alertmanager and all five
node exporters successfully. All three Longhorn claims are bound (24Gi total).
Grafana exceeded the original 256Mi memory limit and was OOM-killed. The approved
Git fix raises its request to 256Mi and limit to 768Mi. The subsequent sync
completed without pruning: the Application is Synced/Healthy, Grafana is 3/3
with no restarts, and both LAN and Tailscale HTTPS health checks report its
database healthy. Initial observed Grafana pod memory is about 445Mi; this is
a startup observation, not a sustained-load test.
All 31 Prometheus scrape targets are healthy after the rollout.

Use ArgoCD's hook sync strategy for chart installation. The apply strategy skips
Helm hooks, including this chart's admission-certificate creation job, leaving
the operator waiting for its TLS Secret. Re-running with the hook strategy
created the certificate and started the operator without pruning or force.
Review the completed Prometheus/Grafana rollout before syncing Loki and finally
Alloy. All apps remain manual.

Loki was subsequently synced with approval, without pruning or force replacement.
It reports Synced/Healthy: the single-binary pod is 2/2 ready, its gateway is
1/1 ready, and neither has restarted. Its 10Gi Longhorn volume is healthy.
The readiness endpoint returns HTTP 200 and the labels query succeeds. Runtime
configuration confirms `168h` retention and filesystem compactor delete requests.
End-to-end collection was subsequently verified after the Alloy correction below.

Alloy's first approved sync created collectors on all five nodes, but runtime
verification found wildcard log paths being treated as literal filenames.
The approved correction enables `file_match` in `loki.source.file`; the rendered
configuration passes validation using the deployed Alloy v1.20.1 binary.
The fix is deployed and Alloy reports Synced/Healthy with all five collectors
2/2 ready and no restarts. ConfigMap propagation and automatic reload completed
without a rollout. Loki queries confirm recent logs from every node, k3s-01
through k3s-05. All six Longhorn volumes remained healthy during deployment.

Home Assistant was installed fresh with approval and reports Synced/Healthy.
Its 5Gi Longhorn claim is healthy, its pod is ready without restarts, and LAN
`http://192.168.0.204:8123` and `https://home-assistant.tailbd291c.ts.net`
return onboarding redirects. User onboarding and a replacement metrics token
are still required; the old instance's token does not authenticate to this one.

ArgoCD self-adoption completed without pruning or workload restarts and reports
Synced/Healthy. A transient Quay DNS failure delayed its Redis secret-init hook;
the automatic retry succeeded and confirmed the existing Redis credential.
LAN access and `https://argocd.tailbd291c.ts.net` both return HTTP 200.
All five nodes and seven Longhorn volumes are healthy after these deployments.

The root app's remaining diff is an explicit empty `group` in the Grafana Secret
ignore rule, which Kubernetes omits from the stored Application. Removing that
empty field preserves the rule while avoiding this serialization difference.
The correction is published in commit `8e675c0`. Refreshing the root comparison
against that revision resolved the diff without resource mutations or pruning.
All 14 Applications report Synced/Healthy and all five nodes are Ready.
Home Assistant onboarding and its replacement metrics token remain user tasks.
