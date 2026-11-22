# Reset milestone status

## Verified

- Clean task worktree: `default-learning-coach-cli`, based on local main
  `260444e18662cf5519842fb1bb53ba7c1b8b771e`.
- Five focused manifest tests passed. All three raw resources passed strict
  Kubernetes schema validation.
- Full repository verification passed: 22 Applications, 524 resources, including
  secret scanning. The old expanded worktree was not imported or altered to
  obtain this pass. Its unresolved findings remain there.
- Bounded direct apply created only namespace `learning-coach`, claim
  `learning-coach-data` and Deployment `learning-coach`. ArgoCD publication and
  registration were not performed. No commit or push was performed.
- Deployment rolled out successfully: one Ready pod, zero initial restarts.
  The new 2Gi Longhorn claim is Bound. No Service was created.
- Official v0.23.2 image and native CLI help were checked inside the new workload.
  The supported exec privilege drop runs as UID/GID10000.
- Native `hermes config set` selected `openai-codex / gpt-6.1-sol`, `clarify` only
  for default/CLI toolsets, and disabled auxiliary title generation.
  Native `hermes memory off` selected built-in memory only.
- Bounded settings readback verified those values, no configured fallback and
  no MCP server. No external memory, Gerrit or messaging credentials were added.
- Default Hermes Deployment UID, generation 85, replica count 1 and image pin
  matched before/after. Its configuration, volumes and credentials were not
  modified or copied.

## Interactive acceptance and controlled restart

The user completed native authentication privately and supplied the two-turn CLI
transcript. Both tutoring replies were nonempty; the follow-up retained the same
pizza-slice example. The CLI explicitly selected `openai-codex / gpt-6.1-sol`.
This establishes a successful requested-model conversation, not independent
attestation of provider internals. No authentication output was inspected.

One controlled restart of only `learning-coach` completed. Pod UID changed from
`421ab54b-6bae-459f-a815-7e44c362cfc9` to
`852cc46d-13bd-48ed-9f5f-21e7c6791437`; the replacement is Ready.
The claim UID remains `6fae088c-2245-47aa-82ba-cf48ce7dc8f6` and the volume name
is unchanged. Model/provider/tool selection persisted. Default Hermes remains
at the original UID and generation 85 with one replica and the same image.

The user reconnected through the native interactive CLI after this restart and
provided a nonempty, correct two-sentence explanation of numerator and
denominator. No new login was requested. This completes the fixed reset
milestone: Ready isolated workload, native authentication, tutoring/contextual
follow-up, and successful tutoring after one controlled restart.

Final live readback confirms Learning coach Ready, the same claim UID/volume
Bound, and default Hermes unchanged at generation 85 and Ready 1/1. No deferred
feature or additional acceptance criterion is being added.

The CLI displayed a low-disk warning while reporting 1.9 GB free. The user was
instructed to press Enter to leave pruning unchanged. No cleanup, automatic
pruning or storage expansion was performed by the agent.

For a genuinely new installation only, native authentication runs in the user's
private terminal. It is already complete here; do not repeat it for the restart:

    kubectl -n learning-coach exec -it deployment/learning-coach -c hermes -- /opt/hermes/bin/hermes auth add openai-codex --type oauth --no-browser

Use the separately authorized account. Keep device codes and authentication
output private. Report only success or a safe failure summary. Do not paste
credentials or adopt credentials from another instance.

After successful login, the supported interactive entry is:

    kubectl -n learning-coach exec -it deployment/learning-coach -c hermes -- /opt/hermes/bin/hermes chat --cli --provider openai-codex --model gpt-6.1-sol --toolsets clarify

Verify the selected provider/model and tool selection before submitting the
harmless tutoring prompt. Stop on an unavailable exact model or unsupported CLI
path; do not add a parser, gateway, frontend build or alternate provider.

## Known limits

- Native CLI help reports the image's existing pnpm synchronization warning.
  The user nevertheless completed the classic interactive tutoring conversation.
  No package installation, frontend rebuild or custom launcher was attempted.
- The PVC's default Longhorn reclaim policy is Delete. Do not delete the claim
  or namespace. ArgoCD deletion annotations are not a backup or a defense against
  direct deletion.
- GitOps manifests are prepared locally but not published/registered. Do not
  claim the live workload is ArgoCD-managed yet.
- Local Python verification initially used an unavailable `yaml` import in the
  runtime. Readback then succeeded with the runtime's existing `hermes_yaml`.
  No package was installed in the workload.
- A new local instruction-file write was blocked by the approval hook and was
  not retried. Scope remains recorded in README.md and the user-approved reset.

No deferred workstream was resumed.
