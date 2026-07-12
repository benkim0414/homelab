# Homelab Health And Access Report

Date: 2026-07-12

## Scope

GitOps-first cluster health and local access investigation. Read-only SSH
hostname probes verify the access baseline; other direct SSH is limited to
targeted read-only node probes unless supporting evidence and a separate
live-change approval are granted.

## Access Baseline

| Check | Result | Evidence |
| --- | --- | --- |
| Expected inventory | pass | `192.168.0.11 rpi5-8gb-crucial-p3-plus-500gb server/control-plane`; `192.168.0.12 rpi5-8gb-crucial-bx500-500gb server/control-plane`; `192.168.0.13 rpi5-8gb-samsung-980-500gb server/control-plane`; `192.168.0.14 rpi5-8gb-rpi-256gb agent/worker`; `ansible_user pi`. |
| Explicit SSH config parse | pass | `ssh -F ~/.ssh/config -G github.com` exited 0. `~/.ssh/config` resolves to `/home/benkim0414/workspace/dotfiles/ssh/.ssh/config`. |
| Global SSH config parse | diagnostic failure | `ssh -G github.com` exited 255: `Bad owner or permissions on /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf`. This is a local Codex/global-config diagnostic; explicit config parsing succeeds. |
| Node SSH hostnames | pass | `192.168.0.11` -> `rpi5-8gb-crucial-p3-plus-500gb`; `192.168.0.12` -> `rpi5-8gb-crucial-bx500-500gb`; `192.168.0.13` -> `rpi5-8gb-samsung-980-500gb`; `192.168.0.14` -> `rpi5-8gb-rpi-256gb`. Read-only explicit-config probes used `pi`; initial sandboxed probes failed with `socket: Operation not permitted`, and approved network probes succeeded. |

Local SSH permissions were verified: `~/.ssh` is `drwx------`,
`~/.ssh/id_ed25519` is `-rw-------`, `~/.ssh/id_ed25519.pub` is
`-rw-r--r--`, and `~/.ssh/known_hosts` is `-rw-------`.

## Cluster Health

| Area | Result | Evidence |
| --- | --- | --- |
| Kubernetes nodes | pass | Four nodes are Ready: `rpi5-8gb-crucial-p3-plus-500gb` (`192.168.0.11`), `rpi5-8gb-crucial-bx500-500gb` (`192.168.0.12`), and `rpi5-8gb-samsung-980-500gb` (`192.168.0.13`) are `control-plane,etcd,master`; `rpi5-8gb-rpi-256gb` (`192.168.0.14`) is the unlabelled worker. All report Kubernetes `v1.31.12+k3s1`, Debian 12, and containerd `2.0.5-k3s2.32`. |
| Node metrics | pass | `.12`: 406m CPU (10%), 5137Mi memory (70%); `.11`: 376m (9%), 4870Mi (60%); `.14`: 60m (1%), 1979Mi (27%); `.13`: 430m (10%), 5990Mi (74%). All nodes report 0Mi swap. |
| Non-running pods | observe-only | Only Completed pods were returned: recent `honcho-pg-backup`, `immich-offsite-backup`, and `immich-pg-backup` backup jobs, plus `kube-system` `helm-install-traefik` and `helm-install-traefik-crd` jobs. No Failed, Pending, or Unknown pods were returned. |
| Warning events | local tooling status | `kubectl get events --all-namespaces --field-selector type=Warning --sort-by=.lastTimestamp | tail -50` could not connect to `192.168.0.11:6443`: `socket: operation not permitted`. This is a Codex sandbox/local-tooling limitation, not a cluster failure, because Kubernetes MCP reads succeeded. |
| ArgoCD apps | concern | All 18 Applications are Healthy. Synced: `alloy`, `apps`, `flannel-ipam-cleanup`, `forgejo`, `forgejo-runner`, `home-assistant`, `honcho`, `immich`, `kube-vip`, `loki`, `longhorn`, `metallb`, `traefik`, and `vaultwarden`. `argocd` is Healthy/OutOfSync; `kube-prometheus-stack`, `sealed-secrets`, and `tailscale` are Healthy/Unknown. Condition details below are findings for Task 3 to assess. |
| Grafana alerts | concern | No firing alert rules were returned and active incidents are empty. Prometheus and Loki datasource health is OK; Alertmanager is unhealthy because its plugin is unavailable (HTTP 500). |

## ArgoCD Condition Evidence

These conditions are findings for Task 3 to assess; they do not establish a
fix or an expected steady state.

- `argocd` is Healthy/OutOfSync. Its automated sync operation is Running on
  retry attempt #3. PreSync hook resources for `argocd-redis-secret-init`
  failed while deleting or getting API resources because Kubernetes API
  discovery timed out with context deadline exceeded against
  `https://10.43.0.1:443`.
- `kube-prometheus-stack` is Healthy/Unknown with `ComparisonError`: manifest
  generation for source 1 of 3 failed with `DeadlineExceeded` while waiting
  for connections to become ready. Many monitoring resources require pruning
  and report Unknown.
- `sealed-secrets` is Healthy/Unknown with `ComparisonError`: manifest
  generation for source 1 of 2 failed because the repository index fetch
  returned `404 Not Found` from
  `https://bitnami-labs.github.io/sealed-secrets`.
- `tailscale` is Healthy/Unknown with `ComparisonError`: manifest generation
  for source 1 of 2 failed with `DeadlineExceeded` and context deadline
  exceeded.

## Findings

| Severity | Component | Finding | Classification | Evidence | Next Action |
| --- | --- | --- | --- | --- | --- |
| info | access | Explicit SSH config works for every inventory host. | observe-only | `ssh -F ~/.ssh/config -G github.com` exited 0 and all four explicit-config hostname probes succeeded. | Continue using the explicit SSH configuration for Codex probes; no remote or repository change is needed. |
| info | access | Plain global SSH parsing fails only inside Codex because it cannot accept the owner or mode of `/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf`. | observe-only | `ssh -G github.com` exited 255, while the explicit config route works. This is a namespace ownership difference between the Codex environment and the system SSH configuration, not node access failure. | Keep this as a local diagnostic. Investigate the host-owned system configuration separately only if plain global SSH is required. |
| info | cluster | Live roles for `.11`, `.12`, and `.13` are control-plane/etcd; `.14` is the worker, matching `host_vars`. | observe-only | All four nodes are Ready and their live Kubernetes roles match the `extra_server_args`/`extra_agent_args` assignments. | No inventory or node recovery action is needed. |
| low | k3s-ansible documentation | `k3s-ansible/README.md` still lists `.12` as worker and `.14` as control plane, and its restart guidance follows the old roles. | repo fix | The README node table and related taint/restart text contradict live state and `host_vars/192.168.0.12.yml` and `host_vars/192.168.0.14.yml`. | Owner: `k3s-ansible`. In Task 4, update the role table and role-specific operational guidance to match the durable inventory. |
| info | workload health | Non-running pods are expected Completed backup CronJobs and Helm install jobs. | observe-only | No Failed, Pending, or Unknown pods were returned. | No action is needed. |
| medium | ArgoCD | `argocd` is Healthy/OutOfSync while automated sync retries after API discovery timeouts during PreSync hook cleanup. | repo fix | The `argocd-redis-secret-init` hook cleanup encountered `context deadline exceeded` against `https://10.43.0.1:443`; live-only drift is not proven. | Owner: `argocd` Application and chart values. In Task 4, inspect the hook cleanup and sync configuration, then make a declarative resiliency fix if the condition persists. |
| medium | ArgoCD monitoring | `kube-prometheus-stack` is Healthy/Unknown because source-1 manifest generation hit `DeadlineExceeded`. | repo fix | ArgoCD reports a `ComparisonError`, Unknown resources, and pending pruning; live-only drift is not proven. | Owner: `monitoring` and `argocd/apps/monitoring.yaml`. In Task 4, inspect the chart source/render path and make the required declarative fix. |
| medium | ArgoCD infrastructure | `sealed-secrets` is Healthy/Unknown because its Helm repository index returns `404 Not Found`. | repo fix | Source 1 is `https://bitnami-labs.github.io/sealed-secrets` in `argocd/apps/infrastructure.yaml`, matching the failing repository endpoint. | Owner: `argocd/apps/infrastructure.yaml` and `sealed-secrets`. In Task 4, verify the supported chart repository and update the declarative source. |
| medium | ArgoCD infrastructure | `tailscale` is Healthy/Unknown because source-1 manifest generation hit `DeadlineExceeded`. | repo fix | ArgoCD reports `ComparisonError` and `context deadline exceeded`; live-only drift is not proven. | Owner: `argocd/apps/infrastructure.yaml` and `tailscale`. In Task 4, inspect the chart source/render path and make the required declarative fix. |
| low | Grafana monitoring | Alertmanager datasource is unhealthy because its plugin is unavailable and returns HTTP 500. | repo fix | Prometheus and Loki datasources are OK, there are no firing alerts or active incidents, and only the Alertmanager datasource is unhealthy. | Owner: `monitoring`. In Task 4, inspect Grafana datasource provisioning and chart values to install, configure, or remove the unavailable plugin declaratively. |
| info | SSH fallback | No node-local symptom requires SSH fallback. | observe-only | All four nodes are Ready, node metrics are adequate for this pass, workloads have no failed symptoms, and no pressure condition or k3s service suspicion was observed. | Do not run SSH fallback probes. If a node becomes NotReady, pressure appears, metrics go missing, or a k3s service is suspected, request approval for targeted read-only `systemctl`, `journal`, `df`, and `free` probes. |

## Fixes Applied

None. No SSH configuration, key material, system files, or cluster resources
were modified.

## Remaining Risks

The plain global SSH configuration remains unusable in this Codex environment.
Use `ssh -F ~/.ssh/config` for subsequent Codex SSH probes unless the local
system configuration ownership issue is separately investigated.

No manual recovery is selected from the current evidence. Any future live
recovery, such as a sync retry or a Job rerun, requires separate approval after
an identifying read-only probe establishes that declarative remediation is not
the appropriate owner action.
