# Goose ACP foreground turn

`runGooseTurn` is the native ACP client for the Goose candidate in
[Matrix #497](https://github.com/AlterMundi/daimon-matrix/issues/497).
It takes an explicit executable, working directory, isolated environment, MCP
server selection, exact tool names, one original and a Gateway journal
callback. The caller supplies the authenticated body and approved credential
selection before use. This module has no owner route, identity or journal of
its own.

Use an isolated Goose profile with each bundled extension disabled. Goose
v1.60.2 synthesizes undeclared defaults. Persist disabled entries using its
supported extension configuration, then read back the effective list. The
client refuses any enabled configured extension. It starts a fresh native
session and compares the complete unfiltered ACP tool list, including its
cardinality, with the selected names. It authorizes no ACP client file, terminal,
permission or other callbacks. The process disables automatic title generation
so session naming cannot trigger an extra provider request.

The callback receives Goose's native ID and must return true only after the
existing Gateway transaction retains that ID with the original and marks
provider exposure. A denied decision sends no prompt. A missing terminal reply,
unexpected session, oversized reply or interruption after exposure retains an
uncertain outcome. On interruption the client requests native cancellation and
bounds process teardown. It never retries. The caller owns the worker process
group and the journal's original and return uniqueness.

Goose keeps cancelled text in the native transcript. Loading an existing
session is outside this entry point, which admits a new original into a fresh
session only. Gateway status or recovery must never call this entry point to
replay an uncertain original.

Run the contract test using Node 20:

```sh
node --test adapters/acp/goose-turn.test.mjs
```

For the real-binary contract set `GOOSE_TEST_ACP_BINARY` to a SHA-256-verified
v1.60.2 Linux `goose-acp` binary and run the same command in an isolated network
with only loopback enabled. The test starts its own synthetic HTTP endpoint and
uses no provider account. It covers catalog discovery, one response and
interruption after provider entry. Signed private Matrix exchange, approved DMK
and attachment to the real Gateway owner route require separate receiving
evidence.
