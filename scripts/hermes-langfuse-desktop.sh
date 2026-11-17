#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 || -z "$1" ]]; then
  printf '%s\n' 'usage: bash scripts/hermes-langfuse-desktop.sh PROFILE [hermes arguments...]' >&2
  exit 2
fi
profile=$1
shift
export HERMES_LANGFUSE_BASE_URL='https://langfuse.tailbd291c.ts.net'
export HERMES_LANGFUSE_CAPTURE=metadata
export HERMES_LANGFUSE_ENV=homelab-desktop
export HERMES_LANGFUSE_SAMPLE_RATE=1
export OTEL_SERVICE_NAME="hermes-desktop-${profile}"
exec hermes -p "$profile" "$@"
