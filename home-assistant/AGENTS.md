# Home Assistant instructions

These rules also apply to `argocd/apps/home-assistant.yaml`. Follow
[ArgoCD instructions](../argocd/AGENTS.md) for chart sources and manual sync, and
[monitoring instructions](../monitoring/AGENTS.md) for Prometheus integration.

## Code Review Rules

- Flag rollouts that create a ServiceMonitor before monitoring CRDs/operator are
  installed. Establish those prerequisites first, or explicitly disable the monitor
  until they exist.
- Flag metrics credential changes that rely only on SealedSecret decryption.
  `home-assistant-prometheus-token` must contain a token valid in the target Home
  Assistant instance; any access or rotation needs authorization. An old restored
  token is not necessarily valid in a fresh instance.

## Verification

- Check `serviceMonitor.bearerToken` name/key references and raw-manifest inclusion
  without reading token values. Local rendering cannot prove credential validity.
- For an authorized live metrics check, confirm Prometheus target health and
  successful authenticated scraping; do not report success from decryption alone.
