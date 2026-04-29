#!/usr/bin/env bash
# seal-secrets.sh — Generate and seal Honcho secrets for the homelab cluster.
#
# Prerequisites:
#   - kubeseal installed and your kubeconfig points to the homelab cluster
#   - GROQ_API_KEY set (free from console.groq.com)
#   - GEMINI_API_KEY set (free from aistudio.google.com)
#   - PyJWT installed: pip install PyJWT
#
# Usage:
#   export GROQ_API_KEY=gsk_...
#   export GEMINI_API_KEY=AIzaSy...
#   bash honcho/seal-secrets.sh
#
# Outputs:
#   honcho/postgres-sealed-secret.yaml  — commit this
#   honcho/honcho-sealed-secret.yaml    — commit this
#   honcho/hermes-jwt.txt               — gitignored, contains the Hermes bearer token

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Validate prerequisites ───────────────────────────────────────────────────
command -v kubeseal >/dev/null 2>&1 || { echo "ERROR: kubeseal not installed"; exit 1; }
command -v kubectl  >/dev/null 2>&1 || { echo "ERROR: kubectl not installed";  exit 1; }
python3 -c "import jwt" 2>/dev/null  || { echo "ERROR: PyJWT not installed (pip install PyJWT)"; exit 1; }

[[ -n "${GROQ_API_KEY:-}"   ]] || { echo "ERROR: GROQ_API_KEY is not set";   exit 1; }
[[ -n "${GEMINI_API_KEY:-}" ]] || { echo "ERROR: GEMINI_API_KEY is not set"; exit 1; }

# ── Generate random credentials ──────────────────────────────────────────────
PG_PASS=$(openssl rand -base64 24 | tr -d '/+=')
JWT_SECRET=$(openssl rand -hex 32)

echo "Generated PG password and JWT secret."

# ── Seal postgres credentials ─────────────────────────────────────────────────
kubectl create secret generic honcho-postgres-credentials \
  --namespace honcho \
  --dry-run=client \
  --from-literal=POSTGRES_USER=honcho \
  --from-literal=POSTGRES_PASSWORD="${PG_PASS}" \
  --from-literal=POSTGRES_DB=honcho \
  -o yaml \
| kubeseal \
    --controller-namespace sealed-secrets \
    --format yaml \
> "${SCRIPT_DIR}/postgres-sealed-secret.yaml"

echo "Wrote postgres-sealed-secret.yaml"

# ── Seal Honcho application secrets ──────────────────────────────────────────
kubectl create secret generic honcho-secrets \
  --namespace honcho \
  --dry-run=client \
  --from-literal=AUTH_JWT_SECRET="${JWT_SECRET}" \
  --from-literal=LLM_OPENAI_API_KEY="${GROQ_API_KEY}" \
  --from-literal=LLM_GEMINI_API_KEY="${GEMINI_API_KEY}" \
  -o yaml \
| kubeseal \
    --controller-namespace sealed-secrets \
    --format yaml \
> "${SCRIPT_DIR}/honcho-sealed-secret.yaml"

echo "Wrote honcho-sealed-secret.yaml"

# ── Mint a long-lived JWT for the Hermes agent ───────────────────────────────
HERMES_JWT=$(JWT_SECRET="${JWT_SECRET}" python3 -c "
import os, time, jwt
secret = os.environ['JWT_SECRET']
token = jwt.encode(
    {'sub': 'hermes', 'aud': 'honcho', 'exp': int(time.time()) + 10 * 365 * 86400},
    secret,
    algorithm='HS256',
)
print(token)
")

cat > "${SCRIPT_DIR}/hermes-jwt.txt" <<EOF
# Honcho JWT for the Hermes agent (valid 10 years, gitignored — do not commit).
# Append these lines to ~/.hermes/.env:
#
#   HONCHO_BASE_URL=https://honcho.tailbd291c.ts.net
#   HONCHO_API_KEY=${HERMES_JWT}
#
# Then run: hermes honcho setup
EOF

echo "Wrote hermes-jwt.txt (gitignored — do not commit)"
echo ""
echo "Done. Next steps:"
echo "  git add honcho/postgres-sealed-secret.yaml honcho/honcho-sealed-secret.yaml"
echo "  git commit -m 'chore(honcho): seal secrets'"
echo "  git push"
echo ""
echo "After ArgoCD syncs and pods are healthy, configure Hermes:"
echo "  cat honcho/hermes-jwt.txt"
