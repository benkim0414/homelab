# Manual specialist-memory image publication

The `Publish specialist memory image` GitHub Actions workflow publishes only the
amd64 image that passes a new real disposable-database acceptance run. It uses
the workflow's temporary `GITHUB_TOKEN`, not a personal token or local login.

The workflow is manual-only and accepts an exact reviewed main commit as
`expected_sha`. It refuses another branch or a mismatched revision. It preserves
the production Docker context and existing validation harness. The new build can
resolve different transitive dependencies, so historical local acceptance is not
substituted for the new run's acceptance.

After all acceptance and cleanup checks pass, the workflow tags the exact tested
image ID, pushes it, pulls the returned registry digest, and checks image identity.
Only bounded synthetic acceptance and registry identity JSON files are uploaded.
No service logs, private configuration or credentials are uploaded.

Dispatch after the workflow is merged:

    gh workflow run specialist-memory-image.yml --ref main -f expected_sha=<reviewed-main-commit>

Read the completed run and download its publication artifact. Verify the
acceptance predicate and registry readback before using its digest in the rollout
proposal. A failed or skipped job is not publication acceptance. Do not retry
failed tests automatically or weaken their guards.

This workflow does not edit deployment files, create application credentials,
provision production schemas, access provider grants, or activate specialists.
It provides no arm64 execution evidence. The existing architecture, recovery,
provider, maintenance-window and authorization gates remain in effect. Registry
package visibility and cluster pull access also require verification before use.
