#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null

KUBECTL_TIMEOUT=${KUBECTL_TIMEOUT:-5s}

kubectl_read() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "${KUBECTL_TIMEOUT}" kubectl "$@"
  else
    kubectl "$@"
  fi
}

NODE_SUMMARY=$(kubectl_read get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.conditions[?(@.type=="Ready")]}{.type}{"\t"}{.status}{"\n"}{end}{end}' \
  2>/dev/null || echo "kubectl unavailable")

if UNHEALTHY_RAW=$(kubectl_read get pods -A --no-headers 2>/dev/null); then
  if [[ -n "${UNHEALTHY_RAW}" ]]; then
    UNHEALTHY=$(printf '%s\n' "${UNHEALTHY_RAW}" | awk '
      function ready_ok(value) {
        split(value, parts, "/")
        return parts[1] == parts[2] && parts[2] != "0"
      }

      $4 == "Completed" || $4 == "Succeeded" { next }
      $4 != "Running" || !ready_ok($3) { count++ }
      END { print count + 0 }
    ')
  else
    UNHEALTHY=0
  fi
else
  UNHEALTHY="unknown (kubectl unavailable)"
fi

if ARGOCD_BAD_RAW=$(kubectl_read get applications -n argocd --no-headers 2>/dev/null); then
  if [[ -n "${ARGOCD_BAD_RAW}" ]]; then
    ARGOCD_BAD=$(printf '%s\n' "${ARGOCD_BAD_RAW}" | grep -cE '(OutOfSync|Degraded)' || true)
  else
    ARGOCD_BAD=0
  fi
else
  ARGOCD_BAD="unknown (kubectl unavailable)"
fi

echo "[cluster-status] Nodes:"
echo "$NODE_SUMMARY" | sed $'s/\t/ /g; s/^/  /'
echo "[cluster-status] Unhealthy pods: ${UNHEALTHY}"
echo "[cluster-status] ArgoCD apps OutOfSync/Degraded: ${ARGOCD_BAD}"
echo "[cluster-status] Run \$cluster-health for full diagnostic."
