#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)

NODE_SUMMARY=$(kubectl get nodes --no-headers \
  -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status' \
  2>/dev/null || echo "  kubectl unavailable")

UNHEALTHY=$(kubectl get pods -A --no-headers \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  2>/dev/null | grep -c . || echo "?")

ARGOCD_BAD=$(kubectl get applications -n argocd --no-headers \
  2>/dev/null | grep -cE '(OutOfSync|Degraded)' || echo "?")

echo "[cluster-status] Nodes:"
echo "$NODE_SUMMARY" | sed 's/^/  /'
echo "[cluster-status] Unhealthy pods (not Running/Succeeded): ${UNHEALTHY}"
echo "[cluster-status] ArgoCD apps OutOfSync/Degraded: ${ARGOCD_BAD}"
echo "[cluster-status] Run \$cluster-health for full diagnostic."
