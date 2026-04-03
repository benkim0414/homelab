#!/usr/bin/env bash
set -euo pipefail
# Resolve Bitwarden secrets and write them to .env.local.
# Run via: mise run secrets

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_DIR/.env.local"

# shellcheck source=/dev/null
source "$(dirname "$(command -v bw-ensure-unlocked)")/bw-ensure-unlocked"

GRAFANA_SERVICE_ACCOUNT_TOKEN="$(bw-field 0e456863-1143-4c67-9f11-1d3be2b14a2f grafana-mcp)"
ARGOCD_API_TOKEN="$(bw-field 7f52fd96-a070-4e18-8f1c-9cb23b53104b argocd-mcp)"

cat > "$ENV_FILE" <<EOF
GRAFANA_SERVICE_ACCOUNT_TOKEN=$GRAFANA_SERVICE_ACCOUNT_TOKEN
ARGOCD_API_TOKEN=$ARGOCD_API_TOKEN
EOF
chmod 600 "$ENV_FILE"

echo "Wrote secrets to $ENV_FILE"
