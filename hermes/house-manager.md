# House manager

## Placement and identity

- Existing `hermes` Deployment, not a separate workload.
- Profile ID: `house-manager`; display name and Bot Mode title: `House manager`.
- Persistent profile home: `/opt/data/profiles/house-manager` on the existing PVC.
- Desktop backend: `https://hermes.tailbd291c.ts.net` (private Tailscale).
- Profile was created fresh with `--no-skills --no-alias`, not cloned.

## Current activation progress

This section supersedes the historical bootstrap state below.

- On 2026-11-14, the operator selected GPT-6 Luna to reduce subscription usage.
  The live profile now uses `openai-codex` / `gpt-6-luna`, set through the
  profile-scoped Hermes CLI. Configuration readback confirmed the model, and a
  fresh one-shot inference request returned exactly `LUNA_OK` (session
  `20261114_092615_c322ef`). No HA tools or device actions were used in this test.
  No gateway restart was performed; existing chats can retain their prior model.
- Codex was reauthenticated interactively; a real no-tool model request succeeded.
- Operator created a dedicated non-administrator HA user and installed its token
  with the hidden-input helper, without placing it in chat or command arguments.
- Official MCP authentication and discovery succeeded using that account.
- Operator restricted HA to Assist only and disabled its administrator requirement.
- MCP is now enabled in house-manager. Its exact allowed server tool is
  `homeassistant__GetLiveContext`; resources, prompts and sampling are disabled.
- Native discovery verified that only
  `mcp__homeassistant__homeassistant__GetLiveContext` is registered. Control tools,
  including generic on/off intents and climate changes, are excluded.
- The `mcp-homeassistant` toolset is enabled on CLI, Discord, Telegram and API-server
  surfaces alongside clarify and TTS. This does not enable those messaging adapters.
- A real agent query for exposed sensors succeeded. The stored session confirms
  the state-query tool call, not just a model claim. No device-control calls ran.
- The installed CLI prints an early unknown-toolset warning for the dynamic MCP
  alias, but subsequent native discovery and the real tool call both succeeded.
- Desktop connection, gateway profile serving, Discord and voice acceptance remain
  pending. Keep control testing deferred until the operator can observe devices.

## Historical bootstrap state (not an operational acceptance)

The profile and its safety instructions exist in the live PVC. Its model selection
is `openai-codex` / `gpt-6.1-sol`. The authentication-status command reported a login,
but an actual chat request failed with HTTP 401: invalidated OAuth token. A successful
login-status check alone is not sufficient evidence of working inference.

The profile has only `clarify` and `tts` toolsets for CLI, Discord, Telegram and
API-server surfaces. No shell, file, browser, delegation or memory tools are enabled.
Local curated memory and user-profile injection are disabled. No external memory
provider or reserve-bank MCP server was copied to this profile. No routines were created.

Official HA MCP is staged but explicitly disabled until authentication and exposed
entities are reviewed. Configuration points to
`http://home-assistant.home-assistant.svc.cluster.local:8123/api/mcp`, with
an environment-substituted bearer authorization header. Its credential variable
was not populated at bootstrap. Sampling is disabled. The initial tool filter
included only `GetLiveContext`; its actual
availability must be checked by authenticated discovery before enablement. The
dynamic `mcp-homeassistant` toolset must be added to the intended platforms when
MCP is enabled; it is deliberately absent while the server is disabled.

The installed HA MCP integration was inspected without extracting credentials:
`all_llm_apis: false`, `llm_hass_api: [assist]`, `require_admin: true`. Its current
version does not expose the newer documented read-only configuration option.
Do not assume newer documentation describes this installed release. Keep write
tools excluded in Hermes, review Assist-exposed entities, and do not weaken HA's
administrator requirement merely to make authentication easier. If server-side
read-only enforcement is required, review an upgrade separately.

Discord is disabled and no Discord bot credentials or sender allowlist have been
configured. Desktop has not been connected or authenticated to this backend.
The desktop automation driver could not discover the running application's
window; it must be repaired or the connection added interactively.

## Network boundary

`network-policy.yaml` permits the Hermes pod to reach HA pods only in namespace
`home-assistant`, matching both application name and instance, on TCP 8123.
This rule was applied using a JSON patch preserving ArgoCD's tracking annotation.
An unauthenticated request from Hermes to HA returned HTTP 401 after the patch,
confirming transport reachability without sending any device commands.

This permission is pod-wide, not profile-specific, and cannot constrain HA paths,
entities or actions. HA authorization and Hermes tool filtering are separate layers.
All prior ingress/egress rules remain. No public ingress was added.

## Activation checklist

1. Authenticate the profile to Codex using the supported interactive OAuth flow;
   never copy rotating credentials from a workstation. Repeat the small no-tool
   chat test and confirm a real model reply.
2. Supply dedicated, operator-approved HA authentication securely to the profile;
   do not reuse a metrics token or extract HA's stored session tokens. Review which
   entities are exposed to Assist, especially locks, covers, alarms and appliances.
3. Authenticate to official MCP and inspect the actual discovered tools. Keep the
   server disabled until the exact read-only tool filter has been verified. Add
   `mcp-homeassistant` to relevant platform toolsets and enable MCP only then.
4. Verify the running gateway serves `house-manager`. At last check, `profile list`
   showed the default gateway running and house-manager stopped. Do not assume a
   profile directory alone means the messaging multiplexer is serving it. Preserve
   the existing gateway while resolving its installed-version multiplex settings.
5. In Desktop, add a Remote gateway named `Home cluster` at the private URL above,
   authenticate, and test HTTP plus WebSocket connectivity. Open House manager in
   Bots. Do not create a duplicate local profile or share the PVC with another writer.
6. Create/configure a distinct Discord bot and allowlist numeric operator IDs.
   Enable Discord only after its credentials and authorization are set. Validate
   unauthorized-user denial before household use.
7. Voice preferences are staged as local STT (`base`) and Edge TTS. Edge is a cloud
   service, not offline speech. Verify installed-version configuration, model and
   dependency availability, actual transcription and playback before calling voice
   operational. Do not install runtime dependencies into the image ad hoc.
8. Validate read-only device queries, ambiguous names, inaccessible entities,
   unavailable devices, transcription errors, connection failures and cross-channel
   isolation. No physical device action has been tested during bootstrap.
9. Only after review, enable selected low-risk controls; keep hazardous actions
   excluded. Home Assistant remains responsible for deterministic automations and
   urgent alerts. Verify state after every future control command.

ArgoCD uses manual sync: committing this declaration does not publish or reconcile
it. The live egress patch can drift from the remote `main` source until the
declaration is published. No workload rollout or broad app sync was run during
the documented activation.
