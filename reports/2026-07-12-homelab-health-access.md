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
| low | k3s-ansible documentation | `k3s-ansible/README.md` had stale node roles and restart guidance. | resolved | The README contradicted live state and `host_vars/192.168.0.12.yml` and `host_vars/192.168.0.14.yml`. | Updated the topology, role table, removed the obsolete `.14` control-plane taint guidance, and corrected server/agent restart commands. |
| info | workload health | Non-running pods are expected Completed backup CronJobs and Helm install jobs. | observe-only | No Failed, Pending, or Unknown pods were returned. | No action is needed. |
| medium | ArgoCD | `argocd` is Healthy/OutOfSync while automated sync retries after API discovery timeouts during PreSync hook cleanup. | no repo fix applied | The `argocd-redis-secret-init` hook cleanup encountered `context deadline exceeded` against `https://10.43.0.1:443`; repository state does not identify a safe declarative resiliency change. | Observe the next sync and inspect current hook/API conditions before selecting a GitOps change or requesting manual follow-up. |
| medium | ArgoCD monitoring | `kube-prometheus-stack` is Healthy/Unknown because source-1 manifest generation hit `DeadlineExceeded`. | no repo fix applied | ArgoCD reports a `ComparisonError`, Unknown resources, and pending pruning; the chart source and application configuration do not identify a safe declarative remediation. | Observe the next manifest-generation attempt; investigate ArgoCD repo-server connectivity or capacity if the deadline condition persists. |
| medium | ArgoCD infrastructure | `sealed-secrets` is Healthy/Unknown because its Helm repository index returns `404 Not Found`. | resolved | Source 1 used the retired `https://bitnami-labs.github.io/sealed-secrets` endpoint. | Updated the Application source and values comment to the official `https://bitnami.github.io/sealed-secrets` repository; observe ArgoCD reconciliation. |
| medium | ArgoCD infrastructure | `tailscale` is Healthy/Unknown because source-1 manifest generation hit `DeadlineExceeded`. | no repo fix applied | ArgoCD reports `ComparisonError` and `context deadline exceeded`; the chart source and application configuration do not identify a safe declarative remediation. | Observe the next manifest-generation attempt; investigate ArgoCD repo-server connectivity or capacity if the deadline condition persists. |
| low | Grafana monitoring | Alertmanager datasource is unhealthy because its plugin is unavailable and returns HTTP 500. | no repo fix applied | The values provision only the Loki datasource; no repository datasource definition identifies a wrong plugin type or an intended Alertmanager plugin. | Confirm the live provisioned datasource owner and intended Grafana plugin before adding, changing, or removing datasource configuration declaratively. |
| info | SSH fallback | No node-local symptom requires SSH fallback. | observe-only | All four nodes are Ready, node metrics are adequate for this pass, workloads have no failed symptoms, and no pressure condition or k3s service suspicion was observed. | Do not run SSH fallback probes. If node-local evidence emerges, targeted read-only probes may be run subject to sandbox/network policy; mutations require separate approval. |

## Fixes Applied

| Type | Target | Change | Verification |
| --- | --- | --- | --- |
| repo | `k3s-ansible/README.md` | Aligned `.11`/`.12`/`.13` as control plane/etcd and `.14` as worker/agent; removed stale `.14` control-plane taint guidance and corrected restart commands. | Review against live roles and `host_vars`; Markdown diff inspection. |
| repo | `argocd/apps/infrastructure.yaml`, `sealed-secrets/values.yaml` | Replaced the retired Sealed Secrets Helm repository URL with `https://bitnami.github.io/sealed-secrets`; the source remains chart `sealed-secrets` at `targetRevision: '*'`. | YAML parse check, diff inspection, Helm repo update, chart search, and Helm render passed. The wildcard resolves to chart `2.19.1` / app `0.38.4`; deployed history last used chart `2.18.6` / app `0.37.0`. The rendered diff from `2.18.6` to `2.19.1` is limited to chart/app labels, controller image, and added pod/container security context fields. |
| none | `argocd`, `kube-prometheus-stack`, `tailscale` | No repo fix applied for timeout/deadline findings because repository state alone does not identify a safe declarative change. | Nearby application and values configuration inspected. |
| none | Grafana Alertmanager datasource | No repo fix applied because no repository provisioning entry identifies an intended plugin or incorrect datasource type. | Monitoring values inspected. |

## Remaining Risks

- Codex plain global SSH parsing still fails without explicit configuration
  because `/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf` has unacceptable
  ownership or permissions in this environment; use `ssh -F ~/.ssh/config`.
- ArgoCD timeout/deadline conditions for `argocd`, `kube-prometheus-stack`, and
  `tailscale` were documented but not speculatively fixed because current
  repository evidence did not identify a safe declarative remediation.
- The unavailable Alertmanager Grafana datasource plugin remains follow-up;
  confirm the live datasource owner and intended plugin before a GitOps change.
- The Sealed Secrets chart repository was fixed and Helm-rendered locally, but
  live ArgoCD reconciliation still needs to pick it up after merge/sync. Because
  the source remains `targetRevision: '*'`, the next reconciliation is expected
  to move from chart `2.18.6` / app `0.37.0` to chart `2.19.1` / app `0.38.4`.

## Final Verification

- `ssh -F ~/.ssh/config -G github.com >/tmp/homelab-final-ssh-explicit.out`
  exited 0; its only pre-command message was the expected non-interactive
  pseudo-terminal notice.
- Kubernetes MCP reports four Ready nodes: `.11`, `.12`, and `.13` are
  `control-plane,etcd,master`; `.14` is the unlabelled worker. All run
  `v1.31.12+k3s1`.
- Final node metrics were `.12` 441m CPU/11%, 5202Mi/71%; `.11` 324m/8%,
  4934Mi/61%; `.14` 62m/1%, 1981Mi/27%; and `.13` 372m/9%, 6082Mi/75%; all
  report 0Mi swap.
- Non-running pods are only Completed Honcho/Immich backup jobs and
  `kube-system` Traefik install jobs; no Failed, Pending, or Unknown pods were
  returned.
- Recent commits include the Sealed Secrets fix, k3s role documentation fix,
  health classification and evidence, SSH baseline clarification, report,
  plan, and design artifacts.
- Sealed Secrets Helm validation passed with temporary Helm `v4.2.3` via
  `mise`: repo add/update succeeded, `helm search repo` returned
  `sealed-secrets/sealed-secrets` chart `2.19.1` / app `0.38.4`, and
  `helm template` rendered the committed values file successfully. Rendering
  chart `2.18.6` and `2.19.1` showed the expected image/version move and
  added security context fields; no cluster or ArgoCD mutation was performed.
