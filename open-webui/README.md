# Open WebUI

Self-hosted chat UI pointed at the Hermes Agent OpenAI-compatible API on the
Framework Desktop (tailnet name `fd`, port `8642`). Reachable only from the
tailnet at `https://open-webui.tailbd291c.ts.net` — no LoadBalancer, no
public ingress, no cloud LLM keys.

## Architecture

```
Tailnet device (browser)
        │  https://open-webui.tailbd291c.ts.net  (Tailscale Ingress, auto LE TLS)
        ▼
┌────────────────────────────────────────────────────────────────────────┐
│  K3s cluster                                                           │
│                                                                        │
│  open-webui Pod ──► hermes-egress Service (ExternalName)               │
│                              │                                         │
│                              │ tailscale.com/tailnet-fqdn annotation   │
│                              ▼                                         │
│                    Tailscale operator egress proxy                     │
└──────────────────────────────┼─────────────────────────────────────────┘
                               │
                               ▼ tailnet
                  Framework Desktop "fd" :8642 (Hermes API)
```

## Files

| File                      | Purpose                                                       |
|---------------------------|---------------------------------------------------------------|
| `namespace.yaml`          | Namespace `open-webui`                                        |
| `values.yaml`             | Helm values for the upstream `open-webui` chart               |
| `hermes-egress.yaml`      | ExternalName Service that the Tailscale operator proxies      |
| `tailscale-ingress.yaml`  | Tailscale Ingress exposing the chart's Service on the tailnet |
| `sealed-secret.yaml`      | SealedSecret holding the Hermes bearer (`OPENAI_API_KEY`)     |

## Initial setup

### 1. On the Framework Desktop (Hermes side)

Generate a bearer token and capture the Tailscale IP:

```bash
~/workspace/hermes/setup/apply-hermes-config.sh
```

Paste the output snippet into `~/.hermes/.env`. **Then add this CORS origin
to that file** (append comma-separated if `API_SERVER_CORS_ORIGINS` is
already set):

```
API_SERVER_CORS_ORIGINS=https://open-webui.tailbd291c.ts.net
```

Restart `hermes-gateway` so the new key + CORS take effect.

### 2. On this machine — seal the bearer

```bash
kubectl create secret generic open-webui-credentials -n open-webui \
  --from-literal=OPENAI_API_KEY='<PASTE_API_SERVER_KEY_FROM_HERMES>' \
  --dry-run=client -o yaml \
| kubeseal \
    --controller-name sealed-secrets-controller \
    --controller-namespace kube-system \
    --format yaml > open-webui/sealed-secret.yaml
```

Commit the resulting `open-webui/sealed-secret.yaml`.

### 3. ArgoCD sync

The `open-webui` Application autosyncs once committed and merged. Force a
sync via `argocd app sync open-webui` or the UI if needed.

## Rotation

To rotate the bearer:

1. Re-run `apply-hermes-config.sh` on the Framework, paste the new value,
   restart `hermes-gateway`.
2. Re-run the kubeseal command above with the new key, overwrite
   `open-webui/sealed-secret.yaml`, commit.
3. ArgoCD picks up the new SealedSecret; the controller decrypts and
   updates the underlying Secret. Restart the open-webui Pod
   (`kubectl rollout restart statefulset/open-webui -n open-webui`) so it
   re-reads the env.

## Verify reachability

From any tailnet device:

```bash
curl https://open-webui.tailbd291c.ts.net/health
```

From inside the cluster (egress sanity check):

```bash
kubectl run -n open-webui --rm -it curl --image=curlimages/curl --restart=Never -- \
  curl -s http://hermes-egress.open-webui.svc.cluster.local:8642/v1/models \
       -H "Authorization: Bearer $(kubectl get secret -n open-webui open-webui-credentials -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d)"
```
