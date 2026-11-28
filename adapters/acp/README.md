# ACP foreground workers

See [Gateway ACP coverage and stack parity](gateway-coverage.md) for the
native and ACP operation inventory across harnesses.

## Antigravity CLI

`runAntigravityTurn` runs the installed `agy acp` with its sandbox and
the selected process environment. It reads back the requested model and
reasoning effort before provider submission. A continuation requires the
exact prior ACP session ID. Failed session loads stay unsent.
The Gateway route uses the configured Antigravity foreground with
`interaction_direct = true` and `agy_cli = true`, an explicitly Antigravity
target, and the common ACP worker. Its owner profile names the absolute
`binary`, paired account `home`, canonical topic `cwd`, `model`, `effort`,
`matrixStatusCommand`, and signed `body`, with `adapter: "agy"`. Set
`bodyGuidanceFile` to the owner-private portable orientation for the selected
embodiment. It is sent in a separate content block on new and resumed turns.
Set `sharedSkillsDirectory` to the installed Skills root for discovery and
on-demand `SKILL.md` reads. Set `sharedMemory` with an absolute reader
`command`, owner-private `bindingFile`, and selected `bodyRef` for DMK
search and paginated read. The broker verifies the receiving body's signed
status on each request and reads the current installed content and memory.
Optional `selectedMemory` exposes one owner-selected record revision for
one original.
The worker accepts only paired text for this topic and uses the journaled
native ID from the same topic generation, workspace and signed incarnation.
There is no fallback to a fresh session after a failed native load.

The pilot approves one ACP permission request at a time for its configured
Matrix status, skills and DMK read tools. No permanent approval is issued. Shipped
default customizations are disabled for this pilot. Wider tool parity,
attachments and native steering are separate receiving checks.

The opt-in live check uses the operator's signed-in Antigravity account and
two synthetic turns. It checks exact reload in a new process, the requested
model configuration, a withheld original and refusal of a missing session.

```sh
AGY_TEST_AUTHENTICATED_BINARY=/absolute/agy node --test adapters/acp/antigravity-turn.test.mjs adapters/acp/gateway-worker.test.mjs
```

## Goose

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
uncertain outcome. A terminal text consisting solely of an unframed local
provider tool call also remains uncertain, even if ACP reports end of turn.
When the ACP client reaches its deadline, it attempts
`session/cancel` and bounds process teardown. On Gateway shutdown the owning
worker group can end before that ACP request. Both paths retain the original
and its provider uncertainty. The caller owns the worker group and the
journal's original and return uniqueness.

Goose keeps cancelled text in the native transcript. Loading an existing
session is outside this entry point, which admits a new original into a fresh
session only. Gateway status or recovery must never call this entry point to
replay an uncertain original.

## Selecting Goose in Gateway

Stock Goose v1.60.2 includes `load_skill` in the model-facing catalog even
with all extensions disabled. Its ACP catalog omits that native operation.
Use the [pinned native skills patch](goose-v1.60.2-native-skills.patch) on
[Goose v1.60.2](https://github.com/aaif-goose/goose/tree/v1.60.2)
(commit `fb55b5a6d7f5b5df96c8f817f1cde6a81880d9f1`, [Apache-2.0](https://github.com/aaif-goose/goose/blob/v1.60.2/LICENSE)) and build
`cargo build --locked -p goose --bin goose-acp --no-default-features`.
The worker disables the native skills operation and slash commands in that
process. It requires the running ACP connection to report skills disabled
before creating a native session or authorizing provider exposure. Stock
builds lack that signal and refuse before dispatch. The joined provider and
DMK test also checks the actual inference catalog.

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

For an owner-managed local OpenAI-compatible endpoint, set `providerPort` in
the private profile. Goose uses only `127.0.0.1` on that port. After confirming
the effective catalog and body, the worker checks the listener before asking
Gateway to release the original. A closed listener is a known unsent turn.
The connection check sends no original or HTTP request.

For an explicitly approved memory read, set optional `selectedMemory` to
`command` (the absolute DMK reader command with its existing owner-local
`--binding` argument), `inputId` (the original event UUID), `pool`,
`recordUid`, `revision` and the configured DMK `bodyRef`. Only that original
can see the extra `dmk_read_selected` tool. Its empty input schema lets the
model read the selected record. The broker independently rechecks Matrix
identity and DMK binding, record identity and revision. It returns up to
8 KiB of complete original text and attribution. Unavailable, longer,
changed or incomplete records are refused. The reader exposes no search,
arbitrary selection or write through this profile.

Use `matrix goose run JSON` with the same owner-selected original shape as
Claude, and `matrix goose status EVENT_ID` for authoritative readback. A
repeated original returns the retained phase, engine and native identity even
if another harness is selected. Gateway authorizes, dispatches and settles the
return once through the existing journal. For software rollback, remove the
Goose configuration before selecting an older executable. Keep the same
journal and retain pending or uncertain work.

`matrix goose interrupt EVENT_ID` requests a stop of the selected current
worker. An already exposed original remains uncertain even when the worker
exits. The status command and restart readback preserve the same attempt.

Run the contract tests using Node 20:

```sh
node --test adapters/acp/*.test.mjs
```

For the real-binary contract set `GOOSE_TEST_ACP_BINARY` to a SHA-256-verified
v1.60.2 patched Linux `goose-acp` binary and run the same command in an isolated network
with only loopback enabled. The test starts its own synthetic HTTP endpoint and
uses no provider account. It covers catalog discovery, one response and
interruption after provider entry. Signed private Matrix exchange, approved DMK
and live Gateway acceptance require separate receiving evidence.

Set `DMK_TEST_SCRIPTS` to the installed DMK scripts directory and
`DMK_TEST_PYTHON` to its interpreter for the read contract. This creates a
disposable synthetic pool, which verifies the returned native record, the
other-record refusal, revision drift and byte-for-byte datastore preservation.

## Signed interop qualification

Set `PYTHONPATH` to the pinned Matrix checkout's `src` and repository root.
Run as the normal test user so the fixture's Unix peer credentials match.

```sh
python3 -B tests/foreground_signed_io.py goose \
  /absolute/gateway-executable /absolute/patched/goose-acp /absolute/dmk/scripts
```

Set `FOREGROUND_TEST_SIGNED_INTERRUPT=before` to test interruption before
provider exposure, or `=1` to interrupt after the fixture provider has
received the request. Both cases check the original across restart.

The fixture checks the exact provider-facing tool list, a read through the
real DMK reader, a signed same-thread reply observed by the sender and
restart without resubmission. It uses a disposable Matrix authority,
synthetic memory and a loopback model responder.

## Qwen Code candidate

`runQwenTurn` uses the shared ACP transport with the owner-selected Qwen Code
installation, workspace, environment, and exact native session ID. For an
existing ID it uses `session/load` and fails before submission if that load
fails. For a topic without a native binding it returns the new ID to the
journal callback, which must durably record exposure before prompt release.
The caller must validate the topic, account, body, workspace, and selected
provider before invoking the adapter.

Qwen Code 0.28.7 emits a roughly 636 KiB command-list notification. Only that
notification can use the Qwen-specific 768 KiB frame allowance. Ordinary
frames and assistant text use the shared limits. The adapter attempts ACP
cancellation after exposure and returns an uncertain outcome if the terminal
reply was not confirmed. It does not replay the original.

For a synthetic receiving test, set `QWEN_TEST_ACP_BINARY` to the pinned Qwen
Code 0.28.7 executable and run `node --test adapters/acp/qwen-turn.test.mjs`
using its compatible Node runtime. The test exercises a denied journal
decision, two prompts through the same native binding, a failed load, and an
interruption after provider exposure,
with only a loopback model endpoint and a disposable home. It disables
background memory, suggestions and provider retries in that test profile.

Use the subscription the owner selects. Alibaba's
[Qwen Code setup](https://www.alibabacloud.com/help/en/model-studio/qwen-code)
distinguishes Singapore Token Plan, Coding Plan and standard API credentials.
Qwen Code 0.28.7 completed one isolated ACP prompt through the Singapore Token
Plan using `qwen4-max`. Gateway topic routing and signed body acceptance remain
separate from the adapter qualification.

### Model Studio tools through Bailian

Bailian (`bailian-cli`, executable `bl`) is a tool for Qwen Code and other
harnesses. Install the pinned release in the receiving tools environment.
Select the existing Token Plan credential through the owner-local secret
binding and put it in `DASHSCOPE_API_KEY` only for the Bailian process.
Use an isolated profile with both `BAILIAN_BASE_URL` and
`DASHSCOPE_BASE_URL` set to
`https://token-plan.ap-southeast-1.maas.aliyuncs.com` for the Singapore plan.
In 2.14.0, the first variable alone did not appear as the selected base in
`bl auth status --output json`. Verify `authenticated`, `api_key.source`
and `api_key.base_url` without emitting the masked key. Keep credentials
out of the tool arguments, repository, project environment and transcript.

Receiving qualification with Bailian 2.14.0 confirmed one bounded real
`text chat` response from `qwen4-max` using the selected subscription key
and endpoint. A local auth-status response only checks configuration.
Each additional capability has its own model and plan eligibility.
Model Studio account operations may require separate console or OpenAPI
authentication, as documented in the
[Bailian installation guide](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/cli/installation).
