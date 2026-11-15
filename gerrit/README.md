# Gerrit learning lab

Personal, private Gerrit review practice. This is not the source of the homelab
GitOps repository and does not replace GitHub. ArgoCD remains on manual sync.

## Implementation status

Prepared in the task worktree; **not installed in the cluster**. The operator
approved implementation of the plan on 15 November 2026 and separately authorized
an atomic implementation commit after private credential provisioning. The
operator-provisioned authentication SealedSecret is included; plaintext remains
private. Publication and live rollout retain the plan's separate gates. Never
substitute demo authentication or a blank password during deployment or recovery.

See the [installation plan](../docs/plans/2026-11-15-gerrit-learning-instance.md),
[ArgoCD pre-sync checklist](../argocd/README.md#verification-before-manual-sync),
[Tailscale runbook](../tailscale/README.md), [storage runbook](../nas/README.md) and
[Sealed Secrets procedure](../docs/operations/sealed-secrets.md).

## Architecture and storage

- Gerrit `3.14.6`, pinned AMD64 manifest; Java 21 runtime verified from that image.
  Both platforms exist upstream, but this manifest selects the AMD64 heavy worker.
- One StatefulSet replica, UID/GID 1000, 2Gi memory request / 4Gi limit and 2Gi heap.
  Nonroot nginx sidecar UID/GID 101, sharing supplemental fsGroup 1000 for the
  read-only Secret. Both roots are read-only, capabilities dropped and API token
  automount disabled. Writable paths are limited to the site and temporary volumes.
- Service exposes only the authenticating proxy at 8080. Gerrit listens at
  `127.0.0.1:8081`, with HTTP identity trusted only from IPv4 loopback.
- Proposed URL: `https://gerrit.tailbd291c.ts.net/`. The actual Tailscale device name,
  certificate, ACL access and connectivity must be verified during rollout. No
  public ingress, MetalLB address or exposed SSH service.
- NetworkPolicy allows ingress only from Gerrit's Tailscale ingress proxy and
  denies all egress. No SMTP, CI, AI provider, webhook, runtime plugin downloads,
  external SQL service, CronJob or new schedule is configured.
- Named `gerrit-site` RWO 10Gi PVC, provisioned by Gerrit-specific `gerrit-retain`
  Longhorn StorageClass: ext4, two replicas, reclaim policy Retain. The default
  StorageClass is unchanged. Claim retention is explicit and there is no cascading
  ArgoCD Application finalizer. Retain is not a backup or permission to delete.

The full Gerrit site lives at `/site`, including all repositories and NoteDb
review/account metadata, configuration, generated secrets, plugin data, indexes,
caches, H2 state and stable site identity. `start.sh` bypasses the image's demo
entrypoint, initializes only an empty unmarked site, installs bundled Gitiles
without downloads, and refuses unreviewed version changes or partial init.

`gerrit.config` is declarative nonsecret configuration. The generated server ID is
preserved separately in `.homelab-server-id` and reapplied on startup; replacing
it breaks access to existing NoteDb changes. Never delete that file or the init/
version markers to get a green rollout. Java `user.home` and launcher `GERRIT_TMP`
are explicitly writable; setting only shell HOME does not redirect every Java
write. Gitiles is the only selected plugin; the stock demo/out-of-the-box plugin
and remote plugin administration are not enabled.

## Private credential provisioning (operator terminal only)

A checksum-verified kubeseal 0.41.2 matching the live controller has been prepared
at `verification/cache/bin/kubeseal` in this worktree. This cache is not committed.
On another workstation, install that release from its official release archive
and verify its published SHA-256 checksum; pass its path via `--kubeseal`.

From the task worktree, run:

```bash
python3 gerrit/provision-auth.py
```

The script prompts locally for a new lowercase username, commit email and password
(at least 16 characters, entered twice). Use one operator account for bootstrap.
Store the new password privately in your vault. Do not paste passwords or hashes
into chat or shell arguments. The script hashes via OpenSSL stdin, pipes an
in-memory Secret directly to kubeseal using configured authentication, and writes
only encrypted `gerrit/auth-sealed-secret.yaml`. It does not apply anything, inspect
existing Secrets or overwrite an existing file. It refuses noninteractive use.

The helper checks controller public-certificate access before asking for passwords.
Too-short passwords or mismatched confirmation reprompt locally. Operational
failures identify the hashing/certificate/sealing stage and exit code, while raw
subprocess output stays withheld. A credential-free end-to-end check is available:

```bash
python3 gerrit/provision-auth.py --check
```

This uses random synthetic credentials in memory; it writes no files or cluster
resources. If it passes but interactive provisioning still fails, share only the
new stage-specific diagnostic, never the password, hash or Secret data.

The Secret contains `htpasswd` and an nginx username-to-email map. All traffic,
including Git HTTP and REST, must pass Basic authentication over HTTPS. nginx
replaces identity headers with authenticated values and removes Authorization
before forwarding. `auth.trustContainerAuth=true` makes the proxy, rather than
Gerrit-generated tokens, responsible for Git HTTP authentication. This is safe
only with the protected loopback backend. An ordinary Tailscale TLS proxy alone
is not the Gerrit identity provider.

Full Name and Display Name are separate account settings managed by Gerrit, not
derived from the login username. The proxy strips `X-Gerrit-Name`, and
`auth.httpDisplaynameHeader` is intentionally unset so Full Name remains editable.
Set each independently in Gerrit's account settings; username and the trusted
email mapping remain unchanged. Keep real names in account data rather than
hardcoding personal profile information into this repository. A change to this
Gerrit configuration requires the reviewed StatefulSet rollout; merely reloading
nginx does not reload Gerrit's authentication realm configuration.

To add a second normal learning account later, first verify the administrator.
A separately reviewed credential replacement can be prepared with `--accounts 2
--output verification/cache/gerrit-auth-next.yaml`, re-entering both accounts'
intended credentials privately. Review/publish the encrypted replacement and
restart the StatefulSet to reload the identity map. No automatic credential
rotation or Secret-reading merge is provided. Basic-auth account switching and
logout have browser limitations; use separate browser profiles when needed.

## Local checks

Use the [repository verification workflow](../verification/README.md). The
ConfigMap is generated from `start.sh`, `gerrit.config`, and `nginx.conf`; its
checksum is also embedded in the pod template to cause a deliberate rollout
when reviewed configuration changes.

```bash
verification/venv/bin/python gerrit/render-config.py
verification/venv/bin/python gerrit/render-config.py --check
bash -n gerrit/start.sh
verification/venv/bin/python -m unittest discover -s verification/tests -v
verification/cache/bin/conftest verify --policy verification/policy
verification/venv/bin/python scripts/verify.py --all --base main
git diff --check
```

The verifier renders raw manifests, checks Application selection/schemas/policies
and scans for secrets. It does not establish that the referenced auth Secret has
been provisioned. Do not sync until the encrypted source is present or an
explicitly approved local Secret injection is established.

### Actual image/runtime rehearsal

`runtime-probe.py` executes the real selected Gerrit and nginx images, not host
substitutes. It uses private user/network/PID namespaces, normalized rootless
image extraction, declared runtime UIDs, read-only image roots, disposable site
storage, generated synthetic credentials and an empty inherited environment.
Neither the Docker socket nor host home/root/credentials are mounted. Rootless
ownership normalization is not a Kubernetes fsGroup or CNI enforcement test.

To reproduce, anonymously fetch the pinned images into ignored
`verification/cache/`, verify registry content digests, and unpack their AMD64
OCI layouts using `umoci unpack --rootless` at:

- `verification/cache/gerrit-bundle/rootfs`
- `verification/cache/gerrit-nginx-bundle/rootfs`

Create empty `/site` and `/config` mount directories in the normalized Gerrit
root and `/config` and `/auth` in the normalized nginx root before running.
Do not merge layers with an unsafe generic tar extraction or use another profile's
credential-bearing caches. The initial rehearsal used crane v0.22.1 and umoci
v0.6.0 (release checksums / GitHub asset digest verified, not signature verification).
The selected nginx AMD64 manifest is
`sha256:209331cfcaec00da781f5b8a38e0d1c0abd00cb2b51e6ad385a30abbbdb04e15`;
the manifest in the StatefulSet is its multi-platform index digest.

```bash
systemd-run --user --scope --quiet \
  -p MemoryMax=5G -p MemorySwapMax=0 -p CPUQuota=200% -p TasksMax=512 \
  python3 gerrit/runtime-probe.py \
    --fixture verification/cache/gerrit-probe-new
```

The probe requires a new fixture directory and verifies its cgroup limits. It
checks missing/wrong credentials, header spoofing, first-account admin membership,
non-admin identity, WebUI HTML/source browsing, authenticated clone/review pushes,
direct-main rejection, patch-set revisions, unresolved comments, self-vote and
submission, stacked-change rebase, persistence after normal JVM shutdown/restart,
and a complete cold-site backup restored to separate disposable storage. Synthetic
logs/state remain in the ignored fixture; the only report is `result.json` without
credentials. The scripts never run against the live cluster.

On 15 November 2026 the real-image rehearsal passed review/submission, stacked
changes, restart persistence and isolated cold restore. Failed earlier fixtures
were preserved, not reset: they caught missing nginx temporary paths and loss of
Gerrit's server identity before live deployment. Local HTTP tests do not prove
browser interaction, Tailscale TLS/ACLs, Kubernetes Secret permissions, CNI
isolation, Longhorn failover or a production NAS backup.

## Publication and rollout gates

1. Finish private credential provisioning and review the encrypted file without
   printing any plaintext Secret/hash. Do not change controller keys or Tailscale
   OAuth credentials. Check the intended username/email and bootstrap scope.
2. Refresh node capacity including existing limits/peak usage and Tailscale proxy
   overhead. The discovery snapshot had k3s-05 memory limits at 114% before Gerrit;
   low current usage is not guaranteed headroom. Do not delete other tasks'
   rehearsal pods to create capacity. Hold or separately propose resizing if needed.
3. Review AppProject cluster-resource permissions, new Retain class/PVC ownership,
   all hook/replacement/data effects, raw-file coverage and finalizers. Verify the
   actual gerrit-retain class after creation before allowing site initialization.
4. Obtain commit/push approval; require passing Verify CI on the exact published
   main revision. Publishing alone does not deploy.
5. Review root drift; register only the new Gerrit child. Do not bulk-sync pending
   unrelated Applications. Review the complete Gerrit diff separately, including
   SealedSecret, storage and exposure, then obtain the rollout approval gate.
6. Sync without prune, force or replace. Verify exact source revision/image,
   Bound retained claim, healthy Longhorn volume and Ready containers. Allow up
   to 15 minutes for fresh initialization before declaring startup failure.
7. Open the private HTTPS URL from an approved tailnet client. The first operator
   login via `/login/` must establish the intended administrator; check group
   membership before permitting a second account. Unauthenticated health probes
   use the loopback version endpoint and must not create a bootstrap account.
8. Verify missing/wrong credentials and spoofed headers fail at the proxy; test
   denied in-cluster access and inability to connect directly to backend 8081 on
   the Pod IP. Do not infer CNI enforcement solely from the NetworkPolicy object.
9. Configure the practice project below, repeat review acceptance tests using the
   private endpoint and record actual change URLs/IDs. Observe memory/restarts
   during real Git operations. Ready/Synced alone does not complete acceptance.

## Practice project configuration

Use the operator administrator to create `gerrit-playground` with branch `main`
and an initial empty commit. After a second normal account is established, create
a `Lab-Reviewers` group containing that account; do not give it global admin.
Configure only this project's permissions:

| Ref | Permission for Lab-Reviewers |
| --- | --- |
| `refs/heads/*` | Read, Code-Review -2..+2, Submit |
| `refs/heads/*` | Block direct Push |
| `refs/for/refs/heads/*` | Allow Push for review |

Project submit requirements (tested with Gerrit 3.14.6):

- `Code-Review`: `label:Code-Review=MAX AND -label:Code-Review=MIN`
- `Resolved-Comments`: `-has:unresolved`

Allow uploader self-approval only here. Do not add a required `Verified` CI label
without a CI system. Inherited/global rules must not be weakened. The runtime
probe contains exercised REST payloads for this exact configuration; its random
fixture identities and generated credentials must never be deployed.

For the walkthrough, clone through HTTPS using the proxy account, install Gerrit's
`tools/hooks/commit-msg` hook and commit with the registered email. Use a credential
manager or interactive Git prompts; never put passwords in the remote URL.

```bash
git clone https://gerrit.tailbd291c.ts.net/gerrit-playground
cd gerrit-playground
curl --fail --user YOUR_USERNAME \
  https://gerrit.tailbd291c.ts.net/tools/hooks/commit-msg \
  -o .git/hooks/commit-msg
chmod 700 .git/hooks/commit-msg
# Make and commit a practice edit, then upload rather than updating main:
git push origin HEAD:refs/for/main
# After reviewing and editing the same change:
git commit --amend --no-edit
git push origin HEAD:refs/for/main
```

Compare patch sets, leave and resolve an inline comment, vote +2 and submit.
Confirm main changes only after submission. Then upload two dependent commits,
revise the earlier commit, rebase the later one and submit in dependency order.
SSH is disabled in this phase; do not advertise unusable SSH clone URLs.

## Backup, recovery and uninstall

No schedule or retention deletion is enabled. Before keeping valuable code,
perform and verify an approved backup to a dedicated NAS archive destination.
The local synthetic restore rehearsal is not a backup of a deployed instance.

For a cold backup, review workload/PVC ownership and retention, stop the single
writer normally, observe JVM shutdown and all claim consumers exiting/detaching,
then copy/archive the complete site with the exact image/config/plugin versions.
Protect `secure.config`, generated keys and other sensitive state with approved
encryption and access controls. Resume the original workload/claim identity;
do not force-detach. Longhorn replicas are not backups, and NAS ZFS snapshots do
not include Longhorn site state unless an explicit archive has been written there.

Restore a verified cold archive to a new retained claim and test it in an isolated
instance with matching image/config/plugins, preserving server ID and internal
repositories. Never test restoration by overwriting live data. A normal project
clone or default branch mirror omits review/account refs and is not a full backup.
Image downgrade alone is not rollback of a site-format migration.

For a failed init, preserve the claim and initialization marker for inspection.
For a version mismatch, stop and prepare an approved migration, not a marker edit.
For uninstall, obtain explicit authorization, stop access/workload and verify an
export first; review each resource and Application deletion mode. Do not delete
the namespace/PVC/PV/Longhorn data, Tailscale device or recovery sets as cleanup.
