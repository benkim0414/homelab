# Desktop Langfuse fail-closed guard verification — 2026-11-18

## Scope and authorization

The operator approved a fail-closed guard for both workstation profiles,
`homelab-scientist` and `default`, before enabling tracing. The operator had
already entered the separate `hermes-desktop` project keys through the private
helper and reported both successful. No keys, credential files, sessions or
transcripts are reproduced here. No inference authentication/provider changes,
core upgrade, gateway restart, messaging configuration or cluster change occurred.

## Implemented and installed

Repository source: `langfuse/plugins/homelab-langfuse-desktop/`.
`langfuse/install-desktop-guard.py` copied the three reviewed plugin assets into
each selected profile's normal user-plugin directory and verified their bytes.
It refuses a different existing installation and does not activate plugins or
read credentials. Installation was followed by supported per-profile plugin CLI
commands, explicitly disabling both bundled aliases and enabling only
`homelab-langfuse-desktop`, without tool-override permission.

Readback established guard enabled, bundled Langfuse disabled, unchanged selected
provider/model/terminal settings and unchanged unrelated enabled plugins in both
profiles. No existing sessions were restarted. These changes apply to new
processes; existing processes are not evidence of new-plugin activation.

The guard requires exact private HTTPS/metadata/desktop/sample/service settings
at registration and on every hook. Its private delegated capture mode is always
metadata; no alternate credential fallback is returned. It binds the registration
home, refuses multiplexing, checks actual SDK destination and rejects existing
same-project resource-manager cache entries. A private OpenTelemetry provider and
owned-resource unload handling avoid exporter accumulation. It pins the exact
reviewed bundled source and never edits Hermes core or the bundled implementation.

Reviewed source SHA-256:
`75f0959a4152145a7c33591d6ddd3c4c8bfd53b29e0807f18abdc19bb8a485d1`.
The installed source checkout reported HEAD
`2237be355906fbe6065ce1815711eee52b2d646e`; older CLI version reports/upstream
abbreviations are not the source-pin authority. The bundled source digest was
unchanged after verification. SDK was 4.15.2 with OTel API/SDK/HTTP exporter 1.39.1.

## Local validation

- Full verification unit suite: 191 tests passed, six skipped. The new guard's
  19 source-dependent tests ran, not skipped.
- Six installer filesystem tests and ten private key-entry tests passed.
- Fake-key guard tests cover unsafe settings, home/multiplex boundaries,
  constructor kwargs/destination, resource-cache collisions, source drift,
  independent generations, unload/reload, frozen metadata and negative payloads.
- `git diff --check` passed.
- Publication CI downloads the reviewed public delegate at immutable upstream
  revision `2237be355906fbe6065ce1815711eee52b2d646e` and verifies the source SHA-256
  above before running tests with `HERMES_TEST_CORE`. The downloaded-source
  fixture was exercised locally: all twenty guard tests ran and passed. A runner
  without the workstation checkout therefore does not silently skip guard tests.
- Native CLI plugin doctor completed but warned that hooks were not registered
  in its isolated test context. That result is not counted as positive hook
  activation evidence; the installed-profile native-loader checks below supply it.

## Live desktop verification

Separate clean processes were used per profile. Normal profile dotenv loading
and scoped secret resolution supplied authentication; no project credentials
were copied between profiles or displayed. The actual shell launcher supplied
policy settings. The installed guard was discovered, gated and loaded using the
native `PluginManager` and real registration ledger, not only a mocked context.

Both profiles registered exactly eleven hooks, authenticated only to the private
`hermes-desktop` project, and exported a deliberately synthetic, no-model root
through the guarded native hook. Bounded private v2 observations readback proved
omitted input content, empty output, desktop environment and absence of the
synthetic canary. No generation/model request was performed or simulated as a
real agent conversation.

| Profile | Installed guard setup trace | Result |
| --- | --- | --- |
| homelab-scientist | `eb1b704220d0c326c4713e964c53390f` | private auth, omitted IO, canary absent |
| default | `66296c04876349a47fb1e77b701c7bf6` | private auth, omitted IO, canary absent |

Changing capture to `full` after registration caused the next hook to be refused;
the delegate's capture mode remained metadata. Separate installed-loader negative
checks covered plain/missing launch settings, a Cloud URL, `full` and `sanitized`
for both profiles: eight refusals, zero registered hooks and zero SDK resources.
The Cloud value was only an admission-negative test; no SDK was constructed for it.

Sanitized local evidence, intentionally ignored rather than committed:

- `verification/cache/desktop-guard-activation.json`
- `verification/cache/guard-scientist-installed-runtime.json`
- `verification/cache/guard-default-installed-runtime.json`
- `verification/cache/desktop-guard-negatives.json`
- `verification/cache/langfuse-guard-full-tests.log`

## Real desktop turns: privacy passed, trace grouping failed

The operator completed a no-tool and terminal-tool turn in each CLI session and
confirmed the lower screenshot pane was the default profile. A bounded private
v2 readback covering 03:54–04:40 UTC on 2026-11-18, restricted to the two known
test sessions, verified all four turns and twelve observations. Each profile had
two roots, three generations and one terminal observation. All completed; each
generation/tool parent matched its own turn root. Available generation usage was
present. Nested system/prompt/response/reasoning/tool argument/result fields and
tool metadata args used omission stubs, and neither test marker nor secret-key
marker appeared in the inspected IO/metadata. No payloads were printed or saved.

| Profile | Trace ID shared by both turns | No-tool root | Tool root |
| --- | --- | --- | --- |
| default | `4b8ce2a61a6a53e984a79c87b56e126d` | `5362ab34b0076066` | `dc59c1c8f10854a6` |
| homelab-scientist | `76e421610dbe5a2f6547e3d97ab7a219` | `aedbaa1f5dc94997` | `be547d820d7962f0` |

Distinct trace IDs per turn did **not** pass: the pinned desktop delegate seeds
`create_trace_id` from session ID and task ID/task key, rather than a unique turn
identifier. The live API shows two different turn roots within each reused trace.
Privacy acceptance is therefore positive, but overall acceptance remains partial
until grouping is corrected and retested. The audit partitions by actual root ID
and verifies complete observation coverage; it does not treat a shared trace as
one turn or hide this defect by relaxing the acceptance result.

Sanitized evidence: `verification/cache/desktop-real-turn-audit.json`.
This verification changed no installed plugin, authentication, provider or session.

## Approved v1.0.1 trace-identity correction

The operator approved the grouping fix. Only the adapter's private delegate now
receives a root-local client view: each new root uses the SDK's fresh unseeded
trace-ID factory instead of the old repeating seed. Session IDs and the native
active-root lookup are unchanged, so requests/retries/tools still reuse their
active turn root. Neither the canonical SDK client nor bundled source is patched.

A regression failed on equal IDs before the fix, then passed with distinct IDs,
stable active-root reuse, unchanged session grouping and omitted content. All
twenty guard tests passed; the complete suite passed 192 tests with six skips.

Both installed copies were updated to v1.0.1 after verifying the exact three
v1.0.0 asset digests. Previous public plugin code only was preserved under
`verification/cache/guard-v100-code-backup-wdlm6x7_`; no credentials were copied.
Updated asset bytes were read back, and the supported CLI reports v1.0.1 enabled
in both profiles with bundled Langfuse still disabled. Configuration, credentials,
core, cluster and existing sessions were not changed or restarted.

Live checks used the installed native loader and actual SDK, creating two
**synthetic no-model** roots in one session in each fresh profile process. Both
roots had distinct trace IDs, the same session ID and the same SDK client. Private
v2 readbacks verified omitted IO and no canary. These are not real agent turns.

| Profile | Synthetic root trace IDs |
| --- | --- |
| homelab-scientist | `031d643b0d256ead6a70df0f7cf9a2a0`, `76e141e2c4d31843abf368c4b638328a` |
| default | `9345148e5ced7e9c5f4b67464cb04d2c`, `ff3fd9cbe7f794a01e9a4e209e8b27cd` |

Eight installed-loader plain/wrong-URL/full/sanitized controls again refused
admission with zero SDK resources. The original bundled source digest remained
unchanged. Evidence: `verification/cache/two-turn-scientist.json`,
`two-turn-default.json`, `guard-turn-id-update.json`,
`turn-id-negative-controls.json`, and `guard-turn-id-full-tests.log` in the same
cache directory. Old shared traces are preserved; this fix only affects new roots
in new processes.

## Real v1.0.1 retest: desktop capture and grouping passed

At 16:17 AEDT the private v2 API confirmed the operator's separate no-tool and
terminal-tool retest turns in each new CLI session. Each session also contained an
earlier combined/conflicting test prompt; the audit explicitly selected the latest
two separate turns per session, not that ambiguous initial attempt. The bounded
discovery window began at 16:10 AEDT and selected only the two approved services.

Four selected turns produced four distinct trace IDs and twelve observations.
Each profile had two roots, three generations and one terminal-tool observation;
all completed, usage metadata was present on generations and each child linked
to its own root. Session IDs remained stable across each pair. Root/generation
system, prompt, response and reasoning content, plus tool input/output and
metadata args, were omission stubs. Neither canary nor secret-key markers appeared
in the inspected IO/metadata. Full observation coverage was checked.

| Profile / session | No-tool trace | Tool trace |
| --- | --- | --- |
| default / `20261118_161104_df8f77` | `2cdde5f8b8d566a3da60cb93af3e4a63` | `a5565b431dde59080e38c6f46b476432` |
| homelab-scientist / `20261118_161056_f79cfe` | `83b4073f6fa73130c6f98a8a2327fb79` | `705d9949c69a66c55f587194b7742955` |

Sanitized evidence: `verification/cache/desktop-v101-real-turn-audit.json`.
Its content, distinct-trace and combined desktop-turn acceptance results are all
true. This supersedes the earlier pending real-turn/grouping gate, not the
historical shared-trace evidence. No runtime changes were made during this readback.

## Remaining acceptance and limits

Desktop real-turn privacy and grouping acceptance are complete. Earlier real
cluster-turn acceptance is separate; the cluster core stays v0.22.2. Controlled
server restart/persistence and disposable client-outage acceptance also remain
pending. This is not backup/restore proof.

Only separate single-profile CLI processes are covered. Multiplexed backends are
refused, not automatically configured. The guard cannot protect against hostile
Python or another independent same-project SDK consumer; keep the bundled plugin
and other same-project SDK consumers disabled. Updating the pinned native source
or SDK private APIs requires review. Already queued metadata can drain at shutdown.

Immediate rollback: use the supported CLI to disable only
`homelab-langfuse-desktop` in the affected profile; leave bundled Langfuse disabled.
Do not delete keys, change inference settings or restart active sessions merely
to roll back tracing. Publication is separate from these desktop verification
operations and does not authorize a cluster rollout.
