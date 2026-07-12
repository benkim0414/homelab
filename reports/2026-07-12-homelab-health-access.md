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

The intended explicit SSH route is functional for every inventory node. Plain
global SSH configuration parsing is blocked by system config ownership or
permissions visible to Codex, but does not affect the explicit configuration
route used for the node probes.

## Fixes Applied

None. No SSH configuration, key material, system files, or cluster resources
were modified.

## Remaining Risks

The plain global SSH configuration remains unusable in this Codex environment.
Use `ssh -F ~/.ssh/config` for subsequent Codex SSH probes unless the local
system configuration ownership issue is separately investigated.

Task 3 should decide whether the ArgoCD API-discovery, manifest-generation,
repository-index, and pruning conditions need remediation or are transient.
