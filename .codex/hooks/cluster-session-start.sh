#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)

NODE_SUMMARY=$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.conditions[?(@.type=="Ready")]}{.type}{"\t"}{.status}{"\n"}{end}{end}' \
  2>/dev/null || echo "  kubectl unavailable")

UNHEALTHY_RAW=$(kubectl get pods -A --no-headers \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  2>/dev/null || true)
if [[ -n "${UNHEALTHY_RAW}" ]]; then
  UNHEALTHY=$(printf '%s\n' "${UNHEALTHY_RAW}" | wc -l | tr -d ' ')
else
  UNHEALTHY=0
fi

ARGOCD_BAD_RAW=$(kubectl get applications -n argocd --no-headers 2>/dev/null || true)
if [[ -n "${ARGOCD_BAD_RAW}" ]]; then
  ARGOCD_BAD=$(printf '%s\n' "${ARGOCD_BAD_RAW}" | grep -cE '(OutOfSync|Degraded)' || true)
else
  ARGOCD_BAD=0
fi

echo "[cluster-status] Nodes:"
echo "$NODE_SUMMARY" | sed $'s/\t/ /g; s/^/  /'
echo "[cluster-status] Unhealthy pods (not Running/Succeeded): ${UNHEALTHY}"
echo "[cluster-status] ArgoCD apps OutOfSync/Degraded: ${ARGOCD_BAD}"
echo "[cluster-status] Run \$cluster-health for full diagnostic."
