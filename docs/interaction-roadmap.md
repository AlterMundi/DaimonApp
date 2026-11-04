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

## Shared attention backend —4November2026

The next source increment reserves a complete execution's maximum provider
attempts in the SAME SQLite transaction that claims its fresh native writer.
The parent account is independent of the sixteen retained detail records.
Pause/resume, restart, source succession and detail pruning do not replenish it;
unknown or known-unsent outcomes stay conservatively reserved. An initial
`configure_resources` uses the shared owner handler while paused at the exact
current generation; a new contract UUID cannot overwrite an existing account.
The contract supplies total/per-execution attempts, complete request bytes,
execution seconds and a fixed expiry. Status labels these as reserved request
attempts, never token or monetary spend. Configuration neither resumes attention
nor changes native goals or a provider account. No receiving account is created
by this source work. The last native-submission callback now reads the exact
already-reserved allocation after owner/generation checks, without charging it
again. Tagged work requires `turn/startBoundedIfIdle` with that allocation;
missing/expired allocations and old servers refuse without an unbounded fallback.
Existing immutable workflows now retain their actual attention execution's
original account and generation. Each fresh delegated worker reserves its own
allocation in the same transaction that claims its exclusive local execution;
it cannot create a target account, replenish the original account or reuse a
physical writer. Busy routed workers retain attention legs in the existing
pending queue, including across physical turn changes. Both the common steer
boundary and final native admission refuse attention work. A worker finishing
between selection and that check reserves a fresh successor instead of using
the stale handle. The native request carries attributed internal tool context,
with the human prompt empty; selected attachments currently refuse explicitly
rather than being discarded. Worker results retain the attention generation,
so their return to the integrator also needs a fresh reservation. Scoped pause
selects root and delegated physical executions; the sixteen-record bound counts
all live cancellation targets and prunes only terminal/transferred details.

Source qualification includes conserved reservations, duplicate-claim refusal,
pause before/after child admission, bounded result returns and capacity retention.
The full text suite passes524 tests (one existing ignored), including the explicit
Resume regressions below. The routing queue
regression is local qualification, not a native routed-worker journey or live
receiving acceptance. Explicit Resume now advances the retained workflow's attention generation only
while its original entry/native grant remains live. Only return legs with no
local/native submission binding and reserved/retained-unsent phase advance;
accepted, submitting, uncertain and previously linked evidence stays unchanged.
It neither allocates resources nor creates/retries an input. Focused tests prove
the same queued step can claim its fresh conserved allocation after Resume and
that replacing the native entry cannot revive an old workflow. Scheduling that
known-unsent work and the actual native busy-worker journey remain unqualified.
The bridge now distinguishes the native idle-admission error's exact
`submitted:false` plus `notIdle`/`pendingTriggerTurn` reasons from a permanent
rejection or uncertain delivery. Only an idle-only bounded request selects this
known-unsent outcome. It retires that execution's unsubmitted ownership without
refunding its reservation. Workflow returns use the existing finite retry/backoff
journal; a delegated step enters the existing retained-unsent recovery lane only
with its exact unsubmitted child-ownership proof. Unsupported methods, plan mode,
missing proof and uncertain/accepted inputs do not select capacity recovery.
Native socket regressions verify both contention reasons without start/steer
fallback; store regressions preserve the same instruction/account across recovery
and refuse to downgrade an ACK. Actual combined native/receiver acceptance and
automatic queued-child recovery remain unqualified. Typed attachments, positive
native agent/reviewer allocation, external-tool inference, the finite producer
and receiving acceptance remain unfinished; do not activate this increment as a
complete heartbeat.


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
4. **Responsive foreground separated from long work.** Keep gpt-6.1-sol / openai / medium as the selected conversational model and native jobs intact. Separate rapid conversational handling from long integrator/reasoner/work execution using supported existing seams. Do not reinstate the rejected Qwen conversational model or silently change every session's effort/model. If a genuinely different foreground model is needed, present the measured tradeoff and obtain the human's model choice. Stream useful response text and playable speech; do not manufacture filler to improve a latency metric.
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

The control reports `attention_engine: not_configured` until a finite producer
contract is selected; configuration alone grants no inference funding. Its `owned_execution_control` now exposes
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

This adds no public source-tagging API or funding grant. The finite producer
and source/publication contract below reuse this fence; combined native and
receiving qualification is still required before activation. Fresh physical ownership and scoped interruption are supported
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
`turn/startBoundedIfIdle`, with no fallback to `turn/start` or the unbounded
`turn/startIfIdle`: a local idle observation is not an atomic native ownership
fence or a resource reservation. Core PR11 extends merged PR10's idle primitive
with the required allocation. The bridge supplies its conserved attempts, bytes
and absolute deadline; it cannot refresh them during preparation. Socket tests
cover exact parameter serialization, unsupported servers, and missing/expired
allocations without input submission. The actual Core mocked-provider journey
refuses a busy human writer, then exhausts a one-request allocation locally
without a second bounded provider request. Native source/receiving selection
remain distinct; ordinary `toolOutput` uses start-or-steer and cannot establish
this ownership or these bounds by itself. Retain at most sixteen records across
the root account's executions, including delegated workers; all live cancellation
targets count toward that bound. Pruning never deletes native
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
The finite producer and reserved workflow delegation are implemented below;
combined native admission/recovery and receiving qualification remain required
before automatic activation. Unreserved native agent/reviewer calls refuse. Native socket fixtures prove prepared
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
remain silent. The finite producer binds its human-selected source/purpose to this existing
report path; an execution tag or arbitrary peer text cannot manufacture that grant. Activation, real receiving cancellation,
successor ownership and physical device acceptance remain unfinished.


### Finite canonical offer producer (development, not receiving activation)

The existing transport-neutral maintenance cycle observes only while holding its
instance lease. `heartbeat configure-producer GENERATION CONTRACT_JSON` selects
`interval_seconds` (30–3600), `max_checks` (1–1024), `expires_at_unix_ms` (at most
seven days and within the existing resource contract), and `matrix_replies` and/or
`workflows`. Configuration requires paused exact-generation ownership, no unresolved
execution and an existing finite resource account. It cannot replace/refill an
existing producer contract. Default remains unconfigured and paused.

One existing `bot_state` parent retains cadence, counters, source-review cursors
and the existing native-return journal. A check consumes its finite counter even
if source lookup fails. No-news checks admit no model. Each batch contains at most
four metadata offers/16 KiB, never copied peer text or fabricated human speech.
The parent stops at sixteen retained receipts, 256 reviewed source keys or
256 KiB; it does not delete native history or silently reset its capacity.
One unresolved batch/execution backpressures observation. Expiry, pause, shutdown,
missing binding and busy entry prevent new admission. These are observation and
request-attempt/byte/deadline bounds, not a token or monetary ceiling.

Sources are existing canonical Matrix replies and workflow attention, including
ready successors. No new remote Matrix inbox reader, private memory pooling or
peer wakeup is installed. Workflow observation scans four rows with a persisted
continuation. Matrix observation excludes already reviewed immutable identities
before its sixteen-result limit, preserving the manual view and separate original
incorporation. Source readers and original human/workflow authority remain intact.

The producer uses the existing fresh integrating return worker and mandatory
bounded native method. Reservation charges the existing account atomically with
exclusive local ownership. Known-unsent retries run only under the held lease,
retain the exact identity/account and existing finite retry bounds, and revalidate
admission freshness. An independently incorporated/stale known-unsent batch is
retired without claiming review, delivery or completion. Submitting/uncertain
inputs are never retried as new inputs. Resume does not refill counters or revive
old accepted submissions.

`heartbeat_reported` records review of an exact accepted batch by its owning
integrator; it is not `matrix_reported`, `workflow_reported`, hearing or completion.
Accepted action narration stays in the same paired-human conversation even when
its actions consume/change offered sources. It retains the original native binding
and admission epoch, grants no Tribe publication, and uses existing canonical/audio
presentation. Pause stops new inference without erasing accepted narration.

The current source qualification is not receiving deployment or device acceptance.
DMK consolidation, Source review, assigned-task intake, Bitácora/Avatar handoff,
combined actual native delegation/recovery and real audio acceptance remain
separate full-roadmap work. No Instant/provider selection is implied.
