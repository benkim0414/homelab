# Honcho

Self-hosted [Honcho v3](https://docs.honcho.dev) — persistent cross-session memory for the Hermes agent. Uses Groq's free tier (Llama 3.3 70B) for deriver/dialectic/summary passes, Gemini's free tier (text-embedding-004) for vector embeddings.

## Stack

| Component | Image |
|---|---|
| API + migrations | `ghcr.io/plastic-labs/honcho` (arm64, digest-pinned) |
| Deriver worker | same image, different command (`python -m src.deriver`) |
| Postgres 15 + pgvector | `pgvector/pgvector:pg15` (arm64, digest-pinned) |
| Redis 8.2 | `redis:8.2-alpine` (arm64, digest-pinned) |

Exposed on tailnet as **`https://honcho.tailbd291c.ts.net`** via Tailscale Ingress.

## First-time setup

### 1. Get API keys (both free, no credit card)

- **Groq:** [console.groq.com](https://console.groq.com) → API Keys → Create Key
- **Gemini:** [aistudio.google.com](https://aistudio.google.com) → Get API key

### 2. Seal secrets and mint JWT

```bash
export GROQ_API_KEY=gsk_...
export GEMINI_API_KEY=AIzaSy...
bash honcho/seal-secrets.sh
```

This generates `honcho/postgres-sealed-secret.yaml`, `honcho/honcho-sealed-secret.yaml`, and `honcho/hermes-jwt.txt`.

**`hermes-jwt.txt` is gitignored — do not commit it.**

### 3. Commit sealed secrets and push

```bash
git add honcho/postgres-sealed-secret.yaml honcho/honcho-sealed-secret.yaml
git commit -m "chore(honcho): seal secrets"
git push
```

ArgoCD picks up the commit and syncs. Watch progress:

```bash
kubectl -n honcho get pods -w
kubectl -n honcho rollout status deploy/honcho-api deploy/honcho-deriver
```

### 4. Verify the deployment

```bash
# All pods running
kubectl -n honcho get pods,svc,ingress

# pgvector extension + schema tables present
kubectl -n honcho exec sts/honcho-postgres -- \
  psql -U honcho -d honcho -c '\dx' -c '\dt'

# API health
curl -fsS https://honcho.tailbd291c.ts.net/health

# Authenticated probe (replace TOKEN with value from hermes-jwt.txt)
curl -fsS -H "Authorization: Bearer TOKEN" \
  https://honcho.tailbd291c.ts.net/v1/workspaces
```

### 5. Configure Hermes

```bash
# Append to ~/.hermes/.env (values from honcho/hermes-jwt.txt)
echo 'HONCHO_BASE_URL=https://honcho.tailbd291c.ts.net' >> ~/.hermes/.env
echo 'HONCHO_API_KEY=<token from hermes-jwt.txt>' >> ~/.hermes/.env

# Backup existing honcho config if present
cp ~/.hermes/honcho.json ~/.hermes/honcho.json.bak 2>/dev/null || true

# Run the setup wizard (answers: workspace=hermes, peerId=ben, aiPeer=hermes)
hermes honcho setup

# Confirm connection
hermes honcho status
```

Hermes activates the memory provider via `memory.provider: honcho` in `config.yaml`. The plugin reads `HONCHO_BASE_URL` and `HONCHO_API_KEY` from `.env` and injects per-session context into the `<memory-context>` block of each user message.

## Upgrading Honcho

1. Resolve the new arm64 digest: `docker manifest inspect ghcr.io/plastic-labs/honcho:latest | jq -r '.manifests[] | select(.platform.architecture=="arm64") | .digest'`
2. Update the `image:` digest in `honcho-api-deployment.yaml` and `honcho-deriver-deployment.yaml`.
3. Migrations run automatically when the API pod restarts (`entrypoint.sh` calls `scripts/provision_db.py`).
4. Commit and push — ArgoCD rolls out.

## Backup and restore

Daily pg_dump at 03:15 to the `honcho-backups` PVC (20 Gi, Longhorn), retaining last 7 dumps.

Restore from a dump:

```bash
# Copy dump out of PVC
kubectl -n honcho cp honcho-pg-backup-<pod>:/backups/honcho-<TS>.dump ./honcho-restore.dump

# Restore
kubectl -n honcho exec -it sts/honcho-postgres -- bash
  psql -U honcho -c 'DROP DATABASE honcho;'
  psql -U honcho -c 'CREATE DATABASE honcho;'
  pg_restore -U honcho -d honcho /tmp/honcho-restore.dump
```

## Groq rate limit tuning

Groq free tier: 30 RPM, 6,000 TPM, 14,400 RPD. If the deriver hits the TPM ceiling:

1. Lower `DERIVER_MAX_INPUT_TOKENS` to `2048` in `honcho-config.yaml`.
2. Raise `DERIVER_POLLING_SLEEP_INTERVAL_SECONDS` to `3.0` or higher.
3. Commit and push — ArgoCD applies the ConfigMap and the deriver pod picks up the new values on restart.
