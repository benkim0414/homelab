# Home Assistant upgrade proposal

Desired chart `0.3.86` → `0.3.91` changes the unoverridden server image from
`2026.10.1` → `2026.11.1`. The packaged chart comparison changes only
`Chart.yaml` (version/appVersion); templates and defaults are unchanged.
This is not deployment evidence or permission to sync.

Reviewed [chart release](https://github.com/pajikos/home-assistant-helm-chart/releases/tag/home-assistant-0.3.91),
[November release and backward-incompatible changes](https://www.home-assistant.io/blog/2026/11/04/release-202611/#backward-incompatible-changes)
and [2026.11.1 patch](https://github.com/home-assistant/core/releases/tag/2026.11.1).
The runtime integration/device/dashboard configuration is on the existing PVC,
not fully declared in Git. Do not infer compatibility from the Helm patch number.

## Before separately approved deployment

- Obtain and verify a current recoverable backup of the **complete `/config`**
  (including hidden `.storage`, automations, custom integrations and recorder
  database); preserve a pre-upgrade copy for rollback. No Home Assistant backup
  Job was present in the read-only namespace Job inventory on 2026-11-12.
  Two Longhorn replicas are not a backup. This proposal does not create a backup
  schedule or inspect archive contents, tokens or on-volume credentials.
- Review the full November breaking-change list against the configured instance.
  In particular: entity display names migrate (entity IDs do not); update custom
  cards first; HACS transitions to the built-in Marketplace. Do not install new
  integrations or enable new capabilities as part of this upgrade.
- Browser minimums are Chrome 67, Safari 15.4 and Firefox 98. Confirm kiosk/mobile
  clients before rollout. Calendar/Sun YAML offsets without `offset_type` change
  interpretation; Matter sensor units, climate turn-on and tilt-only covers change.
  Review removed Hue `None` effect, Ring legacy entities, Nanoleaf triggers and
  Bluesound actions, and all other installed-integration notices in the release.
- Z-Wave users need server >=3.11.0 (Z-Wave JS UI >=11.24.2 or app >=1.9.0).
  Runtime integration inventory has not been inspected here; applicability is an
  operator gate, not a reason to upgrade unrelated controllers automatically.
- November tightens client-ID validation for nonlocal IP access, including
  Tailscale IPs. The configured domain and existing trusted proxy ranges are
  preserved. Test login through both existing entry points; do not widen proxy
  trust or change authentication to bypass errors.
- Render/review the complete diff, preserving the current PVC/Longhorn class,
  `configuration.forceInit: false`, service exposure and manual sync. Check
  Prometheus operator/ServiceMonitor prerequisites and the existing token
  reference without displaying token values. Local render cannot prove token
  validity or successful authenticated metrics scraping.
- Allow startup/database migration time; verify login, dashboards, integrations,
  automations, recorder and metrics before accepting deployment. Stop the new
  process and restore the complete pre-upgrade config/database to a fresh
  destination for rollback; do not merely downgrade against migrated state.

No live change, backup, restore test, configuration read from the PVC or rollout
was performed during this preparation.

## Production rollout and memory sizing (2026-11-13)

The separately approved rollout deployed chart `0.3.91` / server `2026.11.1`
after an observed clean shutdown and a new full NAS checkpoint of the original
Longhorn volume. Independent old/target restored-data rehearsals passed startup
and recorder integrity checks; those disconnected amd64 tests do not establish
ARM64 memory headroom or device/client acceptance.

The ARM64 production pod initially became Ready and scraped successfully, then
experienced sustained pressure at its `512Mi` limit and a liveness-triggered
restart (exit 137, reason `Error`). The observed OOM counter was zero: this is
not evidence of a confirmed kernel OOM kill. A diagnostic version command timed
out; it may have added pressure, but was not established as the sole cause.
The restarted application itself remained near the cap. Avoid launching another
full Home Assistant Python runtime solely for a version check in a tight pod.

The declared limit is increased to `1Gi`, with the existing `256Mi` request,
probes, image, PVC, proxy/authentication settings and manual sync unchanged.
Node capacity was reviewed before proposing this reversible sizing change.
Publishing/rendering alone does not establish that the higher limit is deployed
or sufficient: verify actual pod limits, sustained readiness/restart counts,
memory headroom, authenticated Prometheus scraping and both existing entry points.
Owner login, dashboards, device controls and integration acceptance remain required.
