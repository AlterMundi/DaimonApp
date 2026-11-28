# Claude foreground turn

This adapter implements the preflight and native execution boundary for
[DaimonGateway harness dispatch](https://github.com/AlterMundi/daimon-matrix/issues/497).
It takes the owner-selected signed Matrix binding, a broker backed by its
authenticated client, and the existing Gateway journal's submission callback.
The included status broker exposes one read through an in-process SDK MCP
server. Preflight and the tool use the same owner-selected
`matrix_operator.py --body-status` command. It accepts the private messaging
host binding or the private same-being binding and uses the separate
runtime observation capability in either case. The host verifies the
daemon response and returns only the authenticated body fields needed for
admission. The Claude executable receives no Matrix key or binding path. The
adapter owns no journal, queue or reply publisher.

The Agent SDK must finish initialization before the adapter reads the effective
MCP inventory. The adapter checks the pinned CLI version, exact tools and
in-process server provenance. It rechecks Matrix status before releasing the
prompt. Gateway supplies the two UUIDs for the original and Claude session.
The callback returns true only after persisting the submission boundary with
both UUIDs. Cancellation or execution loss past that boundary keeps the
original uncertain. A completed result is output for Gateway to commit and
return to Matrix.

### Steer a routed conversation

A paired human's plain-text message can join an active routed Claude conversation
through the same Gateway steer admission and receipt journal used by Codex. The
worker offers this capability at preparation and the Gateway enables it only on
an eligible paired local execution. Either side may omit the capability to keep
serial execution. Matrix foreground and dedicated Conversation-provider
exchanges continue to execute one input at a time. Attachments, native goal
commands and attributed handoffs retain their ordinary queued execution.

The worker keeps the same native input stream open and sends an eligible input
with its original UUID and Claude priority `next`. Claude reads it after the
current tool calls, or in its next native turn if the current turn ends first.
A native status or reply frame that echoes the current original and a steered
UUID records incorporation immediately. The paired human's new original can then parent a
local session request within that running turn. The completed result still
records the exact consumed UUIDs. Shared and separate replies retain their
actual native result membership. Inputs known to have stayed
outside the native stream can return to Gateway's queue. A write or execution with
an unconfirmed outcome retains the original without replay. This path never
requests an immediate interrupt.

### Gateway worker

Launch `gateway-worker.mjs --profile <owner profile>` once for a selected
foreground attempt. Gateway owns the process group, starts it with a cleared
environment, and keeps both pipes open until the outcome. The worker's private,
owner-owned profile selects the absolute SDK entry, Claude binary, working
directory, home, Matrix observation command, CLI version, model and body. Use the
Claude Code model alias `opus` to follow its current Opus selection. The
optional `effort` is passed to the Agent SDK as a session option.
Set optional `displayName` to the owner-selected human-readable name for the
verified Matrix body. The native system prompt identifies the harness and this
display name. Device status and body coordinates still come from the authenticated
Matrix broker. The prompt does not grant memory, tools or skills.

Paired routed topics use the directory saved against the logical Gateway
session. The Telegram `/pwd` and `/cd` commands read or change that same
setting. The adapter verifies the directory and returns its selected path
before Gateway commits submission. If the selection changes during
preparation, the original is preserved without native submission. Peer
context and the worker's input text never choose a working directory.

The effective workspace is part of Claude's native history scope. Selecting
the same path as the worker default preserves existing compatible history.
Changing the directory can start a new native history in the same Gateway
topic; the prior history remains recorded and the normal bounded context
handoff applies where available. Private Matrix foreground turns use their
configured default workspace. Deploy and roll back the matching Gateway
binary and worker together.

Set optional `bodyGuidanceFile` to the absolute path of an owner-private UTF-8
file, at most 16 KiB. Select the receiving being's portable orientation and
keep the canonical SOUL in its maintained source. The worker appends the file
to authorized paired or routed host-access turns alongside the current topic
instructions. Scoped Matrix-only turns keep their existing context. The worker
checks that the selected text is stable through submission. Guidance updates
do not change the authorization scope or replace native history. Repository
guidance remains a separate owner selection. This field grants no resource,
tool or route and performs no memory or inbox preload.

Use `--skill-resume-anchor <owner profile>` to read the exact installed inventory
revision and its layout revision. For owner-managed packages, set
`skillContinuity.layoutRevision` to the reviewed layout. Body text and the
conventional quoted `metadata.version` change across compatible releases without
forking a new session. The layout includes names, resolved paths, and all other
frontmatter, including native tool and context settings. A different layout
does not inherit this compatibility. The worker still checks the complete
inventory digest at the submission boundary.

When adopting the feature for a retained native session, set
`skillContinuity.previousRevision` to the exact verified inventory value that
named its existing scope. A new profile can omit that field. Older
`skillResumeAnchor` entries remain supported for explicitly reviewed exact
inventory revisions outside the selected layout. The other scope inputs,
including the body binding, memory and tools, continue to partition native
history. Verify a resumed turn and the new installed skill before reporting
receiving adoption.

For paired topic inputs, Gateway can supply up to three completed exchanges
from the current logical topic generation, with one exchange per native lineage.
It reads the retained originals and completed replies, keeping each exchange
whole within the 12 KiB encoded context bound. A compatible native resume takes
precedence, and the worker omits exchanges already in that native session.
The adapter labels the older exchanges as historical data and keeps them
separate from the current original.

A project's active checkpoint may be kept as UTF-8 `CONTINUITY.md` (up to 8 KiB)
in the Gateway-claimed conversation folder. Install it as an owner-only regular
file and replace it atomically when the project state changes. The Gateway uses
the conversation's own folder claim even when the working directory is a
different project checkout. On a fresh Claude session or when supplying retained
history across a gap, the worker attaches the checkpoint as a separate data
block. Prefer dated status, verifiable revisions and source pointers. The file
carries no approvals or instructions. Missing or invalid files and checkpoints
that exceed the total worker frame budget leave ordinary conversation delivery
available. When the SDK confirms a selected native history is missing before Gateway
commits submission, Gateway may prepare one successor under the same routed
input and local turn. For paired human input, the successor must carry retained
history or a project checkpoint. Cancellation, mismatched scope, confirmed
exposure and uncertain outcomes leave the original retained. A paired
Conversation reply to a canonical result carries the exact
selected text to either a resumed or fresh Claude context. Gateway retains
the selected text digest at capture and verifies the original source and
destination at preparation. A changed delivery status can preserve the same
text; a different result or topic cannot supply the quote. This uses the
normal run queue when a Claude turn is busy. If an explicitly selected result
cannot be supplied, Gateway retains the original without submitting it.
For Telegram replies, Gateway resolves the quoted message ID from the
retained incoming update and matches a publication receipt to an owned final
result in the current topic generation. It uses the canonical result body
even when a Telegram reply points to one part of a split publication. It does
not import the nested Telegram reply text. A prepared quote is revalidated
before submission. An identified result whose text was withheld, exceeds the
context bound, or belongs to a retired generation leaves the input retained.
Other replies keep their existing path. A current canonical local-session
result keeps the caller's Claude controller catalog so the worker can resume
the requesting session. The controller can inspect the returned input and
request status. The result carries attributed evidence and cannot authorize
another local request. An authenticated paired human can use Claude's native
`/goal` command directly in Telegram or in the Conversation composer with the
Claude topic selected. Gateway binds the command to the original and the
selected topic. Quoted, voice-derived, attached, companion and session-authored
inputs cannot invoke the native command through that Conversation path.
Deploy and roll back the Gateway binary
and Claude adapter together, since older workers reject the added start field.

When the last eligible exchange came from the topic's current Codex thread,
Gateway can attach its exact original and final answer to a resumed or fresh
Claude thread. It checks the logical owner and generation, the physical
receipt, and whether multiple originals could have produced the answer. Native
history remains in its own harness. This currently covers routed originals and
direct Telegram originals with matching receipts. When the topic returns to
Codex, its existing native thread is resumed. At the first paired turn after
completed Claude work, Gateway supplies the same topic's owned Claude
exchanges and available project checkpoint as named untrusted native context.
The original input keeps its existing contents and delivery identity. Gateway
checks the selected context again before native submission.

For paired work, optional `matrixMessaging` selects the owner-private
`connection.json` returned by the existing Matrix chat attachment installer.
Provision it using the Claude embodiment's own messaging application and
signed grant. For a standalone Cluster body with the signed Tribe application
selected, use the attachment with the `daimon_matrix.agent_chat` launcher on
`tribe.sock` and keep the identity observer on the sibling `matrix.sock` in the
same runtime directory. Existing shared-socket bindings are also supported.
The worker checks the runtime, embodiment, incarnation and exact four
messaging RPC methods. It registers the maintained stdio MCP only for
paired host-access turns. It checks the precise native catalog before
exposure and rechecks the exact messaging binding before releasing input or
accepting steering. Enabling the binding resumes the existing same-scope
paired history, including sessions already indexed with a messaging
fingerprint. Setup and discovery do not read an inbox or send anything.

For Claude CLI versions that omit tools with a root union schema, use
`matrixMessaging: { "connection": "/path/to/connection.json", "objectToolSchemas": true }`
with a Matrix client that supports `agent_chat mcp --object-tool-schemas`.
This changes catalog presentation only. Matrix validates ordinary send and
exact recovery separately before dispatch.

`sharedDmk` selects the existing being-level DMK reader for normal private
Claude turns. Set `command` to the installed DMK stdio reader invocation
without `--binding`, `bindingFile` to the owner-local binding for this Claude
body, and `bodyRef` to that binding's body reference. The binding may point to
the same authorized DMK pools used by the Codex body. The worker checks the
being and body in the owner-provisioned binding and opens those exact bytes
for the native connector. It requires both DMK recall names in the effective
tool catalog before releasing the original. Claude's own
automatic memory and dreaming are disabled for this route.
The worker submits signed text literally. The CLI does not expand file
mentions or dispatch slash commands from Matrix originals.

`sharedSkillsDirectory` selects the same owner-managed skills directory used
by the other embodiment. The worker exposes its current skill files through
a local Claude plugin with the `compaii-shared` namespace. No skill files are
copied and no user or project settings are imported. Before submission, the
SDK's loaded shared skill names must match the selected directory. Claude
loads a skill through its native `Skill` tool. With a matching
`skillContinuity.layoutRevision`, text and conventional version changes keep
the native session eligible for resume. The worker still checks the exact
current inventory at submission. Changes to the catalog, paths or
authority-bearing metadata change the scope and use the logical
conversation's retained context when a fresh native session is required.

`matrixFoundation` takes the qualified Matrix Foundation stdio `command` and
the exact permitted `tools` list. Use the owner launcher for the Claude
body's existing runtime root and owner-local request directory. The worker
checks the protected client descriptor's embodiment, incarnation and
authority window, then checks the actual SDK catalog and verifies
`daimon_status` through that same capability before submission. Matrix
decides each subsequent call under its signed grant. An owner change to
access that also retires earlier disclosed context should rotate the
Foundation capability, which starts a fresh Claude session. The stdio wrapper
clears inherited provider credential environment variables.

For private turns authenticated as the paired human, portable harnesses use
their native full-access mode without per-tool approvals. Claude's Agent SDK
uses `permissionMode: 'bypassPermissions'` with
`allowDangerouslySkipPermissions: true` and Bash sandboxing disabled. The
default native tool catalog is Bash, Read, Write, Edit, Glob, Grep and
NotebookEdit. Startup remains bounded. After the Gateway records submission,
private full-access turns without an explicit test budget can run until Claude
returns or the input is interrupted. Use `hostTools` to select a subset explicitly. Set
`hostToolDirectory` to the owner-managed directory of shared command wrappers
to expose commands such as the existing `dmk` writer to authenticated Bash
turns. It extends the worker's explicit system path and starts a fresh native
session when the selection changes. Keep the DMK MCP connector as the reader
and use the same installed DMK wrapper and pool as the other local embodiment
for native writes. When this profile selects a DMK reader and its host tool
directory contains an executable `dmk` wrapper, the prompt tells paired Bash
turns about both routes. The owner provisions that wrapper for the same pools
as the reader. The hint preserves the existing native session scope.

For the verified paired subscription profile, Bash inherits the receiving
Linux account's host access, including existing sudo policy. The worker
constructs the subscription environment without provider credential variables.
API-key profiles retain the separate subprocess isolation to keep their key
out of Bash. On Linux that isolation also prevents sudo and limits writes.

Gateway includes the authenticated-original marker only after checking the
retained private Interaction input against the signed Matrix original. Companion
credentials and manual Matrix owner runs retain their existing MCP and skill
catalog. Upgrade the dashboard producer, Gateway and worker together. Changes
to the permission mode or native tool selection start a fresh Claude session.
Tool effects use the process owner's existing OS permissions. Bash uses Claude
Code's subprocess credential-environment scrub.

To try experimental Code Mode in the interactive terminal, use the same
permission mode and disable the Bash sandbox:

```bash
CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1 claude --model opus --effort medium \
  --permission-mode bypassPermissions --settings '{"sandbox":{"enabled":false}}'
```

The interactive CLI handles Code Mode activation. Code Mode uses the same
permission configuration for its tool calls. This headless Agent SDK worker does
not activate it. See [Claude Code permissions](https://code.claude.com/docs/en/permissions)
and [Code Mode](https://code.claude.com/docs/en/code-mode).

Select one authentication mode in the owner profile:

- For a private Claude Code subscription, set `subscriptionEmail` to the exact
  email shown by the already signed-in native CLI. The worker uses the selected
  home's default Claude Code configuration. Its auth probe checks that the
  first-party Claude account matches and has no reported API key source. The
  native CLI manages its own login using the same home in the probe and turn.
  The launched SDK session must also identify the same subscription account
  before Gateway can record and release the original.
- For explicitly selected Console use, set `apiKeyFile` and
  `configurationDirectory` to absolute paths. Store the authorized key in an
  owner-readable regular file with no group or other permissions. The first-party
  auth probe must identify that key environment source before the SDK starts.
  The key goes only to the native SDK launch and auth probe.

Source content cannot select these settings. See
[Claude plan usage with the Agent SDK](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan).

Leave `maxBudgetUsd` unset for ordinary use. Gateway then passes neither an
SDK dollar estimate ceiling nor a maximum number of SDK turns. The provider's
quota and the existing Gateway worker deadline still apply. An operator may
set `maxBudgetUsd` for a bounded qualification profile. That profile also caps
SDK turns at two for status-only runs and six for runs with extra tools. The SDK
estimate can overrun the configured ceiling.

For Foundation catalogs of ten or more tools, native ToolSearch loads Foundation
schemas on demand. The full signed MCP inventory is still checked before
Gateway authorizes submission. The identity check and shared DMK stay available
on the first model call.
[Agent SDK options](https://code.claude.com/docs/en/agent-sdk/typescript#options)

With `interaction_direct = true` in `[interaction.claude_foreground]`,
paired-human Interaction originals enter the Gateway session queue and
outcomes are stored in its canonical turn record. The installed body identity,
effective tool catalog and OAuth selection are still verified before input
exposure. Ordinary messages do not use Matrix transport. This setting affects
the Interaction Claude selection; the explicit signed Matrix route is separate.

Keep the upgraded Gateway binary when rolling back the setting after direct
turns have been exposed. To restore the signed route, turn off
`interaction_direct` and retain the existing `interaction_origin` profile.
The upgraded reader keeps previous direct results and prevents the same native
transcript from reopening behind a newer uncertain attempt. A pre-upgrade
binary cannot interpret that evidence; use a fresh logical generation before
resuming input with it.

The signed Interaction route uses the existing signed CompAII sending
body to transport the original. Interaction retains the paired human as the
author of the original. For authenticated paired-human turns, Gateway's
verified original marker tells Claude to preserve that attribution. Matrix
receipts identify their actual transport signer.

On ITACA use a 30-second Matrix transport deadline for the private foreground
origin and return. Native same-being fanout can finish a separate sibling's
visibility attempt after the selected recipient has already acknowledged
delivery. A shorter outer deadline can lose the selected receipt. Keep a
timed-out original under its existing identity and inspect the native receipts
before taking any recovery action.

The UTF-8 newline-delimited protocol uses schema
`daimon-gateway.claude-turn/v2`. Every frame carries the same `inputId` and
`sessionId`. Gateway sends `start` with the retained `text` and independently
observed Matrix `body`. The worker requires that body to match its private
profile. After the identity and catalog checks, the worker emits
`prepare_submission` with the native session identity and current DMK
authorization scope. Gateway records both and the exposure together in the
existing journal before returning `submission_decision` with
`committed: true`. When the worker advertises `inputAcceptance` and Gateway
selects `observeAcceptance`, the worker emits one `input_accepted` frame
only after the SDK echoes the exact original UUID in the selected native
session. Gateway retains that evidence apart from the result. Older workers
can complete through the existing result path. Each `start` provides a fresh
native UUID independent of the turn's correlation UUID. For a private Interaction conversation, Gateway can
also offer the previous native UUID and scope. It selects that candidate
only when the last exposed turn in the same
conversation and Matrix thread returned a signed reply that Interaction
retained, with the same receiving body and manifest. The worker resumes only
when the current DMK authority matches the scope recorded for that UUID.
Changing or revoking the binding uses the fresh UUID for the new original.
A previous exposure with an
uncertain result starts a separate native session for the next new original.
The same applies if Claude reports that the selected native session is missing
before submission. A new original sent before the previous reply has been
retained in Interaction starts its own session.
Manual owner runs and existing unbound transcripts stay isolated. Deploy
the Gateway and Claude worker from the same revision. Rollback restores
both together with the earlier compatible owner profile. The distinct
native UUID bars a previous Gateway from resuming a scoped transcript.
Status presents both identities, including retained exposures after a restart.
An absent, rejected or mismatched decision prevents prompt submission. The
only terminal frame is `outcome`. A missing outcome after a recorded exposure
keeps the attempt uncertain. A closed owner pipe cancels a running attempt.
The worker neither retries nor writes to Matrix.

### Same-being conversation transport

Gateway uses the existing Matrix `/we` conversation for a turn between bodies
of the same being. `matrix_operator.py --we-read` accepts a fixed body
observation and a selected original identified by its author, event ID, thread
ID and an owner-selected cursor. It returns the message only after resolving
its local intake receipt on that thread. It searches at most 16 pages of four
ledger events under the caller's deadline. A retained cursor close to the selected
event keeps the read within that bound.

`--we-return` rereads the same selection, submits one durable caller-selected
send ID with a 30-second envelope lifetime, and waits for the semantic receipt
from the original author. The response is a new message on the original thread,
addressed to the original author under Matrix's signed sibling audience. The
Gateway journal retains
the correlation with the original. A missing receipt leaves the return
undetermined, including when another sibling has received a copy.

The owner-only `daimon-gateway.matrix-we-binding/v1` document identifies the
source and holds `conversation` and `observation` SDK references to the same
authenticated daemon. Select the maintained Matrix weave grant for
`we.converse` and the observation grant for `runtime.status` and
`we.conversation.page`. The host exposes only those selected operations.
Use the standard private sibling-conversation disclosure policy for the demo. The
signed optional Telegram disclosure must be checked on both demo bodies before
live use. This host adapter provides no enrollment or disclosure writer.

Run the contract tests with Node 20:

```sh
node --test adapters/claude/*.test.mjs
```

Set `CLAUDE_TEST_SDK_PATH` to the pinned SDK entry point and
`CLAUDE_TEST_BINARY` to the matching native executable to include the real CLI
preflight test. `CLAUDE_TEST_CLI_VERSION` defaults to 2.1.323. Run the test in an
environment without provider credentials or external network access. The
fixture covers SDK 0.3.323 with CLI 2.1.323 and SDK 0.3.325 with CLI 2.1.325.
The isolated native checks use a synthetic Matrix broker. The CLI auth probe
selects the synthetic API key against the fixture SDK. The real SDK catalog
probe runs without a key and stops before prompt submission. Native bootstrap
with a synthetic key timed out on the isolated network. The terminal and
lost-output checks use a deterministic SDK double.

The broker's host operation and the same-being transport are tested through an
authenticated Matrix socket with synthetic authority. The round trip runs
Matrix's actual signing, sealing and intake logic on both test bodies with a
fixture peer transport. It exercises refusal for a mismatched selection and
one undetermined return. The Node boundary also checks that the prompt and tool
input cannot substitute the command or receiving selection.

### Selecting a foreground original

In the existing Gateway interaction configuration, set
`interaction.claude_foreground.worker_command` to the absolute Node command,
worker path and `--profile` path. Set
`interaction.claude_foreground.transport` to the existing Matrix host command
shape with the owner-local `/we` binding, the same body identity and a timeout
from 1 to 60 seconds. This independently configured host can coexist with the
ordinary Matrix transport.

Use the authorized owner socket command `matrix claude run JSON`. Its selection
contains `event_id`, `thread_id`, `author` (embodiment ID) and optional `cursor`.
Gateway reads the exact Matrix original and only runs one foreground attempt
per entry at a time. `matrix claude status EVENT_ID` reads the canonical
journal. Repeating the same original reads its retained state. Gateway commits
the provider exposure before acknowledging the worker, and commits the
result and one return UUID before calling Matrix. Interrupted provider or
return stages stay uncertain after restart. A result that cannot be sent
within the return bound is retained locally. There is no background intake.

Synthetic owner-route tests cover durable sequencing and repeat requests after
restart. Live Matrix credentials, provider inference, native session recovery,
signed reply delivery and human readback require receiving evidence.

When updating either Gateway or the adapter, qualify the exact worker command
and profile selected by the candidate configuration, including when the
Gateway executable itself is unchanged. Gateway configuration preflight
does not start the native worker. For a paired topic with Matrix messaging
enabled, run the selected worker with the retained native session, body, and
workspace, then deny the submission decision. Require the expected session
and scope on `prepare_submission` and a `not_submitted` outcome. This checks
the live OAuth account and MCP inventory before switching versions and catches
an older worker that cannot parse the selected messaging profile.

### Signed interop with the native SDK

Use the pinned Matrix checkout's `src` and repository root in `PYTHONPATH`.
Set `CLAUDE_TEST_SDK_PATH` to the pinned Agent SDK entry point and pass the
matching native executable. Run as the normal test user for Matrix's Unix
peer-credential checks.

```sh
python3 -B tests/foreground_signed_io.py claude \
  /absolute/gateway-executable /absolute/native/claude
```

The test uses an owner-private profile with a synthetic API key and a wrapper
that directs the native CLI only to the loopback Anthropic fixture. It checks
the actual provider-facing catalog and one Matrix status read, the durable
exposure decision, the signed return and the sender's original thread. The
reply remains available after restarting Gateway without another provider call.
Set `FOREGROUND_TEST_SIGNED_INTERRUPT=crash` to kill only the fixture Gateway
after the provider has received the original. While it is held, a different
signed original must be refused at capacity before admission. The restarted
Gateway must keep the same attempt and native session, report the exposed
outcome as uncertain,
and leave both the provider and signed return untouched on exact retry. The
fixture disables Telegram, makes Codex unusable, and waits for the receiving
writer lease with a shorter test-only expiry. With
`FOREGROUND_TEST_SIGNED_INTERRUPT=return-crash`, kill Gateway after the signed
reply is retained by the sender but before Gateway receives the acknowledgment.
After restart, the journal must retain the same send ID with an uncertain return
and the sender must still have exactly one signed reply in the original thread.
Set `FOREGROUND_TEST_INTERACTION=1` to drive authenticated Interaction and send
a new original after restarting Gateway. The loopback provider checks for the
first turn's prompt and reply in the resumed native session, and Interaction
reads back the new signed reply.
Set `CLAUDE_TEST_DMK_SCRIPTS` and, if needed, `CLAUDE_TEST_DMK_PYTHON` to run
that fixture with the native DMK stdio recall server over a disposable pool.
Set `FOREGROUND_TEST_SHARED_SKILLS=1` to make the native harness invoke a
fixture skill and verify the provider receives its instructions before the
signed reply.
Set `FOREGROUND_TEST_FOUNDATION=1` to exercise a disposable Foundation
stdio tool in the same native turn.
Set `FOREGROUND_TEST_HOST_TOOLS=1` to run a native Read and a harmless Bash
command on an authenticated Interaction input.

For the composed Gateway and TeleDaimon candidate, set
`FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX=1` to repeat the signed fixture with
external Telegram transport unavailable and no usable Codex executable.
`CLAUDE_TEST_WORKER_PATH` can select that candidate's exact worker source.

For the routed topic tests, invoke the release binary under its `telecodex`
name, which allows the fixture to initialize a disposable Codex session before
switching its Telegram transport to external. Set
`FOREGROUND_TEST_TELEGRAM_TOPIC=1`; the default case checks ordinary input,
result projection, native goal commands and a local session request. Add
`FOREGROUND_TEST_CLAUDE_MISSING_RESUME=1` to remove the fixture's prior native
history and verify the same original reaches a successor with retained context.
Add `FOREGROUND_TEST_TELEGRAM_DEPENDENCY_RETURN=1` to verify a canonical Codex
helper result reaches the same Claude native session and cannot delegate anew.
Combine it with `FOREGROUND_TEST_TELEGRAM_DEPENDENCY_RECEIVE=1` to withhold the
initial return commit in the disposable journal. The next paired Claude turn
uses `session_receive`, observes one reservation on an exact retry, and
incorporates the original canonical result into the same Claude session.
Run the following switches individually with `FOREGROUND_TEST_TELEGRAM_TOPIC=1`:

- `FOREGROUND_TEST_TELEGRAM_FILES=1` for original photo bytes and reply routing.
- `FOREGROUND_TEST_CLAUDE_ADAPTER_RECOVERY=1` keeps Gateway running with
  TeleDaimon stopped and reads a routed Claude result in Conversation. It then
  starts the named TeleDaimon process, verifies one projection of the
  known-unsent result, and checks that a separate lost acknowledgement is
  retained without replay across adapter restart.
- `FOREGROUND_TEST_CLAUDE_WEB_GOAL=1` for native `/goal` readback in the
  selected Claude session through the paired Conversation composer, with no
  additional provider call and a retained refusal for an unpaired companion.
  Add `FOREGROUND_TEST_CLAUDE_GOAL_LIFECYCLE=completed` for goal creation and
  evaluation, or `=active` to leave a goal unresolved in the native session.
  The active case verifies that a subsequent paired status or clear command
  addresses that same session while the earlier turn remains uncertain.
  Both cases verify that resubmitting the same input ID does not run the goal
  again and that an unpaired browser cannot set a goal.
- `FOREGROUND_TEST_CLAUDE_WEB_QUOTE=1` and
  `FOREGROUND_TEST_CLAUDE_TELEGRAM_QUOTE=1` submit an exact reply to an older
  proposal while a newer request is still running in the same native session.
  The fixture verifies the reply stays queued without exposure, then checks the
  selected result and revision in the next provider input, native session reuse,
  and the visible reply on the originating surface.
  Combine either quote switch with `FOREGROUND_TEST_CLAUDE_MISSING_RESUME=1`
  to verify one successor receives the same quote and the topic's retained
  checkpoint as separate historical context when the disposable native
  transcript is unavailable.
  Combine the web switch with `FOREGROUND_TEST_CLAUDE_WEB_QUOTE_INTERRUPT=1`
  to interrupt the active Claude turn through Conversation after provider
  exposure. The queued reply reaches a successor with the exact quote. The
  interrupted original remains uncertain, the late answer is withheld, and an
  exact retry of the interruption does not signal the successor.
- `FOREGROUND_TEST_CLAUDE_WEB_FILES=1` for an authenticated paired photo sent
  from the Conversation composer to a selected Claude topic. The provider
  fixture checks the original image bytes and the human's provenance, with
  and without a caption. The companion attempt is retained before exposure.
- `FOREGROUND_TEST_TELEGRAM_STEER=1` for Telegram and Conversation inputs
  delivered to the already-running Claude turn.
- `FOREGROUND_TEST_TELEGRAM_QUOTA=1` for known rejection and its scoped notice.
- `FOREGROUND_TEST_TELEGRAM_CANCEL=1` for a topic-local Stop after exposure
  and retained uncertainty when Telegram redelivers the original update.
- `FOREGROUND_TEST_TELEGRAM_DMK_WRITE=1` with `CLAUDE_TEST_DMK_SCRIPTS` for
  paired MCP recall and one native write through the `dmk` wrapper. The test
  reads back the exact synthetic record from the same disposable pool.
- `FOREGROUND_TEST_TELEGRAM_SKILL_REFRESH=1` for a compatible version and content
  change. The provider fixture verifies the prior prompt, the new skill
  instructions and the unchanged native session and tool scope.
- `FOREGROUND_TEST_TELEGRAM_CODEX_HANDOFF=1` for the first Claude turn in a
  topic previously served by Codex. The provider sees the exact prior request
  and reply as historical context, and the original Codex binding remains.
  Add `FOREGROUND_TEST_TELEGRAM_CODEX_ROUNDTRIP=1` to switch back and check the
  first Codex submission receives the Claude exchange as untrusted context
  and the next ordinary Codex turn follows its existing native history.
  Add `FOREGROUND_TEST_CODEX_WEB_ROUNDTRIP=1` to submit both transitions
  through the authenticated Conversation HTTP composer and read back both
  canonical answers there. The web return uses a short approval and verifies
  the previous exchange, checkpoint and current input at the Codex boundary.

All Matrix identities, user input and provider output are synthetic.
