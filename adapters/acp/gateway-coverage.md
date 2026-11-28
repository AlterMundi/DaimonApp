# Gateway harness capability inventory

This is the maintained inventory for harness compatibility in Daimon. Its scope
is the union of capabilities across the supported and candidate harnesses.
The original Telecodex integration provides the Codex baseline. Other harnesses
add features to the inventory when those features appear in upstream releases
or in observed native behavior.

Use ACP when the exact adapter preserves the native operation and its
semantics. Otherwise retain a supported native protocol, CLI operation or
explicit entry point into the native session. A connector can expose different
operations over different transports. Gateway still owns one logical topic,
one dispatch decision for an original and one journal of receipts. A native
entry point is only available when it can use the correct account and session
without creating a competing writer. If a provider exposes a feature only in
its own app, record the limitation and the useful native access separately
from Daimon surface support.

Treat a missing feature as a gap in the selected Gateway route, the adapter or
the harness protocol only after checking where it diverges. Keep advertised,
fixture-qualified and live evidence distinct. Record the harness and adapter
versions, operation, receiving surface and evidence when updating a row.
Keep the already working path until its replacement demonstrates the same
behavior, including recovery after lost acknowledgements.

## Harness-specific capabilities and native routes

These additions complement the workflow coverage below. A documented native
operation is a candidate to support, even when the current Gateway pilot is
limited to ordinary text. Features that only appear in a vendor interface
remain part of the inventory.

| Harness | Connector used or being qualified | Capabilities to preserve and next comparison |
| --- | --- | --- |
| Codex | Native App Server in use. Codex ACP is a candidate for equivalent operations. | Keep exact-turn steering, native goals and accounting, quota windows, questions and approvals, side chats, review, thread fork, worktrees and native MCP/tool inventory. Compare ACP against the existing authenticated App Server route by operation. [App Server](https://developers.openai.com/blog/codex-as-a-platform) · [Native remote work](https://developers.openai.com/blog/mastering-codex-remote-for-engineering) · [Codex ACP](https://github.com/agentclientprotocol/codex-acp) |
| Claude Code | Native Agent SDK and OAuth in use. Claude ACP is a candidate for equivalent operations. | Preserve the interactive terminal entry point for experimental Code Mode. Verify whether any selected ACP version can enable it and keep its permission, tool and output semantics. Keep native goal and quota operations, tool/skill discovery, plugins, hooks and subagent controls in the inventory. Agent SDK availability, terminal availability and Daimon projection require separate checks. [Code Mode](https://code.claude.com/docs/en/code-mode) · [Claude ACP](https://github.com/agentclientprotocol/claude-agent-acp) |
| Antigravity | The installed CLI serves topic sessions through `agy acp`. | Verified text, model/effort and exact session load. The installed handshake advertises images, embedded context and session resume. Google also documents in-turn prompting over ACP. Qualify these on Gateway before reaching for another connector. Inventory native workspace edits, shell, plans, plugins, side questions, projects, remote-agent and structured headless output. Compare the terminal and headless interfaces where ACP lacks a faithful operation. [ACP](https://antigravity.google/docs/cli/acp) · [Release history](https://antigravity.google/docs/changelog) · [Headless](https://antigravity.google/docs/cli/headless/) |
| Goose | Native `goose acp` in the Rust pilot. | Preserve recipes, extension management, session inspection, configured models and the native scheduler controls. Goose also offers a scheduler-enabled ACP mode. Check the existing contract before introducing a native connector. Native schedule execution belongs to Goose when explicitly selected. [Goose ACP](https://github.com/aaif-goose/goose/blob/main/documentation/docs/gdk/acp/index.md) · [Goose CLI](https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/goose-cli-commands.md) |
| Qwen Code | Native `qwen --acp` tested in isolation. | Compare the direct CLI/SDK for structured output, tool discovery and plan controls. Evaluate `qwen serve` where HTTP event and workspace lifecycles help. Its agent execution itself goes through Qwen's ACP bridge, so the daemon alone does not close an ACP adapter gap. Preserve the selected Singapore Token Plan route. [Qwen architecture](https://qwenlm.github.io/qwen-code-docs/en/developers/architecture/) · [TypeScript SDK](https://qwenlm.github.io/qwen-code-docs/en/developers/sdk-typescript/) |
| MiniMax Code | ACP fixture and exact native resume are recorded. Subscription-backed pilot remains open. | The CLI and SDK offer `mcode exec` for direct stream and resume comparison. Inventory terminal tools and skills separately from desktop-only features. Verify the selected payer and explain extra observed provider calls before adoption. [MiniMax Code source and connectors](https://github.com/MiniMax-AI/minimax-code) |
| Muse Code | Native MSP is the first candidate; Muse ACP remains experimental. | Preserve stable command IDs, resume/replay, steering and interruption, approvals, model selection, native goals and lifecycle events. The local echo test proves a prompt round trip. The selected Meta login remains unverified on ITACA. [MSP](https://meta-models.github.io/muse-code-sdk/1.4/guides/msp-wire/) · [Muse ACP](https://meta-models.github.io/muse-code-sdk/1.4/guides/editors-acp/) |

## Selecting a harness for a new topic

A topic record retains the selected harness, account, workspace and native
session. An explicitly chosen harness takes precedence. As a future owner
workflow, the integrating conversation can recommend or select an eligible
harness at topic creation using this inventory and the receiving body's actual
configuration. Base the recommendation on the work's required capabilities and
known availability. Ask the human when two reasonable choices involve a material
tradeoff, or when choosing would change the account, billing or privacy terms.
Retain the reason so the choice can be revised. Rebinding a live topic uses its
continuity contract and keeps the old native history available. This selection
workflow is a roadmap item.

## ACP fit for the incumbent native operations

The following comparison scores the operation families used by Codex and
Claude native routes at `3b2405a5`, one equally weighted row per family and
per harness. Request volume and receiving acceptance require separate
measurement. Gateway work without a harness RPC is outside this count.

| Operation family | Codex | Claude Code | ACP path or native requirement |
| --- | --- | --- | --- |
| Initialize and negotiate capabilities | Baseline | Baseline | `initialize`; verify the selected adapter and runtime. |
| Create a native session in a selected workspace | Baseline | Baseline | `session/new` with cwd. Verify that the receipt names the selected workspace. |
| Resume the selected native session | Baseline | Baseline | v1 `session/load` when advertised, v2 `session/resume`. Qualify existing IDs and history. |
| Submit ordinary text | Baseline | Baseline | `session/prompt`; check admission and terminal outcome independently. |
| Submit images | Baseline | Baseline | Negotiated image content. Gateway retains bytes and attribution. |
| Receive streamed output and completion | Baseline | Baseline | Session updates and prompt lifecycle. Verify terminal stop reason and canonical reply. |
| Cancel foreground work | Baseline | Baseline | `session/cancel`; verify exact session, late events and interruption outcome. |
| Project tool events and resolve user interaction | Baseline | Baseline | Tool updates, permission requests and negotiated elicitation. Qualify the native question and approval cases. |
| Discover and choose model and effort | Baseline | Baseline | Negotiated session config options. Check available values and selected-model readback. |
| Supply selected MCP servers | Baseline | Baseline | Session setup. Listing supplied servers and attesting the effective tool inventory are separate operations. |
| Authenticate and verify the selected payer | Conditional | Conditional | Adapter authentication surfaces exist. Qualify selected OAuth, payer and account continuity end to end. |
| Steer an active turn with an incorporation receipt | Conditional | Conditional | `_session/steering` is an extension with version-specific behavior. The v2 proposal and adapter implementations need separate qualification. |
| Reconcile admission after disconnect from exact native evidence | Native | Native | v2 message IDs, replay and idempotency cover parts of this. Verify the same original across actor restart and distinguish queued, inserted, terminal and uncertain. |
| Control and reconcile native goals | Native | Native | Existing goal extensions cover part of the workflow. Keep native controls for exact goal identity, observed state and applicable conditional updates and accounting. |
| Read provider quota windows and resets | Native | Native | Codex App Server limits and Claude account `/usage` readback have provider-specific semantics. |
| Verify the effective tool and skill inventory before model exposure | Native | Native | The configured MCP list does not attest the effective inventory. Also qualify changed skills during native resume. |
| Admit a bounded idle provider attempt and reconcile its accounting | Native | — | The receiving Codex contract reserves the attempt before provider dispatch and retains the native result. |
| Fork and name an existing native session | Conditional | — | Both are adapter capabilities on the Codex ACP route. Qualify source lineage and native name readback on Gateway's selected version. |

**Baseline candidates** account for 10/18 Codex families (56%) and 10/16
Claude families (63%). Including conditional candidates gives 13/18 (72%)
and 12/16 (75%). These figures describe documented protocol fit and do not
qualify any existing production native route for replacement. In particular,
session resume and attachment support depend on negotiated capabilities and
the exact adapter build. Code Mode is an optional interactive Claude Code
capability with no current Gateway operation and is outside the denominator.

Source locations for the native inventory include
[`src/codex.rs`](../../src/codex.rs),
[`src/app/foreground.rs`](../../src/app/foreground.rs),
[`adapters/claude/turn.mjs`](../claude/turn.mjs) and
[`adapters/claude/gateway-worker.mjs`](../claude/gateway-worker.mjs).
Compare [ACP v1](https://agentclientprotocol.com/protocol/v1/overview),
[ACP v2 Preview](https://agentclientprotocol.com/protocol/v2/overview),
[the Codex adapter](https://github.com/agentclientprotocol/codex-acp),
[the Claude adapter](https://github.com/agentclientprotocol/claude-agent-acp)
and [Claude Code Mode](https://code.claude.com/docs/en/code-mode).

## Qualifying a replacement

Run the same Gateway acceptance scenario on the native and candidate routes
with a disposable identity, isolated session and fixed synthetic original.
Check the exact logical topic and native session at admission, incorporation,
terminal result and restart. Compare the negotiated transport, adapter version
and provider selection. A known rejection may take the selected supported
route. After uncertain exposure, the existing journal reconciles the original
before any further dispatch. Carry the original and all receipts through
connector selection and keep one scheduler and canonical journal.

Use minimal reproducible traces upstream. For a protocol gap, contribute the
cross-adapter fixture to the ACP project. For an adapter or harness gap, take
the failing contract to the owning adapter or lab. The first protocol candidate
is [ACP RFD #1261](https://github.com/agentclientprotocol/agent-client-protocol/pull/1261):
send a mid-turn correction, lose its insertion acknowledgement, reconnect,
and verify one attributed correction on the same session. The
[Agentic AI Foundation](https://aaif.io/projects) is a related venue for
shared work on Goose, MCP and Agent Skills.

## Upstream contribution map

Use the inventory as evidence for ecosystem work. When several harnesses offer
the same operation with observably similar semantics, compare their contracts
and take a minimal multi-harness trace to the relevant standards group. If the
standard can already express the operation and one connector loses it, send a
focused adapter fix. When several harnesses need the same host-side plumbing,
look for a reusable module with a stable boundary and publish its contract and
tests upstream or as a small open-source component. Features specific to one
harness remain accessible through that harness's supported surface and can
inform later proposals once another implementation needs them. Keep proprietary
provider internals and user data outside the evidence. Track external proposals
and releases from this inventory so adoption can be checked against the same
fixture.

Wiggle Stash researched these entry points on 2026-11-28.

| Audience | First contribution |
| --- | --- |
| ACP maintainers | Run the exact mid-turn correction and reconnect case against the ACP v2 prompt lifecycle. Bring one reproducible trace to the open prompt-delivery RFD. [Governance](https://agentclientprotocol.com/community/governance) · [RFD #1261](https://github.com/agentclientprotocol/agent-client-protocol/pull/1261) |
| Harness and adapter maintainers | For Codex and Claude, run the same correction over ACP and over the native harness interface. Report the boundary at which the exact original, turn, or incorporation evidence diverges. [Codex ACP](https://github.com/agentclientprotocol/codex-acp/issues) · [Claude ACP](https://github.com/agentclientprotocol/claude-agent-acp/issues) |
| AAIF and MCP groups | Present a synthetic trace that distinguishes transport receipt, model insertion, reconnect readback, and user-visible projection. Goose can supply another comparison. Bring a gap involving MCP tool events or transports to the relevant MCP group. [AAIF Observability and Traceability](https://github.com/aaif/wg-observability-and-traceability) · [MCP working groups](https://modelcontextprotocol.io/community/working-interest-groups) |

Zed and JetBrains share ACP's interim governance. Its [AAIF
application](https://github.com/aaif/project-proposals/issues/1) is a separate
record. Keep published traces synthetic and omit identities, account details
and private history.

## Stack parity inventory

Snapshot for 2026-11-28. **Live** means a receiving route was observed with the
real account or signed peer. **Fixture** means a bounded test, with its
boundaries shown below. **Candidate** means code or an upstream interface is
present. **Open** means comparable evidence is missing. A status on one row
does not transfer to other rows or hosts.

| Stack workflow | Codex | Claude Code | Antigravity / Goose | Qwen / MiniMax |
| --- | --- | --- | --- | --- |
| Selected account, model, effort and payer | Live incumbent route | Live OAuth route. Exact quota windows and per-model selection also need their own readback | Antigravity SDK and Goose ACP use isolated provider profiles. Selected Antigravity model and effort must survive ACP reopen. Goose signed activation is pending | Qwen real Singapore Token Plan first turn, separate from Gateway pilot. MiniMax isolated CLI required authentication on an empty profile. Its paired payer remains open |
| Signed embodiment and scopes | Live incumbent body | Live signed private Matrix exchange on its own body | Antigravity signed identity and separate live private evidence. Goose revision 13 installed stopped. Activation and receiving adoption remain open | Qwen topic pilot lacks observed live body admission. MiniMax open |
| Ordinary text from Telegram and Conversation | Live incumbent | Live topic plus isolated tests of the deployed binary. Fresh live general-to-topic handoff remains open | Paired synthetic-provider basic turns | Qwen joined topic pilot through both surfaces. MiniMax ACP prompt fixture only |
| Reply, thread selection and exact quoted original | Incumbent route and fixtures | Both quoted-reply fixtures passed | Open | Open |
| Images, files, voice and output artifacts | Active stack routes. Qualify each file type and voice variant separately | Image and captionless input passed on both surfaces. Full albums, output artifacts and voice variants require receiving checks | Open by input and output kind | Qwen CLI negotiates image and audio. Gateway pilot is text. MiniMax open |
| Early original, progress and final result in topic and general conversation | Incumbent route plus fixtures | Early handoff and final result qualified in joined fixture. Native result is visible across surfaces in live use. Fresh handoff in the selected build remains open | Basic paired answers only. Visibility timing and general attribution remain open | Qwen paired text receipt. Other projections open |
| Mid-turn steering with same native session and incorporation receipt | Native steer and receipt tests | Telegram and Conversation corrections entered one physical turn with one canonical result in the joined fixture. Native worker retained for current route | Open | Open |
| Targeted cancel and late events | Native route and tests | Telegram cancel, Conversation exact-reply recovery after interruption, and independent signed interruption fixtures | Both interrupted around exposure with isolated signed fixtures | Qwen real CLI ACP cancel against loopback. MiniMax open |
| Goal creation, monitoring, pause/resume/clear and accounting | Native lifecycle including conditional controls | Conversation goal creation, native completion, inspect and clear passed in isolated fixtures. After an unsuccessful goal turn, the retained goal stayed inspectable and clearable on the same native session. Explicit pause, resume and cross-surface accounting need their own evidence | Open against Gateway contract | Open against Gateway contract |
| Topic workspace, exact native resume and cold replacement | Existing path plus per-topic workspace work. Cold migration needs the same test across connectors | Same session through skill refresh passed. Conversation rebuilt the missing native session with the exact retained quote and the selected project checkpoint. The joined Codex–Claude round trip preserved both native sessions, the topic generation, a quoted Codex answer and the project checkpoint. Live migration remains open | Qualified first turns and interruption. Same-topic reload with accepted work and cold fallback remain open | Qwen and MiniMax resumed the same CLI session in a fresh process with prior context. Qwen has scoped topic code. MiniMax has no joined topic evidence |
| Identity guidance, shared skills and enabled tools | Incumbent loaded configuration | Shared skill revision readback proved by fixture. Check actual loaded guidance and full catalog per live body/turn kind | Check loaded guidance, tools and skill refresh. Goose fixture required a pinned patch for complete catalog verification | Check effective catalog and guidance. Qwen isolated settings turn off extra provider calls from native features |
| DMK read and write | Existing receiving tools | Paired read and write passed against a disposable DMK store using the receiving DMK release and interpreter. Live write acceptance remains open | Both have isolated selected-record reads. Authorized write proof remains open | Open |
| Matrix private messages, /we and authorized Tribu tools | Existing receiving scope and tools | Real signed private route verified. Live topic tool inventory and receipt evidence must be scoped to the selected operation | Isolated signed read/reply. Antigravity live evidence is a separate route. Goose pending activation | Open |
| Cross-topic delegation, visible destination and return incorporation | Native route plus joined tests | Progress and final, then retained canonical result recovery without replay, passed in fixtures. Fresh joined human-facing handoff remains open | Open | Open |
| Disconnect/restart, journal fence and duplicate suppression | Incumbent exact receipt and recovery paths | Signed return crash passed in isolation. With the named Gateway and TeleDaimon executables, an adapter-only restart delivered confirmed-unsent results once and preserved an uncertain Telegram acknowledgement without replay. The same Claude topic accepted another original afterward | Both have signed loopback interruption evidence. Live restart and ordinary Telegram migration remain open | Qwen isolated exact load and denial tested. MiniMax fresh-process load tested with four provider requests for two turns. Determine why before certifying one intended request per turn |
| Usage, alerts and limits in the UI | Native usage and limits route | Claude usage adapter and account readback. Verify UI behavior and configuration refresh on each deployed surface | Open | Open |
| Agent questions, plans, review, forks, subagent and background lifecycle | Multiple native App Server entry points and projections | Inventory each supported native workflow and its projection. Ordinary text and goal tests do not qualify these controls | Open | Open |

Owning work and qualification procedures are in
[Matrix #497](https://github.com/AlterMundi/daimon-matrix/issues/497),
[App #452](https://github.com/AlterMundi/DaimonApp/issues/452),
[App #1104](https://github.com/AlterMundi/DaimonApp/pull/1104),
[App #1105](https://github.com/AlterMundi/DaimonApp/pull/1105),
[App #1123](https://github.com/AlterMundi/DaimonApp/pull/1123),
[App #1135](https://github.com/AlterMundi/DaimonApp/pull/1135) and the
[Claude joined qualification guide](../claude/README.md#signed-interop-with-the-native-sdk).
The minimum Rust candidate recorded in Matrix #497 is Goose. The historical
DaimonCraft design has separate evidence requirements.

### Next receiving pilots

Antigravity CLI goes first, then Muse Code. The ITACA `agy` 1.5.18 probe
negotiated ACP v1, opened a sandboxed session, selected Neon with medium
reasoning and received the expected synthetic reply from the selected
account. The common ACP client then reopened the exact native ID in a fresh
process and recovered a synthetic marker from the earlier turn. Its live
check also kept a denied admission and a missing session unsent. The server
advertised image input.
An explicit Gateway foreground profile wires agy through the common ACP
worker and keeps the SDK/local-provider protocol available for existing
profiles. The worker qualification checks selected tool use, journal
refusal, and same-session continuation. The ITACA topic has a recorded live
Antigravity response. A disposable Gateway exchange across Telegram and
Conversation reused the same native session. The signed body profile also
identifies the receiving being in a fresh process and on resume.

A real agy probe sent a second prompt while its first text turn was active.
Both prompts completed in the same session, but the correction marker appeared
only after the first prompt's terminal acknowledgement. This shows live
same-session queueing for that action. A separate probe sent the correction
while a selected MCP tool was pending. The second request received JSON-RPC
`-32603`, and the original turn completed with its original marker.
The tested path therefore has no qualified in-turn receipt. Compare the
specific provider and adapter versions at a tool boundary and after reconnect
before advertising steer on this route.

The real agy test reads an installed fixture skill, searches DMK and reads
the selected original. The staged ITACA binding separately verifies the
installed catalog and the existing owner-selected DMK pool through the signed
body. Complete coordinator access, tools needed by some skills, durable memory
writes, interruption and broader receiving equivalence are still open.

Muse Code 1.4.25 answered the `muse serve` MSP handshake with its echo
provider. The exported stable schema includes native start, resume, steer
and interrupt. A disposable echo-provider session accepted and completed a
native turn. The same MSP path on the installed Meta account reported
`not logged in` at its first turn. Verify the subscription sign-in, native
resume and stable command behavior before adopting it. Its exact-turn steering and stable command IDs are
useful candidates for the existing Gateway acceptance contract. ACP v1
for Muse is a separate experimental route.
[MSP wire guide](https://meta-models.github.io/muse-code-sdk/1.4/guides/msp-wire/) ·
[Muse ACP](https://meta-models.github.io/muse-code-sdk/1.4/guides/editors-acp/)

Use the selected release binary with the signed Claude qualification in
`tests/foreground_signed_io.py`. With `FOREGROUND_TEST_TELEGRAM_TOPIC=1`,
run the visible handoff, same-turn steering, adapter recovery and harness
switch cases independently. The fixture seeds an existing embedded Telegram
installation, then drives the named Gateway and TeleDaimon roles with a
loopback model provider and disposable accounts. These checks exercise the
host, journal and projections, while live paired acceptance also requires
the selected OAuth account and actual topic receipts.

Run the DMK write case with `CLAUDE_TEST_DMK_SCRIPTS` and
`CLAUDE_TEST_DMK_PYTHON` selected from the receiving DMK release. The fixture
creates its own database and binding. Running it against another checkout or
interpreter does not qualify the installed DMK tool.

The selected Claude CLI exposes native set, inspect and clear through
[`/goal`](https://code.claude.com/docs/en/commands). Treat Codex-style pause
and resume as separate controls. A plain argument to Claude's native command
can set a new condition, so forwarding a control as a condition cannot
establish pause or resume parity.

Run the stack checks through the actual receiving surfaces and operation writer.
For a shared feature, use the same acceptance assertion per adapter. For a
provider difference, record the exact adapter, actual account class and observed
semantic difference. For upstream reports, retain synthetic originals and the
minimum event trace needed to reproduce the difference.
