# Sealed Secrets operations

These procedures involve credential access or secrets changes and require explicit
user authorization. Never print plaintext secret values or controller private keys
in reports, diffs, or tool output. Do not execute these commands for routine checks.

## Create an encrypted application secret

Create plaintext input locally with restrictive permissions using an approved
credential source. Avoid secret literals in shell arguments or history. Pipe the
local Secret manifest directly to the controller's public-key sealing workflow:

```bash
kubeseal \
  --controller-name sealed-secrets-controller \
  --controller-namespace kube-system \
  --format yaml < path/to/local-secret.yaml > path/to/app/sealed-secret.yaml
```

Replace the example paths with the approved input and app destination. To build
the input manifest, use `kubectl create secret generic` with the intended name,
namespace, `--from-env-file=path/to/local-secret.env`, and `--dry-run=client -o yaml`;
write it to a restricted local file or pipe it directly to `kubeseal`.
Keep plaintext input outside tracked files and remove it after sealing with
approval. Only the encrypted SealedSecret belongs in Git; include it in the application's raw-manifest
glob. Verify the intended namespace/name, since sealing is scoped by default.

## Back up controller keys

The existing ignored backup location is
`sealed-secrets/sealed-secrets-master-keys.yaml`; a root-level backup of the same
name is also ignored. These contain private keys, not safe-to-commit SealedSecrets.
With authorization, write a restrictive backup without emitting it to the terminal:

```bash
(
  set -eu
  umask 077
  backup=sealed-secrets/sealed-secrets-master-keys.yaml
  temporary=$(mktemp "${backup}.tmp.XXXXXX")
  trap 'rm -f -- "$temporary"' EXIT
  kubectl get secrets -n kube-system \
    -l sealedsecrets.bitnami.com/sealed-secrets-key=active \
    -o yaml > "$temporary"
  test -s "$temporary"
  ln -T -- "$temporary" "$backup"
)
```

The export must exit successfully and produce nonempty output before publication.
The same-directory hard link publishes the file atomically and refuses to replace
any existing destination. Failed or empty exports leave no destination; temporary
files are removed on exit. If the destination exists, publication fails: inspect
it through an authorized workflow rather than treating its existence as proof of
a valid backup. This requires `mktemp` and GNU `ln -T` (available on Linux).
Arrange an approved external backup; without the original keys, existing SealedSecrets cannot be recovered on
a fresh cluster. Restoring those keys must precede application secret recovery.

## Recovery references

Use the [rebuild record](../superpowers/plans/2026-10-14-cluster-rebuild.md) and
[application recovery instructions](../../immich/README.md) for ordering. Preserve
existing application credentials during restore; rotation is a separate operation.
