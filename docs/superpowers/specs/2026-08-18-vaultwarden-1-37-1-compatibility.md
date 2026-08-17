# Vaultwarden 1.37.1 Compatibility Fix

## Goal

Align the deployed Vaultwarden server image with the current Helm chart's
application version so clients and chart defaults target the same supported
Vaultwarden release.

## Evidence

- ArgoCD currently renders `guerzon/vaultwarden` chart `0.46.0`, whose
  application version is `1.37.1`.
- `vaultwarden/values.yaml` overrides the chart image tag with `1.35.8`.
- The live StatefulSet and pod therefore run
  `docker.io/vaultwarden/server:1.35.8` even though the chart labels the
  workload as version `1.37.1`.

## Approved Approach

Change only `vaultwarden/values.yaml` so `image.tag` is `"1.37.1"`. Preserve
the floating chart revision and every other Vaultwarden setting. Validate the
YAML and verify the configured image tag before committing.

## Boundaries

- Do not change the Helm chart revision or ArgoCD Application.
- Do not mutate or manually sync the live cluster.
- Do not change storage, networking, secrets, sign-up policy, or admin-token
  configuration.
- Do not add a repository test framework for this one-value GitOps change.

## Validation

- Parse `vaultwarden/values.yaml` as YAML.
- Assert that the rendered input value `image.tag` equals `1.37.1`.
- Review the final diff to confirm the image pin is the only runtime change.
