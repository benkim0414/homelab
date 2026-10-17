# Homelab GitOps

This repository manages a K3s homelab through ArgoCD. Application directories
contain Helm values, Sealed Secrets and raw manifests; ArgoCD Applications live
under `argocd/apps/`.

## Cluster layout

| Hostname | Address | Role | Hardware |
| --- | --- | --- | --- |
| `k3s-01` | `192.168.0.11` | Control plane and etcd | Raspberry Pi 5, 8 GiB RAM, 256 GB NVMe |
| `k3s-02` | `192.168.0.12` | Control plane and etcd | Raspberry Pi 5, 8 GiB RAM, 256 GB NVMe |
| `k3s-03` | `192.168.0.13` | Control plane and etcd | Raspberry Pi 5, 8 GiB RAM, 256 GB NVMe |
| `k3s-04` | `192.168.0.14` | Worker | Raspberry Pi 5, 8 GiB RAM, 512 GB NVMe |
| `k3s-05` | `192.168.0.22` | Worker | Mac Pro Proxmox VM, 4 vCPUs, 16 GiB RAM, 128 GiB disk |

The Pis run Raspberry Pi OS 64-bit Lite based on Debian 13 Trixie. The replacement
VM runs Debian 13 Trixie. OS hostnames and K3s node names match. Hardware and
role changes belong in inventory and labels rather than hostname suffixes.

K3s is pinned to `v1.36.5+k3s1`. Bootstrap uses `.11`; the API VIP is `.10` once
kube-vip is installed. MetalLB reserves `.201`–`.205` for individual services;
the general pool contains `.200`, `.203` and `.206`–`.250`.
Longhorn stores database volumes; the separate NAS at `.40` stores Immich media
and backups. The NAS and Proxmox host at `.20` are outside the cluster node set.

## Provisioning and recovery

See [K3s setup](k3s-ansible/README.md) for inventory, host prerequisites and
installation. Local SSH aliases are configured in `~/.ssh/homelab_config`;
the Pis and VM use the client key `~/.ssh/pi_ed25519`. The VM login is
`benkim0414`; Pi logins use `pi`. The replacement VM's SSH host key was verified
through Proxmox. After the later `.22` migration, verification used temporary
trust; a persistent known-hosts update for that key remains unrecorded. Private
keys never belong in Git.

The [October 2026 rebuild record](docs/superpowers/plans/2026-10-14-cluster-rebuild.md)
records recovery sequencing and the verified Immich and Vaultwarden backups.
Restore Sealed Secrets master keys before applying encrypted secrets, and restore
application data before enabling application sync. VM replacement, infrastructure
bootstrap, application recovery and manual GitOps adoption are complete.

## Infrastructure bootstrap

The rebuild uses kube-vip chart `0.11.1`, MetalLB `0.16.1`, Longhorn `1.13.0`
and ArgoCD chart `10.10.3`. Matching versions are pinned in the Applications.
Longhorn creates default SSD-backed disks on labeled nodes, with two replicas.
Its NAS backup target is `nfs://192.168.0.40:/longhorn-backups`.

Use the dedicated rebuild kubeconfig explicitly. Install each chart with its
local values before applying MetalLB pools and the Traefik HelmChartConfig.
Defer registering `argocd/apps.yaml` until the Sealed Secrets keys and application
data are restored and the reviewed configuration is available on `main`. The root
and selected child Applications use manual sync: registration alone does not
deploy workloads. Review the deployed versions and ArgoCD diffs before syncing.

Immich recovery uses chart `0.12.0` with server `v2.7.5`, matching the server
observed before backup. Vaultwarden uses chart `0.46.3` with image `1.37.1`.
Both are restored and pass LAN and Tailscale HTTPS health checks; the user confirmed
both applications work. The original Tailscale URLs, `https://immich.tailbd291c.ts.net` and
`https://vaultwarden.tailbd291c.ts.net`, now point to the rebuilt cluster.
VM 210 is Ready as `k3s-05` at `.22`, migrated from `.21` after an IP conflict.
See [Tailscale setup](tailscale/README.md) for operator credentials.
S3 backups still need replacement credentials.
Immich database backups run daily at 03:00 and full Vaultwarden archives at 03:30
in `Australia/Melbourne`, retaining seven successful backups in dedicated NAS
directories. Both configured jobs passed manual runs. Immich media remains on
the NAS, with the separately verified rebuild copy preserved; a recurring media
snapshot job runs at 03:45 Melbourne time with seven snapshots retained;
see [NAS storage and snapshots](nas/README.md). Its first snapshot succeeded.
Manual GitOps adoption is complete; Home Assistant onboarding and its replacement
metrics token remain user tasks.

## GitOps workflow

Make changes on a feature branch and review them before merging to `main`.
Applications combine Helm, repository values and raw manifest sources as needed;
see the [ArgoCD instructions](argocd/AGENTS.md).
After K3s and storage are ready, bootstrap ArgoCD using
[its setup instructions](argocd/README.md).

## Verification before deployment

Use the [verification command and CI checks](verification/README.md) for Helm
rendering, schema validation, repository safeguards and sanitized resource-change
previews. Follow the [manual pre-sync checklist](argocd/README.md#verification-before-manual-sync)
before deploying the verified revision.
