# Langfuse coordinated recovery proposal

Status: proposed on 2026-11-18; not implemented or exercised. The operator approved
publishing the resilience results and proceeding with next steps. This document
makes the recovery scope reviewable; it does not authorize secret exports,
production downtime, new storage, restore execution, schedules or retention pruning.
Traces remain disposable until a coordinated restore passes.

The [first recovery-set plan](RECOVERY-FIRST.md) records the 2026-11-20 read-only
storage/capacity preflight, bounded proposed scope and remaining implementation,
encryption, destination and execution-approval gates. Preparation is approved;
no confidential capture, production pause or isolated restore has been performed.

References: [application runbook](README.md), [resilience evidence](../reports/2026-11-18-langfuse-resilience.md),
[NAS runbook](../nas/README.md), and [Sealed Secrets recovery](../docs/operations/sealed-secrets.md).

## Recovery set

A backup must describe one coordinated recovery point across these dependencies:

| Component | Required state |
| --- | --- |
| PostgreSQL | Application database, schema and migration history, organizations/projects, users, project-key records and references into other stores |
| ClickHouse | Trace/observation data, schema and migration state, including the supported backup mechanism's metadata |
| SeaweedFS | Object contents plus persistent filer metadata, not merely one bucket listing or a copy of volume files |
| Valkey | Queued ingestion/export state and the supported persistent AOF/rewrite state; verify queues are drained or account for outstanding work |
| Stable secrets | Existing application/session/encryption/salt and datastore credentials; project keys and controller-key recovery dependencies must remain recoverable without rotation |
| Configuration | Exact Git revision, image/index digests and platform mapping, chart pin, source manifests, database versions and captured volume identities |

Do not assume a series of independently taken live volume snapshots is an
application-consistent recovery set. Longhorn replication is not a backup, and
NAS snapshots do not capture Longhorn volumes unless a separate supported backup
has actually placed recoverable state there.

Database exports and object archives are confidential even with metadata-only
tracing. Never inspect or print their contents. Stable-secret and controller-key
handling needs explicit authorization and an operator-private workflow; do not
open existing ignored key backups just to check whether they exist.

## Gate 1: approve one manual rehearsal

Before any backup or restore write, present the operator with an exact execution
plan containing:

- The selected source Git revision, pinned images, all production PVC/PV/volume
  identities, measured source sizes, free Longhorn space and NAS headroom.
- The supported native export/restore procedure for each pinned datastore
  version. Validate it first on generated disposable fixtures; do not use this
  proposal as a substitute for implementation review.
- One new, non-overwriting archive destination on the NAS and an approved
  encryption recipient/key reference. The NAS path must be checked against its
  actual mount/export mapping; do not assume a recorded directory already exists.
- An exact outage window and client-quieting method. Confirm both desktop and
  cluster clients are idle; do not restart live sessions or silently drop active
  work to obtain a quiet snapshot.
- Exact restore namespace, new claim names and requested capacities, and the
  additional storage/replication budget. Never reuse production claims or volume
  handles. Include restore staging and archive overhead, not only current data.
- The operator-approved scope for confidential exports and private secret
  restoration, without passwords, tokens, plaintext Secrets or controller keys
  appearing in chat, Git or logs.
- A recovery path that resumes the original production workload on its unchanged
  volumes and configuration if any backup or rehearsal step fails.

First rehearsal policy: one manual recovery set, no schedule, no automatic
retention, and no deletion of existing archives. Recovery-point and recovery-time
objectives remain operator decisions; record actual measured timings before
proposing automation or claiming an SLA.

## Gate 2: capture a coordinated recovery point

The final reviewed procedure must provide these properties, not just a successful
backup command exit:

1. Record source workload, volume and image identities and a bounded baseline of
   known trace/observation IDs in both `hermes-desktop` and `hermes-cluster`.
   Confirm a private owner-login test is available without asking for a password
   in chat.
2. Quiet the enrolled clients, finish in-flight ingestion and account for pending
   queues. Agree how clients behave while ingestion is paused: existing SDKs have
   no durable offline spool and may lose observations during an outage.
3. Quiesce every Langfuse writer for the coordinated point, including web, worker,
   background jobs and any remaining external ingest path. Specify the exact
   resources, order and replica restoration in the approved implementation.
   Preserve manual ArgoCD policies and do not broad-sync Hermes or its pending
   core upgrade. Do not stop datastores blindly: native exports and clean offline
   copies have different prerequisites.
4. Capture each dependency through its reviewed native mechanism while preserving
   the quiescent point. A raw live copy of database, objectstore or AOF files is
   not an accepted substitute. Do not accept partial exports or mix independently
   captured generations.
5. Encrypt confidential streams without plaintext logs or unprotected temporary
   artifacts. Publish only a complete new recovery-set directory with checksums,
   byte counts, versions, coordination timestamps and success/failure receipts.
   An interrupted set remains explicitly incomplete and must not become the
   recovery baseline. Checksums prove integrity, not application consistency.
6. Resume only the paused original resources and clients, restoring their recorded
   settings and replicas. Verify private readiness, both projects' old trace
   readbacks, a fresh metadata-only export and unchanged production storage and
   recorded pre-operation Hermes image. Do not restore the superseded v0.22.2
   pin from historical evidence. If verification fails, stop and report; never prune or
   overwrite data as remediation.

The exact native commands, scripts and secret-consumption mechanism are still
unimplemented and require review before this gate can run.

## Gate 3: restore only into an isolated target

- Use a separately approved new namespace and entirely new claims. Inspect the
  complete rendered target first, including hooks and initialization scripts.
  Nothing may mount, overwrite or adopt a production PVC/PV or restored source
  identity. Do not create or activate an ArgoCD Application for the rehearsal.
- Start with restrictive network policy. No Tailscale ingress, public exposure,
  production client enrollment or access to production datastores/object storage.
  Explicitly bind every restored component to its own restored dependencies.
  Approve only the minimum diagnostic/restore access required; do not modify
  cluster-wide authentication or Tailscale ACLs.
- Restore the captured versions and schema state first. Do not combine recovery
  with an image/chart upgrade, forced migration, key rotation or storage resize.
  Prevent first-install/bootstrap hooks from reseeding users/projects or creating
  data in production. Inspect the actual entrypoints and pending migrations;
  an apparently stateless web container can mutate databases at startup.
- Reuse the original application identity/encryption material only through the
  explicitly approved private restore workflow. Strict namespace/name-scoped
  SealedSecrets cannot simply be copied into a new namespace and assumed to
  unseal. Controller-key restore is a separate privileged operation, not a
  prerequisite to bypass by reading keys from another profile.
- Give any owner-login test a separately approved private access path and restored
  endpoint configuration. Never point production clients at the rehearsal or
  alter production authentication to make the test pass.

## Gate 4: acceptance and retirement decisions

A recovery set is accepted only after actual target execution establishes:

- Successful native integrity checks for every store, no unexplained pending or
  dirty migrations, and expected dataset/object/queue reconciliation.
- Both projects and the recorded pre-backup trace/observation IDs are readable,
  with correct parents, completed state and metadata-only content.
- Existing owner login works through the private test path, with no password
  reset or project-key rotation needed to hide an incomplete restore.
- A new target-only metadata trace can be ingested and queried without contacting
  or writing to any production dependency.
- Production remains healthy and its volume/workload identities are unchanged.
  Record measured recovery point, elapsed restoration time, coverage and limits.

Do not delete the first accepted set, previous independent recovery archives or
rehearsal volumes automatically. Deletion/pruning, retention schedules and teardown
of restored confidential state each need explicit scope and approval. Only after
successful rehearsal should the operator decide whether to adopt durable tracing,
set RPO/RTO/retention, and authorize any scheduled backups.
