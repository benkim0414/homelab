#!/usr/bin/env bash
# Never trace secret-bearing assignments, even when invoked with bash -x.
set +x
set -euo pipefail
umask 077
# Resolve Bitwarden secrets and write them to .env.local.
# Run via: mise run secrets

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_DIR/.env.local"

# shellcheck source=/dev/null
source "$(dirname "$(command -v bw-ensure-unlocked)")/bw-ensure-unlocked" >/dev/null 2>&1

read_token() {
    local value
    # A sentinel preserves trailing newlines so validation cannot miss them.
    if ! value="$(bw-field "$@" 2>/dev/null && printf '.')"; then
        echo "Secret retrieval failed; cache unchanged." >&2
        return 1
    fi
    value="${value%.}"
    # bw-field uses jq -r, which appends one transport newline. Remove only that
    # terminator; any embedded or additional newline remains invalid.
    value="${value%$'\n'}"
    if [[ -z "$value" || "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
        echo "Invalid secret value; cache unchanged." >&2
        return 1
    fi
    printf '%s' "$value"
}

GRAFANA_SERVICE_ACCOUNT_TOKEN="$(read_token 0e456863-1143-4c67-9f11-1d3be2b14a2f grafana-mcp)"
ARGOCD_API_TOKEN="$(read_token 7f52fd96-a070-4e18-8f1c-9cb23b53104b argocd-mcp)"

TEMP_FILE="$(mktemp "$ENV_FILE.XXXXXXXXXX")"
trap 'rm -f -- "$TEMP_FILE"' EXIT
trap 'exit 1' HUP INT TERM
cat > "$TEMP_FILE" <<EOF
GRAFANA_SERVICE_ACCOUNT_TOKEN=$GRAFANA_SERVICE_ACCOUNT_TOKEN
ARGOCD_API_TOKEN=$ARGOCD_API_TOKEN
EOF
mv -fT -- "$TEMP_FILE" "$ENV_FILE"

echo "Wrote secrets to $ENV_FILE"
