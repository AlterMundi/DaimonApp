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
directory, home, Claude configuration directory, Matrix observation command,
CLI version, model and body. Use an isolated Claude configuration directory.
The profile's `apiKeyFile` is an absolute owner-local path to the authorized
Anthropic Console key. Store the single key in an owner-readable regular file
with no group or other permissions. Claude's local authentication status must
identify the selected first-party API key before the SDK starts. The key is
passed only in the environment of the native SDK launch and its authentication
probe. Source content cannot select any of these settings.

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
`submission_decision` with `committed: true`. Claude uses the allocated UUID
as its native session ID. Status presents both identities, including retained
exposures after a process restart.
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
