# Goose ACP foreground turn

`runGooseTurn` is the native ACP client for the Goose candidate in
[Matrix #497](https://github.com/AlterMundi/daimon-matrix/issues/497).
It takes an explicit executable, working directory, isolated environment, MCP
server selection, exact tool names, one original and a Gateway journal
callback. The caller supplies the authenticated body and approved credential
selection before use. The ACP client shares Gateway's foreground owner route and existing journal.

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

## Selecting Goose in Gateway

The private `interaction.goose_foreground` configuration uses the same
`transport` and `worker_command` shape as `interaction.claude_foreground`.
Select a Goose Matrix body, its authorized `/we` transport and the absolute
Node command invoking `adapters/acp/gateway-worker.mjs --profile PROFILE`.
The owner-private profile selects `binary`, `cwd`, `stateRoot`, `provider`
(`openai` or `anthropic`), `model`, `providerKeyFile`,
`matrixStatusCommand` and the exact signed `body`. The worker uses at most
two Goose turns for the read and reply. Select an owner-only state directory
and a workspace suitable for the approved provider. The configured status command must
read the same authenticated body before submission and for each status tool
call. The MCP server returns only the verified binding fields.

Use `matrix goose run JSON` with the same owner-selected original shape as
Claude, and `matrix goose status EVENT_ID` for authoritative readback. A
repeated original returns the retained phase, engine and native identity even
if another harness is selected. Gateway authorizes, dispatches and settles the
return once through the existing journal. For software rollback, remove the
Goose configuration before selecting an older executable. Keep the same
journal and retain pending or uncertain work.

Run the contract tests using Node 20:

```sh
node --test adapters/acp/*.test.mjs
```

For the real-binary contract set `GOOSE_TEST_ACP_BINARY` to a SHA-256-verified
v1.60.2 Linux `goose-acp` binary and run the same command in an isolated network
with only loopback enabled. The test starts its own synthetic HTTP endpoint and
uses no provider account. It covers catalog discovery, one response and
interruption after provider entry. Signed private Matrix exchange, approved DMK
and live Gateway acceptance require separate receiving evidence.
