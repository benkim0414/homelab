# Specialist memory: production deployment proposal

Status: review-only draft. Not deployable. No publication, credential creation,
cluster changes, specialist activation or Git publication is authorized here.
Baseline: merged PR 123, `c2dbb6eed77fe85d414597880161a05283957fb1`.

The proposal lives outside the Hindsight Application's explicit file selection.
`deployment-patch.json.template` is a strategic-merge PATCH, not a full manifest and not
an apply command. Its image is deliberately unresolved. Do not place the local
Docker image ID into Kubernetes or replace the placeholder with a made-up hash.

## Exact proposed change

Target only Deployment `hindsight/hindsight-api`, container `api`:

- Replace the official base image with a separately published, reviewed digest
  for proposed repository `ghcr.io/benkim0414/hindsight-specialist-memory`.
  The repository name is a proposal, not an existing published artifact claim.
- Set command `/app/api/.venv/bin/hindsight-specialist-api`.
- Set the tenant and operation-validator extension slots to the reviewed custom
  classes. Both slots reuse the existing legacy bearer token by its current
  Secret reference. Never read, copy, rotate or redistribute its value.
- Explicitly retain the legacy schema `public`, subject to read-only live
  metadata confirmation before any rollout.
- Add the four new role-key references to both extension slots. These references
  are mandatory, not blank/default credentials or optional fallbacks.

Preserve replica count 1, `Recreate`, one API process, internal worker identity
`hindsight-api`, two worker slots, current Service/Ingress/ports, probes, limits,
security context, PVC identities and manual ArgoCD sync. Preserve existing
`openai-codex` / `gpt-5.6-luna`, local BGE embeddings and local MiniLM reranking.
Do not copy the no-LLM/ONNX/RRF fixture overrides into production.

Do not change the PostgreSQL image or PVC, chart pin 1.2.1, UI, existing clients,
legacy aliases/banks, API/UI Secrets, subscription grant, backup policy or
initializer. Chart API/worker/PostgreSQL components stay disabled. No pruning,
force/replace, automatic sync, new service, proxy or shared session store.

## Credential and schema preparation — approval required

Proposed new Secret: `hindsight/hindsight-specialist-memory-credentials`.
Its four distinct fresh keys are references only in this draft:

| Secret key | Server role | Bank / schema |
| --- | --- | --- |
| `LEARNING_COACH_API_KEY` | Read-only specialist | `infinite-recursion` / `user_learning_coach` |
| `CAREER_ADVISOR_API_KEY` | Read-only specialist | `next-level` / `user_career_advisor` |
| `OPERATOR_LEARNING_COACH_API_KEY` | Separately controlled writer | Same learning bank/schema |
| `OPERATOR_CAREER_ADVISOR_API_KEY` | Separately controlled writer | Same career bank/schema |

No Secret or SealedSecret has been created. After separate approval, generate
and seal the fresh values without displaying or placing plaintext in arguments,
Git or reports. Append only the new SealedSecret document to the already selected
`hindsight/sealed-secret.yaml`, preserving every existing document and value.
If a separate file is preferred, its Application include change must be reviewed
at the same time. Do not enable this patch without all required keys present.

Only the API receives all server-side references. Later specialist configuration
must receive only its own read-only key, never `envFrom` of the whole Secret,
operator keys or the legacy all-bank key. No agent configuration is in this draft.

The native startup lifespan migrates the configured legacy schema plus the two
fixed specialist schemas. This is a database write, not a health-only action.
Verify actual database role privileges, current migration heads, default schema,
new schema-name absence/collisions and global migration/function effects before
approval. Preserve all legacy data and aliases. Do not move or rename banks.
New bank rows need not be seeded by an admin PUT: native retain creates its bank
lazily after authorization. Each production save still needs exact content and
destination approval. This setup proposal authorizes no memory payload.

## Release gates and disruption review

1. Image: separately approve publication of a build from the reviewed revision.
   Record the registry manifest/index digest, dependency versions and platform
   coverage. The accepted local image is an amd64 image configuration ID, not
   a pullable registry digest. Verify every eligible node architecture or obtain
   approval for an explicit placement restriction. Do not silently add one.
2. Credentials: separately approve fresh-key creation/sealing and injection.
   Validate names/key presence through metadata, not secret values. Preserve
   the existing legacy API/UI token references and OAuth volume ownership.
3. Legacy metadata: read-only preflight must confirm live desired-state drift,
   legacy schema/routing, workload/PVC identities and the existing initializer's
   banks. Repository history is not verified live health. Stop on discrepancies.
4. Recovery: verify a fresh complete database backup and isolated restore evidence
   covering all schemas, roles/ownership prerequisites and the current migration
   version. Schedule a final write-excluded backup for the maintenance window.
   The existing full-database dump has no schema filter, but excludes cluster
   roles, Secrets, the subscription grant and model cache. Archive listing alone
   is not restore proof. Its template runs retention, including when manually
   triggered. Review possible archive deletion before authorizing that action.
   Do not restore over production or copy/revive the rotating subscription grant.
5. Native startup: review exact new-schema and global-function migration effects.
   Preserve one process/credential owner and worker discovery of legacy plus both
   specialist schemas. Do not start a parallel canary against the auth PVC.
   Bind migration-source and UID 1000 writable-path checks to the exact candidate
   image. Preserve the current runtime layout. Do not add filesystem restrictions
   without proving compatibility. Account for the server's five-second graceful
   shutdown within the existing 60-second pod termination grace.
6. Provider compatibility: the accepted test used `none` LLM, ONNX and RRF.
   Production uses the existing subscription model, local sentence-transformer
   embeddings and cross-encoder. Normal dependency compatibility is not real
   provider acceptance. Startup may verify the LLM or resume pending work.
   New-tenant retain/consolidation and worker identity propagation were not proved
   by the no-LLM fixture. Verify those preserved-production paths before approving
   operator writes. Report incompatibility rather than broadening worker authority
   or disabling existing legacy processing to obtain a pass.
   Obtain the applicable separate INFERENCE approval and fixed request/response
   bounds before any new provider test. LOGIN remains separate and only if needed.
   Do not reauthenticate for review, reuse a spent approval, retry automatically,
   inspect auth state or add a paid fallback.
7. Diff and window: review the materialized API diff plus actual encrypted Secret
   addition, complete ArgoCD diff and hook effects against the pre-sync checklist.
   `Recreate` means an API outage. UI-backed operations and existing memory clients
   can fail during it. Arrange client/write quiescence and an approved window.
   A no-prune sync still runs hooks and migrations. No sync is authorized now.
   Normal full sync runs `hindsight-initialize-reserve` after health. Its
   `BeforeHookCreation` policy deletes the previous same-named hook Job even
   without pruning. It checks `reserve-bank` and `homelab-protocols` using the
   existing legacy reference, creating an empty bank only on HTTP 404. It does
   not retain memories or initialize specialist banks. Its 300-second deadline
   and two Job retries can repeat checks. The backup CronJob is not a backup hook.

The proposal checker reports these gates as unresolved. A structural pass does
not certify image availability, Secrets, live state, backup validity or approval.

## Bounded rollout acceptance — future approval only

After all gates and a separate deployment approval, promote only the reviewed
patch and encrypted Secret addition. Use the existing manual Hindsight workflow
without pruning or force. Do not sync an unrelated parent diff or other apps.
Wait for the previous credential owner to stop before the new API starts.

Check image identity, entrypoint, single-process ownership, original PVCs,
readiness and all tenant schema heads. Check that existing normal-key clients
still route to their original banks. Use metadata and approved bounded requests,
not raw authentication/provider console or stored personal content dumps.

Test specialist isolation with the new read-only credentials before exposing them
to agents. An absent bank may remain absent until an explicitly approved operator
save. Any production retain test needs the exact harmless payload/destination
and applicable inference authority. Recheck save/readback, nonempty own recall,
cross-bank denial and readonly-write denial. Keep automatic retention/mirroring
and provider-lifecycle ingestion disabled in specialists. No silent write grant.

Connect Learning coach first and Career advisor only after its own reviewed
read-only acceptance. Native HTTP MCP needs no package injection into accepted
Hermes runtimes. These activation edits and actions are separate approvals.

The bounded local acceptance deliberately used typed legacy MCP recall without
inventory-based SDK output-schema validation. Its full legacy tool inventory
exceeds the 65,536-byte test cap. Do not present that as full legacy discovery
acceptance or change response limits to obtain a pass. Review actual existing
client compatibility before production acceptance.

## Rollback — preserve data and grants

Rollback is an operational action requiring the reviewed window and authority.
It is not automatic deletion or a database downgrade.

1. Stop new specialist clients and write callers first. Confirm no specialist
   work is pending/in progress before restoring the old worker. If work cannot
   be quiesced safely, stop and escalate rather than dropping jobs or schemas.
2. Revert only the candidate API image, explicit command and added/replaced
   extension/schema/key-reference environment entries to the reviewed baseline
   `hindsight/api.yaml` at the revision above. Preserve the same Deployment,
   Service, PostgreSQL instance, PVCs, subscription grant and legacy Secret refs.
   Use the exact published rollout revision for a reviewed inverse diff rather
   than blindly resetting unrelated changes or applying an old whole repository.
3. Review the complete rollback ArgoCD diff and hooks. Use manual no-prune sync
   with `Recreate`, never force/replace or a second credential owner.
4. Check the previous immutable API image and built-in tenant extension, readiness,
   original legacy schema/banks and existing client routing. Do not infer success
   from health alone or a successful command acknowledgement.
5. Leave the new schemas, banks and encrypted Secret in place. Extra schemas may
   remain visible to shared maintenance functions and worker discovery. Do not
   promise that reverting the API makes them inactive. Do not
   delete PVCs, drop schemas, prune Secrets or restore a database as routine
   rollback. New data must survive. Review global migration-function and worker
   discovery compatibility first. If incompatible, keep the API stopped and seek
   explicit recovery approval. Restoring a backup can discard later data and is
   a separately approved last resort, not a rollback shortcut.

## Local checks

From this worktree:

```sh
verification/venv/bin/python -B -m unittest discover -s verification/tests -p test_specialist_memory_proposal.py
verification/venv/bin/python -B hindsight/proposals/specialist-memory/check_proposal.py --check
verification/venv/bin/python scripts/verify.py --all --base c2dbb6eed77fe85d414597880161a05283957fb1
git diff --check
```

The checker performs local structural/baseline checks only. It emits no Secrets,
contacts no registry/cluster/provider and writes/applies no manifest. Its optional
Python `materialize()` function substitutes a syntactically valid proposed
registry digest into the PATCH only. It does not clear the release gates or prove
that an image was published. No apply-ready candidate has been produced.
