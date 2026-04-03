#!/usr/bin/env bash
set -euo pipefail

# Ensure Bitwarden vault is unlocked (global helper from dotfiles).
# Must be sourced so BW_SESSION propagates to this shell.
# shellcheck source=/dev/null
source bw-ensure-unlocked

export GRAFANA_TOKEN
GRAFANA_TOKEN="$(bw-field 0e456863-1143-4c67-9f11-1d3be2b14a2f grafana-mcp)"

export ARGOCD_API_TOKEN
ARGOCD_API_TOKEN="$(bw-field 7f52fd96-a070-4e18-8f1c-9cb23b53104b argocd-mcp)"
