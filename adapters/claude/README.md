# Claude foreground turn

This adapter implements the preflight and single-input execution boundary for
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

### Gateway worker

Launch `gateway-worker.mjs --profile <owner profile>` once for a selected
foreground attempt. Gateway owns the process group, starts it with a cleared
environment, and keeps both pipes open until the outcome. The worker's private,
owner-owned profile selects the absolute SDK entry, Claude binary, working
directory, home, Matrix observation command, CLI version, model and body. Use the
Claude Code model alias `opus` to follow its current Opus selection. The
optional `effort` is passed to the Agent SDK as a session option.
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

Set `maxBudgetUsd` to the owner-approved SDK estimate for one invocation. The
worker permits up to two agent turns for the one read tool and reply. The SDK
estimate can overrun its limit, so applicable provider-side limits still control
spend. [Anthropic authentication guidance](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use) ·
[Agent SDK options](https://code.claude.com/docs/en/agent-sdk/typescript#options)

The UTF-8 newline-delimited protocol uses schema
`daimon-gateway.claude-turn/v1`. Every frame carries the same `inputId` and
`sessionId`. Gateway sends `start` with the retained `text` and independently
observed Matrix `body`. The worker requires that body to match its private
profile. After the identity and catalog checks, the worker emits
`prepare_submission` with the native session identity. Gateway records that
binding and exposure together in the existing journal before returning
`submission_decision` with `committed: true`. A fresh Claude session uses the
allocated UUID. For a private Interaction conversation, Gateway can send
`resume: true` with the previous native session UUID. It selects that UUID
in the canonical journal only when the last exposed turn in the same
conversation and Matrix thread returned a signed reply that Interaction
retained, with the same receiving body and manifest. The original still has
its own input ID and submission decision. A previous exposure with an
uncertain result starts a separate native session for the next new original.
The same applies if Claude reports that the selected native session is missing
before submission. A new original sent before the previous reply has been
retained in Interaction starts its own session.
Manual owner runs and existing unbound transcripts stay isolated. Deploy
the Gateway and Claude worker from the same revision for resumed turns.
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
Set `FOREGROUND_TEST_INTERACTION=1` to drive authenticated Interaction and send
a new original after restarting Gateway. The loopback provider checks for the
first turn's prompt and reply in the resumed native session, and Interaction
reads back the new signed reply.

For the composed Gateway and TeleDaimon candidate, set
`FOREGROUND_TEST_WITHOUT_TELEGRAM_CODEX=1` to repeat the signed fixture with
external Telegram transport unavailable and no usable Codex executable.
`CLAUDE_TEST_WORKER_PATH` can select that candidate's exact worker source.
All Matrix identities, user input and provider output are synthetic.
