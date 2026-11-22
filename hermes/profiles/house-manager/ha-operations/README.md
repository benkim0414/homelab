# Fixed Home Assistant workload operations (prepared, not deployed)

This is a credential-free **source bundle**, not a new generic Kubernetes MCP
server. The broker receives the existing dedicated HA bot's bearer token for one
request, validates it through HA's fixed WebSocket endpoint, requires an exact
non-admin/non-owner user ID, and discards it. It creates/stores no shared secret
and never reads HA authentication storage. Only the broker receives its own
rotating projected Kubernetes service-account token; Hermes receives none.

## API contract for the trusted connector

Fixed base: `http://ha-operations.hermes.svc.cluster.local:8080`.
Only these HTTP requests exist:

| Method/path | Exact body | Effect |
| --- | --- | --- |
| `POST /v1/health` | `{}` | Sanitized readiness, replica, revision, pod and container restart-count diagnostics |
| `POST /v1/restart` | `{}` | Request a normal rolling restart of the existing HA StatefulSet |

Supply exactly `Content-Type: application/json` and the existing HA bot bearer
header through the connector's normal secret provider, **never tool arguments**.
Do not expose a URL, workload, namespace, JSON patch, token, exec or shell parameter
to the model. Do not log headers or include them in exceptions. Only expose two
zero-argument typed tools. The body is deliberately strict: the two bytes `{}`,
no extra keys, trailing whitespace, query parameters or browser Origin header.

The broker has no logs API, shell, exec, Secret, list/watch, scaling, deployment,
image, storage, arbitrary patch or physical-device operation. It GETs only
StatefulSet `home-assistant` and pod `home-assistant-0` in namespace
`home-assistant`. RBAC restricts these exact resource names. The only write
constructible through the API is a timestamp under the StatefulSet pod-template
annotations. Kubernetes RBAC cannot constrain individual patch fields: compromise
of the broker process itself would permit arbitrary patches **to that one
StatefulSet**. The model-facing API cannot construct such patches. If that residual
risk is unacceptable, an independently reviewed admission policy is required;
this bundle does not change cluster admission/security policy.

## Restart safety and limitations

- The live workload was read-only verified as **StatefulSet**, not Deployment:
  one replica, RollingUpdate, partition zero, revision converged. The current
  pod was Running/Ready with zero restarts. No workload or PVC was changed.
- Require that topology, observed generation, converged revision, one updated
  replica, a non-terminating pod, and matching StatefulSet controller ownership.
  A not-ready pod is not by itself a refusal: restarting the unchanged workload
  can recover some application failures. Pending rollouts and owner drift refuse.
- Preserve image, replicas, strategy, storage/PVC identity and all other template
  data. Preserve existing annotations. Never delete a pod, force/replace, or patch
  its contents. Use resourceVersion/UID JSON-patch tests to refuse concurrent drift.
- Serialize requests. A persisted template annotation imposes a five-minute
  cooldown across broker restarts and replicas. Invalid/future stamps refuse.
  No automatic retry of an ambiguous PATCH. Read back the exact StatefulSet and
  verify UID and annotation before reporting `restart_requested=true`.
- `annotation_verified=true` is **not rollout verification**. Follow with health
  reads until observed generation, revision, pod readiness and restart counters
  settle.  A response explicitly sets `rollout_verified=false`.
- A live restart annotation can produce an ArgoCD OutOfSync difference. Preserve
  manual sync. Before a later HA sync, review whether removing that annotation
  would itself restart HA; do not automatically sync/revert it or broaden ignore
  rules without an explicit GitOps field-ownership decision.
- Every restart requires a **fresh successful HA config check**, after exact bot
  authentication and before the Kubernetes mutation. The application callback
  POSTs the exact `{}` body and the same bearer to the fixed existing HA origin:
  `http://home-assistant.home-assistant.svc.cluster.local:8123/api/house_manager_general/check-config`.
  Parent integration supplies this authenticated facade around native
  `async_check_ha_config_file`; this read-only source-config validation is an
  accepted prerequisite, not a config edit, service call or second HA runtime.
  No HA admin token or exec permission is needed.
- The facade must return exactly `{"valid":true,"checked_at":"<ISO UTC>"}` to
  permit restart. False validity, missing callback, missing/unavailable route,
  malformed/extra fields, non-UTC or stale timestamps, HTTP errors, redirects and
  timeouts fail closed without PATCH. The broker bounds the response to 4096
  bytes and call to 30 seconds, does not follow redirects or use environment
  proxies, never returns raw upstream errors, and never caches check results.
  A receipt must be at most 60 seconds old, allowing five seconds of future clock
  skew. Health-only diagnostics do not require the config-check route.
  Successful restart responses include `config_check_verified=true` and the
  normalized UTC `config_checked_at`, but still do not prove rollout success.
  Config can change after validation: this is not a lock on HA's source files.
  The facade must be deployed and bot-authorized before restart acceptance.
- HA itself must answer authentication. When HA is down/unresponsive or the bot
  token is revoked, this broker fails closed, including diagnostics. Recovery
  then belongs to the operator; there is deliberately no cached authorization,
  unauthenticated recovery endpoint or new shared recovery token.
- A restart interrupts HA and automations briefly. It is not a backup/restore,
  upgrade, PVC migration, hazardous device operation or proof of physical state.

## Network and credential boundaries

The broker is ClusterIP-only, no ingress/Tailscale/NodePort. A new NetworkPolicy
allows TCP 8080 only from `app=hermes` in namespace `hermes`. An additive Hermes
egress policy permits only that destination/port. Broker egress is limited to HA
8123, CoreDNS, and Kubernetes API ClusterIP plus the three read-only observed
control-plane endpoint IPs on 443/6443. Recheck endpoints/CNI behavior before
rollout. Apply the broker policy **before** creating its Deployment.

This reuses the existing HA in-cluster HTTP trust model: HA WebSocket and broker
HTTP traffic are not TLS encrypted. NetworkPolicy is pod-level, not profile-level,
and is not cryptographic workload identity. Other profiles in the Hermes pod share
network reachability, but cannot authenticate without this bot's existing token.
Keep tokens in the trusted connector process, not the model. Host/node compromise,
NetworkPolicy enforcement gaps, and principals authorized to create/relabel pods
are outside this boundary. If the acceptance policy requires encryption in transit
or separate per-profile network identity, do not deploy this design until existing
mTLS/service-mesh identity or an equivalent separately reviewed mechanism exists.
Never compensate with an unauthenticated endpoint or a newly shared static key.

## Render, verify, integrate

Local dependencies: Python, PyYAML, aiohttp. Runtime reuses the repository's
existing digest-pinned Hermes image solely as a Python/aiohttp runtime: explicit
Python command, UID 10000, no s6/root bootstrap, all capabilities dropped,
read-only filesystem, no PVC/host mounts. Runtime image startup has **not** been
exercised by these local tests; verify aiohttp and the Python path in that image
before rollout.

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover \
  -s hermes/profiles/house-manager/ha-operations -p 'test_*.py' -v
# BOT_USER_ID is a non-secret HA user ID, never a token. Obtain it from the
# existing trusted identity receipt/configuration without reading token values.
python -B hermes/profiles/house-manager/ha-operations/render.py \
  --bot-user-id "$BOT_USER_ID" > "$TMPDIR/ha-operations-rendered.yaml"
kubectl apply --dry-run=client --validate=strict -f "$TMPDIR/ha-operations-rendered.yaml"
```

The generator refuses missing/malformed IDs. `resources.yaml.in` is deliberately
not a selected Kubernetes manifest. No root `ha-operations.yaml` is generated or
ArgoCD include altered automatically: the exact bot ID and integration review are
prerequisites. Parent integration may generate
`hermes/profiles/house-manager/ha-operations.yaml`, deliberately add it to the
Application include, run the repository verifier, review cross-namespace RBAC and
the complete diff, and perform a staged no-prune rollout under its authorization.
Do not apply the `.in` template directly; its empty identity is fail-closed.

Local acceptance covers HTTP operations and rejection paths, an actual local
WebSocket auth/current_user exchange against a **synthetic** HA server, exact
patch construction, guarded restart/readback/cooldown, upstream error redaction,
and manifest RBAC/caller policies. All 20 unittest cases passed, including fixed
HTTP config-check transport, exact body/bearer forwarding, invalid/unavailable or
absent callback refusal without PATCH, fresh receipt validation, no result caching,
redirect/error/oversize rejection, and rendered source/checksum consistency. Rendering with a
synthetic non-secret bot ID passed `kubectl apply --dry-run=client --validate=strict`
for all eight resources. No resource was created. These are not production authentication,
NetworkPolicy, runtime-image, or rollout acceptance. Hindsight recall was not
available in this subagent's tools; no historical claims were substituted for
live verification.

Live acceptance must use configured auth normally without extracting it: verify
right-bot health success, wrong/missing-token refusal, non-Hermes source denial,
Hermes-only token custody, exact service-account allowed/denied permissions, and
one separately authorized restart with post-restart readiness and unchanged PVC
identity. Diagnostics/auth tests must not operate physical devices. Stop if HA is
unavailable, authentication changes, or the complete rollout diff is not reviewed.

To roll back, first disable only the two new connector tools. Stop/remove the new
broker Deployment and its dedicated policies/service/RBAC through a reviewed
operation; do not remove Hermes's existing policy or any HA/PVC resources. Leaving
the harmless restart timestamp on the HA template does not require a second
restart or template rollback.
