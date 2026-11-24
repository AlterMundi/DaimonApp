# Claude foreground turn

This adapter implements the preflight and single-input execution boundary for
[DaimonGateway harness dispatch](https://github.com/AlterMundi/daimon-matrix/issues/497).
It takes the owner-selected signed Matrix binding, a broker backed by its
authenticated client, and the existing Gateway journal's submission callback.
The included status broker exposes one read through an in-process SDK MCP
server. Preflight and the tool use the same owner-selected
`matrix_operator.py --body-status` command. It uses the existing private v1
host binding and its runtime observation capability. The host verifies the
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
publish through its existing Matrix return path.

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

The broker's host operation is tested through an actual authenticated Matrix
socket with synthetic authority. The Node boundary also verifies that neither
the prompt nor tool input can substitute the command or receiving selection.

A Gateway caller still has to bind this module to the selected foreground
dispatch, journal and return route. Live Matrix credentials, provider
inference, native session recovery, signed reply delivery and human readback
require separate receiving evidence. This adapter currently claims only
discrete turns and retains an uncertain outcome when its result is missing.
