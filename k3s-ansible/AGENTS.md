# K3s instructions

These rules also apply to `scripts/provision-macpro-k3s-vm.sh` and
`scripts/repair-macpro-k3s-vm-offline.sh` at the repository root. Read the
[runbook](README.md) and relevant [documented solutions](../docs/solutions/)
for node, containerd, CNI, or VM recovery changes.

## Preserve bootstrap and recovery constraints

- Inventory and host vars define node identities, interfaces, and storage roles.
  Keep dependent scripts aligned; do not copy old IPs or storage exclusions from
  historical VM plans over the rebuilt configuration.
- Bootstrap through the first server's real IP; the API VIP is unavailable until
  kube-vip is running. Let the upstream role control cluster initialization:
  never put `cluster-init` in the shared `server_config_yaml`.
- Join an additional worker using `join-workers.yml`, limited to that worker;
  do not rerun the server role to join it or print the existing join token.
- Preserve Pi cgroup boot parameters, persistent iSCSI modules/services, and NFS
  prerequisites. Store boot-file backups outside the FAT boot partition.
- Preserve strict SSH host-key verification and explicit VM destruction guards.
  VM recreation and node reboots require operational authorization.
- Do not remove host-local IPAM leases from a Running-pod-only comparison or when
  API queries fail. Flannel cleanup remains excluded from ArgoCD discovery.

## Verification

- Run `bash -n` on changed shell scripts. Check inventory/host-var consistency and
  YAML structure; use Ansible syntax checks when dependencies are available.
- `scripts/preflight-check.sh` here can change node boot parameters. It is not a
  read-only local test. Inspect scripts before executing them against nodes.
- Local checks do not establish cluster health. Separate any approved live
  verification from local validation and report the distinction.

## Code Review Rules

- Flag `cluster-init` in shared server configuration or server-role execution for
  worker-only joins. Let the upstream role initialize servers and limit worker
  joins to the worker playbook and intended node.
- Flag preflight execution described as read-only validation: it can modify boot
  parameters. Use local syntax checks or obtain authorization for node changes.
- Flag lease cleanup based on failed API queries or only Running pods. Preserve
  valid starting attachments and investigate targeted cleanup with authorization.
