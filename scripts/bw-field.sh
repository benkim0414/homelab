#!/usr/bin/env bash
set -euo pipefail
# Usage: bw-field.sh <item-uuid> <field-name>
bw get item "$1" | jq -r --arg f "$2" '.fields[] | select(.name==$f) | .value'
