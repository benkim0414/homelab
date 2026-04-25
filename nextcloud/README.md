# NextCloud (decommissioned 2026-04-25)

This directory is a working snapshot of the NextCloud deployment at chart
version `nextcloud/nextcloud@9.0.5`. Never deployed in production; removed to
free cluster resources.

## To revive

1. Restore `argocd/apps/nextcloud.yaml` from git history:

   ```bash
   git show $(git log --oneline -- argocd/apps/nextcloud.yaml | head -1 | cut -d' ' -f1):argocd/apps/nextcloud.yaml \
     > argocd/apps/nextcloud.yaml
   ```

2. Regenerate both sealed secrets against the live cluster (originals are
   encrypted to the old cluster key):

   ```bash
   # nextcloud-credentials (postgres + admin creds)
   kubectl create secret generic nextcloud-credentials -n nextcloud \
     --from-literal=db-password=<pw> \
     --from-literal=nextcloud-password=<pw> \
     --dry-run=client -o yaml \
     | kubeseal --controller-name sealed-secrets-controller \
                --controller-namespace kube-system --format yaml \
     > nextcloud/sealed-secret.yaml

   # s3-backup-credentials
   kubectl create secret generic s3-backup-credentials -n nextcloud \
     --from-literal=access-key=<key> \
     --from-literal=secret-key=<secret> \
     --dry-run=client -o yaml \
     | kubeseal --controller-name sealed-secrets-controller \
                --controller-namespace kube-system --format yaml \
     > nextcloud/s3-sealed-secret.yaml
   ```

3. Verify NFS exports exist at `192.168.0.40:/k3s-storage/nextcloud/{data,backups}`.

4. Re-add the Renovate entries to `renovate.json5` (copy pattern from the
   immich block for fileMatch; restore the `Group NextCloud packages` packageRule
   from git history).

5. Commit and merge to `main` — ArgoCD self-heals automatically.
