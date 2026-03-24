# Incident Report: Flannel IPAM Exhaustion on rpi5-8gb-rpi-256gb (.14)

**Date:** 2026-03-24
**Severity:** High
**Duration:** ~23 hours (approx. 2026-03-23 09:00 AEDT to 2026-03-24 19:00 AEDT)
**Affected node:** rpi5-8gb-rpi-256gb (192.168.0.14)
**Status:** Resolved

---

## Summary

Node `.14` had its entire Flannel subnet (`10.42.1.0/24`, 254 usable IPs) exhausted
by stale IPAM lease files left by ungracefully-terminated pods. No new pods could
be scheduled to the node. Three Longhorn DaemonSet pods were stuck in `Unknown`
status, and one Alloy DaemonSet pod had been stuck in `ContainerCreating` for 19+
hours. The node had been rebooted the previous evening, which did not clear the
stale leases (lease files survive reboots). The `flannel-ipam-cleanup` DaemonSet
intended to prevent this was never deployed due to a YAML syntax error introduced
at the time of its initial commit.

---

## Timeline

| Time (AEDT) | Event |
|---|---|
| 2026-03-23 ~09:00 | Previous instability event on .14 — pods die ungracefully, Flannel IPAM leases not released |
| 2026-03-23 ~23:27 | Node rebooted (kubelet startTime: `2026-03-23T23:27:49Z`); stale leases survive reboot |
| 2026-03-23 ~23:30 | kube-vip, metallb-speaker, node-exporter restart (DaemonSet pods use hostNetwork — unaffected by IPAM) |
| 2026-03-24 ~00:00 | New Longhorn and Alloy pods attempt to schedule on .14; all fail with `no IP addresses available` |
| 2026-03-24 ~08:00 | `engine-image-ei-75a03ec3-287jv` (16 restarts), `engine-image-ei-ff1cedad-5stqb` (63 restarts), `longhorn-manager-cvcch` (65 restarts) all stuck Unknown on .14 |
| 2026-03-24 ~08:00 | `alloy-6v5h9` stuck ContainerCreating for 19h |
| 2026-03-24 ~18:54 | Diagnosis confirmed via Kubernetes events showing `FailedCreatePodSandBox` with IPAM exhaustion error |
| 2026-03-24 ~19:00 | Root cause identified: `flannel-ipam-cleanup` DaemonSet not deployed (YAML parse error) |
| 2026-03-24 ~19:00 | YAML fixed; manual IPAM cleanup pod deployed to .14 |

---

## Root Cause

**Primary:** A YAML block scalar in `flannel-ipam-cleanup/daemonset.yaml` was
malformed. A shell line-continuation backslash (`\`) at the end of line 81 caused
line 82 to have zero indentation inside a YAML literal block scalar (`|`). The YAML
parser ended the block scalar prematurely, producing a parse error:

```
yaml: line 89: could not find expected ':'
```

ArgoCD reported `ComparisonError` and `sync.status: Unknown` for the
`flannel-ipam-cleanup` application from the moment it was first applied
(2026-03-23). The DaemonSet was **never deployed to any node**.

**Contributing factor:** Flannel host-local IPAM lease files
(`/var/lib/cni/networks/cbr0/10.42.X.X`) are written to disk and persist across
full node reboots. When pods are force-deleted or die before the kubelet can call
the CNI DEL hook, their IP leases are never released. Without the cleanup DaemonSet
running, these stale leases accumulate across every instability event, progressively
consuming the `/24` subnet until no IPs remain.

---

## Impact

- **Scheduling blocked on .14** for ~23 hours: all new pods requiring a Flannel IP
  failed with `FailedCreatePodSandBox`.
- **Longhorn degraded:** three DaemonSet pods (`longhorn-manager`, two
  `engine-image` instances) stuck `Unknown` on .14, leaving Longhorn storage
  running without a manager/engine instance on that node.
- **Alloy monitoring gap:** `alloy-6v5h9` stuck `ContainerCreating` for 19h —
  logs and metrics from .14 were not collected during this window.
- **ArgoCD app state:** `alloy` app in `Progressing` health; `longhorn` app in
  `Progressing` health — both caused by the stuck pods on .14.
- **No data loss.** Longhorn volumes remained accessible via the other three nodes.
- **No user-facing service disruption.** Immich, Home Assistant, Vaultwarden
  continued serving traffic normally.

---

## Resolution

### Immediate (manual)

Deployed a one-off privileged pod (`flannel-ipam-cleanup-manual`) with
`hostNetwork: true` to .14. The pod mounts `/var/lib/cni/networks` from the host
and deletes all `10.42.1.*` lease files. Since all Running pods on .14 at the time
of cleanup used `hostNetwork` (no active Flannel IPs), all lease files were stale
and could be safely deleted.

### Permanent (code fix)

Fixed the YAML syntax error in `flannel-ipam-cleanup/daemonset.yaml` by collapsing
the two-line shell `echo` statement onto a single line, eliminating the
zero-indentation line that broke the block scalar:

```yaml
# Before (broken — line 82 has 0 indentation, ends the YAML block scalar early)
                      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) \
removing stale Flannel lease ${IP} on ${MY_NODE_NAME}"

# After (fixed)
                      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) removing stale Flannel lease ${IP} on ${MY_NODE_NAME}"
```

Once merged to `main`, ArgoCD will deploy the cleanup DaemonSet to all nodes.
The DaemonSet runs every 30 minutes, deletes zero-byte lease files immediately,
and cross-references non-empty leases against `kubectl get pods` to evict stale
ones. It uses `hostNetwork: true` and `priorityClassName: system-node-critical`
so it can always be scheduled even when the node's Flannel subnet is exhausted.

---

## Why .14 Specifically?

Node .14 is the only cluster node using built-in Raspberry Pi storage (`rpi-256gb`
— microSD or eMMC) rather than an NVMe SSD. Slower storage I/O may contribute to
kubelet timeouts and higher pod crash rates under load, producing more ungraceful
pod exits and therefore more orphaned IPAM leases per instability event compared to
the NVMe-backed nodes.

The IPAM exhaustion pattern has also affected .12 (metallb-speaker at 351 restarts)
but has been most severe and recurring on .14 due to the combination of slower
storage and the cleanup job never running.

---

## Follow-up Actions

- [ ] Force-delete the three stuck Unknown pods on .14 after IPAM is cleared so
      Longhorn can reschedule them: `longhorn-manager-cvcch`,
      `engine-image-ei-ff1cedad-5stqb`, `engine-image-ei-75a03ec3-287jv`
- [ ] Verify `flannel-ipam-cleanup` DaemonSet deploys successfully on all nodes
      after the YAML fix merges to `main`
- [ ] Investigate metallb-speaker-cxv4m on .12 (351 restarts) — separate issue
- [ ] Investigate ArgoCD `argocd` app OutOfSync — likely a pending chart upgrade
- [ ] Consider migrating .14 to an NVMe SSD to reduce I/O-driven pod instability
- [ ] Export `GRAFANA_SERVICE_ACCOUNT_TOKEN` before future sessions so alert rules
      and Loki logs are queryable via MCP

---

## Lessons Learned

1. **A broken GitOps manifest silently prevents a safety net from deploying.**
   The `flannel-ipam-cleanup` app showed `sync.status: Unknown` from day one but
   this was not acted on. `ComparisonError` conditions on ArgoCD apps should be
   treated as alertable, not just informational.

2. **IPAM lease files survive reboots.** A node reboot is not sufficient to clear
   Flannel IPAM exhaustion. After any reboot that follows a period of Unknown pods,
   run the IPAM cleanup proactively before pods start rescheduling.

3. **YAML block scalars and shell line continuations don't mix.** A `\` at the end
   of a line inside a YAML `|` block scalar does not continue the line — it is a
   literal backslash. Any continuation character that strips the newline in the
   rendered shell script will produce a zero-indentation follow-up line, breaking
   the YAML.
