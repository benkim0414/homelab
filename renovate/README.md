# Renovate

Renovate has an Application in `argocd/apps/renovate.yaml` using the official
Renovate Helm chart. It is currently excluded from root discovery; secret creation
does not authorize activation.

## Update detection decisions

`renovate.json5` is repository policy; the chart's config selects this repository
and requires that policy to exist. Vaultwarden values contain an image tag without
its repository, so a custom regex manager associates it with
`docker.io/vaultwarden/server`. Vaultwarden updates are grouped without the
monthly infrastructure delay: an earlier stale pin caused client login
compatibility problems. Infrastructure and monitoring retain their monthly
schedules. The CronJob uses `concurrencyPolicy: Forbid` to prevent overlapping runs.

Review proposed chart and server image versions together; a chart's appVersion
label does not override an explicitly pinned image. Git history records the
original one-tag Vaultwarden correction; the current manifests define its pin.

## GitHub Token

The CronJob expects a Kubernetes Secret named `renovate-token` in the `renovate` namespace with a `RENOVATE_TOKEN` key. Do not commit a plaintext Secret.

With explicit authorization, create the SealedSecret using an approved GitHub
token. Follow the [Sealed Secrets runbook](../docs/operations/sealed-secrets.md).
Prepare a restricted local env file containing `RENOVATE_TOKEN` outside tracked
files; do not put the token in shell arguments or history. Replace the example
input path below:

```bash
kubectl create namespace renovate --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic renovate-token -n renovate \
  --from-env-file=path/to/local-renovate-token.env \
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
