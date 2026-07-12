# Homelab Health And Access Report

Date: 2026-07-12

## Scope

GitOps-first cluster health and local access investigation. Direct SSH is used
only for targeted read-only node probes unless a separate live-change approval
is granted.

## Access Baseline

| Check | Result | Evidence |
| --- | --- | --- |
| Expected inventory | pass | `192.168.0.11 rpi5-8gb-crucial-p3-plus-500gb server/control-plane`; `192.168.0.12 rpi5-8gb-crucial-bx500-500gb server/control-plane`; `192.168.0.13 rpi5-8gb-samsung-980-500gb server/control-plane`; `192.168.0.14 rpi5-8gb-rpi-256gb agent/worker`; `ansible_user pi`. |
| Explicit SSH config parse | pass | `ssh -F ~/.ssh/config -G github.com` exited 0. `~/.ssh/config` resolves to `/home/benkim0414/workspace/dotfiles/ssh/.ssh/config`. |
| Global SSH config parse | diagnostic failure | `ssh -G github.com` exited 255: `Bad owner or permissions on /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf`. This is a local Codex/global-config diagnostic; explicit config parsing succeeds. |
| Node SSH hostnames | pass | Read-only explicit-config probes using `pi` returned the expected hostname for all four inventory IPs. The initial sandboxed probes failed with `socket: Operation not permitted`; the approved network probes succeeded. |

Local SSH permissions were verified: `~/.ssh` is `drwx------`,
`~/.ssh/id_ed25519` is `-rw-------`, `~/.ssh/id_ed25519.pub` is
`-rw-r--r--`, and `~/.ssh/known_hosts` is `-rw-------`.

## Cluster Health

Pending.

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
