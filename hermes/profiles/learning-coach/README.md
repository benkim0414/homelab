# Learning coach — reset scope

One isolated in-cluster Hermes instance, one interactive CLI channel, official
runtime, `openai-codex / gpt-6.1-sol`. No custom runtime or provider parser.

## Scope and acceptance

This profile's tutoring milestone is complete. Career advisor is a separate
profile under [../career-advisor](../career-advisor/README.md). Memory-bank
integration, Gerrit publishing, desktop A2A, Discord, custom authentication and
further safety/recovery subsystems remain deferred for these specialist profiles.
Do not add them as prerequisites. Report unsupported capabilities as blockers
instead of extending scope.

Acceptance is one Ready isolated workload, genuine native provider login, a
nonempty tutoring answer and contextual follow-up in one CLI session, then
another tutoring answer after one controlled workload restart. Do not infer
entitlement from login or an echoed model identifier alone. No paid fallback or
model substitution is approved.

## Minimal deployment

`resources.yaml` declares only a namespace, a new 2Gi RWO claim and one Deployment.
The official v0.23.2 multiarch image matches the existing cluster runtime pin.
The image's own `main-wrapper.sh` supports `sleep infinity` and drops its command
to UID10000. Keep the image entrypoint and exec shim; no image build is needed.

The main process waits without starting a gateway, dashboard or model request.
There is no Service, ingress, Secret, external memory configuration, shared
credential projection or service-account token mount. The supported CLI may use
its native pod-local session infrastructure; no additional access channel is
exposed by these manifests.

The claim and namespace are distinct from the default Hermes instance and all
older pilot attempts. No old credentials or configuration are copied. Recreate
prevents overlapping Deployment writers. Readiness checks writable state as the
Hermes user; it does not prove provider authentication or model completion.

This reuses the existing Longhorn class and adds no storage platform. The class
has reclaim policy **Delete**. ArgoCD `Prune=false,Delete=false` annotations protect
normal application reconciliation, not direct PVC/namespace deletion. Do not
remove the claim/namespace or force a replacement on another node without data
preservation and fencing. No destructive cleanup is part of this milestone.

The Application uses manual sync and tracks main. Preparing these files does not
publish them. Do not sync the root Application or change existing apps to deliver
this isolated workload. Any bounded direct rollout must use only this manifest
and leave the default Hermes workload unchanged.

## Native CLI only

After workload readiness, first verify `hermes --help` and the native login help
inside this isolated pod. Use the official `/opt/hermes/bin/hermes` shim so exec
commands drop privileges instead of writing root-owned credentials. Authenticate
interactively in the user's terminal. Do not capture authentication output or
read auth files. Do not start login or inference as a smoke test.

The tutoring invocation uses the native CLI, explicit `--provider openai-codex`,
`--model gpt-6.1-sol` and the existing `clarify` toolset. The pinned image source
contains that toolset. It excludes terminal, file, messaging, memory and
publication tools without a custom tool registry. Verify runtime help and tool
selection before sending a prompt. Do not configure a fallback provider.

The user should keep authentication codes and tokens out of chat. The existing
default instance, its process environment and all historical pilot stores are
not authentication sources for this workload.

## Verification and preservation

Run the five focused manifest tests and the repository's existing verifier.
Use the fixed acceptance above; do not create another test framework.

The expanded historical implementation remains untouched in the separate
`default-career-learning` worktree. It is not imported, deleted or excluded to
make this candidate pass. The completed single-workload files are now organized under
`hermes/profiles/learning-coach/`; this directory move changes no runtime setting.

Official references (capabilities must also match the pinned image):
- https://hermes-agent.nousresearch.com/docs/user-guide/docker
- https://hermes-agent.nousresearch.com/docs/user-guide/cli
- https://hermes-agent.nousresearch.com/docs/guides/oauth-over-ssh
