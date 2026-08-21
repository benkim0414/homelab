# Renovate

Renovate is deployed by ArgoCD from `argocd/apps/renovate.yaml` using the official Renovate Helm chart.

## GitHub Token

The CronJob expects a Kubernetes Secret named `renovate-token` in the `renovate` namespace with a `RENOVATE_TOKEN` key. Do not commit a plaintext Secret.

Create the SealedSecret after generating a GitHub token with repository write access:

```bash
kubectl create namespace renovate --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic renovate-token -n renovate \
  --from-literal=RENOVATE_TOKEN='<github-token>' \
  --dry-run=client -o yaml \
  | kubeseal \
      --controller-name sealed-secrets-controller \
      --controller-namespace kube-system \
      --format yaml > renovate/sealed-secret.yaml
```

Commit `renovate/sealed-secret.yaml` after confirming it contains only encrypted data.

## Validation

After the secret is synced, confirm the CronJob exists and inspect the latest run:

```bash
kubectl get cronjob -n renovate
kubectl get jobs -n renovate --sort-by=.status.startTime
kubectl logs -n renovate job/<job-name>
```
