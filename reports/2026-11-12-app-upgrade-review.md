# Application upgrade review — 2026-11-12

Status: candidate desired-state changes, **not evidence of deployment**.

Local validation was repeated after all app candidate edits against base
`80213556973e48cf247bd1ff19deb7437bbbc3c3`: 19 Applications and 472 rendered
resources, all 472 schemas valid with none skipped, no desired resource removals.
The unit suite reported 78 tests with 6 skipped; all 5 Conftest policy tests passed.
This does not satisfy the remote exact-commit CI or generated-to-live diff gates.
The operator requested all app upgrades and explicitly approved app-scoped commits,
push and staged no-prune rollout. This does not approve unresolved migrations,
credential changes, new automation or materially disruptive operations.

## Application candidates and remaining gates

- **Hermes** 0.22.2 -> 0.23.1 and **OpenClaw** 2026.10.5 -> 2026.11.3:
  target multiarch index digests verified and preserved on every image reference.
  Startup modifies persisted config/session state. Test migrations on isolated,
  credential-sanitized state before production; preserve selected model/provider,
  auth, API-server and messaging posture. [Hermes review](../hermes/README.md#upgrade-review-v0231-prepared-not-deployed),
  [OpenClaw review](../openclaw/README.md#upgrade-review-2026113-prepared-not-deployed).
  OpenClaw has **no live backup/recovery Jobs or completed Longhorn backup** for
  its source volume. Its declarative backup files do not satisfy recovery gates;
  do not activate their schedules during this upgrade.
- **Immich** 3.2.0 -> 3.4.1, chart unchanged at 0.13.4: irreversible data changes,
  face backfill and index builds require an isolated restored-checkpoint rehearsal,
  matching pre-upgrade database/media checkpoints and a write-frozen rollout.
  See [migration/recovery review](../immich/UPGRADE-v3.4.md). Do not repeat the old
  PG14-to-PG16 cutover or use its stale rollback database for this upgrade.
- **Home Assistant** chart 0.3.86 -> 0.3.91 / app 2026.10.1 -> 2026.11.1:
  no backup Job was found; establish complete recoverable `/config` coverage and
  review actual integrations/custom cards and November breaking changes before
  startup. See [instance compatibility gates](../home-assistant/README.md).
- **Vaultwarden** chart 0.46.3 -> 0.46.4 / desired server 1.37.4 -> 1.37.5:
  live baseline is 1.37.1. Review that full path, persisted numeric/cron settings,
  proxy/client compatibility and complete SQLite/attachment recovery. No auth or
  client credential rotation is part of the proposal. [Review](../vaultwarden/README.md#upgrade-review-server-1371-to-1375).
- **Hindsight** remains **0.10.3** everywhere. The requested 1.2.1 is held because
  index/date migrations are not fully reversible and this deployment's canonical
  banks, aliases, tenant extension and subscription/schema contract have not been
  tested on the target. No asserted PG17 incompatibility or forced DB migration.
  [Evidence and unhold checklist](../hindsight/UPGRADE-1.2.md).
- **Monitoring**: kube-prometheus-stack 92.7.0 -> 93.2.2, Alloy 1.13.1 -> 1.15.0,
  Loki 7.3.0 -> 7.6.0. The stack renders Prometheus 3.16.0, Alertmanager 0.35.0,
  Grafana 13.3.1 and operator/CRDs 0.95.2. Its admission hook deletes/recreates one
  named Secret to migrate its type and gains a scoped delete permission; this
  requires explicit migration/security approval and recovery planning, even with
  prune disabled. Grafana's data needs compatible backup/rollback. Alloy renders
  1.21.3; log pipeline unchanged. **Loki runtime remains 3.6.11**: chart 7.6.0's
  packaged image default differs from its 3.6.18 appVersion. Do not claim a Loki
  runtime upgrade or add an unreviewed 3.7.x override. [Detailed review](../monitoring/README.md).
- Database engines/extensions, Valkey and other independently newer dependencies
  remain unchanged where the parent chart or app bundle still pins them. Any
  separately newer dependency requires its own compatibility/migration review.

## Infrastructure candidates

- Argo CD chart 10.10.3 -> 10.18.0 / app 3.5.5 -> 3.6.1.
- MetalLB chart/app 0.16.1 -> 0.16.2; use its bundled FRR-k8s 0.0.27 and
  FRR 10.6.2 rather than independently upgrading the dependency images.
- kube-vip chart 0.11.1 -> 0.11.2 / explicit app 1.0.4 -> 1.3.1.
- Sealed Secrets chart 2.20.0 -> 2.22.0 / controller 0.40.0 -> 0.41.2.
- Tailscale operator chart/app 1.104.1 -> 1.104.4. This is the latest published
  stable chart, not the separately newer Tailscale application 1.104.6.
- Longhorn 1.13.0 and Herdr 0.9.5 already match latest stable; preserve their
  versions and Longhorn's tested CSI dependency images.
- K3s and its bundled Traefik, CoreDNS and metrics-server are outside this app
  rollout. A node upgrade needs a separate operation and supported-path review.

Pinned chart indexes and anonymous public image manifests were checked. The
infrastructure target images include both Linux AMD64 and ARM64. Desired-to-desired
infrastructure rendering found no storage identity, resize or removal violations.
That does not establish live equivalence or admission success.

## Rollout gates and findings

1. **Authentication blocked:** ArgoCD MCP `get_application(argocd,argocd)` rejected
   the configured token with `invalid session: token signature is invalid`.
   Grafana datasource/alert reads returned HTTP 401. Only the operator should
   restore these integrations through the fixed-service Vaultwarden launcher in
   a private terminal. Do not retrieve old env files, read its session cache,
   rotate tokens, or use another profile. No live sync was attempted.
2. **Do not sync the root wholesale.** Its live directory exclusion still excludes
   Renovate; the repository root selects it and includes Herdr, which has running
   resources but no live Application in the inspection. Root reconciliation could
   register apps outside this existing-app upgrade. Review root differences and
   select only the reviewed, already-existing child Application resources, or use
   an equivalently scoped reviewed update. Do not activate Renovate or schedules.
3. **Argo CD security/behavior review:** the new chart adds `update` on
   `*/finalizers` to `argocd-server`'s ClusterRole and adds default RuntimeDefault
   seccomp contexts. The new controller headless Service is internal, not a new
   external endpoint. The existing Redis-secret initialization hook remains and
   changes image; inspect its behavior before sync without accessing secret
   values. Argo CD 3.6 automatically uses server-side diff for Applications with
   ServerSideApply=true. Do not enable/disable a diff strategy to bypass checks.
   Approve the RBAC/security effect explicitly before this rollout.
4. **kube-vip availability:** three live control-plane pods were Ready; the
   DaemonSet rolls one unavailable at a time. Preserve VIP 192.168.0.10,
   `plndr-cp-lock`, interface and lease timers. Current service/egress modes are
   disabled, so 1.3's shared-Service-VIP restriction and iptables egress removal
   are not configured uses. API VIP failover is still a disruption risk: require
   direct-node recovery access and verify failover during the separately reviewed
   rollout. No node/network change was performed.
5. **Sealed Secrets:** 0.41 heals manually modified generated Secrets. Existing
   SealedSecrets reported Synced=True, which does not prove live Secret payload
   equivalence. Before rollout confirm manual overrides will not be reverted;
   credential export/rotation and controller-key reads are not authorized here.
6. **Backups:** Kubernetes Job status showed successful regular Hermes,
   Hindsight, Immich and Vaultwarden backups on 2026-11-11 UTC, plus a successful
   Hermes recovery Job on 2026-11-12. A successful Job is not a tested full restore.
   Recheck freshness and each app's recovery gate immediately before deployment.
7. Preserve every PVC/PV, reclaim/retention policy, external credential reference,
   manual sync policy and disabled manifest. Do not prune, force or replace.
8. After publication, require a successful Verify check for the exact main SHA,
   review generated-to-live differences (including pre-existing drift, hooks and
   removals), then sync and verify each app separately. A local render is not
   live verification. Stop on a failed app rather than bulk-continuing.

## Sources

- [Argo CD 3.5 -> 3.6 upgrade guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/upgrading/3.5-3.6/)
- [Argo chart target](https://github.com/argoproj/argo-helm/releases/tag/argo-cd-10.18.0)
- [MetalLB release notes](https://metallb.universe.tf/release-notes/#version-0-16-2)
- [kube-vip 1.1](https://github.com/kube-vip/kube-vip/releases/tag/v1.1.0),
  [1.2](https://github.com/kube-vip/kube-vip/releases/tag/v1.2.0),
  [1.3](https://github.com/kube-vip/kube-vip/releases/tag/v1.3.0),
  [1.3.1](https://github.com/kube-vip/kube-vip/releases/tag/v1.3.1)
- [Sealed Secrets release notes](https://github.com/bitnami/sealed-secrets/blob/v0.41.2/RELEASE-NOTES.md)
- [Tailscale changelog](https://tailscale.com/changelog)
- [Repository pre-sync checklist](../argocd/README.md#verification-before-manual-sync)
