# Career advisor

## Fixed scope

The user authorized Career advisor without extending the plan. Deliver one
isolated in-cluster Hermes workload through one native interactive CLI, using
`xai-oauth / grok-4.7` and separately authorized subscription authentication.
Reuse the reviewed Learning coach deployment pattern, not its state or credentials.
Preserve default Hermes, Learning coach and the historical local pilots.

Acceptance: Ready isolated workload, native user login, one nonempty career
advice answer and contextual follow-up, then another answer after one controlled
restart without another login. Login alone does not establish model entitlement.
Report unsupported subscription/model access and stop. No substitute model,
API-key billing, custom authentication, parser or compatibility loop is approved.

Memory integration, Gerrit publishing, job applications/submissions, email,
Discord, desktop delegation, cross-agent sharing and additional channels remain
deferred. The advisor can discuss career preparation. It cannot submit anything.

## Deployment and preservation

`resources.yaml` contains only a namespace, new 2Gi Longhorn RWO claim and one
Deployment, labeled with display name `Career advisor`. The official Hermes
v0.23.2 image is pinned by digest, matching the working Learning coach pattern.
The supported entrypoint runs an idle command without automatic model calls.
No Service, ingress, Secret mount, service-account token, shared volume or host
path is declared. Readiness proves writable state, not authentication/inference.
The accepted live configuration limits the CLI to the existing `clarify`
toolset. No external memory provider, MCP server or fallback provider is
configured. These settings live on the private claim; `resources.yaml` alone
does not provision them. On a fresh claim, run the native configuration commands
after readiness and before authentication or chat:

    kubectl -n career-advisor exec deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes config set model grok-4.7
    kubectl -n career-advisor exec deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes config set model.provider xai-oauth
    kubectl -n career-advisor exec deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes config set toolsets '[clarify]'
    kubectl -n career-advisor exec deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes config set platform_toolsets.cli '[clarify]'
    kubectl -n career-advisor exec deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes config set memory.memory_enabled false
    kubectl -n career-advisor exec deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes config set memory.provider ''

Fallback providers and MCP servers are empty by default on the fresh claim.
These steps do not import another instance's configuration or credentials.

Longhorn reclaim policy is Delete. ArgoCD claim annotations protect normal
reconciliation, not direct namespace/PVC deletion. Never delete the claim or
namespace or force volume replacement as cleanup. To stop this workload safely,
scale only this Deployment to zero and retain its claim. Recreate prevents
simultaneous writers during the controlled restart.

The Application tracks main with manual sync. Files remain local until separately
authorized publication. Do not sync the root or alter another application.

## Native authentication and chat

Only after readiness, authenticate in the user's private terminal:

    kubectl -n career-advisor exec -it deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes auth add xai-oauth --type oauth --no-browser

Do not paste codes, tokens or authentication console output. Do not reuse other
instances' credentials. Native login may update provider defaults; explicitly
select the required provider/model for every acceptance conversation:

    kubectl -n career-advisor exec -it deployment/career-advisor -c hermes -- /opt/hermes/bin/hermes chat --cli --provider xai-oauth --model grok-4.7 --toolsets clarify

Example harmless acceptance prompt:
"I am preparing for a junior platform engineer interview. Suggest three practice
topics. Keep it brief."
Then: "Turn the second topic into a short practice exercise."
After one controlled restart, request another brief interview preparation answer.
Use invented examples rather than private employment records for this test.

The official documentation warns that xAI may deny OAuth inference for some
subscription tiers even after successful browser login. Stop on that error.
The documentation's suggested paid API-key alternative is not authorized here.
An unavailable exact model is likewise a blocker, not permission to substitute.

## Verification

    verification/venv/bin/python -B -W error verification/tests/test_career_advisor_cli.py -v
    verification/venv/bin/python scripts/verify.py --all
    git diff --check

These are local manifest/policy checks, not proof of successful live advice.
The CLI may report the existing image pnpm warning. Do not rebuild its frontend
or install packages to hide that warning.

References:
- https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth
- https://hermes-agent.nousresearch.com/docs/user-guide/docker
- https://hermes-agent.nousresearch.com/docs/user-guide/cli
