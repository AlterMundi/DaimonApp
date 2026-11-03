# Shared context between Live voice and Sol

Current receiving status,3November2026: native and webPR566/source22ed3856
are selected on CompAII ITACA after full CI41609604965. Native adoption preserved
40session bindings,13goal definitions/budgets/monotonic accounting and4exact
physical collector receipts. The subsequent idle web adoption verified75composed
runtime files,21local/public assets and both generated shells. Four Python
modules changed; unrelated selected Matrix modules and all other bytes remained.
Core/native/goal/collector services and configuration were preserved during the
scoped web restart. UI92a44cdc7ead, Charon/manualCPU and ordinary Sol/Qwen remain
unchanged. No provider was opened or input replayed during adoption.

Closed assistant audio without output text now reaches Sol as an explicit unknown
observation. The close journal separates pending-analysis audio, unsent analyzed
phrase audio and activity-end-to-input-confirmation wall wait. These measurements
support the next human trial; accumulated delay is not declared resolved. Close
and reopen the avatar for this backend; the UI label may remain unchanged.

The dated preparation/qualification sections below preserve their original
status. Actual Sol/Gemini/CPU two-successor continuity and one late pending-work
return across a successor are digitally qualified. Actual Sol full-reader and
semantic checkpoint retained a missing-caption observation as unknown language,
without human originals/work/memory/publication. Automatic recovery of unknown
words, device hearing/useful latency, full128k admission, long/noisy speech,
broader concurrent effects and unfinished roadmap/Android/Beacon/iOS remain open.
The five-minute pilot is retained. Rollback keeps the compatible native writer
and current journals; a caption-aware web reader is required while typed unknown
observations remain pending. Exact current receiving/health/operator guidance:
[receiving record](https://github.com/compaii/shared-resources/blob/main/docs/services/interaction-receiving.md).

## Selected continuation after actual provider qualification

The existing manual-activity route now has an actual mounted continuous-input
qualification with two checkpoint-seeded Gemini successors. The local CPU
speech/turn detector owns explicit spans; quiet capture remains local, and only
never-sent backlog enters a successor. The selected next candidate uses this
route for NEW dialogues, not an in-place conversion of an automatic connection.
In-session contextUpdate and append-anchor sliding remain unqualified and OFF.
This route is now selected for new receiving560 dialogues as recorded above;
selection is not device acceptance. Exact qualification and limits are recorded
at the end of this document.

## Human outcome and ownership

Nicolás's instructions15907154/166edb59/fe543d9a/74ae68c5 require:

- Sol receives BOTH sides of the selected avatar conversation, not only work
  requests. Routine transfer is incremental, not full-transcript resubmission.
- Full active context is readable when needed. Live has a128000-token budget,
  compacts before its limit with headroom, and remains conversational while Sol
  works. Sol can guide the selected Live dialogue.
- Live is temporary. Sol, its native history and existing DMK own durable being
  continuity. No separate independent avatar memory corpus is required.
- Context does not independently admit or route work. Exact retained human
  originals and the existing delegation path continue to own work admission.
- Original recovery, source attribution, corrections, uncertainty, shared login,
  ordinary Sol/Qwen and unrelated sessions remain intact. No global Stop, host
  shutdown, peer/Matrix attention or uncertain input replay.

Instruction9667cfdb asks for Astra high review before implementation proceeds.
The existing PR560 provider-setup seam was prepared earlier; the context bridge
below is being implemented in source and has not been deployed.

## Existing implementation evidence

Receiving558/ec81eb0e remains selected, client92a44cdc7ead. One later owned phone
trial retained13assistant utterances,3accepted originals, two interruptions and a
clean client close after281302ms, without a provider/transport failure code. This
is digital metadata, not hearing, fluency or full acceptance. PR559 is merged and
CI41540386526passed; its read-only result index is not selected yet.

Human originals already live in the native `conversation_inputs` journal, with
foreground_dialogue, source UUID, capture order and exact interpreted text.
Assistant speech is in app `NativeHistory`, with monotonic text append, closed/
interrupted flags and client playback positions. Those positions are not hearing.
The app owns the provider output; browser input must never author assistant text.

Core/Telecodex already supports retained `NativeToolOutput` internal steering:
`src/codex.rs::send_steer_request` uses turn/start with empty human input and
attributed toolOutput, including during an active native turn. Native returns
already share accepted/rejected/uncertain outcomes and collector/publication
handling in `src/store/workflows/native_returns*` and `src/app/workflows.rs`.
There is no passive context-append operation found in the inspected protocol;
do not invent one or impersonate a user utterance to call turn/steer.

The Gemini setup-only probe accepted contextWindowCompression trigger102400 and
slidingWindow target64000, then closed with zero audio, tools or human input.
This is not proof of compaction semantics. Official slidingWindow DISCARDS older
turns rather than summarizing them. It cannot independently satisfy continuity.

## Proposed source and transport model

Use the existing native Store as the actor/entry-bound owner of a small pending
context projection, not a new memory service or independent work queue. Add one
foreground-context source type to the source-independent native return dispatcher;
do not create a synthetic workflow or another worker registry.

A logical context session is bound to:

- actual authenticated human and integrating entry/session;
- current entry-generation binding, native integrator thread and admission epoch;
- the server-created logical avatar dialogue UUID and its open/closed producer.

The app registers that producer only after existing owner/native preflight. The
public browser cannot register arbitrary native threads or assistant authorship.
Context writes use the existing owner-local control route. Expose only guarded
read/incorporation/guidance operations to the actual integrating native execution.
No worker receives this full context by default.

A delta event carries a monotonically ordered sequence, stable source UUID,
role(human/assistant), source revision and predecessor revision, text append or
explicit correction, text offset, final/interrupted state and provenance. Human
events reference the actual retained input and capture order; native Store checks
that the dialogue, owner and text match. Assistant events are generated by the
trusted server output path, not accepted from browser text. Generated text and
client-observed playback remain different fields; interrupted text may be unsaid.

Emit complete human interpretation only after its durable original is confirmed.
Assistant text may arrive incrementally; coalesce append/closed changes rather
than creating an event per PCM chunk. No audio or unrelated private history is
copied. Playback-only changes do not produce repeated language-context updates.

The context ledger stores bounded post-checkpoint deltas, a compact checkpoint,
source/revision cursors and dispatch receipts. Supplied deltas become attributed
Sol context; meaningful durable recall uses the existing DMK route deliberately.
A complete current projection can be reconstructed
from checkpoint plus all subsequent deltas, including already incorporated text.
Retained Core tool outputs alone do not guarantee complete retrieval after Core
compaction. Existing old recovery/history is not deleted
by this feature or made a prerequisite to preserve another Live archive.

## Delivery, acknowledgment and recovery

### Missing-caption recovery implementation in progress

`dashboard/native_caption.py` prepares transient generated-PCM ownership for
future caption recovery. It is not wired into the selected voice service and
opens no provider, writes no media and schedules no task. Existing receiving566
continues to retain explicit unknown observations, without recovered words.

One owner accounts for at most300seconds of24kHz monoPCM16 across the complete
logical dialogue, including retired utterances and provider successors. It keeps
at most120seconds for one missing-caption clip, matching the existing file-ASR
adapter. A longer clip releases its retained bytes and reports ineligibility;
it never returns a silently truncated transcription input. Provider text releases
the corresponding PCM immediately. Closing releases the current incomplete
buffer. A finished missing-caption buffer transfers to its finite recovery
caller, which must consume/clear it; that transfer is not a durable-media receipt.

Before runtime enablement, finish the source-owned finite recovery job using the
existing file-ASR outcome/uncertainty rules, immutable derived assistant-caption
provenance and parent/hash validation, late closed-producer delivery and UI
association. Do not overwrite an already finalized unknown source, admit human
work, claim exact words/hearing or retry an uncertain provider operation. The
utility's focused byte/cleanup tests are preparation, not end-to-end recovery.

1. Producer writes an idempotent delta after the existing canonical retention.
   A repeated same event ID/revision returns its receipt; changed content under
   the same identity is rejected. Work admission is not touched.
2. Coalesce a bounded contiguous sequence range into one attributed internal
   native-return envelope. Normal transfer includes only that range plus exact
   reader references for overflow. Never resend the entire dialogue per update.
3. Reuse native internal-return admission/collection with actual binding/epoch
   checks and accepted/rejected/uncertain receipts. At most one context range is
   outstanding per dialogue. Append later deltas while Sol processes that range.
4. Sol can read bounded exact pages from the selected range or full active
   checkpoint+delta projection. Every page is source/revision-bound. Native
   acceptance is not incorporation and neither is a transport acknowledgment.
5. Sol explicitly acknowledges the incorporated range/revision after reading its
   required pages. ACK never advances across gaps, unseen changes or later data.
   ACK retires dispatch; exact text retires only when a committed checkpoint
   represents that incorporated prefix.
6. A known-unsent native write may use the existing bounded recovery
   route. An uncertain native write never gets another send identity. Reconcile
   with the retained native collection or leave it uncertain for explicit recovery.
7. A process restart recovers the same source IDs/ranges/outcomes. It cannot
   reinterpret old unacknowledged context as permission to execute work again.

Context-only native outputs have NO automatic ordinary-chat publication grant.
Extend existing source/publication handling so an internal context wakeup cannot
spam duplicate spoken/text responses. Sol uses the guidance tool for that Live
session. A real subsequent human original retains its own ordinary presentation
lifetime; context cannot suppress it. Incorporation is internal bookkeeping, not
an instruction to narrate a status update to the human.

## Sol-to-Live guidance

A guarded native controller operation records bounded assistant-authored guidance
for the selected logical dialogue and acknowledged context revision. It carries
its own stable ID, expected revision, mode(context-only or explicit spoken offer),
and source/constraint attribution. It is neither a new human utterance nor a work
request, capability grant, worker control or identity replacement.

The existing database-change watcher offers current guidance to that producer.
Apply at an idle audio/turn boundary without interrupting new human speech.
Context-only guidance updates Live without asking it to speak; an explicit spoken
correction may ask it to respond. Keep sent/applied/uncertain receipts distinct;
never replay a possibly applied guidance write. Closed/replaced dialogue IDs,
superseded basis assumptions and changed owner/native epochs reject new guidance.
New speech by itself does not invalidate useful guidance.
A reconnect must select the same logical producer explicitly; no silent creation
of another session or replay of prior audio/tools.

## Context budget and semantic compaction

The128k bound is TOKENS, not bytes. Continue separate byte/media/event/retention
bounds; they do not prove token accounting. Use actual provider usage counts as
observations, with conservative fallback when absent, and explicit semantic
provider-generation rollover. Request the checkpoint early enough for Sol to
catch up before hard input reserve. The earlier102400/64000 setup probe is not
an enabled admission guard. Optional unknown usage is not an empty context.

Before old Live context may be discarded for continuity, Sol must have incorporated
the corresponding delta range and produced a revision-bound compact checkpoint:
identity/relationship continuity, active conversation purpose, unresolved requests,
corrections, relevant facts and memory/source references, and exact pending effect
receipts. Keep work admission/result/uncertainty outside the compactable language.
No repeated ASR/audio, model tool effect or native work submission is part of
compaction. Reopening Live from checkpoint must not re-execute its contents.

Reviewed design decision: automatic provider slidingWindow can run before a
fresh Sol checkpoint is available. Do NOT enable unconditional discard as though
it were semantic compaction. Need a qualified ordering/gating mechanism, or a
safe explicit provider-session rollover from the acknowledged checkpoint at an
idle boundary. State the actual API constraint rather than inventing a passive
system-instruction update on the Developer API. Never silently drop unincorporated
context to keep speaking. Source PR560's setup setting stays unselected until this
is implemented and qualified. Unconditional automatic discard is removed.

Repeated compaction should permit a bounded long conversation, not just replace
the current five-minute close with unbounded resources. Retain connection/session
resumption tokens privately only through the supported provider contract; a lost
socket and an uncertain effect are different. The old five-minute pilot bound
stays until coherent rollover/resumption and recovery are qualified.

## Bounds and lifecycle

Initial implementation bounds to review:

- One selected context producer and one outstanding range per actor/dialogue;
  reuse existing two-owner native-voice capacity rather than another concurrency
  setting. Coalesce at completed semantic turns, not every audio buffer.
- At most16KiB immediate native context envelope; full exact text uses bounded
  pages. Do not label a clipped preview complete or ACK an unread page range.
- A bounded pending projection per active dialogue; select a byte/event quota
  after measuring serialized128k-token text and existing Store/native input bounds.
  Never claim a byte quota is an exact tokenizer. Stop new capture with retained
  recovery if the pending quota cannot absorb another confirmed original.
- Compact/checkpoint state remains small; one current plus actual in-flight prior
  checkpoint until its effect is resolved. No unbounded version archives or
  unbounded watcher/queue/log growth.
- Opening the human's selected avatar enables this finite event-driven integration;
  closing ends new source updates/guidance. Already admitted ranges can finish
  incorporation. Unsent/uncertain closed-session data remains explicitly retained
  and readable, without an indefinite wakeup/timer/retry daemon.
- Exact post-checkpoint data is retired only after an incorporating checkpoint
  commits. No deletion of existing native originals/DMK/history is implied.

## Recovered previous dialogue

On2November the human asked to recover the last avatar conversation, not only
build future synchronization. The selected canonical journal contains12human
originals and13terminal assistant utterances. Both sides were read completely;
the selected private recovery record preserves source IDs, separate capture/
retention chronology and interruptions. No old work was replayed.

Recovered product requirements: natural first-person phrasing during actual
consultation; no false durable-note claim for temporary adaptation; distinguish
historical significance from current task priority; let the human return to read
or replay the previous avatar reply after accidental interruption. The replay
control remains implementation work, not an already delivered capability.

## Source implementation checkpoint

The native Store now has a bounded owner/generation/epoch-bound language
projection, finalized immutable sources, canonical-human verification, capture
order distinct from arrival sequence, frozen exact readers, contiguous-page
incorporation and separate checkpoint retirement. Ordinary batches are supplied
inline. Prefix source receipts survive text retirement to deduplicate catch-up.
Existing owner-local producer and integrating controller operations expose these
primitives without submitting work. Producer `sync` catches up finalized human
originals from the selected native canonical journal, with source receipts rather
than a row cursor that could miss slow finalization. It does not re-run ASR, touch
media or change work admission. Bounds:64dialogues,2MiB serialized per
dialogue,64MiB globally,4096source receipts per dialogue,16KiB/event and64KiB
checkpoint; saturation stops writes transactionally while retaining old context.
These are storage bounds, not tokenizer accounting or a raised pilot duration.

The native internal-return dispatcher now has a foreground source, sharing its
existing worker, empty-human-input `toolOutput`, exact native acknowledgments,
known-unsent recovery, uncertain retention and collection ownership. One frozen
range is outstanding; later complete sources coalesce until incorporation. The
integrating controller's incorporation starts the next pending range, rather
than waiting for another human utterance.

Foreground returns never contribute a publication grant or a negative fence
against independent human/work sources. Completed context bindings consolidate
within a physical turn while its internal-only lifetime bit remains; retiring
batch IDs cannot silently widen publication. This passed40sequential batches in
one physical turn. After incorporation, duplicate full-text transport envelopes
retire while the exact post-checkpoint event tail remains readable. All retained
transport receipts share the projection's quota; saturation retains existing
sources and stops new writes.

Qualification:238Store tests passed, including8projection/transport tests. A
new actual-wrapper/socket/controller/SQLite journey with a synthetic Core proves
human canonical catch-up plus assistant context, active and idle delivery,
incorporation, native producer-operation denial, pure-context silence and the
independent human reply's presentation. Existing workflow and routed-return
journeys also pass, including known-unsent recovery, completion-race collection
and late canonical results. These tests use zero models; they do not establish
actual Core/model incorporation, Gemini delivery or device acceptance.

### Mounted producer qualification —3November2026

The mounted voice route now registers an authenticated context producer before
microphone readiness. The listener must advertise `foreground_context:v1` before
the provider opens. One event-driven task shares the bridge's existing two owner
slots; captions, PCM chunks and playback positions do not create native context
turns. Complete originals and terminal/interrupted assistant utterances signal
the task. Native `sync` atomically catches up human originals and up to8selected
assistant sources/64KiB of language, then reserves one coalesced native range.

Terminal assistant retention and its outbox reference commit in the same app
SQLite transaction. The outbox stores stable source IDs, semantic revisions and
native retention receipts, not another copy of the language or PCM. Its semantic
revision ignores playback/hash/byte changes. A lost retention acknowledgment
leaves the reference pending; cleanup does not automatically repeat an unknown
boundary. The next explicit avatar open reconciles the same producer/source IDs;
the native journal keeps its original return IDs and uncertain transport outcome.
An abandoned connection's retained partial assistant language is sealed as
interrupted, without inventing its ending or a hearing receipt. Slow closure of
an earlier row is recovered independently of newer row positions.

Close drains pending semantic references with an18second bounded wait, after
audio/output ownership ends. Failure stays `needs_review`/closing with retained
sources. Producer `closed` means retention/producer close was confirmed; it does
not mean Sol incorporated the context. The native Store's incorporation watermark
remains authoritative. This adds no startup model turn, timer, peer attention,
audio/ASR replay, worker registry or background loop after the selected voice
connection closes.

The app producer metadata is bounded to64producers and4096source references per
dialogue; outbox rows reference the existing bounded canonical history. Completed
source metadata retirement remains required before lifting the pilot. The
native2MiB/dialogue and64MiB/global reservations still stop on saturation while
retaining originals and existing context.

Four SQLite/outbox tests and43mounted voice tests pass, including receipt loss,
same-identity recovery, partial/slow closure, semantic-vs-playback revisions,
batch limits and owner boundaries. A joined WebSocket → actual voice decoder and
completed-only original → app canonical history/outbox → actual owner socket →
native Store/controller journey passes both roles, explicit incorporation,
producer close and internal-only presentation. Its audio, detector and Core
reasoning are simulated; it uses zero models or hardware capture. Eight native
projection/transport tests and the actual-wrapper context journey still pass;
clippy with warnings denied passes.

The joined fixture initially used amplitude-one PCM, which the actual decoder
correctly rejected as inaudible, then an unsupported synthetic model label, which
the actual transcript validator correctly rejected. The fixture now supplies a
bounded synthetic tone and the selected model's allowed metadata. No production
speech gate, selected provider or model was changed to make the fixture pass.
The mounted close fixture waits for its actual close receipt before teardown;
close metadata also checks the new fixed producer-state scalar. These verifier
corrections are not evidence of an audio-quality improvement.

Receiving activation must select the native listener and web producer together.
Once native foreground-return records exist, a native rollback must retain their
reader and publication handling; the old558native reader is not a compatible
rollback for this new source. Existing receiving558 remains unchanged while this
draft is qualified.

Still required before receiving selection: Sol-to-Live guidance, semantic provider
rollover, retirement of completed source/transport metadata and coherent actual
Core/provider qualification. The128k-token admission guard and long-session
continuity are not proved by these storage/batching tests. The five-minute pilot
limit stays in place; physical hearing, fluency and full-goal acceptance remain
unfinished.

## Qualification and delivery

First review this architecture against the actual source owners. Resolve unknown
API/publication/ordering details before claiming them implemented. Then implement
one coherent vertical journey, not a collection of disconnected APIs:

- both-role complete context with append, correction, partial/interrupted speech;
- incremental cursor, duplicate/gap/stale/cross-owner rejection and exact-page ACK;
- actual native internal context admission/collection without fake human input,
  duplicate work or unsolicited ordinary-chat output;
- Sol guidance reaching the SAME still-conversational Live dialogue while real
  work continues, with new human speech/corrections and no overlapping voices;
- two compaction cycles with complete pre-compaction incorporation and meaningful
  checkpoint continuity, keeping pending effects and once-only originals intact;
- process/socket/owner change, uncertain writes, bounded saturation and recovery.

Reuse prior unchanged voice/provider/browser/native evidence. Use a bounded actual
native/provider journey for the new internal admission/compaction uncertainties;
no physical microphone or human input replay. Follow current native maintenance
and idle writer-preserving rollout for required Rust/listener changes. No global
Stop, goal/accounting reset or Source revival. Publish the owning runbook/context;
record source/CI/deployment and actual human hearing/fluency acceptance separately.


## Source implementation: same-dialogue guidance

Sol's native `live_context` control now accepts `guide` and `guide_status` for
the current logical dialogue and producer generation. Each guide has a stable
UUID, an incorporated basis watermark, mode `context_only` or `spoken_offer`,
and at most8192UTF-8 bytes. Later speech does not invalidate an older useful
basis. Only pending known-unsent guidance can be superseded. The projection
retains at most64guides within its existing byte quota; full context reads expose
their content, attribution and delivery phase alongside language events.

The authenticated owner producer peeks without writing, claims once, then records
`sent`, known `unsent`, or `uncertain`. Restart converts an in-flight claim to
uncertain; closing retires pending guides. Neither path replays an unknown write.
Guidance creates no native human input, work admission or publication grant.

One coalesced task on the existing event-driven return watcher handles guidance
and canonical-return notices. Owner control reads never block the provider audio
receive loop. Generation and captured-speech state must be idle; spoken offers
also wait for queued client playback. The final send shares the acoustic lock
and provider socket lock, with a fresh actor check. Known busy state waits before
claiming, avoiding claim/defer writes that wake their own watcher repeatedly.

The provider receives explicitly attributed internal Sol context through
`clientContent`, without replacing system instructions or impersonating human
speech. Context-only uses `turnComplete:false`; an intentional spoken offer uses
`true`. The [official Live protocol](https://aistudio.google.com/api-reference/live)
says client content interrupts active generation and mixing it with realtime
input has no ordering guarantee. Local serialization therefore does not prove
provider application or predict future speech. A socket send receipt never means
applied, spoken or heard; it must not prompt reauthoring under another ID.

Qualification includes240native Store tests,35provider transport tests,5producer
tests,45mounted voice tests and a separate held-control regression proving audio
arrives while the owner read remains blocked. The joined mounted journey crosses
both real SQLite stores, the actual owner/control/native controller and returns
one Sol guide to the same Live socket. Audio, detector and Core reasoning remain
synthetic; actual Core/provider continuity and device acceptance are pending.
The earlier CI joined fixture failed fetching CSRF through the unrelated full
dashboard state endpoint; it now uses the existing shared-browser authentication
fixture and access endpoint, with an exact matching WebSocket host. This is a
fixture correction, not an audio improvement.

Receiving558 remains selected. Real-provider rollover, repeat compaction,
completed metadata retirement and the complete receiving journey remain pending;
PR560 stays draft.

### Provider-generation transition kernel

The owner-local native context route now supports `rollover_read` with the
current dialogue/generation and `rollover_commit` with the same scope, a fresh
`next_generation` UUID and the exact read revision. These operations remain
unavailable to the model's integrating controller. They never dispatch a native
turn or call a provider.

Preparation is read-only and requires an open dialogue, no unfinished frozen
reader, all retained language incorporated and represented by Sol's current
checkpoint, and no pending/submitting guidance. The returned seed contains that
checkpoint and settled guidance as attributed non-executable continuity. Its
serialized24KiB ceiling reserves space within provider setup; it is not a token
count or a guarantee that every selected identity/setup combination fits. An
oversized seed is rejected intact, never clipped. The caller must still check
the complete setup and request a smaller semantic checkpoint when necessary.

Commit compares the exact seed digest again, so new language, a new checkpoint
or changed guidance invalidates the candidate. Preparation and commit also check
the canonical human journal within their transaction: a newly finalized original
not yet caught up by the projection blocks rollover. Unfinished capture/completion
still belongs to the runtime owner's idle-boundary check. Commit advances only the projection's
producer generation; it does not assert provider readiness or application. The
socket owner must coordinate the actual idle boundary, candidate setup/readiness,
canonical pending-effect references, local generation journal and commit before
accepting new capture. Socket writes/tool calls/native work are not replayed from
the checkpoint. The active-loop coordination below implements this source path;
actual provider and receiving acceptance remain separate.

The last exact transition receipt supports inspection after a lost native commit
ACK, including restart; reissuing it does not mutate state or open a socket.
Old generations lose append authority, source receipts still deduplicate canonical
catch-up, and retired generation UUIDs cannot regain authority. Retain at most
65generation IDs and one transition receipt per logical dialogue: after64rollovers
the finite session must end or use a separately supported continuation. No
unbounded transition history or background continuation is introduced.

Kernel qualification covers two checkpoint/rollover cycles across native restart,
old writer rejection, canonical source deduplication, unchanged read accounting,
stale language/guidance digests, late canonical-original catch-up and exact
oversized-checkpoint retrieval. These
tests do not establish socket rollover, repeat provider compaction, token
admission, pending-tool handover or receiving acceptance. The five-minute runtime
pilot and receiving558 remain unchanged.

### Local journal recovery and prepared provider successor

The app's existing producer table now holds one small pending transition intent
(`previous`, `next`, exact seed revision) and its last exact local settlement
receipt. The receipt makes a committed SQLite update inspectable when its
awaiting coroutine is cancelled before updating its in-memory projection.
`NativeContext` serializes context
sync, guidance and generation mutation through one operation lock. It records
the intent before a caller opens its candidate, checks the unchanged basis again,
and advances the local producer generation only after an exact native receipt.
Completed assistant outbox/source identities remain unchanged. The new nullable
column requires a compatible app writer on future adoption/rollback; it is not
yet in receiving production.

A lost commit acknowledgment cannot be resolved by a read-only status=false:
the commit might still be queued. Owner-local `rollover_abort` atomically either
observes that exact committed transition or retires the candidate UUID, fencing
any delayed commit. It never reverses an actual commit. Its result distinguishes
`rollover_committed` from `rollover_fenced`; status is read-only. Fenced/committed
candidate IDs share the existing65-ID bound. If even that outcome is unavailable,
retain the one local intent and stop claiming a known generation. The next
explicit avatar opening resolves it, seals/catches up and closes the prior
logical dialogue without reopening its old socket or replaying any operation.

`NativeDialogue.successor` prepares one replacement socket from the exact Sol
checkpoint, owner identity and bounded canonical pending-effect references. It
checks the complete32KiB context before opening and waits for actual setupComplete.
Only setup is sent: no captured audio, completed original, provider tool call ID,
function response or generation request is replayed. A failed candidate closes
itself while the original transport remains available. Preparing a candidate is
not installing it or evidence that its checkpoint was understood.

Qualification now includes38transport tests,9local producer/recovery tests,
46mounted voice tests and245Store tests, with15focused final kernel checks.
The joined real-owner/control/native-controller/SQLite journey also runs two
incorporation/checkpoint/generation cycles, deliberately loses the ACK after
actual native commits, and verifies that a delayed native commit is rejected
after its candidate was fenced. Synthetic Core reasoning and transport peers
are explicit; these fixtures use zero model/hardware calls. The prior joined
voice/context/guidance journey still passes.

The prepared methods do not implement128k-token admission. Their active-loop
integration and remaining delivery requirements are described below. PR560
remains draft and the five-minute runtime pilot remains.

### Active voice-loop handover —3November2026

The prepared successor is now connected to the existing explicit avatar loop.
An advisory request occurs at102400observed provider tokens,240seconds,24tool
proposals,128tool responses or early text/guidance bounds. This hint is not a
tokenizer, hard admission rule or permission to discard context. Rollover still
requires a current complete Sol checkpoint. Token/headroom-triggered checkpoint
delivery and hard admission are unfinished.

Candidate setup runs while the old stream continues receiving audio and serving
new speech. At installation, the owner pauses/drains its provider event reader,
checks any already-dequeued output batch, acquires the acoustic boundary, waits
for serialized playback and requires complete original retention. The final
transport gate takes its thread lock without waiting and rejects active output,
unknown provider writes and pending tools other than the known idle return watch.
Provider usage observations retain monotonic peaks and wake this control path
without being displayed as conversation content or treated as authority.
Native/local generation commits before the stream references change. Failed or
stale preparation closes the candidate and resolves/fences its exact intent;
a candidate setup failure leaves the healthy old conversation available.
Only a changed seed or another completed provider turn permits a new attempt;
idle reads do not write sync repeatedly and wake their own database watcher.

Only an idle queue wait may be retired, never a tool send, admission or native
job. Known-unoffered canonical returns remain in the same queue; a failed
installation can resume the same old watch. The successor receives bounded
admission/uncertainty references, and any late result uses the existing canonical
reader/notice path. A second proposal for the same retained original returns its
actual previous admission or uncertainty rather than minting another work intent,
including when a new provider reuses a raw call ID. Per-provider tool IDs retire;
the bounded logical admission ledger remains.

Logical capture/detector clocks and source IDs remain monotonic. Incoming provider
activity offsets are rebased by the bytes already sent before replacement; old
PCM is never resent. Automatic mode additionally requires an exact acknowledged
boundary with no unassigned tail. The existing300second logical PCM/output and
128capture pilot bounds remain; aggregate output is bounded across generations.
At most one candidate or retiring stream exists per active owner. Closing during
preparation resolves its transition while preserving any separate unknown source
retention failure for explicit recovery. The fixed scalar close journal adds the
rollover count, candidate setup-failure count and retired output totals, never
checkpoint/tool content.

Qualification:49mounted voice tests,25bridge tests,25acoustic tests,13producer
tests and39transport tests pass. The joined mounted journey now performs two
active socket handovers through actual owner/controller/SQLite incorporation and
checkpoints, once-only completed human originals, canonical assistant outbox and
one Sol guide. Four sources survive, old PCM is not replayed and private native
bookkeeping stays unpublished. A separate mounted journey speaks across both
replacements while integrating work remains pending, then receives its late
canonical return without another admission. Holding candidate setup still permits
old audio; changed floors defer installation. Audio/detector/Core/provider peers
remain synthetic. These are not real-provider continuity or hearing receipts.

Previous-head CI41558621219 passed native text/other applicable jobs but its
dashboard scalar-boundary test timed out awaiting cleanup's journal after2seconds.
That privacy/retention verifier now allows a finite30seconds; all its exact scalar
and no-private-content assertions remain. This is not a claimed audio or latency
improvement, nor a finding of the underlying timing cause.

CI41565184983 completed successfully for published217c, including native text,
mounted dashboard and joined voice/controller journeys.

### Early checkpoint pressure and conservative input reserve

The owner reports pressure once per physical generation through
`checkpoint_needed`. The native projection freezes that control with the next
internal context range, including an empty range when all language was already
incorporated. A previously frozen range cannot acknowledge a later request.
Repeated pressure does not write/wake another return. Sol receives an executable
full reader and must incorporate the complete active checkpoint plus all exact
tail pages before writing its new semantic checkpoint. A pressure ACK alone is
not semantic compression or handover approval. Handover requires its request to
be acknowledged and the existing complete checkpoint/idle/effect gates. The next
committed generation resets the single request slot. A quiet receive timeout
surfaces pressure once through the existing event loop; no new timer or poller.

The selected model's read-only catalog reports131072 input tokens; the user cap
remains128000. Live does not support `countTokens`, so local accounting is
explicitly an estimate, not an exact provider tokenizer: UTF-8 text/protocol
bytes,64tokens/second for each PCM direction and a512token allowance per requested
generation. It anchors upward to valid monotonic provider prompt/total usage and
never releases reserve on a lower or missing observation. The64token estimate
has margin over the documented approximate25audio tokens/second, but is not a
provider guarantee for every text normalization, hidden accounting or event.
Before writes it keeps8192tokens of input reserve; owned phrase-end/stop controls
can use that reserved space. Crossing the local128000estimate or an observed
provider total above the cap closes to retained review. A locally refused write
is known unsent, including guidance; an attempted socket write remains uncertain.
No unconditional provider context discard or second model/counting call is added.
Sources: [Live token counting](https://firebase.google.com/docs/ai-logic/count-tokens),
[Live session audio accounting](https://firebase.google.com/docs/ai-logic/live-api/sessions)
and [Live wire reference](https://aistudio.google.com/api-reference/live).

Qualification:17projection tests,42transport tests,14producer tests and49mounted
voice tests pass. The joined actual owner/controller/SQLite journey now requests
pressure after both roles' language is already incorporated, dispatches an empty
control range, reads and incorporates full active context, writes a semantic
checkpoint and performs two active handovers. Sources/work/audio remain once-only
and internal bookkeeping stays unpublished. Core reasoning, provider audio and
detector remain synthetic. Actual-provider token accounting and continuity are
still unqualified; these results do not establish hearing or receiving adoption.

Remaining before adoption: joined actual Core/provider continuity/performance,
active-turn integration, long-pilot retention/continuation and receiving/device
acceptance. PR560 stays draft,
receiving558 is unchanged and the five-minute pilot is not lifted.

### Completed-copy retirement and actual provider/Core evidence

At an installed idle handover, the acoustic buffer releases only the completed
original prefix through its validated boundary. Unassigned/trailing PCM stays
available for later source correlation or close recovery. A base offset keeps
capture/detector/provider positions monotonic; releasing bytes does not reset the
logical duration/input allowance. Completed capture objects and notification
references retire after their actual reservation/completion/notification tasks
finish. The latest capture stays available for tool correlation; seen source IDs,
originals, admission references and uncertainty survive under the existing bounds.

Guidance text retires only when Sol has acknowledged an exact full snapshot
including its current disposition and committed a checkpoint covering its basis.
A newer guide or a send disposition changing after freeze cannot borrow that ACK.
The semantic checkpoint then carries the meaning; compact ID/text-digest/send
receipts keep duplicate rejection and unknown outcomes, without repeating retired
text in future setup seeds. Accepted incorporated native-return metadata retires
only after binding consolidation leaves no collector referencing it. Active,
uncollected or uncertain receipts and the context-only publication lifetime fence
remain. These are selective live-copy retirements, not original/history deletion.

A finite real Gemini qualification opened one initial and two successor sockets.
Each returned digital audio and the correct synthetic continuity word; successor
checkpoints changed that word twice. No tools were proposed, old sockets remained
open during preparation and all three closed afterward. First PCM arrived
0.634/0.626/0.671seconds after a spoken internal guide. These are three provider
observations, not end-of-human-speech latency, intelligibility or device hearing.
The local estimate19727–20392 exceeded observed total usage4287–4464 in these
small cases; this is not proof of an exact universal token bound.

The first real Sol test exposed a schema/usability fault: it guessed two wrong
CAS field names before writing the correct checkpoint, then re-read an identical
already-incorporated snapshot without another ACK, leaving handover blocked.
Full readers now supply an exact `checkpoint_writer` template: add only
`arguments.text`, retaining the supplied `revision` and `through`. A checkpoint
can release a fully supplied identical re-read only when its exact revision has
an existing full-incorporation receipt; changed or unread ranges retain their
ACK gate. No alias parameters or guessed incorporation are accepted.

A distinct new actual Sol6.1/openai/medium case using that contract completed
two internal native admissions with empty human input and five controller calls:
range incorporation, pressure-range incorporation, full read, full incorporation
and one semantic checkpoint. Both attributed roles and the exact temporary word
survived; no work, memory write or ordinary chat publication occurred. The full
test took25.9seconds, not a speech-latency measurement. Previous native work and
its failed verifier outcome were retained without replay. Native Core and Gemini
have now been exercised separately at these changed seams. A further actual-Core
case admitted a correction while Sol was awaiting an already-applied controller
response: both admissions acknowledged the SAME physical turn. A subsequent idle
pressure admission produced a semantic checkpoint with the corrected temporary
word. Three internal admissions and seven controller calls completed in26.458s;
no work, durable memory write or ordinary chat publication occurred. Active-turn
context steering is therefore qualified at Core; the mounted journey with both
real providers and device acceptance remains open.

Qualification:250Store tests/20focused projection tests,26acoustic and26bridge
tests,49mounted voice tests, joined actual owner/controller/SQLite voice journeys,
mixed human/context publication and clippy all targets with warnings denied.
CI41568933929 failed its formatting check on the final reserve predicate; the
actual job diff was inspected and formatting corrected. Final-tree formatting is
checked separately. No runtime or audio diagnosis follows from that CI failure.
The corrected source575748a passed CI41572683749, including native text and the
applicable dashboard/speech/Matrix/routing checks. This does not qualify physical
handover under continuous capture or authorize treating the draft as deployed.

## Astra high review — accepted decisions

The human-requested Astra high agent reviewed this complete plan and actual
Store/native-return/producer/Core source before implementation. Its findings:

1. Separate incorporated and checkpointed watermarks. ACK retires dispatch, not
   post-checkpoint exact text. Full active read is a committed checkpoint plus
   ALL subsequent deltas through a frozen watermark. Retained toolOutput alone
   does not guarantee full retrieval across Core compaction.
2. Reject unconditional slidingWindow. It has no Sol-incorporation barrier.
   Choose logical dialogue with physical provider-generation rollover from an
   acknowledged compact checkpoint, exact incorporated tail and external-effect
   references. Request checkpoints early; if Sol cannot catch up, retain/review
   before exhausting hard input reserve. Resumption is a separate future transport
   optimization, not semantic compaction or permission to replay.
3. A foreground context return never contributes a publication grant. Do not use
   it as a negative fence against genuine admitted human/work outputs. Current
   physical-turn collectors cannot prove sentence-level causal attribution for
   mixed contexts; do not promise that stronger property.
4. Supply ordinary batches completely inline, overflow through exact pages,
   followed by one explicit range/revision incorporation ACK. Supplied text plus
   the explicit claim is the receipt; it is not machine proof of comprehension.
5. Start with finalized human and terminal assistant/interrupted utterances;
   use semantic text/state revisions, never playback-dependent history revisions.
   Canonical restart catch-up closes the two-database retention/projection gap.
   Preserve capture chronology separately from projection arrival order.
6. Existing recovery retries known-unsent, NOT rejected records. Do not replay
   uncertain submission. Do not copy32-source-per-physical-turn/16return/four-routed
   version limits into unbounded dialogue batches; consolidate context metadata
   after incorporation without losing in-flight/uncertain publication evidence.
7. Guidance uses logical dialogue/generation/owner epoch and a basis watermark,
   not equality with the newest transcript revision. New speech alone does not
   make useful guidance stale; superseded assumptions do. Serialize clientContent
   guidance against capture at idle. Socket write is sent, not applied. Existing
   tool paths and current original/delegation guards remain authoritative.

Implementation order: bounded projection/read/watermarks/catch-up; native internal
return+ACK+publication; same-dialogue guidance; explicit checkpoint rollover with
all counter/media retirement; restart/saturation and receiving/device acceptance.
No additional reviewer quorum, permission ceremony or autonomous attention is
introduced. The source-only automatic compression setting was removed after
review. Its setup acceptance remains dated evidence, not the selected design.

## Continuous capture correction — 3 November 2026

The focused follow-up to the requested Astra high review found a real mismatch
in the physical-generation design: automatic `boundary` is the last detected
speech END, while `sent` includes later microphone PCM, including silence. The
current `boundary == sent` handover gate therefore normally stays closed with a
continuously open microphone. The earlier joined fixtures stopped PCM exactly at
their synthetic endpoint; they do not establish normal continuous handover.

Do not remove that equality to make a fixture pass. Bytes after the last END
have already reached the old provider without a finalized source assignment.
Reassigning them to a successor can cross generation ownership; omitting them can
lose a delayed phrase. Automatic close currently retains that raw tail only
after an uncorrelated transcript sets `unassigned`, not merely because raw bytes
remain. The complete tail-ownership/recovery behavior remains a concrete gap.

Two distinct mounted actual-provider cases delivered synthetic eSpeak PCM but
received no activity, transcript or audio after readiness; no human original or
Sol input was admitted. The diagnostic case observed208844PCM bytes reaching both
ASGI and Gemini, and clean explicit close. Earlier retained natural-Qwen evidence
already demonstrated automatic activity. These failures identify an unsuitable
fixture input, not a universal provider/VAD diagnosis. Their terminal outcomes
remain retained. A distinct natural-Qwen case then used continuous silence frames
without forcing pressure. One mounted Gemini/Sol connection transmitted2187136PCM
bytes over68.348s, finalized five unique originals, generated1796644PCM output
bytes, and observed two interruptions. Actual Sol dispatched one worker request
and its amendment exactly once; a canonical worker result was accepted and
reported by Sol. The temporary continuity word also returned with digital audio.
The worker remained a synthetic delayed fixture; no real external work occurred.

This is partial integration evidence. Gemini did not speak the returned worker
ideas; it resumed the earlier local tree conversation instead. A final context
incorporation failed after fixture shutdown, with the actual native thread later
observed idle and all physical turns completed. Retain that exact pending tail.
The verifier itself raised because its generic wait checked a receiver's
WebSocketDisconnect before an already-present deliberate-close receipt. Readback
confirmed clean explicit provider/producer cleanup, with no provider failure.
Correct the observation from retained results; do not replay speech or worker
requests to obtain a green label. A native result ACK or generated PCM is neither
the useful spoken-result journey nor physical hearing/device acceptance.

Source inspection against the current official FunctionResponse schema also
found `scheduling` nested inside application `response` data. It now sits beside
`id`, `name` and `willContinue`, with `response` containing only the actual result.
The selected value remains WHEN_IDLE, which is also the documented default;
this shape correction alone does not explain or repair the missing spoken result.
All42transport tests pass, including the corrected protocol assertion. Primary
schema: [FunctionResponse](https://raw.githubusercontent.com/googleapis/python-genai/main/google/genai/types.py).

The current primary SDK adds Developer API `send_context_update`, serializing
`contextUpdate.systemInstruction` in order with other inputs. This corrects any
earlier claim that active preamble replacement was unavailable. It neither
triggers compression nor provides an application acknowledgment. The follow-up
review prefers evaluating in-session semantic checkpoint replacement before
making physical replacement the ordinary compaction path:

- Preserve the existing Sol frozen-read/incorporation/checkpoint barriers.
- Serialize immutable base instructions plus attributed checkpoint data through
  the same provider writer; omit tools so the catalog remains unchanged. Record
  watermark, digest and sent/uncertain outcome without claiming comprehension.
- Sliding may retire only checkpoint-covered material. The newer exact tail and
  unfinished audio need a proven protected suffix. `targetTokens` is a reduction
  target, not a documented minimum suffix; do not enable sliding from that
  heuristic alone. System instructions are expressly excluded from eviction.
- Bound never-sent input while checkpoint coverage catches up. Do not replay
  already-sent PCM to manufacture a handover or token-budget receipt.

This is a conditional design revision, not an implemented/qualified replacement.
The existing automatic sliding setting stays OFF. If suffix protection cannot be
established, physical rollover still needs an acoustic transport fence. Distinguish
last speech END, old-generation send frontier, frozen transport fence and captured
never-sent bytes. `audioStreamEnd` can request finalization, but neither a timeout
nor an arbitrary `turnComplete` proves all preceding PCM became an original or
certified non-speech. Current Developer API transparent-resumption conversion is
unsupported. Retain uncertain old-generation tails rather than invent a drain ACK.

Likewise, the128000-token cap is the human's limit, not a qualified server-enforced
ceiling. The local reserve/estimator and optional observed usage remain bounded
engineering controls; observed excess cannot retroactively prove prevention.
The five-minute pilot and receiving558 stay unchanged while these gaps are open.

Primary references checked3November2026:
- [SDK context-update implementation and Developer API converter/tests](https://github.com/googleapis/python-genai/commit/364889a)
- [Sliding-window eviction boundary and system-prefix exclusion](https://googleapis.github.io/js-genai/release_docs/interfaces/types.SlidingWindow.html)
- [Live capabilities and audio-stream finalization](https://ai.google.dev/gemini-api/docs/live-api/capabilities)

## Returning speech during an admitted human turn — 3 November 2026

Readback of the partial natural-Qwen case localized its missing result before the
Gemini prompt: Sol's useful worker-result commentary was canonical, but its
`presentation_input` retained the concurrent human correction. The returning
source association was absent. Voice correctly filters ordinary commentary;
therefore that result never entered the provider's integrating-source tool
response. Earlier response bodies had been admission/correction answers, not the
worker's returned ideas. Do not diagnose this as Gemini ignoring an offered
result or repair it by repeating the worker request.

New native message inserts freeze accepted current return-source IDs separately
from `presentation_input`, in nullable `native_return_sources`. The human's
ordinary presentation lifetime remains unchanged. The existing canonical reader
exposes `native_returns` when that complete frozen set is still current, allowing
the existing voice return watcher to offer meaningful commentary. If any source
changes, the return association disappears; the ordinary human message remains
readable. Reobserving an existing native item does not add later source bindings.
Context-only batches never contribute return IDs. No new queue, work dispatch,
model admission, publication audience or hearing receipt is introduced.

The added column is nullable and uses explicit inserts. Startup does not backfill
old items, infer their causality from later bindings or replay their audio/work.
Existing internal-only publication/source-set fences remain authoritative. This
is source association at the existing collection boundary, not sentence-level
causal attribution. Rollback/readers must retain the new metadata to preserve
this returning-speech behavior; old readers retain ordinary human history but
cannot offer these mixed-turn commentary returns to voice.

A regression fixture records ordinary progress before a real return, accepts the
return during an independent human turn, records useful commentary, and reads it
through both presentation list and exact part. It verifies that earlier progress
never gains the association and that a later correction retires only the offer,
preserving human visibility. The251Store and49mounted voice checks and clippy all
targets with warnings denied pass. A distinct actual Gemini/Sol natural-speech
journey closed before its worker-result step: it observed three originals,
sixteen source reads and eleven invalid-argument rejections, eventually exhausting
the existing32tool-proposal bound. One worker request had been admitted; its
correction and result were not qualified. The fixed close code was
`native-dialogue-invalid-provider-event-tool-envelope`; exact recordings and
admissions remain retained. No duplicate request or replay was used to repair it.
The rejection event currently omits the invalid argument's specific shape, so
the next focused diagnosis must capture bounded field/type evidence rather than
guess whether the model supplied an invalid UUID, cursor, extra field or tool.
This failure does not disprove the deterministic association repair, but it also
does not qualify the complete actual-provider spoken-result journey. No receiving
or device acceptance follows from the unit checks.

A subsequent distinct, instrumented mounted journey passed on source5786323:
actual Gemini3.8Live and actual Sol6.1/openai/medium exchanged five fresh natural
Qwen originals on a continuous microphone timeline. Sol dispatched one request
and its amendment exactly once to the synthetic delayed Alpha worker. The actual
canonical integrating-source response then carried the returned ideas; Gemini
generated PCM and the corresponding complete phrase about chickpea salad and
vegetable soup without an oven. One barge-in was observed. Input/output totaled
2242094/964328PCM bytes. The useful return's first generated PCM arrived0.554s
after its integrating-source tool response: one digital interval, not final-human-
speech latency, intelligibility, phone hearing or a comparative benchmark.

Explicit close completed cleanly. Exact actual-Core readback showed five physical
turns completed, all controller calls succeeded and native idle. The last closed
projection receipt had high11/incorporated11, establishing final context drain
rather than only transport ACK. No runtime deployment or physical handover
occurred; the successful disposable fixture was removed with native history and
bounded evidence retained. Do not rerun this accepted journey for another green
label. The earlier invalid-argument loop was not reproduced, so its cause and
robustness remain unresolved. A separate short actual-provider diagnostic also
produced valid arguments; it is not evidence that the intermittent fault is fixed.

## In-session pinned language — focused Astra follow-up,3November2026

The requested reviewer accepted a practical replacement for ordinary physical
rollover: one replaceable system preamble containing immutable identity/policy,
Sol's checkpoint through C, the EXACT newer canonical both-role tail through P,
and pending effect references. Provider sliding may then remove duplicated
completed conversation while Sol alone performs semantic compaction. This is the
next implementation, not yet a selected runtime setting; sliding remains OFF.

The current SDK exposes ordered `contextUpdate.systemInstruction`, preserving tools.
Actual application on the selected Developer API endpoint still needs qualification;
SDK serialization and a successful socket write do not establish that application.
Mark pin coverage dirty immediately when terminal human/assistant information
arrives, before asynchronous retention; keep reading provider events. Freeze the
canonical snapshot after retention and recheck its revision before sending.
Prioritize a ready dirty pin over PCM, tool responses and guidance through the
same writer. Coalesce superseded unsent revisions. Near the volatile-suffix limit,
buffer only newly captured never-sent PCM with byte/time bounds while retention
finishes; never hold the acoustic lock waiting for native storage. Older uncertain
PCM and attempted writes are not replayed.

Retire exact tail only after Sol commits its semantic checkpoint. Incorporation
ACK alone cannot remove it. Replace with the new checkpoint plus every newer
event, rejecting stale prepared revisions. Late human interpretations retain
their original capture chronology; interrupted generated assistant text stays
attributed and potentially unheard. The ordinary provider suffix needs room for
ALL unresolved retention/transcript/output lag, not just the latest human turn.

Repeated compaction requires checkpoint-cycle identity within the SAME physical
provider generation, replacing once-per-generation pressure suppression. Account
the current preamble independently from cumulative transmitted/billable data;
replacements must not accumulate forever in `context_estimate`. Historical peak
usage is not current occupancy after an observed slide, and expecting a slide
does not justify reclaiming history allowance.

Bound preamble, exact tail, unresolved lag and never-sent input explicitly; request
Sol compaction early. Qualify two actual slides under continuous natural PCM,
inspecting provider usage and pin revisions as well as distinctive facts present
only in checkpoint versus exact tail. Include delayed retention, late transcript,
interrupted output, input during replacement and a pending actual-source result
with no duplicate admission/offer. Reuse the accepted Sol/Gemini journey above.
If Sol cannot catch up within the bounds, retain recovery and end gracefully.
The guarantee is completed canonical language preserved by the pinned checkpoint
and exact tail, with qualified bounded lag for unfinished material. Exact universal
128000-token prevention remains limited by provider accounting; conservative
headroom is an engineering control, not a tokenizer proof. No additional VAD,
Gemini tool catalog or physical reconnection is needed for ordinary compaction.

The first implementation seam is available as owner-only `pin_read`: it returns
a revision-bound checkpoint plus exact post-checkpoint events and current
uncheckpointed guidance, within49152serialized bytes. It requires the active
generation and canonical-human catch-up, never clips an oversized pin, and leaves
Sol's frozen reader, incorporation watermark and stored projection byte-for-byte
unchanged. Incorporation alone does not shrink its exact tail; a semantic
checkpoint does. The native model controller cannot invoke this producer read.
The253Store tests include these retirement/staleness/boundary cases; the actual
owner/controller/SQLite journey confirms human/assistant roles, interrupted text,
producer-only authorization and no new native wakeup. Dashboard's29owner tests,
formatting and clippy all targets pass. This does NOT yet update Gemini's
preamble or activate sliding: ordered pin writing, repeated checkpoint cycles,
occupancy accounting, never-sent pressure buffering and actual-slide qualification
remain the next implementation work.


## Ordered pin writer and actual endpoint discriminator,3November2026

The transport now has an explicit `context_pinning=False` prototype, with no
application enablement or receiving adoption. Owner snapshots must match their
canonical SHA256 revision and serialized byte count. A separate short producer
lock allows a ready pin to queue while the socket writer is occupied. The same
writer drains pending pins before subsequent PCM, tool results and guidance;
known-unsent intermediate revisions coalesce. It preserves the complete immutable
identity/policy preamble and leaves tools unchanged. Replacements do not accumulate
old preamble byte estimates as resident context. Observed whole-window usage is
never reduced by subtracting an estimated old prefix; historical allowance remains
conservative. Sequence, owner, revision, byte and count bounds reject stale data.
Attempted writes become sent, known-unsent or uncertain, without automatic retry.
A sent phase is deliberately NOT an applied receipt.

Forty-seven transport checks pass, including writer contention/priority,
coalescing, changed content, replacement accounting and uncertain-write handling.
The49mounted voice and26bridge checks pass with the default path unchanged. The
actual owner/controller/SQLite journey additionally checks that Rust's canonical
pin bytes and SHA256 match Python's encoding. These checks establish local
ordering and the snapshot contract, not provider continuity or semantic coverage.

Actual selected Gemini3.8Live probes did not establish context replacement. A
configured CompAII probe produced voice but returned an identity-related value
instead of the new synthetic fact; another asked for a source without producing
voice. A distinct minimal probe removed the application policy and ALL tools:
its baseline spoke the two initial synthetic values correctly, but the response
after `contextUpdate.systemInstruction` still spoke the old values. A corrected
minimal probe using `context_update.system_instruction`, as spelled in Google's
WebSockets guide, likewise spoke its baseline correctly and retained the old
values after the update. Both completed their responses without a protocol error. A third minimal
input-path discriminator used `realtimeInput.text` instead of `clientContent`: its
baseline again spoke the initial values and the post-update response retained
them. The missing uptake is therefore also observed on that text input path;
this does not establish the behavior of captured speech or another endpoint.
One intervening verifier had an inconsistent initial expectation and never reached
its update; that setup error is retained separately and is NOT provider evidence.
Every connection is closed. No media, human input, native work, recovery replay,
production change or sliding activation was involved.

The primary Python SDK's `send_context_update` and Developer API converter expose
this message and the SDK defaults to the same v1beta endpoint; an assumed alpha
version mismatch is therefore not a finding. Google's Cloud Live guide documents
ordered prefix replacement, while the inspected Developer API Live reference did
not describe a ContextUpdate type. These observations leave endpoint rollout,
applicability and input-path behavior unresolved; they do not prove a universal
provider limitation or identify a model-prompt defect. Keep pinning and automatic
sliding OFF. Do not build protected eviction on an unobserved prefix update, infer
application from send(), or rerun paid fixtures merely for another green label.
The next investigation must resolve the actual endpoint/input contract or qualify
a supported continuity alternative; repeated checkpoint-cycle integration and
input-pressure buffering remain pending that decision.

Primary sources inspected:

- https://raw.githubusercontent.com/googleapis/python-genai/main/google/genai/live.py
- https://raw.githubusercontent.com/googleapis/python-genai/main/google/genai/_live_converters.py
- https://raw.githubusercontent.com/googleapis/python-genai/main/google/genai/_api_client.py
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/start-manage-session
- https://aistudio.google.com/api-reference/live


## Unexpected-close audio recovery —3November2026

Automatic voice previously kept an uncorrelated PCM tail only after receiving a
transcript without START. A provider send failure or connection loss before any
onset/transcript could therefore discard bytes already present in the acoustic
buffer. Unexpected close now preserves that buffer's post-boundary tail through
the existing private WAV/original-retention route. It does not require text to
prove that received PCM might contain speech. A completed original's prefix is
not captured again; an open owned span still uses its existing source identity.
At most three120second chunks fit the existing300second acoustic bound. Earlier
arm-time question narrowing remains frozen for an uncorrelated tail. These are
unconfirmed recordings for explicit review, never invented complete utterances,
automatic ASR, provider audio replay, work admission or Sol language context.

The mounted regression exposed a second concrete race: close set the bridge's
live-tools flag before a newly scheduled capture reservation reached its owner
write. The private WAV survived but its native input reference was not retained.
Already captured deferred retention now finishes through the same bounded owner
slots, with fresh actor/binding validation, independently of the live-tools flag.
New captures, interpretation completion and tool effects remain closed. If that
validation is revoked, native retention is rejected and the exact private bytes
remain unconfirmed; no fallback work authority is inferred.

Validation:29acoustic,28bridge and50mounted voice tests pass. Coverage includes
missing START/text, a completed original plus new tail, chunk/scope bounds,
idempotent close, a provider write with unknown outcome, immediate-close
retention and revoked actor rejection. The existing actual owner/SQLite/decoder
journey now also closes immediately after capture: the exact WAV and
foreground_captured journal entry survive, binding is rechecked, and no extra
ASR, interpretation or native work occurs. The first added verifier run reached
those owner assertions but had a missing helper import before its final WAV
comparison; the corrected zero-model fixture passes. No human/provider work was
replayed to fix the verifier.

This is an unexpected-close recovery repair, NOT continuous handover acceptance.
Ordinary explicit close does not manufacture a new recovery recording merely
from trailing PCM. Missing-onset audio on that normal-close path, frames still
waiting in the receive inbox/current batch, and automatic old-generation tail
ownership remain open. No additional VAD, namespace/store, pilot duration,
provider endpoint selection or receiving deployment is introduced. The five-minute
pilot, disabled pinning/sliding and full unfinished product scope remain.


## Natural-audio discriminator and append-anchor fallback review

A distinct natural-PCM probe now establishes that missing context-update uptake
is not limited to text questions. On the selected v1beta/Gemini3.8Live endpoint,
the first synthetic spoken question was fully transcribed and its two initial
facts were spoken correctly. After the context update, the second distinct
spoken question was also fully transcribed, with automatic START/END observations,
but the reply repeated the old facts. The connection closed after15.534seconds;
91204generated PCM bytes were counted, not retained as another media copy.
Two fresh Qwen samples used the existing bounded cache. No native/human work,
hardware, replay, deployed endpoint change or sliding activation occurred.

The requested Astra high reviewer read this evidence and selected the next
specific fallback to qualify: append a self-contained internal anchor through
clientContent with turnComplete:false, at a verified idle generation boundary.
The anchor contains the semantic checkpoint, EXACT newer both-role language,
source revisions, interruptions and pending-effect references. Immutable setup
identity stays fixed and describes these records as attributed source data,
not new human speech, work, authority or a request to talk. Each refresh is
complete without depending on a prior anchor; Sol transfer remains incremental.
This is a reviewed candidate, NOT an enabled or qualified compaction mechanism.

The SDK sliding contract retains a suffix cut at a USER-turn boundary. Its target
is a reduction target, not a guaranteed minimum suffix or a promise to preserve
a particular USER anchor. Therefore source text MUST NOT describe this fallback
as equivalent to a protected system preamble. It needs a selected-endpoint
qualification and conservative coverage bounds. For a64000target, the review's
starting envelope is immutable prefix+anchor<=24000estimated tokens, newer admitted
history<=16000, unfinished/output/retention reserve<=8000 and16000margin. Bounds
must also leave room below the trigger for a fresh anchor and pending output;
these estimates do not claim exact tokenizer accounting.

Use the existing idle guidance gate. Unlike a preamble replacement, clientContent
can interrupt generation even when turnComplete:false, so do NOT drain anchors
indiscriminately before every write. Queue/coalesce preparation, wait for actual
terminal provider state, acquire/recheck the shared writer and append before
new PCM/tools/guidance. Retain bounded NEVER-SENT incoming PCM near coverage
pressure; no old sent audio is replayed. A late provider onset can race a local
idle observation, and a terminal assistant may precede its human source's durable
interpretation: retain and budget those coverage gaps rather than claim complete
coverage. Only a committed Sol checkpoint retires the canonical exact tail.

Next qualifier: one connection, ordinary immutable setup, two actually observed
prompt-occupancy reductions, independently distinguishable checkpoint/tail facts,
a correction, late interpretation, interrupted output and natural PCM arriving
at refresh. Inspect revisions, write order and current usage as well as digital
spoken recall. Recall alone does not prove a slide. Do not repeat the passed
full Gemini/Sol worker journey. If the newest complete anchor is evicted within
these bounds or blocks later audio, do not add unqualified rescue anchors. The
review's smallest existing alternative is a NEW manual-activity dialogue using
local detector-owned spans, end ACKs, bounded never-sent backlog and checkpoint-
seeded rollover between spans; never convert a running automatic dialogue or
replay its old sent tail. No new contextUpdate probe is needed.

Primary contract: https://googleapis.github.io/js-genai/release_docs/interfaces/types.SlidingWindow.html

## Python3.11 cleanup cancellation qualification

CI41584589629's dashboard job timed out in the new unexpected-close test. The
same failure was reproduced locally under the locked dashboard dependencies and
Python3.11: cleanup awaited a cancelling native-return observer before retaining
the tail. A separate deterministic source-wakeup test proved that cancellation
racing a ready notification returned normally instead of closing the watcher.
Python3.11's wait_for can return an already completed inner future in that race.
The local3.13 pass had not qualified the actual CI interpreter.

Source watching, the bounded bridge owner/file waits and native socket sends now
use asyncio.timeout around the awaited operation. The original heartbeat,2/18second
owner/file limits,3second send limit, protected running threads and actual slot
release are preserved. External cancellation propagates instead of becoming a
successful notification/control result. The close regression observes owned
cleanup and exact retained bytes rather than waiting on a logging callback;
removing that callback wait alone did NOT fix the3.11 failure. The wakeup test
failed before the source change and passes after it. All3watcher,28bridge and
50mounted voice checks pass on both3.11 and3.13. Full CI for the corrected source
is still required; no receiving deployment follows from these local results.


## Append-anchor wire outcomes and selected continuation

The first finite append-anchor qualifier ended during repeated-token synthetic
prehistory, before sending ANY anchor. Its later prehistory generation produced
partial unrelated text without PCM and the next generation timed out. Zero
anchors and zero reductions were observed; this is not anchor-eviction evidence.
Its exact outcome remains retained without replay. The fixture was corrected to
use balanced descriptive synthetic records and to start continuous PCM only after
initial history preparation. The two completed Qwen samples were read from their
verified cache, without new synthesis requests or media copies.

That corrected fixture used the ordinary immutable identity/tools setup and
isolated compression trigger24000/target22000. Seven prehistory responses
completed; prompt observations rose from4212to22443. One self-contained canonical
anchor was then sent with turnComplete:false, while newly arriving natural PCM
was queued behind its writer fence. The natural question was fully transcribed,
but there was no generated PCM or turn completion within the finite15second
response wait. The connection closed after23.279seconds, with threads stopped.
No slide, post-slide fact recall, second anchor or actual native/Sol work was
qualified. The previous prehistory problem therefore did not become a false
success or a reason to add rescue anchors. The test establishes an unusable
outcome for this attempted flow, not a universal cause or API prohibition.

The requested Astra review already specified the alternative for blocked
subsequent audio: qualify a NEW dialogue using the existing manual-activity
route. It keeps the same Gemini3.8Live conversational layer and Sol integration,
but local detector-owned spans and explicit provider END acknowledgments give
the existing checkpoint-seeded physical rollover an owned boundary. Continuous
quiet PCM is analyzed locally rather than becoming an uncertain sent tail on
the retiring provider. Only never-sent backlog may enter the successor. Do not
convert an already running automatic dialogue or replay its transmitted audio.

This is the selected next isolated qualification, not a receiving mode switch.
Reuse the earlier actual Sol semantic-checkpoint and useful-return evidence;
qualify two actual provider successors during continuous natural capture with
readable checkpoint facts and uninterrupted source identity. Source durations,
retention and final input ownership still require actual checks. The full goal,
ordinary Sol/Qwen chat, runtime558, source-host hold and disabled provider
pinning/sliding remain unchanged.


## Actual continuous manual-route qualification,3November2026

A mounted authenticated ASGI journey used the existing actual local CPU detector,
Gemini3.8Live and continuously arriving16kHz mono PCM. Four natural Spanish Qwen
phrases introduced lapacho, asked for recall, corrected the word to sauce and
asked again. Three physical provider sockets completed TWO committed successors;
both later questions returned the current word with generated24kHz PCM. Output
was191044bytes across the logical conversation; received capture was1131830bytes.
The complete finite run took37.437seconds, including preparation; this is not a
speech-latency distribution or a physical-hearing measurement. All seven
detector-segmented originals reached foreground completion. The detector split
some spoken sentences, so four test phrases do not imply four endpoint events.
No provider error, boundary mismatch or candidate setup failure was reported.

The checkpoint owner was synthetic and seeded successors only from actual
retained input captions and assistant language, including the correction. It
exercised the production owner/bridge/generation shape without another Sol
inference or worker journey. The separate actual Sol idle/active incorporation,
semantic-checkpoint and mounted useful-return evidence remains valid; this test
does not alone prove the complete actual Sol+provider rollover composition.
Pressure was deliberately raised to exercise both transitions; actual128000token
admission under a full context, long/noisy speech, barge-in during handover and
receiving/device acceptance remain separate unfinished requirements.

The first attempt proved one successor and correct recalled speech but its
verifier incorrectly required a literal sauce acknowledgment instead of allowing
an ordinary acknowledgment followed by semantic recall. Its close observation
also stopped at the owner's early close event; fixture shutdown then cancelled
remaining cleanup. The corrected fixture reused verified completed synthesis
cache without new requests and waited for actual owned cleanup completion.
An intermediate cache-shape assertion failed before any provider opened and was
corrected against the real cache contract. Neither fixture failure is evidence
of a provider capability failure. The final run reported context_producer closed,
cleanup completed and stopped threads; its disposable media fixture was removed.
Earlier failed originals and outcomes stay retained without replay.

Reusable lessons were published in Skills PR233, daimon-matrix-contributions
2.0.16, and installed through the existing selective updater on this body. The
isolated install qualification, installed readback and surface check passed.
That source publication/local adoption does not claim another body's adoption.

Continue with the complete integrating/receiving qualification and remaining
input ownership, pending-work, interruption and device obligations. Do not repeat
accepted provider probes or switch the selected receiving dialogue in place.


## Actual Sol and continuous provider rollover composition

The next mounted journey replaced the synthetic checkpoint owner with the actual
Core Sol6.1/openai/medium integrating session and production Store/controller.
Only internal attributed context was submitted, with empty native human input;
no worker request, ordinary message publication or new speech synthesis was
needed. Four cached natural Spanish phrases exercised selection, recall,
correction and later recall while input capture continued throughout both
checkpoint preparations and socket replacements. Two real Sol-written semantic
checkpoints seeded two committed Gemini3.8Live successors. The final answer
retained sauce, superseding lapacho. The owner and app finished closed, projection
high11/incorporated11/range empty, native busy0 and actual Core status idle.

Nine internal admissions shared three actual physical Sol turns;15controller
calls were all live_context. Three Gemini sockets generated177122PCMbytes;
continuous input received2184630bytes. The voice interval was69.677seconds and
the whole bounded fixture83.460seconds. These durations include deliberately
waiting for checkpoint/replacement between phrases; they are not a conversational
latency benchmark. Cleanup completed without provider error, boundary mismatch,
failed send or candidate setup failure. The successful disposable fixture was
removed while native conversation history and bounded evidence remain retained.

The first composition attempt also proved one actual Sol checkpoint and correct
spoken recall after its successor, then its diagnostic recorder exhausted its
128KiB cap by retaining every acoustic activity frame. That assertion affected
fixture callbacks and cleanup, so it cannot diagnose a product failure. The
actual native session was subsequently read back idle with both turns completed;
no uncertain input was replayed. The corrected recorder aggregates acoustic
activity and observes terminal native state before teardown. Keep diagnostic
capacity independent from provider/control callbacks. This lesson is included
in the shared contribution skill2.0.16.

CI41588065499 passed for source d16930d0, including the actual Python3.11 dashboard
job and text/native/lifecycle/presentation qualifications. Subsequent edits here
only record the evidence and selected continuation; no Rust or Python behavior
changed after that source. Receiving558 remains selected until the owning
writer-preserving adoption route is executed. The complete token-limit, active
speech/pending effects during handover, noise, device and remaining roadmap
requirements still need their applicable evidence; do not replace them with a
claim that two successful checkpoints complete the milestone.


## Pending work across an actual provider successor —3November2026

A distinct isolated mounted journey on sourceec9991b7 used actual
Sol6.1/openai/medium, Gemini3.8Live, the local CPU detector and the existing Qwen
route for one new synthetic input recording. Its two sentence boundaries yielded
two retained interpreted originals; only the second requested work. A synthetic
Alpha worker received exactly one accepted request for two snack ideas.

With Alpha still pending, injected conservative context pressure requested an
actual Sol full-context read and semantic checkpoint. One real Gemini successor
was prepared and installed while capture continued. Alpha still had exactly the
same one admission afterward. Only then did the fixture complete Alpha with two
ideas. The canonical integrating return reached the new provider and produced
199202bytes of native24kHzPCM plus the matching spoken transcript: a toast with
cheese and fresh fruit. No original, worker admission or old provider audio was
replayed. The source-return tool receipt and generated speech are digital
observations, not physical hearing or a useful-speech latency benchmark.

The logical voice lasted60.753s; the complete fixture took79.962s. Close retained
one rollover, no provider failure, context high4/incorporated4/closed, completed
cleanup and native idle. Input queue peak was3200bytes with2msobserved wait;
local analysis peak200ms of captured audio, unsent analyzed phrase peak564ms of
audio and activity-end-to-final-input-confirmation peak216ms of wall time. The
identity peer and client playback were synthetic, so these values do not measure
production network/grant or phone performance.

The successful disposable fixture/media were removed; its exact operation,
source hash and bounded scalar qualification remain in the receiving operator
record. Native history remains preserved. This closes this specific pending-job
return-at-handover case, not full128k saturation, arbitrary concurrent effects,
barge-in during commit, long sessions or device/noise/hearing acceptance.
No production runtime changed: receivingPR563 stays selected while the human
browser trial is pending; PR564's scalar diagnostics are merged/prepared only.


This same journey also produced a separate closed assistant row with285600bytes
of generated audio and no observed output transcription. No retained audio or
physical hearing establishes whether it contained intelligible speech. The
sourceec9991b7 outbox excludes empty-text rows: high4/incorporated4 therefore
proves only the four language-bearing sources, not complete coverage of all
generated audio. This missing-caption case remains an explicit investigation
item; the useful late-result transcript/audio above is independently present.


## Explicit missing-caption sources — prepared successor

Closed assistant audio without any output transcript is now a typed source in
prepared code. The web outbox retains its original source UUID, empty text,
interruption flag and `audio_without_transcript` observation containing the
PCM SHA256 and generated byte count. It never invents text, marks the audio as
silent/heard, invokes ASR or turns it into human ingress. Empty rows with neither
text nor generated audio still add no source. Normal language-source revisions
remain unchanged; playback-dependent revisions do not define context identity.

The native sync accepts this observation only with empty text, a lowercase
64digit hash and a positive even byte count within the existing300second output
bound. Repeated source IDs reconcile the same receipt; changed evidence is
rejected. The full reader/pin carries the observation through ordinary context
incorporation. Its policy explicitly says that no words, intelligibility,
silence or hearing are established. Semantic checkpoints must preserve that
uncertainty rather than summarize invented speech. Existing projection/source/
byte quotas and original/routing ownership are unchanged.

This paired web/native candidate requires
`input voice capabilities.foreground_audio_observations = "v1"` in addition to
the existing context/guidance/rollover contracts. An older listener is refused
before provider open or browser microphone acquisition. Future adoption must
select the compatible native writer before this web candidate. Keep that
writer/current journals on rollback, and retain a caption-aware web reader until
any pending typed observation has been retained by native context. An older web
reader cannot drain its new empty-text outbox payload; never restore an old
journal or silently discard it to make rollback appear compatible. The compatible native receiver is now selected as recorded above; the paired
web candidate remains prepared. PR563web continues during the current browser
trial, with unchanged Core/configuration/voice/UI and ordinary chat.

Qualification includes the actual mounted web/history/owner/native-controller/
SQLite journey: two source-preserving provider handovers, followed by an
audio-only assistant turn, exactly one new missing-caption observation reaching
the synthetic Core, incorporation high5 and no extra human original, worker,
ASR attempt or public bookkeeping. Existing checkpoint4 remains distinct from
the newly incorporated observation5. The first verifier still expected the old
four-source fixture; its final assertion was corrected to preserve this new
uncheckpointed tail. Provider/detector/Core peers in this transport test are
synthetic and no model or hardware is involved.

A separate bounded actual Gemini wire/parsed-text comparison on3November2026
produced two audio turns with96and100UTF8caption bytes, respectively; all were
preserved by the parser. No missing-caption turn reproduced in that probe.
The earlier285600byte empty-caption case remains unexplained. Recovering its
unknown language is not claimed: that audio was not retained. Future caption
recovery can reuse the selected pure file-ASR helper, with explicit assistant
provenance and draft status; it must not rewrite a finalized source, replay a
work admission or treat generated audio as human speech. Automatic recovery and
its bounded transient-audio retention are still unfinished.


Actual Sol semantic qualification on the prepared typed observation completed
in29.955s with two internal admissions/five controller operations. Sol6.1/openai/
medium incorporated the exact source, read all full context and wrote a semantic
checkpoint explicitly preserving unknown words, language, intelligibility,
silence and physical hearing. No human original, task/worker, memory write or
ordinary publication occurred. This proves this semantic handling only. Native
history remains retained; the successful disposable fixture was removed. Both
the new caption-aware fixture and the actual old selected563Python app passed
the joined owner/controller/SQLite handover tests on the exact new release.
