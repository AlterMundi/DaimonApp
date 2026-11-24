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
authenticated daemon. The conversation grant contains `we.conversation.page`
and `we.converse`. The observation grant contains `runtime.status`. Use the
standard private sibling-conversation disclosure policy for the demo. The
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
The real CLI checks use a synthetic Matrix broker and intentionally stop at
the submission boundary. The terminal and lost-output checks use a
deterministic SDK double.

The broker's host operation and the same-being transport are tested through an
authenticated Matrix socket with synthetic authority. The round trip runs
Matrix's actual signing, sealing and intake logic on both test bodies with a
fixture peer transport. It exercises refusal for a mismatched selection and
one undetermined return. The Node boundary also checks that the prompt and tool
input cannot substitute the command or receiving selection.

A Gateway caller still has to bind this module to the selected foreground
dispatch, journal and return route. Live Matrix credentials, provider
inference, native session recovery, signed reply delivery and human readback
require separate receiving evidence. This adapter currently claims only
discrete turns and retains an uncertain outcome when its result is missing.
