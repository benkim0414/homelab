#!/usr/bin/env bash
set -euo pipefail

# Ensure Bitwarden vault is unlocked (global helper from dotfiles).
# Must be sourced so BW_SESSION propagates to this shell.
# shellcheck source=/dev/null
source bw-ensure-unlocked

export GRAFANA_SERVICE_ACCOUNT_TOKEN
GRAFANA_SERVICE_ACCOUNT_TOKEN="$(bw-field 0e456863-1143-4c67-9f11-1d3be2b14a2f grafana-mcp)"

export ARGOCD_API_TOKEN
ARGOCD_API_TOKEN="$(bw-field ac83bfad-e137-4330-99ee-5f24c42ce2a3 argocd-mcp)"
