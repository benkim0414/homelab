# Flannel IPAM exhaustion on node .14 — 24 March 2026

**Status:** Historical incident, resolved. The original automatic-cleanup
recommendation is superseded by the October rebuild assessment. The cleanup
Application remains excluded from ArgoCD discovery; do not enable it as recovery.

## Incident and evidence

For approximately 23 hours, node `.14` exhausted its Flannel `/24` allocation
with stale host-local lease files in `/var/lib/cni/networks/cbr0/`. Kubernetes
events reported `FailedCreatePodSandBox` and `no IP addresses available`.
Three Longhorn DaemonSet pods were Unknown and Alloy remained ContainerCreating.
Host-networked pods still started, and a reboot did not clear persisted leases.
Other nodes kept application volumes available; no data loss or user-facing
application outage was reported.

Ungraceful pod exits left leases without a completed CNI DEL. The intended
cleanup DaemonSet had never deployed: malformed indentation in a YAML shell
block caused an ArgoCD ComparisonError. Fixing the YAML restored manifest
parsing, but did not establish that the cleanup algorithm was safe.

## Recovery and superseded remediation

A one-off host-networked privileged pod cleared `.14`'s leases after confirming
all Running pods on that node used host networking and no active Flannel IPs
needed preservation. This was a targeted historical action, not a general
instruction to clear leases during normal operation.

The original report recommended a recurring cleanup job and proactive lease
removal after reboots. The October review rejected that automation because:

- A failed API query becomes an empty active-IP set and can delete live leases.
- A Running-pod-only comparison misses starting or pending attachments.
- The privileged host-filesystem mutation and old image/tooling need separate review.

The October rebuild replaced the old node disks; `.14` now uses NVMe. Read-only
inspection of all five rebuilt nodes found no zero-byte or orphaned lease IDs,
and no retained CNI/IPAM exhaustion events. That snapshot does not prove the
problem cannot recur. See the
[ArgoCD adoption record](../argocd/README.md#flannel-cleanup-decision).

## Reusable lessons

- Persisted host-local leases survive reboots; restarting a node alone may not
  resolve allocation exhaustion.
- Treat ArgoCD ComparisonError as failure to produce desired resources, even
  when an application's health field appears benign.
- Parse YAML containing embedded shell before publishing it. The incident's
  continuation line lost indentation; shell continuations themselves are valid
  when the YAML block remains correctly indented.
- Investigate lease IDs against runtime attachments and preserve valid starting
  attachments. Never infer safe deletion from a failed API query.
- Obtain approval for any live lease mutation and verify scheduling and storage
  afterward. The old pod names and unchecked follow-ups are no longer actionable.
