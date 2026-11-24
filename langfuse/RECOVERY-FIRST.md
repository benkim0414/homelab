# First Langfuse coordinated recovery set — historical procedure and outcome

Status updated 2026-11-24: the separately authorized, bounded coordinated capture
and isolated four-store restore completed. Native/queue/object reconciliation and
synthetic isolated ingestion/readback passed; original-owner login and old-trace
UI readback were operator-confirmed, not an agent-inspected browser session.
The three reviewed datastore PRs #106/#107/#111 were subsequently merged and
manually rolled out with native checks and unchanged original claim bindings.
See the [chronological evidence and limits](../reports/2026-11-21-langfuse-recovery-preparation.md).

The dated baseline and proposal below are retained as history, not current
execution instructions or standing authorization. In particular, the capture
helpers deliberately retain the original image/identity baselines and can refuse
today's upgraded installation. Do not rewrite their pins, replay old journals,
repeat confidential exports, or recreate/delete recovery resources merely to
make a preflight pass. A new operational attempt requires fresh review of its
actual versions, identities, capacity and authorization. No schedule, retention
automation or general backup framework was introduced.

Publication safety review subsequently found a delayed watch-event admission
race in the historical adapter. The publication copy now refuses live pause
before intent/write because shared Pod/Deployment revision ordering has not
been validated. Conditional generated tests are not production proof; see the
[explicit live-execution limitation](recovery/README.md). This is not a new
operationally admitted capture implementation or authorization to repeat the set.

Secondary Vaultwarden key custody remains operator-reported. A later ordinary
production CLI smoke turn returned successfully, but its production trace was
not found by bounded readback; post-upgrade production ingestion is not accepted
on that result. These limits do not rewrite the earlier isolated restore proof.

## Verified baseline — read-only preflight on 2026-11-20 AEDT

Source revision: `711afda9bb092669db5f79b31f3e5b920b57229e`.
All six Langfuse workload Pods were Ready with zero restarts; private HTTPS
health returned `OK`, version `4.77.0`. No backup CronJobs or Jobs exist in the
namespace. Pins and identity references come from [values.yaml](values.yaml),
[clickhouse.yaml](clickhouse.yaml), [objectstore.yaml](objectstore.yaml) and live
projected workload/storage metadata. No Secret values or trace payloads were read.

| Store / claim in `langfuse` | Claim UID | PV / Longhorn volume | Capacity | Allocated filesystem KiB |
| --- | --- | --- | --- | --- |
| PostgreSQL: `postgres-data-langfuse-postgresql-0` | `dbfbc0a0-97e4-4d3d-b6ae-e4d9c581ea7f` | `pvc-dbfbc0a0-97e4-4d3d-b6ae-e4d9c581ea7f` | 10Gi | 71028 |
| ClickHouse: `langfuse-clickhouse-data` | `e82ce5a4-cd40-4353-a02a-d54a3d96203b` | `pvc-e82ce5a4-cd40-4353-a02a-d54a3d96203b` | 30Gi | 599152 |
| Valkey: `langfuse-redis` | `d8f49983-f38d-4de2-8651-283d16a732b4` | `pvc-d8f49983-f38d-4de2-8651-283d16a732b4` | 5Gi | 30692 |
| SeaweedFS: `langfuse-s3-data` | `26a2ea71-3030-4d2d-b894-b8f8cf5627f9` | `pvc-26a2ea71-3030-4d2d-b894-b8f8cf5627f9` | 20Gi | 1336 |

All four PVs have reclaim policy **Delete**. Both StatefulSets declare
Retain-on-scale and Retain-on-delete. Recheck actual claim owner references,
consumers and retention immediately before any pause. Never delete a namespace,
claim, volume or retained rollback/rehearsal artifact.

The four filesystems used 685.75MiB allocated in total; their Longhorn actualSize
sum was 6.3292GiB. Neither figure is the eventual archive size. All four volumes
were attached/healthy with two replicas. Production claim capacities total 65Gi.

Configured NAS alias `nas` resolves to `pi@192.168.0.40`, with strict host checking
and configured authentication working. Pool `storage` was ONLINE. Dataset
`storage/k3s`, mounted at `/storage/k3s` and bound at `/export/k3s-storage`, had
188936757248 bytes (175.9611GiB) available. This is distinct from parent pool free
space and the dataset's quota. No export, mount, permissions or NAS data changed.

## Bounded destination and confidentiality decision

Proposed new destination:
`/storage/k3s/langfuse/recovery/first-20261120` on NAS, corresponding to the
existing `/k3s-storage` export mapping. It was absent at preflight. Treat that as
a dated observation, not permission to overwrite it later. Never place the set
under Immich/Vaultwarden scheduled-retention directories.

`/storage/k3s` is root-owned mode 2755 and is not writable by the configured NAS
user. Before capture, the operator must approve provisioning only a new dedicated
private directory, owned by the intended archive writer, mode 0700; files 0600.
Do not chmod/chown the existing dataset or change NFS exports. Confirm the exact
writer UID/GID and destination identity in the reviewed implementation.

The operator must select an encryption recipient and private restore-key custody
mechanism. Supply only a **public recipient or nonsecret key reference**, not a
private key in chat. No key creation/rotation is implied. Before production use,
a generated-fixture round trip must prove encryption/decryption and complete
opaque archive parsing. Ciphertext count/hash checks alone are not a restore test.

No confidential recovery set will be written before directory and encryption
choices are approved. Existing unencrypted Longhorn/NAS backups are not a silent
substitute for this encrypted coordinated recovery set.

## Capture design to implement and fixture-test before requesting execution

Prefer native full exports at one writer-quiescent point, preserving original
production volumes and pins. No chart/image upgrade is part of capture. A backup
helper must use native configured authentication internally, suppress raw errors
and outputs, and never put secret literals in command arguments, receipts or Git.

| Store | Selected candidate mechanism | Mandatory pre-production proof |
| --- | --- | --- |
| PostgreSQL | Full `pg_dump` custom-format application DB plus globals/role material needed for recovery, from pinned major 18 | Generated fixture restore, complete archive parse, version/extension/schema inventory and role ownership; all confidential bytes encrypted |
| ClickHouse | Native full BACKUP/RESTORE covering application schema/data and required access metadata | Prove destination semantics under exact 26.8.36.3 image; require BACKUP_CREATED and isolated RESTORE, row/schema reconciliation and latest migration record |
| SeaweedFS | Native `fs.meta.save` of the filer root plus `weed backup` for every referenced volume; include master/collection/volume mapping and required persistent metadata | Generated small and chunked objects restored with matching bytes and metadata; enumerate all volumes, detect command-level failures and truncation independently |
| Valkey | Quiescent native persistence checkpoint plus complete multipart AOF/manifest/rewrite dependencies; retain matching configuration/ACL recovery input | Exact 8.0 image fixture restart, AOF integrity and key/queue reconciliation; never use repair/`--fix` on production data |

Important implementation constraints already identified:

- ClickHouse's live `backups.allowed_path` is the literal relative value
  `backups`. There is no declared backup mount. This does **not** establish an
  allowed Disk destination or a safe/writable File path. Test path resolution and
  bounded scratch space with fixtures before presenting executable production
  commands. Do not change production config or restart the database to force it.
- SeaweedFS 4.23 `fs.meta.save` creates/truncates its output and requests mode0644.
  Run only in a new private staging directory with umask077, never verbose.
  Its `weed backup` command is not a shell `volume.backup` subcommand. Command
  exit semantics must be tested; do not accept a generic successful process exit
  as proof all volume bytes were captured.
- A generic copy of live PostgreSQL files, live ClickHouse parts, SeaweedFS
  LevelDB/volume files, or changing Valkey rewrite state is not accepted. A cold
  physical fallback would be a separately reviewed plan amendment, not an
  automatic retry when native exports fail.
- Exact helper image digests, commands, native auth consumption, scratch paths,
  transport protocol and stop/resume guards are not implemented by this planning
  change. Review them and fixture results **before** requesting production
  execution approval. Keep any fixtures synthetic, isolated and credential-free.

## Exact intended outage scope and order

Ask the operator for one maintenance window; a provisional 30-minute ceiling is
proposed, **not a measured capture duration or availability promise**. Measure
fixture/export throughput first and revise the request if that budget is not
credible. No unattended retry or automatic rollback against modified data.

1. Reverify source SHA, exact image digests, volume IDs, healthy replicas, capacity,
   manual policies and absence of concurrent operation. Capture nonsecret workload
   identities, replica counts, read-only schema/migration/queue baselines and
   existing trace/observation identifiers for both projects. Obtain a private
   owner-login acceptance path without retrieving its password.
2. Operator confirms desktop and cluster clients idle. Pause only selected
   version-appropriate tracing clients; do not restart agent sessions or alter
   inference providers/authentication. SDKs have no durable offline spool, so
   disclose potential observation loss during the window.
3. Quiesce ingestion by stopping only `deployment/langfuse-web` after in-flight
   requests settle; let `deployment/langfuse-worker` finish pending work. Require
   the real queue/transaction-idle checks, then stop worker gracefully. Record
   both normal terminations and absence of remaining writers. If drain fails,
   stop the attempt; do not clear queues or kill writers to manufacture a pass.
4. Keep datastores running for the reviewed native exports. Capture all four
   stores and required identity material at this writer-excluded point; freeze
   proof spans the whole operation. Publish only complete, independently verified
   encrypted outputs with component byte counts/hashes and coordination times.
   Stable-secret recovery is an explicitly approved private substep, not a broad
   Secret dump or controller-key export.
5. Restore original web/worker replicas and client settings on their unchanged
   images/volumes. Verify database migration status first: web startup can perform
   migrations even on the same image. Verify HTTPS readiness, old observations,
   fresh metadata-only ingestion and unchanged identities. A failed capture stays
   recorded/incomplete; do not repeat it without renewed bounded authorization.

## Isolated restore scope and resource budget

Proposed namespace: `langfuse-recovery-first-20261120`, with deny-all ingress and
restricted egress only to its own restored dependencies/DNS as reviewed. No
Tailscale ingress, public exposure, production client enrollment, ArgoCD
Application, production Service selectors or access to production stores.

Four entirely new claims: `recovery-postgresql` 10Gi, `recovery-clickhouse` 30Gi,
`recovery-valkey` 5Gi, `recovery-seaweedfs` 20Gi. Use dynamically allocated new
volume handles and two replicas; never bind production PVs. Additional logical
storage is 65Gi / 130Gi replicated, plus archive/scratch overhead. Longhorn disks
were Ready/Schedulable, but no capacity is reserved by this document. Recheck
per-node replica scheduling, disk minimums/reservations and actual headroom.

At preflight, request accounting included normal containers, restartable init
sidecars, init peaks, Pod-level requests when present and Pod overhead:

| Node | CPU request headroom | Memory request headroom |
| --- | --- | --- |
| k3s-01 | 2980m | 5856.31Mi |
| k3s-02 | 3275m | 6050.31Mi |
| k3s-03 | 2952m | 5161.31Mi |
| k3s-04 | 2330m | 3052.31Mi |
| k3s-05 | 920m | 5485.25Mi |

Production Langfuse requests total 1600m/5376Mi before any new helper. A restored
full stack at equal requests needs another 1600m/5376Mi; budget a bounded helper
separately. Candidate placement is web/worker on AMD64 k3s-05, with datastores
spread across ARM64 nodes. A second ClickHouse on k3s-04 is not automatically
accepted: production ClickHouse and Prometheus already share it. Prefer a
separately verified compatible ARM64 target such as k3s-02, after checking CPU
features and the exact image's bounded version probe. Its compatibility is not
yet established. Do not move or resize production Prometheus.

Request fit is not proof of runtime memory safety; inspect live working sets,
limits and initial restore overhead before accepting placement. Do not lower
production/test database limits to force admission. Restore/CSI attach and
engine readiness need separate bounded deadlines.

Restore captured versions first, not PR targets. Restore all component data and
privately approved original identity material; suppress bootstrap reseeding and
unreviewed startup migrations. Verify native integrity, queues, old trace IDs
and parents, schema/latest migration state, existing owner login, and one new
fixture-only metadata trace. Prove no production dependency was contacted.
Production must remain healthy. Leave recovery artifacts intact; teardown,
pruning, retention schedules and upgrades are separate decisions.

## Next decisions required

1. Approve a dedicated private NAS destination provisioned without changing the
   existing dataset, and name its intended writer.
2. Select a public encryption recipient/nonsecret custody reference and a private
   original-identity restore workflow. Do not send credentials in chat.
3. Complete native-method fixture implementation/review, target CPU/capacity proof
   and measured timing. These are prerequisites, not claimed test results.
4. Then approve one exact capture/restore execution scope and maintenance window.

Until those gates pass, #106/#107 stay open and undeployed. Prefer the Valkey
security fix first once recovery is accepted; PostgreSQL's same-version rebuild
still needs its exact contents/entrypoint review. No image-only downgrade is
assumed to reverse datastore changes.

## Sources

- [PostgreSQL physical-backup restrictions](https://www.postgresql.org/docs/18/backup-file.html)
- [ClickHouse native BACKUP/RESTORE](https://clickhouse.com/docs/operations/backup/disk)
- [Valkey persistence](https://valkey.io/topics/persistence/)
- [SeaweedFS 4.23 metadata exporter](https://github.com/seaweedfs/seaweedfs/blob/4.23/weed/shell/command_fs_meta_save.go)
- [SeaweedFS 4.23 volume backup command](https://github.com/seaweedfs/seaweedfs/blob/4.23/weed/command/backup.go)
- [NAS identities and retention boundaries](../nas/README.md)
