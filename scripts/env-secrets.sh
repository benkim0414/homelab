#!/usr/bin/env bash
set -euo pipefail

# Ensure Bitwarden vault is unlocked
if ! bw status 2>/dev/null | jq -e '.status == "unlocked"' &>/dev/null; then
  echo "Bitwarden vault is locked. Unlocking..." >&2
  BW_SESSION="$(bw unlock --raw)"
  export BW_SESSION
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export GRAFANA_SERVICE_ACCOUNT_TOKEN
GRAFANA_SERVICE_ACCOUNT_TOKEN="$("$SCRIPT_DIR/bw-field.sh" 0e456863-1143-4c67-9f11-1d3be2b14a2f grafana-mcp)"

export ARGOCD_API_TOKEN
ARGOCD_API_TOKEN="$("$SCRIPT_DIR/bw-field.sh" ac83bfad-e137-4330-99ee-5f24c42ce2a3 argocd-mcp)"
