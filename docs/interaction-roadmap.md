# DaimonApp — full roadmap and continuous-voice delivery plan

This is the maintained product roadmap, not a claim that the later stages are
implemented. Human selection, 2026-10-26: move from the accepted single-chat base
to genuinely continuous voice, responsive foreground dialogue and the necessary
parallel-work attention coordination as one coherent delivery.

## Project name and pending Telegram separation —4November2026

Nicolas selected **DaimonApp** for the project, repository and existing development
session formerly named Realtime. The app's visible/store name is **Daimon**.
The existing repository was renamed in place from `AlterMundi/telecodex` to
`AlterMundi/DaimonApp`, retaining its identity, history, issues and pull requests.
Existing executable/configuration names and receiving URLs are compatibility
surfaces; this naming change does not replace native state or deploy new clients.

Keep the already-owned #452 refactor on this roadmap: identify and separate the
shared backend/native execution, admission, journals and coordination used by
DaimonApp from Telegram polling, bot credentials, topics and presentation.
Telegram must remain an optional adapter, with the existing web/mobile app
working without it. Reuse the extraction already underway; do not create a
parallel backend or duplicate session/goal stores. Preserve public APIs and
receiving history, validate both Telegram-disabled app operation and the retained
Telegram adapter, and document the resulting maintained component boundaries.
Nicolas further clarifies that the existing **Telecodex development session stays
Telecodex** and owns Telegram-specific work; it is not renamed or retired by the
repository change. DaimonApp and Telecodex are intended to be independently
usable domains/clients that can interoperate through a common backend when
selected. Neither client should require the other. Talking with a daimon through
the app, including children's use, must not require a Telegram account, bot or
transport. Preserve both current access paths during this evolution. The common
backend owns shared native state/coordination through explicit contracts rather
than one frontend importing or depending on the other frontend's lifecycle.

This remaining refactor is explicitly **not the current priority or a new gate**
for the app or the Matrix/heartbeat work. Its implementation remains pending.

## Current provider priority —5November2026

Nicolas2a453b61 closes this Qwen iteration and selects moving now to OpenAI
voice/GPT-Live. Unproven sustained phone/hearing/noise acceptance remains in
#301/#304/#609; it is not a gate for starting the comparison and is not silently
marked achieved. Keep Qwen available while the next provider is qualified.
Gemini remains deferred without balance. The existing ordinary integrating
provider/model, active work, original journals and diagnostic bounds stay intact.

First reuse the supported Codex/ChatGPT WebRTC route, before asking for an API
key. The18October #118 comparison actually decoded/transcribed corrected Spanish
voice through native login; today's loaded native metadata confirms ChatGPT/Pro
but is not a fresh voice entitlement test. The public GPT-Live WebRTC endpoint
requires project access; the existing Realtime adapter is a distinct protocol.
`clientManagedHandoffs` alone does not define native work ownership. Nicolas
1eb74b0e selects evaluating OpenAI/Codex native handoffs and managed Responses
first, without assuming our current custom architecture is better. Native backend
work may be the intended integration; measure its actual ownership/history/cost. Use the
[official-practice comparison](interaction-gpt-live-practices.md), preserve full
identity/memory/results/questions and existing integrating responsibility, and
redesign provider-specific transport when appropriate.

Merged [#632](https://github.com/AlterMundi/DaimonApp/pull/632) now contains the
separate, default-off native Codex WebRTC application route and explicit engine
choice. Nicolas6ea37cd3 requires preserving Qwen/Gemini, frozen visit selection,
and no silent fallback or default replacement. Capture-only original recovery,
completed-source transcripts and existing native collector attachment are wired;
mounted API and synthetic Chromium journeys qualify those application boundaries.
Actual native application tests confirmed identity uptake, nonzero remote audio,
original receipts and a surviving backend capability result. They also exposed
lost inline corrections after reconnect. The candidate now restores a flat bounded
window via native `initialItems`, with source hashes and a separate durable
completeness barrier; incomplete histories reconcile from exact closed native
sources or stay in review. Repeated corrected-word recall now passed across later connections. An explicit
clarification returned the useful previous capability result through a completed
native handoff, in audio, without repeating its tool. Retain the silent visit and
misheard question as negative observations. The exact receiving-compatible native
composition also returned the corrected word and committed its original. These
are synthetic-media observations; sustained phone hearing and continuity beyond
the bounded restore window remain open.
See the [native mode contract](interaction-native-codex-voice.md). Initial receiving
activation632 exposed OpenAI as a separate choice in UI0976269baac7. Its compatible
native d35949a5 preserved44bindings/four active collectors/Core/goals; no voice
provider or capture was started during adoption. Existing provider defaults and
diagnostic/storage limits are unchanged.

Native follow-up637 now persists terminal voice tails in the backing history
without an extra backend inference in the actual test. Native compaction completed
and its replacement history retained the new fact, but startup-only voice recall
failed when app history was omitted. A distinct native-memory handoff returned
the fact correctly in audio without repeated tools. Keep recent app restore,
source-linked backing-memory retrieval and retained negative observations. The
4KiB native tail bound and durable coverage for longer inline-only visits remain
open under [301](https://github.com/AlterMundi/DaimonApp/issues/301#issuecomment-6656496340).
Owner briefv2 requests natural native-memory lookup instead of guessing. Current
UI/defaults/bounds remain unchanged; phone acceptance is still pending.

Source-backed native memory now uses an owner-scoped metadata index over complete
retained voice visits. The native backing conversation reads selected original
records through its existing tools instead of receiving the entire archive again.
Canonical native proof deduplicates the short location context across reconnects;
queued/lost-ACK writes are retained without retry, and observed compaction can
refresh confirmed context. Existing source/window/visit bounds remain, with
at most1MiB of bounded index metadata. Actual native tool reads returned the
oldest user and assistant sources in audio with originals retained, without
application transcript restoration. However the foreground also invented early
answers before correcting them from the source. Factual waiting remains an OPEN
interaction defect under [303](https://github.com/AlterMundi/DaimonApp/issues/303#issuecomment-6657695743),
including after explicit wait instructions. Neither source retrieval nor a
compaction/context acknowledgement completes sustainable or children-ready voice.

Follow-up: explicitly ground "previous voice visit" in the latest completed
source-bearing record. Empty reconnects leave that reference unchanged. Actual
native source selection followed the new reference, but ASR changed the requested
quantity and foreground waiting still failed. Acknowledgement-filler and BEM
experiments are not selected fixes. Keep #303 open for verified final-result
delivery, natural waiting and useful spoken answers.

The native role/channel follow-up qualifies a bounded two-visit case with the structured rolev3
and native commentary routing, preserving automatic handoffs and suppressing
acknowledgement filler. A real source read preceded the correct spoken result;
after confirmed physical replacement the same result was recalled without
re-executing its source command. Both original recordings, transcript barriers
and useful remote audio were retained. This improves the evidence beyond an ACK
or caption alone. A separate native compaction then retained the code in its
canonical replacement history; a fresh voice visit recalled it without repeating
tools, with its complete original and useful signal retained. This qualifies one
compaction/replacement case, not repeated sustainable renewal, late returns or
phone acceptance; the full #303 surface remains open. Reusable role guidance lives in the native voice guide and
its owner-rendered template, not only one conversation's instructions.

A further late-return case held one actual read-only tool reply across confirmed
voice replacement and released it once. The task survived; a new spoken status
request recovered the correct result with useful audio and all originals retained,
without another tool call. There was no unsolicited offer during12seconds before
that question. Automatic late-result attention therefore remains a concrete gap;
context delivery or task completion alone does not qualify it. Preserve native
handoff ownership and investigate the supported native speech/attention path,
without user-input replay or another manual delegation loop.

Avatar now exposes the existing For you panel and scoped pending count without
stopping voice or renewing its budget. Explicit request read-aloud waits for the
existing capture/peer closure barrier before ordinary speech is requested.
Explicit written-answer selection exits
through ordinary hold/flush, preserves the draft and binds the exact question
revision; reading/selection alone sends no answer. Shipped-shell synthetic
Chromium qualifies this combined pending-question/voice/recovery UI at desktop
and mobile widths. Actual native qualification now distinguishes regular RPC
questions from native async questions. The regular question survives replacement
and accepts one exact typed reply; spoken acknowledgement alone does not resolve
its RPC. Under ordinary Default settings, an async structured question survives
two visits and its spoken answer triggers actual native source work and the
correct spoken result. Its metadata is absent from both application pending
ledgers: the source now projects native async questions into existing For you task cards
with source-linked ordinary input and explicit dismissal/retirement. Receiving
delivery and automatic spoken-answer matching remain unqualified. Do not
invent an RPC responder or enable experimental regular questions globally.
See the native voice guide for failed-control evidence, exact limits and verified
originals. This is synthetic-engine evidence, not phone/hearing acceptance;
production Core settings and source647 remain unchanged.

The complete fullscreen controller had a separate inherited five-minute guard
that closed continuous Avatar before its configured600second capture budget.
Its continuous view guard now uses ten minutes; the old alternating view retains
five. The engine's existing limit and ordered leave/flush remain authoritative.
A deterministic view regression covers survival at five minutes and one bounded
close at ten, not phone/hearing acceptance. The sustained engine-only case below
did not mount this view and must not be read as full-view endurance evidence.

A sustained actual native case now covers540seconds, eight spoken questions,
two factual corrections, one canonical compaction and three explicit microphone
visits, with all original receipts/closure barriers and two independently
transcribed output clips. Identity and final corrected facts were preserved.
This is bounded digital continuity, not phone/noise/arbitrary-task acceptance.
A deterministic client clock regression additionally catches SDP time shifting
planned closure beyond the recorder deadline; the planned flush now starts from
capture's clock with a2second margin inside the unchanged600second visit bound.
No automatic microphone budget reset or provider default change is introduced.

The source-linked predecessor-offer follow-up now carries exact pending native
task references across visits, reads only a completed task's own final item and
waits for connected WebRTC before presenting it. Its retained intent prevents
uncertain speech replay. A three-visit actual case automatically announced the
late result, suppressed a repeat on the next connection and recalled the code
without another tool/backend task. All originals and transcript barriers survived.
Native delegation remains automatic; this is result presentation, not another
execution loop. Optional source/offer failures must not cut useful voice. The
native guide records the bounded source/frame/journal rules and failed controls;
arbitrary result/task kinds, long pressure/corrections/questions and phone/hearing
remain unfinished.

## Qwen iteration checkpoint —5November2026

PR608 is receiving-selected: oversized closed reconnect can obtain a source-bound
semantic checkpoint before voice opens. Actual Luna/Qwen correction-memory/PCM
qualification recovered after its first20second preflight was pending. This is
bounded recovery, not full useful phone latency or uninterrupted start acceptance.

Issue [#609](https://github.com/AlterMundi/DaimonApp/issues/609) separates small
semantic continuation preparation from physical replacement. PR610/612 are now
receiving-selected, including nonce-bound full-read/checkpoint cycles, exact
later tails, one outstanding operation and finite rearming/request bounds.
Actual Luna low qualification produced two semantic checkpoints while Qwen stayed
open, followed by two separately committed Qwen replacements and a manual
reconnect, each with corrected-key text and decoded PCM. That digital fixture
predated the subsequent negative phone trial; it did not prove sustained device
use, natural-pressure renewal or physical hearing.

The phone trial then exposed separate original-audio archive exhaustion, late
input reservation while tools were pending, and recursively escaped inherited
reconnect language. PR614/615 are receiving-selected with workspace613 over the
compatible native590 composition. Reconnect preserves inherited language bytes;
requested tool results can settle within the reserved input margin; selected
original holds preserve pending audio through ASR/restart until matching archive
handoff. Existing64k/48k/600s diagnostic and storage bounds remain unchanged.
A new bounded digital regression against the selected composition completed in
92.149seconds: two real Luna low semantic checkpoints, two committed Qwen
replacements and one manual reconnect, with three complete corrected-key text/
decoded-PCM responses and a1375byte reconnect seed. The selected native's separate
20empty-visit regression passed with byte-identical inherited language. These
checks cover different scopes; the paid provider fixture did not execute20visits
and neither proves natural-pressure acoustic handover or sustained phone use.

A subsequent sustained-phone trial again hit the local input bound: its semantic
checkpoint covered nine events while all sixteen events had been incorporated.
The first close preceded the UI deployment; a later reconnect ended with an
observed client disconnection whose cause remains unproven. PR624 removes the
checkpoint-tail barrier without changing bounds. Receiving-selected625/626
coordinates deferred controls and wholly unsent audio at the owner boundary,
while preserving all required tool-result answers. Actual Qwen wire-induced
pressure crossed two native replacements and returned three corrected-key text/
PCM answers; sustained natural phone acceptance remains outstanding.627/628 are
also receiving-selected for ordinary Conversation speech reserve and explicit
failed-history recovery; these are separate from Avatar continuity.

A later browser regression reproduces immediate first-response failure when a
reconnected AudioContext inherits the prior visit's75second playback deadline.
The browser repair resets that clock, keeps continuous PCM fragments adjacent
with80ms arrival reserve, and separates distinct assistant interventions by180ms.
Source qualification and physical receiving/hearing acceptance remain distinct.

The pending hold is not permanent archive closure. Archive transfer/retirement,
long/noisy real speech, useful latency and actual phone continuity remain open.
See [the context contract](interaction-live-context.md#active-continuation-preparation-5november2026)
and the concise Shared Resources current receiving guide for exact selection.

The session workspace foundations606/607 and UI613 are also receiving-selected,
with the619–622 compact-layout and shared title-control follow-ups. Source tests, actual receiving delivery
and human acceptance remain distinct. OpenAI comparison is now current; Gemini is
explicitly deferred without balance and must not be called for qualification.
Full useful Qwen audio after repeated replacements, manual reconnect, physical
hearing and every prior milestone obligation remain part of this goal.

## Session workspace and adaptive header —4November2026

Nicolas selected #602 as a complete interface/routing change, with #603 direct
input, #604 session rail and #605 technical event view. Preserve the Avatar
continuity work while implementing this base-experience refinement in milestone8.

The authorized inventory covers all owned sessions. Following the5November
phone feedback, the collapsible column shows sessions active within24hours, with
fresh running/tool/active-goal sessions first, then conversation activity. Observer
refresh alone does not qualify an idle session. Hidden old rows do not change
existing pins, frozen captures or drafts. Existing Telecodex markers and fresh
observer facts represent work, active/blocked goals, human requests and results
to review. Unknown/stale observations stay explicit; color is not the only cue.
The latest-message bubble uses an exact current source/revision reply. A separate
pin selects the default destination; no pin means integration. Expanding a session
shows its live conversation and temporarily targets it; Back restores the previous
explicit pin. Freeze destination and question scope at capture/submission, keep
drafts and uncertain originals, and never silently route a stale target elsewhere.
Text and ordinary Conversation speech sent to a pinned worker bypass an integrating
model turn; observer visibility does not imply another model call per message.
Avatar delegation remains independent. Reuse existing native admission/history.

Keep compact Mute/Solo and pin controls beside session titles in both the menu
and individual updates, synchronized through the existing audio mix and one
workspace pin store. Reset audio filters sits above the menu controls. Pin/reply
selection closes the menu; audio controls keep it open. The destination line
above input shows the selected pin and provides unpin. Expanded sessions expose
a terminal-symbol view of
the harness events actually available (tools, commands/output, exposed reasoning
summaries), replacing session-specific Under the hood content while retaining
useful app diagnostics. Do not invent hidden events or create a transcript store.

The header compacts to one line on deliberate forward scrolling and reappears on
reverse scrolling or header focus, including the pending/status lane. The compact
session menu opens upward from above input. Programmatic speech-follow scrolling must not
hide it. Preserve readable identity, header actions, keyboard/touch access and
reduced motion. Qualify desktop/mobile combined pin/back/reply/text/voice/audio
and live-tool journeys without Telegram or model/provider expertise.

Implementation checkpoint: #606/#607 provide the merged metadata, exact
session-destination and explicit workspace-grant foundations. Merged #613 adds
the rail, temporary expansion, exact latest-message reply,
grouped audio and selected native technical history, preserving the existing
composer and Avatar scope. Its bounded reader exposes available tool/output and
reasoning-summary events without widening the global feed or adding a transcript
store. See [the maintained workspace contract](interaction-session-workspace.md)
for input precedence, limits, permission loss and qualification.

Retained final-result availability is distinct from unreviewed-result status:
the latter remains unknown rather than being inferred from work completion or
viewing. The adaptive header and combined workspace have synthetic actual-shell
Chromium coverage at1280px/390px, including deliberate scroll/focus and draft
preservation. Native/HTTP text and recorded-ASR voice qualification uses synthetic
peers with zero models. On5November2026 the combined workspace613/phone614-615
composition was receiving-adopted: native590-compatible sourceb5d300a9,
web613-615 composition, UIb7092302eace. The existing shared-Home owner has its
explicit workspace grant; other device scopes remain unchanged. Actual owner
metadata, capabilities and served assets were verified while preserving native
work, Core, journals and original protection. Combined exact-staged HTTP/ASR/
restart and desktop/mobile Chromium journeys passed. This is receiving delivery,
not phone/hearing acceptance or closure of the complete base-experience roadmap.
The preceding Avatar phone trial was negative; sustained Qwen acceptance remains
open. Keep the compatible native reader on rollback; never restore journals or
replay originals. The current operator selection and qualification remain in
Shared Resources' maintained Interaction receiving record.

## Shared attention backend —4November2026

Nicolas requests a heartbeat joining new Matrix messages, assigned tasks,
authorized session progress/results, presentation and iteration through Avatar,
and selected experience/discovery evidence for Bitácora. The continuing native
integrator owns judgment and routing; there is no second I/O reasoning session.
The [single Matrix310 plan](https://github.com/AlterMundi/daimon-matrix/issues/310#issuecomment-6621485717)
records that path under the full Matrix437 foundation goal.

The backend separation already belongs to #452. Core attention, state and
single-writer admission must work independently of Telegram credentials,
polling, topics and API availability. Web, Avatar and Telegram are client/adapters,
not core prerequisites. Reuse the existing journals, observer, owner controls and
native return path; do not introduce another scheduler or task/goal store.

The initial extraction moves the existing maintenance runner into transport-neutral
`src/backend.rs`, with receiving callbacks in `src/app/backend.rs`. Ownership
renewal, native-output recovery, known-unsent returns and retained artifacts keep
their existing journals. Optional Telegram projection remains an adapter callback.
Idle cancellation now exits the wait immediately; a journal recovery already in
flight retains its existing outcome rather than being abandoned halfway through
an external effect. This extraction does not activate new inbox discovery,
model turns, attention policies or Bitácora publication. Native goal/history,
uncertain operations and current configuration remain authoritative.

Future selected discovery must batch only new source-linked revisions with durable
cursors, backpressure, pause/stop and enforced inference/cost limits. The timer's
no-news path requires no model. A light model may classify genuinely new evidence
or draft a summary; execution and deeper work use the existing selected sessions.
Evaluate Nicolas's Instant suggestion against actual client availability and
account limits; Chat availability is not proof of a free backend model route.
Do not change ordinary worker/integrator models to implement this role.

Qualification must include tokenless/Telegram-disabled operation, loss of the
owner fence, cancellation between recovery operations, exact-once retained returns,
and the actual Matrix→integrator→worker→Avatar/Bitácora path as each part lands.
The extracted runner and tests do not establish that complete receiving loop.

## Native voice foreground — human correction,1November2026

The next implementation is a native speech-to-speech conversational layer
**above** the existing integrating Conversation. It talks with the person,
helps formulate a useful prompt, delegates only content needing resolution to
the existing Sol integrator, remains conversational while that work continues,
and speaks the integrating returns. It does not directly replace or reroute the
integrator's persistent workers. The modular ASR→Sol→Qwen TTS route remains
available for ordinary chat and recovery; it is no longer the architecture to
polish into the primary fluid avatar conversation.

Reuse the retained15/18/26October research and existing ingress, source,
question/result, correction and recovery boundaries. The scoped foreground
model/voice change is now selected; this does not change the models of ordinary
chat or existing native jobs. First engineering candidate: Gemini3.8Live with
the existing server credential. Both ordinary and extended-thinking Live model
metadata were read successfully; catalog availability is not a qualified session,
Spanish/device experience or latency measurement. The
[native foreground implementation contract](interaction-voice-foreground.md)
records the separation, known seams, bounds and next delivery path. Historical
modular decisions and their useful evidence remain below with their dates.

The1November canonical-question pilot was receiving-qualified at
backend2f7bbdf4b482 (PR512), UIf26ddac2f03e. Subsequent exact receiving
selection belongs to the maintained
[receiving operation](https://github.com/compaii/shared-resources/blob/main/docs/services/interaction-receiving.md),
not the older qualification snapshots in this roadmap. It keeps complete work products separate from concise
spoken presentation and makes admission acknowledgment no stronger than the
observed request-sent outcome. Exact offered canonical returns support bounded
revision-checked pagination; partial input transcripts and empty output metadata
are handled. Browser interruptions retire old output between chunks, with
Chromium offline waveform evidence for old silence and fresh playback.

Complete canonical pending questions and their choices now reach the same return
watch. Their capture-version availability reaches the client before question
audio and freezes at the first local acoustic marker, without late widening.
The no-marker arm-time fallback stays frozen; answers retain the existing
originals→Sol→native authority path. A real Gemini/CPU/Sol question-answer-result
journey and a separate full-avatar browser scope/caption/original/return check
are recorded below in the qualification protocol with their distinct limits.
Missing final interpretation/manual-end ACK closes to retained review after
15seconds rather than waiting indefinitely. These changes do not establish
physical hearing or useful device latency.

An actual mounted Gemini/CPU/Sol6.1 journey retained three exact originals in one
formulation, dispatched once to a simulated worker, preserved its complete
1851character report, and returned/spoke the requested short conclusion after
Sol read both report pages. An independent real Chromium/worklet/CPU/Gemini
trial with fake microphone/local owner confirmed two originals without Send
and completed a correct spoken answer through11Web Audio buffers. These are
complementary bounded digital observations, not one full physical-device trial.
See the [qualification record](interaction-qualification.md) for limits and
retained failed attempts, which were not replayed.

A later rendered390pxConversation/avatar qualification joins the shipped capture
worklet/output/IndexedDB with actual CPU/Gemini/Sol integration and an actual
worker in one journey. A casual eclipse answer is interrupted and corrected to48;
the independent worker's complete60-prime report returns as the requested7699sum.
Only work originals delegate. The96.8ms input-request→source-stop-call interval
is not acoustic silence/hearing. Synthetic injected media/actor, muted output
and excluded ordinary app.js/shared-login bootstrap keep phone/physical and
full-product acceptance distinct; see the qualification record.

Full applicable CI and exact receiving bytes/capabilities passed for the selected
runtime. Physical microphone/hearing, the full avatar journey on the person's
phone, echo/noise, interruption/correction and useful real-world latency remain
open. The753ms synthetic detected-end→browser-playing interval does not establish
final-speech→heard latency. The requested phone trial remains pending. This
advances the selected architecture and does not complete stages2/3/necessary4
or the retained Android/Beacon/iOS/base obligations.

## Navigation and current selection

Human priority restored, 31 October 2026: close stage2 continuous avatar voice
with the responsive foreground from stage3 and the attention required from
stage4 as one usable experience. The same native goal/accounting continues.
The independent Android client remains supported with its unfinished native
mixing/Beacon/iOS work; it does not displace this current outcome. Accepted detail
fixes and earlier maintenance are not work to repeat. The
[lost-response/reload journey](interaction-streaming.md#continuous-voice-lost-response-and-reload-recovery--31-october-2026)
adds synthetic integrated recovery evidence; actual provider/device/echo/noise
and useful-latency acceptance remain distinct and unfinished.

Human selection, 2026-10-29: the next delivery focus also includes an independent
Android APK with native audio ownership, usable as the sole client of a hosted
daimon. Reuse the web conversation and shared login; Telegram stays optional.
The [native client plan](interaction-native-clients.md) defines the foreground
pilot, native audio/focus, progressive/background follow-up, future Beacon
mixing/filters and iOS equivalent. This explicitly selects the necessary part
of stage6 now; it does not complete or discard unfinished stages2/3/required4.

| Scope | Plan | Execution |
| --- | --- | --- |
| Full product vision | This document and [Matrix parent #313](https://github.com/AlterMundi/daimon-matrix/issues/313) | [Project14](https://github.com/orgs/AlterMundi/projects/14) |
| Accepted base and remaining v0.2 obligations | [v0.2 plan](interaction-v02.md) and [qualification protocol](interaction-qualification.md) | [Milestone8](https://github.com/AlterMundi/telecodex/milestone/8), [#208](https://github.com/AlterMundi/telecodex/issues/208) |
| Current v0.3 continuous-voice delivery | Executable plan below | [Milestone9](https://github.com/AlterMundi/telecodex/milestone/9), [#301](https://github.com/AlterMundi/telecodex/issues/301) |

Issues carry their owning milestone; milestone descriptions link back to the
relevant plan. A native goal is an execution continuation, not the only place
where the roadmap can be found. Update these existing records when scope changes;
do not create a competing plan in a new conversation.

## The complete horizon

1. **One conversation, many persistent jobs.** Independent authenticated app,
   text and voice, retained routing, intermediate/final returns, useful questions,
   steering, and continuity across app/Telegram/CLI. This is the human-accepted
   functional base; specific remaining obligations stay in milestone8.
2. **Genuinely continuous voice.** Recognize during speech, show revisable
   captions, stream useful output, handle pauses and endpointing, and interrupt
   speech without losing the conversation or cancelling work. Current file-ASR
   does not meet this stage. This is the next selected outcome.
3. **Responsive dialogue separated from long reasoning/work.** A fast foreground
   conversation remains available while integrator/reasoner/native workers run.
   Reuse the persistent task registry, native sessions and versioned observer.
   Architectural separation does not authorize an unrequested model change.
4. **Attention and coordination.** Order simultaneous progress, results and
   questions; track what was actually heard; avoid overlapping voices and stale
   answers; let corrections reach the right ongoing work. Implement the part
   needed for stages2/3 now, retain broader scheduling work in the roadmap.
5. **Continuity across clients and bodies.** Carry the same authored conversation,
   permissions and useful context across devices and authorized embodiments,
   including cross-body work. Cross-body Weave/sync implementation belongs to
   the Matrix workstream; this goal does not duplicate it.
6. **Situated embodiments.** Android native-audio pilot is now selected under the
   [native client plan](interaction-native-clients.md); iOS audio parity, native
   mixing/filter work and receiving acceptance remain unfinished. Native mobile,
   physical/Bluetooth badge, selected
   camera/visual and gesture interaction, appropriate local audio handling.
   Existing selected images do not mean continuous camera/video is enabled.
7. **Full individual and collective daimon experience.** Evolving per-being
   visual/sonic expression, appropriate memory and personal continuity,
   multi-human/tribe collaboration and accessible profiles. Preserve distinct
   identities, audiences and authority while expanding the experience.

Stages2/3/4 are being developed together where they depend on each other. The
selected Android part of stage6 proceeds with them; other stages5–7 remain the
visible horizon, not hidden prerequisites or completed features.

## Dedicated voice view and attention — human selection, 28 October 2026

Tap the existing avatar to enter a fullscreen avatar view dedicated to direct
voice with the local integrating Conversation. Preserve the normal timeline,
composer, explicit Send, draft, files and reply destination for return. Voice
mode must not inherit a focused worker reply or consume attached draft files.
Its temporary Conversation-only mix must not overwrite ordinary Mute/Solo.
Keep capture opt-in foreground-only, bounded and recoverable on exit/failure.

Conversation-only audio also needs awareness of meaningful internal returns.
Reuse already received, revisioned result/question events, not continuous model
polling. Intermediate progress is not an announcement trigger. Distinguish a
session's final message from completion of its whole task; retain corrections,
stale/current state and actual question ownership. Coalesce and deduplicate brief
spoken offers such as “There is a result from X; would you like to hear it?”
without reading the whole result or interrupting the human's speech. Make the
selected offer reference available on demand to the foreground conversation,
so a reply can resolve its subject without copying every session's history.
An offer never answers, approves or cancels a pending question. This attention
work remains part of #303/#304; a fullscreen shell alone does not complete it.

## Evidence and research used for architecture selection

The updated Collective Research speech frontier and integrating-conversation
studies guide experiments. Keep their audience restrictions; do not publish the
private corpus. Recheck selected provider documentation and actual receiving
capabilities before implementation. Relevant public primary sources include
[Agents Thinking Fast and Slow](https://arxiv.org/html/2410.08328v1),
[LiveKit delegation](https://docs.livekit.io/agents/logic/patterns/subagent-delegation/),
[Kyutai Unmute](https://github.com/kyutai-labs/unmute),
[Qwen streaming ASR client events](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-realtime-client-events)
and [server events](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-realtime-server-events).
These establish documented designs/contracts, not an independent performance
ranking or this account's entitlement. Native account WebRTC previously returned
synthetic audio, but that alone did not qualify backing-work admission, real
microphone/speaker use or the full production journey.

## Current v0.3 executable plan

## Outcome
From the human-accepted functional app, deliver genuinely continuous voice and a more responsive conversation: recognize speech while the person speaks, begin useful speech promptly, allow interruption, and keep long native jobs progressing with coherent intermediate/final communication. Implement roadmap stage 2 together with the useful separation from stage 3 and the attention coordination required from stage 4. A streaming demo that weakens routing, recovery or ordinary chat is not the outcome.

Baseline: immutable `interaction-functional-sol-2026-10-26`, web/scripts source2917d8ee and native source6eff7b4. Preserve the earlier baseline tag. Prepared streaming ASR now uses Gemini with exact-original reuse; Groq final-file ASR remains the fallback and Qwen API supplies TTS (PR341). Revisable live captions and progressive spoken output are receiving-enabled. Complete continuous voice/full duplex and measured responsiveness remain unfinished. Parent: AlterMundi/daimon-matrix#313; Project14; previous integrated milestone: #208. PR300/#263 ordered-image support is now receiving-deployed with native sourced6667ba8 and web source884f884. It remains outside the earlier immutable tagged baseline.

Human clarifications, 2026-10-28: continuous realtime dialogue uses the local
**Conversation** track only, equivalent to Solo Conversation. Direct internal
tracks remain muted while their progress, results and questions stay visible and
their jobs continue. Meaningful results and missing decisions must still reach
the human through an attributed offer in the integrating Conversation, including
when internal audio is muted. Use the existing bounded, revision-aware native
return journal and selected reporting policy; ordinary progress does not require
another model rewrite, and no model polling or second task queue is implied.
The integrator retains progression and final-return responsibility until the
required successor work finishes. Explicit Listen remains available. Never blend
the raw multi-session audio queue into the local voice dialogue. Receiving source
and digital qualification do not establish complete device/hearing acceptance.

## Architecture and execution sequence
1. **Inspect and measure the existing path.** Reuse current PWA/shared auth, fetch-SSE events, player, ingress journal, observer, native session routing and results. Record actual capture/final-speech, partial/final ASR, commit, first useful model text, first playable sound and interruption-to-silence times on the same journey. Existing accepted behavior needs no generic repeat test. Consult the updated Collective Research speech frontier and prior native WebRTC/Talker-Reasoner evidence. That evidence is not a provider benchmark or a production entitlement.
2. **Choose the smallest complete streaming path.** Compare the already exercised native account WebRTC route with modular streaming ASR + foreground response + incremental TTS. Inspect supported native admission/handoff behavior before choosing: a realtime connection must not silently start unintended backing work or suppress useful returns. Recheck selected primary provider docs, existing credentials, Spanish/English support, actual capacity and grants. Start with existing resources; do not assume a free GPU or buy a service. Preserve the current text/file-ASR fallback.
3. **Streaming input and durable utterance commits.** Send bounded audio chunks while recording; render revisable transcript deltas promptly. Partial hypotheses are display/preparation data, never executable human instructions. Retain utterance identity and ordering; explicit Send commits exactly one original. An optional conversational endpointing mode must be explicit and handle pauses/corrections; retain push-to-talk. Discard never dispatches. Reconnect observes the existing outcome, without blind re-transcription or native replay. Preserve selected image/text context and transient raw-media retention with durable transcripts.
4. **Responsive foreground separated from long work.** Preserve the existing integrating role and persistent jobs while selecting the voice foreground independently. The earlier rejection of Qwen as the integrator does not prohibit the subsequently human-selected Qwen voice foreground. Gemini and Qwen now have foreground adapters; the prepared OpenAI Realtime candidate still requires access and integrated qualification. The human has also selected an OpenAI voice comparison. Keep role, model, transport and account access distinct. Stream useful response text and playable speech; do not manufacture filler to improve a latency metric.
5. **Duplex and attention.** Barge-in fades/stops audible output immediately, preserves what was heard and unsaid, and lets the person correct/continue. It does not cancel native jobs. Coordinate simultaneous session updates, questions and foreground turns; useful intermediate/final results remain visible, ordered, attributed and deduplicated across app/Telegram/CLI. Avoid overlapping voices and stale spoken answers. Keep bounded context and versioned observer freshness; no mandatory extra LLM rewrite of every callback. Preserve explicit goal controls and direct-topic ingress boundaries.
6. **Deliver and qualify one coherent experience.** Keep the existing interface, Follow, accessible controls, ASCII and click-free Beacon/ducking working. Finish the relevant pending fixes rather than rebuilding accepted functionality. Ship progressively behind the existing configuration path with an actual rollback to the tagged baseline; once new durable formats exist, rollback must retain a compatible reader. Publish current source/deployment/health/operator guidance through existing shared records.

## Acceptance and evidence
- Streaming captions appear during speech; one committed original routes once with its context. Finalization and provider failure are visible and recoverable without losing or duplicating input.
- Useful conversational response is measurably faster than the tagged baseline on equivalent short Spanish/mixed-English journeys. Target under one second from final intended speech to first intelligible sound for simple turns where the chosen stack supports it; report actual distributions and conditions, never promise provider latency or count filler as success.
- Long speech, pauses, self-corrections, barge-in during playback, noisy/echo conditions, background/foreground transitions, network loss and late worker returns retain their meaning. Test automatic mechanics with synthetic/delayed workers and bounded fixtures; use real providers only for uncertainties they can resolve.
- Speak while a long native task and another question/result are pending; interrupt, answer/correct, reconnect and finish the conversation without visiting session topics. Stop audio and cancel work remain different actions. No unseen concurrent dispatch, duplicate result, lost draft, capture or answer.
- Measure partial/final ASR, final speech-to-useful audio, inter-segment gaps and barge-in-to-silence separately. Track the heard portion. Real phone/hearing acceptance is separate from digital evidence; do not reopen the obsolete generic testing request already answered.

## Existing work and limits
Reuse #271 for streaming ASR/latency/recovery, #278 for speech providers/voice character and Voice Lab, #297 for shared backend goal controls, #61 for pending, and #208 for remaining integrated experience. Retain the receiving-deployed PR300 image-array capability and finish any remaining #263 acceptance and v0.2 polish; cosmetic work is not a prerequisite to exploring continuous voice. Internationalization relevance remains #295. Native mobile/badge/video, cross-body Weave and the full later roadmap stay future work unless needed and explicitly selected. No global Stop, new hardware capture, background peer attention, credential uploads or uncertain input replay.

Progress and remaining gaps belong here and in the linked issues. Complete this milestone only after the integrated receiving experience is delivered, with its real limitations recorded.

## Turn-taking component evidence

The [CPU turn-taking candidate](interaction-turn-taking.md) records the pinned
Smart Turn v3.2 runner, measured resource/timing bounds and contrasting synthetic
versus author-held-out Spanish results. Optional avatar-mode source now connects real VAD, capture-generation fences
and the existing original recovery path. Explicit-avatar continuous mode is
receiving-enabled through PR421/422; PR427 now installs bounded ordinary canonical
result/question returns through Conversation alongside declared workflows. These
component deliveries do not complete stages2/3/required4: foreground responsiveness,
integrated speech/coalescing, physical echo/noise and actual useful-audio latency
acceptance remain unfinished.

## Delivery tasks

### Current refinement toward an approachable Avatar — 4 November 2026

This is the next execution slice of #301/#303/#304, with provider comparison in
#278 and input recovery in #271. It refines stages2/3/required4 rather than adding
another roadmap. Human selection: keep the existing diagnostic context/session
bounds unchanged while repairing continuity; compare OpenAI voice; make Avatar
the same daimon's approachable face, with model-independent integrating roles.
These are selected design requirements, not a claim of new runtime delivery.

Later4November priority: finish Qwen workflow first, then OpenAI GPT-Live.
Gemini qualification, including Extended Thinking and its distinct lifecycle,
is deferred for lack of account balance in #599. Do not run Gemini trials while
that hold applies. The current diagnostic context/visit bounds remain unchanged.

The Qwen integrating-model experiment is completed historical work, not a
pending migration. The human rejected that model for the integrating role.
Preserve the supported ability to change integrator provider/model deliberately;
do not pin that role permanently to Sol or confuse the independently selected
Qwen voice layer with a return to the abandoned integrating-model experiment.

**Observed state.** PR597 supplies manual reconnect and exact-original recovery
on top of the Qwen native foreground. Actual human feedback confirms the ordinary
voice is now recognizable and exchanges can be fluent. Sustained continuity is
not accepted: three selected4November trials closed after approximately117,
201 and70seconds at `native-dialogue-context-input-bound`, with checkpoint
requests but zero installed provider successors. This is our conservative local
admission bound, not evidence that the provider exhausted its real window.
The existing rollover path requires an idle acoustic/output/tool floor and an
incorporated native checkpoint. The exact blocking condition still needs a
retained diagnosis; checkpoint acknowledgment alone does not establish handover.

**One conversation, replaceable voice connections.** Preserve three distinct
lifetimes: the human's durable conversation, a finite opt-in microphone visit,
and each replaceable provider connection. Compression or replacement must not
finish the human's task, stop native jobs, clear pending questions, or pretend
that a configured visit-duration cap has disappeared. The currently selected
600second visit and all existing capacity bounds remain unchanged in this repair.
A later longer-visit policy is a separate explicit configuration change after
continuity qualifies. No always-on microphone or background listener is implied.

**Continuity workflow to implement and qualify:**

1. At open, assemble a compact, versioned identity/capability packet plus the
   latest acknowledged integrating checkpoint and recent source-linked delta.
   Identify Avatar mode, current modalities, available tools and their limits,
   and how the integrating role provides memory, deliberation and work access.
   Include current conversation purpose, human corrections, unresolved requests,
   pending questions/results, and heard/interrupted speech. Do not load every
   worker transcript or the entire memory corpus into the voice prompt.
   Manual reconnect creates a new visit UUID. The reconnect-continuity candidate
   adds an authenticated exact prior checkpoint/tail copy, native source linkage
   and pre-provider hydration, preserving earlier visits through repeated opens.
   See `interaction-live-context.md` for `resume_read` and source-bound `open`.
   This candidate is not receiving/device acceptance. Qualify reconnect after an
   acknowledged checkpoint; keep pending-effect receipts independent and never
   reopen old provider sockets or replay work.
   The closed-oversize candidate now requests the existing integrator's complete
   semantic checkpoint and waits boundedly before opening another provider.
   Prior pressure requests and reader revisions remain fenced, and an oversized
   summary cannot retire exact sources. Pending preparation retains the last
   established visit for another explicit reconnect. Native integration and
   receiving/useful-audio qualification remain separate from preparation.
2. Keep canonical human originals and assistant utterances available to the
   integrator through ordered deltas with an acknowledged cursor. A complete
   selected history remains readable on demand; do not resend it each update.
   Summaries retain exact source ranges/revisions and do not replace originals.
   Durable memory curation belongs to the integrating role, not the ephemeral
   provider. No unrelated private-history import follows.
3. Before the existing hard reserve is exhausted, produce a semantic checkpoint
   through the current native contract. Account separately for bootstrap text,
   PCM, internal updates, tool output and generation reserve. Measure checkpoint
   latency and remaining headroom; a fixed trigger alone cannot guarantee time
   to obtain a checkpoint. Budget the successor packet so it can actually fit
   with room for further speech. Bound internal tool returns and fetch details
   by reference rather than repeatedly pasting full state.
4. Prepare at most one successor from an acknowledged basis. Commit the switch
   only at a provider-appropriate safe boundary with exact original/tool/question identities
   preserved. Separate a durable raw recording awaiting interpretation from
   audio still in flight: neither silently discard it nor let it create an
   unexplained permanent renewal barrier. Any relaxation of the current floor
   needs explicit supported ownership and a regression, not a skipped check.
5. Record fixed, bounded reasons when renewal cannot proceed: checkpoint absent
   or stale, new input, output not drained, unresolved original, tool/effect in
   flight, successor setup failed, or generation changed. Reuse the existing
   close/reconnect diagnostics and retention; do not add a transcript log per
   tick. A checkpoint request and a socket-open receipt are separate from a
   committed successor and useful audio after it.
6. If remaining reserve cannot cover safe renewal, pause new provider admission
   before the hard failure, preserve owned originals and show one understandable
   reconnect/review action. Do not accumulate an unbounded audio queue or replay
   an uncertain operation. Keep Check observational and Retry tied to the same
   exact original. A finite logical visit ending is a distinct normal outcome.

Provider-side compression/resumption can support this workflow, but does not
replace the canonical checkpoint, source history or exactly-once work ownership.
Provider truncation is not semantic memory. Keep cost, retained prompt size and
connection lifetime bounded even when a provider allows longer contexts.

**Speech, identity and tools.** Use a short foreground operating prompt and a
small task-relevant capability description, instead of appending more repeated
policy paragraphs. Being identity, selected SOUL and appropriate remembered
preferences survive connection replacement. The same daimon speaks through
both interfaces; changing the voice model does not create another being.
Read-only task/result/pending views expose current observations with freshness
and explicit unavailable fields. Memory lookup, uncertain capability requests,
planning and actions pass through the existing integrating role with the exact
human request/corrections. The foreground does not choose workers, duplicate
orchestration or declare work accepted merely because it spoke a destination.
Keep detailed tool procedures in their owning backend/skills; expose callable
capabilities rather than dumping Codex-only skills into a direct provider prompt.

Ordinary speech is brief, useful and lightly poetic when appropriate; failures
need clear practical language. Do not narrate tool mechanics or announce work
on a simple greeting/test. For a task lookup, a short “I'll check our progress”
may be useful; otherwise perform the read quietly and report the result. Never
claim success before the actual receipt. Do not casually mention “Sol,” worker
sessions or model names; explain the real architecture clearly when asked.
Avoid filler, repeated permission questions and premature replies to unfinished
speech. A technical fault is not an occasion for a poetic metaphor.

**Present results where the person can use them.** Reuse the existing timeline,
viewers and For you ledger. Offer a concise spoken answer and a linked card for
the actual image/model/report/result; allow “show it,” “tell me more,” and a
short answer to the actual pending question. Preserve result revision, subject,
audience and responder ownership. Distinguish working, blocked, needs your input,
and result ready without exposing session machinery as the main navigation.
Coalesce ordinary updates, never overlap voices, and offer meaningful returns
at a conversational pause. Opening a result is not approval or task completion.

**Next delivery order and a first children/family pilot:**

1. Diagnose and repair renewal at the unchanged current bound. Demonstrate two
   real successor installations with source continuity, late work return and
   useful speech, plus deterministic blocked-checkpoint/empty-final/tool-race
   coverage. A longer timeout or several manual reconnects do not pass this.
2. Qualify the concise identity/capability packet and behavior with ordinary
   greetings, interrupted sentences, task-status questions, unavailable memory,
   delayed results, corrections and an explicitly named work destination.
3. Compare the selected Qwen baseline with OpenAI through the same originals,
   integration and return contract; measure useful audio, interruption, delayed
   tools, renewal and cost. Record hearing/device acceptance separately from
   mocks or generated text. Keep the current provider until a candidate passes.
   For GPT-Live, follow its own continuous-audio, transcript/delegation and
   playback lifecycle rather than inheriting Qwen/Gemini manual-turn mechanics.
   Start from the official workflow and relevant inspected implementations;
   redesign our transport/foreground seam where that produces a better result.
   The prepared Realtime adapter is not a prerequisite or a substitute for this.
4. Finish the result/question presentation slice above and exercise a guided
   family journey without Telegram, terminal access or knowledge of model/session
   names: converse, request a small creation, see/hear its result, correct it,
   interrupt, reconnect and continue. Visible microphone control and a clear exit
   must work. Respect each participant's actual data/tool permissions; do not
   inherit the developer's private sessions simply by using the same product.

The pilot is a bounded real-use acceptance step, not completion of all seven
stages or a reason to require the full #452 backend separation first. Android,
Beacon, pending navigation and other unfinished base obligations remain visible.
No new provider/account selection, limit increase, automatic attention or
continuous recording is performed by this documentation update.

Provider limits and OpenAI integration paths are recorded in the
[current service brief](interaction-avatar-services-20261102.md#4november-continuity-and-openai-integration-update).

Human clarification,2November2026: the native voice model is primarily the
conversational and prompt-formulation layer. Sol retains deliberate reasoning,
memory lookup, routing and coordination; persistent work sessions retain their
own goals and histories. Capture/playback/observer facts remain deterministic
application responsibilities. A bounded read-only session-status tool gives the
interlocutor observed facts without making it a second orchestrator. Complex
questions and work still pass to the integrator with exact human originals.
Durable memory remains DMK, not an ever-growing voice prompt or a duplicate
foreground task store. The comparison with cognitive layers guides separation
of responsibilities; it is not a literal human-brain implementation or evidence
that changing a model would solve missing plumbing. Recover earlier research
and scope decisions before inventing another architecture.

- [ ] #302: select transport and qualify architecture
- [ ] #271: streaming ASR, latency and retained-input recovery
- [ ] #303: responsive foreground with persistent native work
- [ ] #304: interruption, heard speech and concurrent attention
- [ ] #278: speech provider/voice qualification
- [ ] Integrated receiving delivery and current operator guidance


2November automatic-activity update: a distinct natural-Qwen-speech/noise native
protocol trial produced two provider-detected phrases and their correct spoken
answers on one continuous PCM stream. The opt-in automatic owner now preserves
exact originals, question scope and source readiness separately from the local
CPU/manual path. See the automatic-owner section of
[the foreground contract](interaction-voice-foreground.md). This advances the
noise/turn-taking repair; digital evidence does not close phone fluency, useful
latency or the remaining milestone obligations.


### Avatar provider and Instant comparison — 2 November 2026

The [dated provider brief](interaction-avatar-services-20261102.md) continues the
15/18/26October research. It compares native and managed speech routes, identifies
GPT-Live client delegation as an architectural challenger to the selected Gemini
foreground, separates Instant's text/tool capabilities from native audio, and
retains credit/access and phone qualification gaps. This research does not switch
providers, replace Sol, close milestones or authorize a new account/billing change.

### Retained selected Matrix reply progress

`matrix_status` remains an explicit, one-page operation. Select `request_id` and
`receive_next: true` to continue from that original's saved global inbox cursor,
or use `receive_after` for an explicit historical read. These selectors are
mutually exclusive. The existing request row stores progress; verified canonical
replies and cursor commit in one SQLite transaction. A failed page commits
neither. Only pages covering the saved cursor advance progress; explicit reads
ahead do not skip an unread gap. Existing rows migrate to cursor zero without
losing replies. The active tool owner is rechecked after SDK I/O, and
acknowledgment is rechecked at commit. Historical replies remain readable without
reviving work. No scheduler, peer activation, automatic input, new queue or
inference is enabled. This is a resumable selected-reply primitive for #452 /
Matrix #310/#437; new unsolicited inbox attention and its resource admission
remain unfinished.

### Matrix evidence in existing integrator attention

The explicit `workflow_attention` read also returns `matrix.envelopes`: at most16
oldest unincorporated canonical replies, with `has_more`, exact authorship and
revision, text size/hash and the existing `conversation_part` reader. It performs
no remote reads and copies no reply body into another journal. Current owner,
admission epoch and later human amendments determine eligibility; retired sources
remain readable as history but do not become current offers.

After actually reading/incorporating the exact source, `matrix_reported` records
its canonical revision on that same reply row. Exact retry is idempotent across
restart. This is an integrator assertion of incorporation, never hearing, a peer
response, execution approval or human-task completion. One optional64byte marker
and a partial pending index share the reply history's retention; no offer queue
or growing per-tick log is created. Workflow bounds remain unchanged and Matrix
has its own16-envelope bound so pending work is not displaced. Neither this read
nor its acknowledgment enables discovery polling or automatic model admission.
The periodic attention policy/shared resource admission and real receiving loop
remain unfinished under #452 / Matrix #310/#437.

### Shared persistent heartbeat admission control

The owner console `telecodex --control CONFIG heartbeat pause` and the scoped
integrator `heartbeat_control` operation (`action: pause`) use the same model-free
handler. `heartbeat status` observes its persisted flag/generation.
`heartbeat resume GENERATION` requires the exact current generation and only
clears the admission gate; it does not start a timer or grant an account/budget.
Default is paused. Repeat pause is idempotent, restart preserves it, and a later
pause invalidates older resume generations. One small record per configured
entry uses the existing state store; no growing operation log or second queue
is added. Human access needs no live native turn.

The control reports `attention_engine: not_implemented`; it does not activate
periodic attention or grant funding. Its `owned_execution_control` now exposes
exact native interruption for server-owned executions, as described below.
Admission-paused is not provider quiescence: inspect each execution and its
terminal/unconfirmed observation. Ordinary human contact, shared maintenance,
goals and funding remain unchanged. Paired-human visible/audio reporting still
requires its own source publication binding.

### Heartbeat generation at existing native return boundaries

An optional server-owned `attention_generation` on the existing native-return
receipt closes its admission when the shared control is paused, missing or on
another generation. The existing transactional link/submitting checks and final
steering/submission validation use that same fence. Ordinary returns omit the
field, preserving their existing serialized history and separate policy. Pause
never invalidates presentation/history reads or drops a late canonical native
ACK. Resume never reopens a previous submitting/uncertain generation.

This adds no public source-tagging API or funding grant. The heartbeat producer,
bounded/coalesced idle admission and its source/publication contract still need implementation
before activation. Fresh physical ownership and scoped interruption are supported
below; no public producer or automatic attention is enabled. A tagged receipt alone
is not proof that its physical turn is exclusively owned; do not use it as
permission to interrupt a human execution.
An RPC already between final validation and its ACK remains a retained
submitting/uncertain operation; exact ownership, interruption and terminal
observation must close that race before automatic attention is selected. These
checks do not establish provider quiescence.

### Exact heartbeat execution ownership and scoped pause

Only the serialized entry worker may link a tagged return to a fresh empty local
turn. Ordinary active-writer steering rejects that tag. The store verifies the
entry/native owner, current generation, absence of human ingress/collection or
other source bindings, and at most one unresolved heartbeat execution. Ownership
is retained beside the existing turn in the state store, with the exact physical
native ID added on its callback. Tagged execution requires native
`turn/startIfIdle`, with no fallback to `turn/start`: a local idle observation is
not an atomic native ownership fence. Older servers reject before submission.
Core source4dc51af25, now proposed in compaii/codex#10, exposes the existing
atomic StartIfIdle through that method. Actual App Server mocked-provider busy
refusal/independent internal-turn and legacy-permission regressions plus317
protocol/export/schema tests pass. It is not yet receiving-selected and remains
a prerequisite for actual cancellation qualification; ordinary `toolOutput`
uses start-or-steer and cannot establish this ownership by itself. Retain at most sixteen records (one live owner
plus fifteen prior terminal/transferred records); pruning never deletes native
history, source receipts or an uncertain execution. Turn deletion removes only
its matching ownership metadata.

Human/external steering crosses an ownership handover callback before its actual
provider write, after ordinary source admission checks. If handover wins, the
execution becomes transferred and heartbeat pause cannot cancel it, including a
later human physical successor. If pause wins, the input receives a known-unsent
rejection rather than entering a turn being interrupted. Prepared coalesced inputs
and active/queued steering use the same boundary. This ownership is independent
of canonical publication; transfer does not fabricate a human original.

Pause persists its admission fence before claiming an owned execution as stopping.
For an observed physical identity it uses existing exact `turn/interrupt`, then
reads that same native turn's terminal status. An interrupt ACK alone is not
termination. Missing identity, failed observation or nonterminal status remains
unconfirmed with its retained ownership; a late native ID asks only that owning
runner to interrupt its exact turn. Only known native rejection/non-submission
may release an owner as `not_submitted`. Resume never resets resource counters or
replays an uncertain input. The control never invokes session/global Stop.

This is source-level execution control, not a complete running heartbeat.
The trusted bounded producer, actual resource admission, descendant/successor
ownership and producer source/publication binding remain to be implemented
and qualified before automatic activation. Native socket fixtures prove prepared
and active ownership refusal prevents provider writes while original work still
finishes; SQLite tests cover both race winners, late identity, restart and bounded
retention. They do not prove actual receiving-model cancellation or device hearing.


### Canonical reports reuse the existing integrating return path

A heartbeat-owned execution does not grant publication by itself. Its admitted
retained source must carry the existing paired-human integrating return authority.
For that source, completed native commentary and final answers already use
`interaction_native_messages`, immutable native thread/turn/item identities and
frozen native-return source associations. Reuse this path; do not create a second
report feed, fabricated human input, new audio queue or broad Tribe audience.

The scoped heartbeat admission pause does not retire those accepted source
reports. A regression covers accepted tagged source→pause→canonical commentary,
exact repeated item deduplication, preserved same-integrator currentness and
reader ownership, then ordinary source expiry without deleting history. The
existing foreground canonical reader and mounted native-voice pending-return
journey pass with these same `integrator_progress`/`native_returns` descriptors.
Native voice continues while awaiting an integrating return and source revisions
are revalidated before offers. This is source/fixture evidence, not actual phone
hearing or acceptance of a fully activated producer.

Meaningful actions, replies, results and pending outcomes belong in that same
conversation and its enabled audio surface. No-news ticks and routine incorporation
remain silent. The future trusted producer must bind its finite human-selected
source/purpose to this existing report path; an execution tag or arbitrary peer
text cannot manufacture that grant. Activation, real receiving cancellation,
successor ownership and physical device acceptance remain unfinished.
