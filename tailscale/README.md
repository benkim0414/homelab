# Tailscale Kubernetes Operator

[Tailscale Kubernetes operator](https://tailscale.com/kb/1236/kubernetes-operator) deployed on the K3s Raspberry Pi 5 cluster. Exposes in-cluster services over the Tailscale tailnet with automatic HTTPS (LetsEncrypt).

## Architecture

```
Tailnet device (phone/laptop)
        │
        │  https://<service>.<tailnet>.ts.net
        ▼
┌─────────────────────────────────────────────┐
│  K3s Cluster                                │
│                                             │
│  tailscale-operator (ns: tailscale)         │
│       │                                     │
│       │ watches Ingress (class: tailscale)  │
│       ▼                                     │
│  ts-ingress proxy Pod ──► backend Service   │
│  (auto TLS via LE)                          │
└─────────────────────────────────────────────┘
```

The operator watches for Ingress resources with `ingressClassName: tailscale` and creates a proxy Pod (StatefulSet) for each. The proxy joins the tailnet as a device, obtains a LetsEncrypt TLS certificate, and forwards traffic to the backend service's ClusterIP.

## Prerequisites

1. **MagicDNS** and **HTTPS Certificates** enabled in the [Tailscale admin console](https://login.tailscale.com/admin/dns).

2. **ACL tags** added in the [ACL editor](https://login.tailscale.com/admin/acls/file):

   ```json
   "tagOwners": {
     "tag:k8s-operator": [],
     "tag:k8s": ["tag:k8s-operator"]
   }
   ```

3. **OAuth client** created in [Settings → OAuth clients](https://login.tailscale.com/admin/settings/oauth):
   - Scopes: **Devices Core** (write), **Auth Keys** (write), **Services** (write)
   - Tag: `tag:k8s-operator`
   - Save the Client ID and Client Secret

## Deploy

```bash
helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update

helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --namespace=tailscale \
  --create-namespace \
  --set-string oauth.clientId="<CLIENT_ID>" \
  --set-string oauth.clientSecret="<CLIENT_SECRET>" \
  -f tailscale/values.yaml \
  --wait
```

OAuth credentials are passed via `--set-string` at install time and not committed to Git.

## Verify

```bash
# Operator pod running
kubectl get pods -n tailscale

# Operator appears as a device in the Tailscale admin console
# https://login.tailscale.com/admin/machines
```

## Exposing a Service

Create an Ingress with `ingressClassName: tailscale`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-service-tailscale
  namespace: my-namespace
spec:
  defaultBackend:
    service:
      name: my-service
      port:
        number: 8080
  ingressClassName: tailscale
  tls:
    - hosts:
        - my-service  # becomes my-service.<tailnet>.ts.net
```

The `tls.hosts[0]` value becomes the device name on the tailnet.

### Currently Exposed Services

| Service | Tailnet URL | Namespace |
|---------|-------------|-----------|
| Immich | `https://immich.<tailnet>.ts.net` | immich |

## Upgrade

```bash
helm upgrade tailscale-operator tailscale/tailscale-operator \
  --namespace=tailscale \
  --set-string oauth.clientId="<CLIENT_ID>" \
  --set-string oauth.clientSecret="<CLIENT_SECRET>" \
  -f tailscale/values.yaml \
  --wait
```

## Uninstall

```bash
# Remove all Tailscale Ingress resources first
kubectl delete ingress -l tailscale.com/managed=true --all-namespaces

# Uninstall the operator
helm uninstall tailscale-operator -n tailscale
kubectl delete namespace tailscale
```
