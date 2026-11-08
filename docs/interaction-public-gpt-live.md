# Optional public GPT-Live comparison

This default-off comparison uses public GPT-Live WebRTC with managed Responses
delegation. It is distinct from Realtime and OpenAI · Codex voice. It does not
replace the integrating Codex session or inherit its identity, memory, credentials,
tools or active work automatically. The [roadmap](interaction-roadmap.md) retains
those requirements.

## Voice and backend instructions

Keep public Live instructions separate from the native Codex voice brief. Native
handoff instructions cannot create native tools in managed Responses. Adapt the
[public voice template](../templates/public-live-voice-brief.txt) with the actual
owner's identity, paired human and dialect in an owner-only file, replacing all
placeholders before selecting it through `identity_file`. Keep backend procedures
and actual tool definitions in their existing backend configuration. Updating an
owner-specific brief does not replace another being's identity or voice choices.

The [official prompting structure](https://developers.openai.com/api/docs/guides/live-prompting)
uses Backchannel/Interruption/Delegation policy, actual backend capabilities and
the `<|SpawnThinking|>` trigger. Concise speech must still preserve all explicitly
requested facts. A no-repeat/read-only clarification constrains a pending request;
it does not replace the requested answer. Prior observed source qualification
returned complete backend text but an incomplete spoken transcript; prompt
alignment is a correction to evaluate, not proof of a unique cause or completion.
Original audio, automatic captions, backend output, playback and human hearing
remain distinct evidence. Preserve existing accepted results and uncertain writes.

Synthetic qualification must not close a call using an old acknowledgment as
the final spoken response. Wait for the known synthetic input to end, all known
backend work to settle, a spoken transcript update after the backend result,
the scenario's required spoken facts, then the quiet tail. A pause after only
half the requested answer cannot establish success. `tests/dashboard_live_semantic_tail.js` covers this collector
condition; it is not a production utterance detector or audio-done event. A
deadline remains a failed/unconfirmed observation, never permission to replay.
The earlier page/part trial's collector could close immediately after backend
completion even if only its earlier acknowledgment had been heard. Its incomplete
spoken transcript therefore does not by itself establish a provider omission.

Native work integration must reuse the existing source-bound foreground delegate
and native execution owner. Public `LiveCreations.recording` currently retains
raw audio and a receipt only; it deliberately does not enroll a native conversation
input or authorize work. Automatic transcript deltas and backend function arguments
cannot be submitted as fabricated human text to bypass that missing admission.
The next integration needs a sealed, retained original prefix, its exact owner/
source/provenance admitted by the native writer, one durable delegation intent,
and exact native results returned through the managed tool continuation. Reuse
the existing capture flush/hold and foreground-original/delegate contracts rather
than adding another task store, model owner or retry loop. Hearing, late returns,
interruption and successor continuity remain required after that seam is joined.

## Configuration and selection

Use the existing authenticated dashboard and owner configuration. Never export
Codex login tokens as project keys or put credentials in the browser, URLs,
source, issues or logs. Explicit public project access and a selected backend
model are required. Private files use the existing owner-only reader; identity
and backend instructions are bounded to8KiB each. Invalid configuration refuses
startup. An unavailable key refuses activation before microphone permission or a
provider POST; it does not discover credentials.

See the commented `openai_live` settings in `dashboard/config.example.toml`.
Session/backend/delegation options pass through bounded owner configuration rather
than reducing provider features to the old manual-turn adapter. Browser overrides
are not accepted. WebRTC negotiates audio format. Total serialized configuration
is bounded to32KiB.

After explicitly configuring and qualifying this mode, select **Under the hood →
Avatar → OpenAI · GPT-Live comparison**. Activation is a human action. Existing
current-provider defaults and native Codex remain unchanged. Choice and owner are
frozen per visit; there is no mid-capture switch or silent fallback. Disable only
through scoped voice-idle maintenance, preserving journals and recovery readers.

## Capture, recovery and bounds

Server admission acquires the existing cross-mode voice lease before microphone
permission. One monotonic admission covers negotiation/capture: at most600seconds
and19,200,000input PCM bytes. Configuration may reduce this to300–600seconds;
reconnect cannot enlarge an existing admission. Local recording starts before the
WebRTC offer. Listening requires the validated HTTP creation answer and a connected
peer. The HTTP request starts a WebRTC session; an optional frontend data-channel
startup event is not another admission gate. The WebSocket transport's separate
`session.started` requirement must not be imposed on WebRTC. Backend events still
retain their exact session/source ownership. See the
[official transport startup contract](https://developers.openai.com/api/docs/guides/live-conversations#prepare-a-session-for-forking).

Originals reuse the browser20MiB/128-record budget and receiving original store.
Engine tags isolate recovery in the historical `codex_voice` store; its name does
not select Codex. One-second fragments permit interrupted-prefix recovery; an
unsaved tail may be missing. Server receipts must match visit, binding, ordinal,
SHA-256, bytes and provenance before local retirement. **Try saving audio** retains
the same original: it never reruns ASR, submits speech, dispatches work or creates
another session. Save/Discard affect local originals, not server work. Rollback
must keep a reader that ignores foreign-engine records and preserves originals.

Original-audio POSTs have no application wall-clock abort. Network failure still
retains the same local original; only its confirmed receipt permits source sealing
or local retirement. This extends the ordinary audio/image upload policy to the
public voice path, keeping all byte/storage and capture bounds unchanged.
The public and native capture-only server routes also omit an absolute body-read
deadline; the two upload slots, byte ceiling, fresh authentication/CSRF and
post-read owner recheck remain. Disconnect or network failure retains the
unconfirmed local original. Provider/capture/cleanup deadlines are unchanged.

A WebRTC `disconnected` transition shows reconnecting while allowing the same
transport to recover. It does not close and replace a paid call. Explicit Stop,
background lifecycle and the existing visit/capture limit still end capture;
`failed` or `closed` pauses as before. No automatic ICE restart, new negotiation,
provider call or audio replay is introduced. See the
[WebRTC state/restart contract](https://w3c.github.io/webrtc-pc/#dom-rtcofferoptions-icerestart).
The deterministic browser journey covers a delayed confirmed upload after all
application network clocks expire, transient recovery on the same call, and a
subsequent terminal failure. This is source qualification, not phone/WiFi/hearing
acceptance or proof of the cause of each historical disconnect.

The journal is limited to512records/32MiB,256KiB per receipt, two unsettled
creations total and one per human. Admission reserves2MiB of trusted source
capacity inside that aggregate bound. Meaningful provider events are capped at
8192/2MiB per visit and32KiB each; raw media frames are not copied. Source pages
contain at most64events/64KiB with exact revision continuation. Interrupted writes
count toward capacity. Refuse admission before billing at capacity; never evict
uncertain work/originals. No automatic retirement or per-frame log is installed.

## Review retained conversation

After reload, the comparison can restore the latest owner-bound voice transcript
without activating the microphone or connecting to OpenAI. **Earlier voice
conversation** pages one retained visit at a time through the existing journal;
its source reader follows exact byte/revision cursors, at most128pages/2MiB per
visit. Names and spacing remain the provider's automatic transcript, not a
verified human original, utterance boundary or evidence of hearing/task completion.
The interface groups fragments for display only, retains its existing64-card/
128KiB window, and does not feed this viewer history back into a model.

Failed reads retain the same visit cursor and deduplicate already shown source
IDs. **Retry voice history** resumes that read; ordinary presence refresh does
not loop failed reads or rescan a successfully restored binding. New/changed
owners invalidate pending reads before presentation. Prior histories never
replace live captions. Source/original review grants no new tools, input replay,
backend completion or new voice-call creation.

## Closing and uncertainty

One durable intent precedes one creation POST. Exact retries only read retained
outcomes. Lost responses, process loss and failed receipt commits do not authorize
another billed call. The sideband attaches to the exact opaque ID with the same
project access and receives future events only. Its trusted reader is installed
before the SDP answer reaches the browser.

Stopping capture starts a bounded30second drain of known managed Responses and
needed client continuations. One durable `session.close` is sent only when those
are complete. Unconfigured function/client work is never fabricated or executed. Trusted
`session.closed`, usage and backend completion remain separate. Missing
finalization stays unconfirmed. Disconnect cleanup detaches control, releases the
media lease and retains outcomes; it never sends close as a cancellation shortcut.
Do not delete records, change UUIDs or replay commands to clear uncertainty.
An unresolved prior call blocks automatic billed admission. A known-created
native visit with ended capture can use the explicit source-bound replacement
review described below; this retires its transport without confirming its bill.
Unknown creation outcomes and incomplete replacement commits remain held.

An unexpected exception from the owned native preparation task follows the same
graceful-close path as a held preparation. Retain its original and uncertain
ASR/native intents, stop new preparation, drain the existing eligible close and
wait for trusted `session.closed`. Log only the exception class. A failed task
must not abruptly detach the sideband and turn a recoverable failure into lost
finalization evidence. Cancellation and independent accepted native work remain
separate; this does not reconcile an older already-detached visit.

### Documented observation limits after disconnect

Checked7November2026 against the official [Live Sessions reference](https://developers.openai.com/api/reference/python/resources/live/subresources/sessions)
and [session lifecycle guide](https://developers.openai.com/api/docs/guides/live-conversations#usage-and-graceful-close).
The reference documents recording download and accept/fork/hangup/refer/reject
actions; it does not document a generic session-state or final-usage GET.
Recording availability or duration does not replace cumulative billed usage.
Do not invent an endpoint or repeat attach/close/create to clear a lost receipt.
A sideband receives future events; no replay of finalization is promised.

Keep latest usage provisional until a trusted `session.closed` confirms its final
value. Missing final usage is unconfirmed, not zero. The native replacement offer
is a read-only review of the retained owner, capture and source revision, not
settlement or a new admission. Only the later explicit reviewed reconnect can
admit its destination. Preserve the old record and original effects, and keep
provider billing uncertainty separate from source/native continuity acceptance.

## Optional current-conversation context

The owner may explicitly select `conversation_context=true`. Managed Responses
then receives one application function, `compaii_conversation_read`, backed only
by existing authorized presentation-page and exact source/revision readers. The
browser supplies no tool calls, authority, source text or provider commands.
Pages retain their exact cursors and bounded previews; part reads retain offsets
and revisions. Ownership and paired-actor access are checked before and after
the read. Returned text is source data, not new instructions or execution proof.
The selected operation determines which arguments are used. Page cursors are
ignored for exact-part reads, and part references are ignored for page reads;
unused fields cannot override the selected source or cursor. Actual managed
Responses supplied a nonzero unused delivery cursor with a valid source/revision;
rejecting that irrelevant field falsely reported an unavailable source. Exact
part identity, revision, offset and current owner checks remain unchanged.
This covers the current conversation, not DMK, arbitrary private sessions, native
task execution or full being memory. Those roadmap requirements remain open.

Only trusted completed function items select a read; argument deltas cannot.
At most16calls are retained per visit, each with at most4KiB arguments and8KiB
output, inside the existing256KiB receipt/32MiB aggregate journal bounds. A
result intent precedes its single `response.item.create` write. Once all known
results for that response are sent, a durable intent precedes one `response.create`.
Socket sends are not acknowledgments. A lost write/commit is never retried; restart
retains the unresolved intent and blocks close. Unknown tools remain unresolved.
The documented continuation has no separate item success acknowledgment: trusted
new Responses lifecycle and matching completion settle backend work. An old
response completion cannot close over a new running response. No native input,
work delegation, ASR retry, media replay or extra provider session is created.

Source and mounted tests cover read authorization, two pending results, resumed
completion, restart/lost-write refusal and storage bounds. Actual owner page/part
reads establish access wiring; useful model recall and physical speech need their
own receiving qualification. Keep this feature off on unconfigured receivers;
ordinary common software delivery does not enable providers or copy credentials.

## Optional provider-stored continuation

The owner may select `resume_mode="stored_fork"` together with explicit
`session_options={store=true}`. The default is `fresh`; neither remote storage nor
continuation is enabled implicitly. This choice requires project storage to be
enabled and permitted by its data policy. OpenAI documents30day availability of
stored recordings; Zero Data Retention disables this feature. Actual account
eligibility, recording readiness and useful behavior must be tested separately.
See [OpenAI's stored-session workflow](https://developers.openai.com/api/docs/guides/live-conversations#prepare-a-session-for-forking).

The first explicitly activated visit creates a stored source. On a later
activation, the server selects the unique terminal source in that owner's
continuation chain. Parent references determine this chain; wall-clock movement
cannot select an earlier ancestor. Before microphone permission or a billed POST,
the source must be trusted-closed, storage-requested, configured identically and
free of known pending/failed/incomplete Responses or needed client results.
Changed identity, voice, backend/tool policy, ambiguous source chains or missing
storage require review rather than silently starting an unrelated conversation.
Each activation retains the existing600second/PCM admission bound.

The [documented WebRTC fork](https://developers.openai.com/api/docs/guides/live-conversations#start-a-webrtc-fork)
uses the source's exact opaque ID and only a new SDP offer. Provider inheritance
carries the original model, voice, instructions and conversation; no previous
startup envelope, serialized prompt or transcript is nested into the new request.
The application retains a flat predecessor reference and configuration/request
digests. Controls and sideband attach to the new child ID. A response reusing the
parent ID is unconfirmed, not a successful replacement.

One durable intent owns each fork. Lost responses and process loss preserve
uncertainty and prevent a second fork/fresh fallback; exact retries only read the
retained outcome. Existing published fresh-call receipts keep their digest
contract. A closed event, synthetic context construction or successful fork ACK
is not proof that the next voice remembers a correction, preserves task semantics
or speaks useful results. Within a call, GPT-Live's provider-owned compaction
remains distinct from application task records and cross-call continuation.
Unexpected disconnects without trusted closure and unavailable/expired stored
recordings still require reconciliation; saved-text/semantic-checkpoint fallback
and late-work routing remain unfinished. No timeout or diagnostic context bound
is enlarged by this option.

## Qualification boundary

The current [retained real-voice chain](interaction-qualification.md#retained-real-voice-native-handoff--7november2026)
adds two actual source-bound native admissions, one acknowledged canonical progress
return and a current canonical final after the closed voice visit. Existing memory
curation/readback matches its original. This is partial work continuity, not an
audible final return or memory lookup from inside a fresh live connection.

Mounted authorization/upload/cancellation tests and Chromium synthetic desktop/
mobile journeys cover wiring and original recovery. They make no public provider
request, use no human microphone and prove no hearing quality. Public access,
useful tasks, full identity/memory/work/tool integration, artifacts/questions
and sustainable renewal remain open. Retained transcript presentation is
implemented separately from provider reconnection and memory hydration. Follow the
[practice comparison](interaction-gpt-live-practices.md) before enabling a
person-facing trial; this is not full-stack adoption.

## Receiving sideband media observation

Actual project WebRTC qualification observed raw `session.input_audio.append` and
`session.output_audio.delta` frames on the attached sideband without event IDs.
They belong to media transport and are discarded before source-ID validation;
they are never journaled or forwarded as conversation text. Transcript, backend
and close events retain strict source identities. A synthetic spoken backend
question returned its backend-only fact, completed Responses and trusted close
with24seconds usage; this is digital qualification, not physical hearing or full
being/memory/native-tool acceptance.

### Native acoustic-original enrollment (prepared; default off)

The owner-only `openai_live.native_originals=true` option connects newly retained
public microphone recordings to the existing native foreground reservation.
This is an intermediate handoff prerequisite, not a completed native tool or
permission to execute work. It is not selected in receiving684. Browser payloads
cannot enable it or supply native text/formulations.

The adapter uses the existing public visit journal and the existing native input
journal, with the original's server-derived UUID, exact WAV hash, frozen actor
and entry binding. Native `conversation_voice_submit` receives
`foreground_dialogue=visit` and `defer_foreground=true`. It reserves original
chronology without ASR, interruption or a native model turn. A later correction
therefore remains after its acoustic original even before interpretation finishes.
Interrupted/recovered prefixes stay in review rather than being silently enrolled.

A native write intent is durable before its single submission. Lost ACKs can be
reconciled by reading that same native input, including after App restart; missing
status never authorizes another send. Restart cannot backfill an original with no
retained enrollment intent. Current owner authorization is checked before and
after native access. Existing original media and journal quotas still apply;
no new queue, database, attention producer or funding mechanism is introduced.

The native/current-conversation readers can observe a captured original, but this
release does not manufacture its transcript from Live captions, invoke the
existing file-ASR fallback, select another provider, or formulate/dispatch tasks.
Prepared interpretation/import components are described below. The remaining
work is explicit native handoff and sourced return to continuing speech,
interruption and renewal.
Keep this option off until that complete comparison journey is qualified.

Qualification includes locked Python3.11 component/mounted HTTP tests and the
actual native668 owner/SQLite foreground journey with synthetic transport and
zero models: one original, exact hash and chronology, no extra ASR/work, lost ACK
then restarted read-only reconciliation, and later-correction order. These are
native admission facts, not physical hearing or full being/memory acceptance.

#### Prepared OpenAI interpretation component

`openai_live_transcription.py` implements the current official file-transcription
route (`gpt-transcribe`, `/v1/audio/transcriptions`) for a completed canonical WAV.
It reuses approved project-key custody, never Codex credentials or another audio
provider. It is not mounted or selected in receiving684. Older transcription
model examples are deprecated in the current official guide; do not silently
substitute one of them or the configured ordinary voice-note ASR.

An interpretation requires an observed native acoustic reservation and the exact
still-uninterpreted canonical source, current actor/binding, and original bytes.
A visit admits at most16 interpretation attempts within its existing600second
recording bound. Each paid intent reserves20KiB inside the existing bounded visit
record before HTTP. The result replaces that reservation; concurrent source
writes cannot consume its promised space. Response bytes/text, input PCM, network
waits and redirects are bounded. Errors, interruption and uncertain replies never
repeat the POST. An old receipt can be read without key access or another model
call; restart cannot start a previously unattempted interpretation.

Completed text is retained under the frozen acoustic source even if viewer access
is revoked during HTTP, then access is checked before exposing or using it. It is
a machine interpretation, not verified written human speech or work authority.
The component does not synthesize a native original from Live captions, run the
ordinary file-ASR fallback, or dispatch work. Its HTTP/model, timeout, restart,
revocation, result-space and once-only behavior currently have mocked-provider
qualification; no paid transcription has been used to claim acceptance.

#### Prepared source-bound native interpretation import

The native owner command `input foreground interpret JSON` imports completed
`gpt-transcribe` text into its existing held acoustic original. Its closed fields
are `binding`, `id`, `dialogue_id`, `audio_sha256`, `model`, `text`, `audio_millis`
and `transcription_millis`. The native writer verifies owned entry/dialogue,
canonical private WAV, exact hash/duration, immutable completion and original
chronology. It commits the existing original directly from `foreground_captured`
to `foreground` in one transaction; it starts no ASR or native work. A matching
completed import is idempotent even after the working clip was archived.

The importer sets the existing `preserve_original` archive hold atomically with
the transcript. A status/list read cannot retire this original without an exact
archive receipt. This does not change the ordinary Qwen/Gemini/native voice-note
behavior or enlarge existing original-storage quotas. Full storage still refuses
new preparation instead of discarding unfinished originals.

`commit_interpretation` uses only the retained completed derivative, reserves a
1KiB native-receipt slot within existing visit quotas, and records an intent before
its single native write. A lost ACK, crash or missing status only permits reads of
the same ID. Known-unattempted completed metadata can finish after restart; this
starts no model, replays no audio/work and creates no new original. Access is
checked before use/exposure; matched native receipts survive an in-flight viewer
revocation. Older readers refuse before a new ASR request or native-import intent.

The experimental acoustic enrollment currently narrows question versions to none:
this route does not yet freeze them at the first local acoustic marker. Questions
observed at upload time cannot acquire answer/approval authority. Actual voice
question answers require the first-marker snapshot integration or existing
explicit controls; this remains part of the unfinished full voice goal.

Qualification includes seven commit-state tests, eight interpretation tests, six
acoustic-enrollment tests, native store/WAV tests and an actual owner/SQLite/WAV
journey with synthetic recognizer/transport: one source row, exact machine proof,
protected original still present after status reads, lost-ACK read reconciliation,
no extra ASR/work, and later human correction ordering. No paid transcription or
physical hearing is claimed. These components are connected by the optional native
backend below; receiving selection/real voice acceptance remain unproven.

The existing native foreground delegate owns explicit work; its sourced result
can reach continuing Live speech through the optional same-turn return. Real
native context/memory, late returns,
interruption, physical renewal, hearing and the other full-goal obligations remain
unfinished; this import is preparation, not an end-to-end acceptance claim.

Official contract: https://developers.openai.com/api/docs/guides/speech-to-text
and https://developers.openai.com/api/docs/guides/live-delegation .

#### Prepared direct client-to-native work bridge

The official client-delegation mode lets GPT-Live delegate to an application's
existing agent. It is a candidate for the persistent Codex integrator, alongside
the existing managed Responses comparison, not evidence of a better result yet.
Choose the mode at session creation; a running Responses visit cannot switch to
client mode. Keep native Codex subscription authentication and the separate
approved public voice API project unchanged.

`session.delegation.created` supplies a trusted delegation ID and target, **no
task text**. Input/output transcript deltas are fragments, not completed turns;
their approximate session offsets are not packet arrival times. A silence gap
does not prove an utterance ended. The existing30second durability chunks must
not be treated as complete instructions or used to bypass the native latest
captured-correction fence. Exact acoustic sealing/correlation remains unfinished.

The server component `openai_live_native_work.delegate_native` accepts
only a retained client delegation, one to eight ordered acoustic originals whose
OpenAI interpretations were already committed to native storage, and a separately
attributed assistant formulation. It uses the existing native foreground delegate
to the integrator; it does not select workers or synthesize human text. The native
transaction freezes source text/hash, acoustic provenance and capture chronology,
and independently rejects an older root when a later correction exists.

Before submitting, the component reserves2KiB for its acknowledgment inside the
existing visit quotas and persists the exact intent/formulation/source hashes.
The record inherits existing32delegation,8source,8192byte formulation and64KiB
source-context bounds. It cannot start new work after capture expiry or reader
restart. Lost acknowledgment, process exit, native rejection or unavailable status
permit only reads of the same root; none permits another write. Observed receipts
survive in-flight access revocation without exposing them to the revoked viewer.
A second delegation cannot reuse an already reserved root. Later corrections may
include earlier context with a new root; they never replace the first intent.

Nine component tests cover these boundaries. The actual native-owner/SQLite/WAV
journey also lost the work acknowledgment after admission, reconciled it after
restarting the App reader and observed one native request containing the exact
formulation and acoustic proof. Its recognizer, public creation and native model
are synthetic: no paid call or real model execution was made. Native admission is
not a completed task, successful memory lookup or heard answer.

The bridge is mounted only behind the owner-selected native backend below, with
source seals required. Receiving selection and real native turn/result acceptance
remain unfinished. For client tasks, official results use
`session.commentary.append` with the original delegation ID; quiet progress uses
`session.thinking.append`. These500token appends and their context-injection ACKs
do not establish spoken delivery. Preserve long outputs in native storage and
use bounded current-source readers, corrections and late-return handling.

`openai_live_native_results.return_native_part` prepares that result return using
the existing canonical presentation reader. It requires an observed work intent
and freshly rechecks the original's native ownership. An integrator item must
belong to its associated local native turn. A worker delivery instead needs an
available, current, instruction-covered result in the original's existing trace;
the representative request ID alone is insufficient. Foreign/currentness failures
and correction-pending sources refuse before a context append. Turn association
does not itself prove that the model incorporated every instruction; real semantic
qualification remains required. A final message is not proof of the entire task's
completion, and progress never becomes a completed-task claim.
The work intent also freezes the newest canonical native-message cursor before
admission. A message already present at that boundary cannot return as the new
answer, even if a later input steers the same native turn. This bounds attribution
to a new source; semantic incorporation still needs the real-model journey.

Each returned fragment keeps its exact canonical source/revision/character cursor
and reads the source again before use. Quiet progress uses thinking appends;
results use commentary appends. A conservative384UTF-8-byte source fragment plus
a small attribution/partial marker stays below the documented500token append
bound without assuming a model tokenizer. Long Unicode text is preserved through
explicit cursors, not truncated into an apparently complete result. No metadata
identifier must be narrated to the human. At most128append records per visit fit
inside existing receipt quotas; reaching capacity refuses before writing and keeps
the remaining canonical cursor. No result archive or new unbounded queue is added.

The exact command and512bytes of acknowledgment space are committed before one
sideband send. Unknown sends or missing ACKs block advancement and never retry,
including after App-reader restart. Only the trusted matching append ACK records
`context_injected`; it is not playback, hearing or work completion. In-flight ACKs
cannot be downgraded by a late socket-send receipt. Updates remain within the
existing finite visit and30second finalization envelope. Old visits can read a
retained receipt but cannot start another append after reader restart.

Ten result tests cover native/request association, ownership/currentness,
Unicode pagination, quiet progress, unrelated ACKs, lost send/restart, revocation
and capacity, including an ACK racing the socket-send receipt and a preexisting
answer in the same native turn. The actual
owner/SQLite/WAV journey also produces a synthetic final
item on the admitted native turn, reads its canonical revision and appends that
result exactly once over a synthetic sideband. Its context-injection ACK remains
separate from unobserved hearing. These are source/transport qualifications, not
real model/memory/device acceptance. Automatic result discovery, actual source
sealing, native late-return/renewal integration and mounted lifecycle completion
remain unfinished; do not bypass pending-work closure fences merely because a
source exists.

#### Prepared raw source-seal control

`openai_live.source_seals=true` explicitly opts into recorded-prefix controls;
the default is off. This flag does not choose a client backend, start ASR/native
work or change providers. It cannot be combined with upload-time
`native_originals=true`: the sealed path must select its exact source window
before native enrollment, rather than enrolling later raw durability chunks as
new corrections while an earlier request is being prepared.

Within the existing authenticated/CSRF-protected voice visit, only a trusted
client-delegation source may request a boundary. The server persists a unique
request and12KiB of receipt space first. The browser reuses the recorder's
existing `boundary(token)` operation to drain pending PCM without stopping the
microphone. It checks the acknowledged cumulative byte count, then synchronously
fixes that prefix and flushes it into the existing original-upload pipeline;
new microphone frames continue in another segment. It acknowledges only after
all ordinals through that boundary have matching server upload receipts. A
duplicate request echoes its cached acknowledgment without flushing or uploading
new audio. Failed originals or changed conversation ownership cannot produce a
successful acknowledgment and retain ordinary recovery behavior.
The processing-marker wait is bounded to3seconds; a missing marker preserves
ordinary original recovery and cannot become a successful source seal. The
browser fixture includes an unflushed producer tail before acknowledgment.

The server validates a closed acknowledgment containing only the request ID,
exclusive recording ordinal and cumulative PCM byte count. It requires every
server-recorded original in that prefix, exact contiguous ordinals/bytes and no
interrupted-prefix flag. The resulting receipt references existing original IDs,
hashes and sizes; it does not copy media. The next task starts after the previous
boundary. Empty windows are explicit and cannot become native work. Multiple
trusted client tasks serialize only their short capture boundaries, not native
execution. The existing32delegation/32recording,600second, local two-store
20MiB/128record and server storage limits stay unchanged. No background poller,
provider call or new timeout coordinator is installed.

An unconfirmed request is never re-authored or resent by the server. After reader
restart, a retained completed receipt is readable, but pending capture cannot be
silently restarted or declared complete. When a native work intent has a seal,
it must use that exact acknowledged nonempty ordinal/hash window. Sealing cannot
retroactively attach another source to a previously admitted native intent.

This establishes a raw capture boundary, **not** a human utterance end. Durability
chunks can straddle words and several exchanges; provider transcript fragments
may arrive late. GPT-Live offsets must not be equated with local PCM sample
positions: recording/connection startup and transport timing differ. Semantic
formulation, first-acoustic-marker question scope, full source assembly/correlation
and real native-mode qualification remain unfinished. Existing pending-work/closure
fences remain; source acknowledgment is neither task completion nor hearing.

Qualification: eight server seal tests, ten native-work tests including its seal
fence,27mounted API tests, and browser scenarios covering continued frames,
duplicate requests, missing uploads, empty capture and changed ownership. The
actual prepared native owner/SQLite/WAV journey also checks the sealed original
hash before the one native admission and sourced result return. Provider/media/
model peers remain synthetic; no paid inference or device acceptance is claimed.

#### Optional native client backend prototype

For a separately selectable comparison, the owner enables
`openai_live.native_backend_enabled=true`. Keep `backend_mode` and the existing
Responses settings unchanged. Under the hood then offers **OpenAI · GPT-Live +
CompAII** in addition to the current modes; the additional option is disabled
when the server does not advertise it. Selecting it sends only the bounded
`backend="native"` admission choice, authenticated through the existing
grant/CSRF. The server checks its configured availability and actual native
reader before paid creation or microphone permission. The browser requires the
matching native prepared-mode acknowledgment, freezing its choice before any
asynchronous setup; there is no switch/fallback during capture.

This additional choice requires the current fresh-visit/no-upload-enrollment
profile. It uses exact source seals and client delegation without managed
Responses tools, even when the unchanged Responses mode has its conversation
reader enabled. The admitted `backend_mode` is retained in the existing visit
journal and status response. No additional account, key, history store or
automatic provider activation is created. Qwen/current voice, Codex voice and
the original GPT-Live mode/default remain unchanged. Operator enabling an option
is not human microphone activation or real identity/memory/hearing acceptance.

The owner may explicitly select `openai_live.backend_mode="native"` for the
public GPT-Live comparison. The default remains `"responses"`; existing provider,
native Codex login and deliberately chosen integrator settings are unchanged.
Native mode creates the documented `delegation.type="client"` session and uses
the existing native integrator for reasoning, memory and execution. It does not
start a second Responses backend. Keep the existing approved voice API custody
and select an appropriate bounded native voice brief through
`openai_live.native_identity_file`. Render the
[native voice template](../templates/public-live-native-voice-brief.txt) with the
actual being, paired human and dialect. This separate private absolute file is
read once (maximum8192bytes) when the app starts; Responses keeps `identity_file`.
Its native capability description delegates authorized memory and work to the
existing integrator. It must not inherit the managed reader's limited-context
description. For existing configurations without this optional field,
`identity_file` remains the fallback; an explicitly selected unreadable native
file refuses startup rather than silently using the managed brief. Retained
Responses-only backend settings are not used in native mode.

Native mode requires source seals (enabled for that explicit mode), forbids
upload-time native enrollment and managed-Responses conversation tools, and checks
the selected native reader's `foreground_live_window="journal-input/v1"`
capability and configured raw voice capture before microphone admission or public
voice creation. A deferred acoustic reservation needs no completed-ASR command.
An older reader
refuses before a paid creation; it never falls back to file recognition.

After a confirmed nonempty acoustic window, one owned task enrolls its exact raw
originals and freezes the input-speaker deltas already retained by the trusted
Live sideband. It makes no second ASR request. The existing native delegate reads
that exact private journal prefix, verifies its file identity, boundaries, hash,
input count and text digest, and atomically binds the grouped language and raw
originals to the existing integrator. Assistant output cannot become request text.
The root carries the group's language; earlier raw clips intentionally have no
per-clip transcript. This is approximate provider language for a source window,
not verified speech, an utterance-end marker or exact audio/text alignment.

Each window starts after the prior frozen window. Late fragments stay in the
journal for the next window and semantic context; they never rewrite a frozen
work intent. Missing input language holds the originals without another recognizer.
A source window reads at most4MiB/8192 journal records, with the unchanged64KiB
language bound. A Live-only grouped handoff may include all32 retained raw
recordings in the existing600second visit; the legacy per-clip interpreted
delegate retains its eight-source limit. The existing192KiB native document and
visit/store quotas still apply, so capacity failure holds the exact originals.
Native overlap checks reject reuse by another work intent; exact retries observe
one retained outcome, and uncertain writes never resubmit automatically.

The voice/control loop remains responsive during source preparation. Its stop
fence is checked after freezing and at native dispatch; closure preserves retained
sources without creating new work. Historical completed file interpretations and
their proofs stay immutable. The earlier components above retain their historical
proof/outcome contracts; new public Avatar delegations never invoke file ASR.

Once grouped windows are retained, keep a window-aware native writer during web
rollback: earlier strict readers cannot deserialize the new optional delegation
proof. The former web/native pair is a pre-window rollback only: its public
backend starts file ASR and is not an acceptable enabled rollback for this mode.
After window admission, recovery must retain a qualified window-aware pair or
leave public creation unavailable, with originals and explicit alternate modes
preserved. This source change is not receiving selection or physical acceptance.

Public transcript context charges the complete typed source plus reserved native
envelope against the existing16KiB native language limit. The12KiB individual
provider-delta bound is separate: a valid delta near that bound must not fail
merely because its exact speaker/timestamp/journal evidence adds metadata. The
adapter keeps whole deltas and source ranges, with no clipping, new ASR or change
to visit/context/storage limits. Complete typed evidence that cannot fit still
refuses before cursor advancement.

Same-turn canonical native progress/results are polled through bounded existing
presentation pages and returned with the source/revision/append safeguards above.
Worker returns use the original's existing native trace, including all covered
request links rather than only a delivery's representative request. The trace
now includes the scoped canonical source revision, or null when that source is
unavailable. Up to five routes/eight results per route are inspected per poll;
an explicit `more_results` remains incomplete coverage. Available, current,
instruction-covered results are rechecked against the exact original and
canonical revision immediately before one context append. A worker can finish
after the native turn and outside the current conversation page; no history
rescan, repeated ASR or new work is required. Unavailable routes are read afresh
later. Older readers lacking result revisions keep same-turn results only;
their excerpts are never manufactured into a revision or speech source.
Ordinary speech fragments prefer sentence/whitespace boundaries within the byte
cap instead of splitting a word. Injection ACKs remain separate from hearing.
Native handoff observation is not a completed task: admitted native work remains
owned by Codex after voice closes. Preparation failures, while current authority
remains valid, use the single close-intent/finalization path and retain their
receipts. A duplicate browser close observes that same intent. Confirmed closure
updates the UI to the ended/review state instead of leaving “Finishing” visible.
Result discovery also has one owned task per visit: a slow native trace or
canonical read cannot occupy the browser-control loop. Close sets the existing
visit stop fence before cleanup; reads check it between owner calls and before
creating a new append intent. If Close is observed after intent persistence but
before the transport call, the journal records `not_sent`, distinct from a lost
send acknowledgment. Neither state permits replay. Already-started writes keep
their actual outcome. Cleanup waits for the owned task with the existing finite
50second bound; it never cancels the independent native work or reopens audio.

This prototype deliberately accepts only `resume_mode="fresh"`. Native stored
fork remains unsupported. Later sections describe source/receiving support for
semantic startup, returns across visits and older-result pagination. Useful
spoken incorporation, first-marker question scope, long/concurrent semantic
behavior and actual memory/device/hearing acceptance remain unqualified. They remain part of the full goal;
do not report this source prototype as a completed voice circuit or silently
fall back to Responses to conceal the gap.

Qualification includes eight pipeline tests,32mounted API tests, nine interpretation
tests and eleven result tests, using the locked Python3.11 dependencies, plus
browser closure/state regressions. The mounted route exercises the complete
source→Live input window→native handoff→canonical result→context ACK path, a missing
reader before paid creation, failed interpretation with one voice close, and a
slow interpretation where Close stays responsive and the late derivative is
retained without native dispatch. All provider/model peers are synthetic. These
checks do not establish real CompAII identity, memory, speech, billing or hearing.
Four additional pipeline tests cover trace-located late workers, unavailable and
uncovered results becoming observable later, fresh association rechecks and
foreign-owner refusal. The owner/SQLite/native HTTP journey checks canonical
revision equality for both originals covered by a shared worker delivery.
A further mounted race keeps a trace read blocked while Close reaches finishing
and trusted closure; the work stays admitted and no late context append occurs.
Two result tests distinguish closure during a canonical read from the known
unsent post-intent outcome. These33mounted and13result tests pass with the locked
dependencies on Python3.11 and3.13; no provider/device acceptance follows.
The result scan retains its native cursor across bounded catch-up batches; a
tested64-item unrelated backlog does not permanently hide the later matching
answer. Source cursors/unknown append guards still apply before any new send.
### Page-local usage comparison

The prepared Under the hood panel reads the existing trusted server usage and
finalization messages; it creates no API, provider call, timer or persistent store.
It retains at most eight observations on this page and clears them on reload or
conversation reset. Backend labels follow the accepted admission, not a guessed
default. Ordinary data-channel events cannot confirm billing duration.

Only `finalization.voice_usage_confirmed=true` with a valid finite nonnegative
`usage_seconds` supplies the final duration. An intermediate usage counter stays
provisional; a lost final receipt stays unconfirmed, even after local Hold.
The displayed voice-only estimate uses the checked7November2026 GPT-Live1 rate
of USD0.05/minute, prorated by actual reported seconds. This is not an invoice,
credit balance, project eligibility observation or total stack cost. Backend/tools,
separate transcription and TTS remain outside it. See official
[pricing](https://developers.openai.com/api/docs/pricing) and
[voice cost accounting](https://developers.openai.com/api/docs/guides/voice-latency-cost#voice-session-costs).
Display callbacks cannot break capture or finalization. Source tests distinguish
confirmed zero from absent, malformed or partial usage and late observations.
Source preparation is separate from receiving selection and real trial acceptance.

# Native results across fresh voice connections

## Current integrating context at entry

This prepared increment is evaluated against the later same-general-conversation
direction. It does not establish another persona, native thread, login or history
store. Voice/text windows belong to the existing authenticated native entry. The
old PR737 review-delegation question was withdrawn after the revised direction;
its historical pending label is not a current approval or delivery receipt.

On8November the source was rebased onto798. The actual configured owner read
12native messages and14canonical sources from the same selected general thread:
14,516 embedded bytes within16KiB, no provider, native input or memory write.
78startup/context/mounted API tests passed against that base. Source preparation
and read-only authority evidence do not prove speech, receiving adoption or the
complete shared-conversation experience.

The prepared public-native entry now reads the current integrating thread with
the existing owner-local read-only observer (`thread/items/list`) and the latest
canonical integrating originals/results through their existing readers. This
second window matters: a visible correction or worker return may not yet have
been incorporated into the native thread. The previous voice producer is still
settled through its existing semantic continuation, with its original opening
time and relative transcript timing; it is no longer the sole startup source.

The voice policy reconciles timestamps and original capture order across the
windows, including the inverse case where voice is newer than native text.
Read/append order does not make an old statement current. Native harness roles
retain their attribution; original voice language remains machine interpretation.
Private analysis and tool outputs are excluded. Current progress remains progress,
not a completed goal or a new action. Unknown order and earlier-history coverage
stay explicit; missing facts go to the same native integrator and memory tools.

The observer reads at most four16-item pages and retains at most16 complete
conversational items. The integrating window uses one bounded input/result page,
at most16 selected sources, and exact canonical text cursors. A bounded window
stops scheduling reads after12seconds; one already-issued read keeps its existing
transport deadline and the mounting owner's late-I/O exclusion until it ends.
A bounded window
omits only complete older sources with an explicit earlier-history marker; an
oversized latest source refuses for semantic preparation rather than clipping its
text. The combined reserve is at most16KiB inside the unchanged complete32KiB
public session specification. Charge context as JSON text embedded in the final
JSON request, including both escaping layers; quotes/backslashes cannot use a
raw-byte estimate. Measure the actual developer-message envelope and policy
before allocating that reserve. Whole older sources can be omitted; the latest
source still refuses if it cannot fit. The boundary fixture fills the complete
32KiB specification without clipping or another context read. Existing
native24KiB resume and64k/48k/600s limits
are unchanged. No history store, provider call, new human original, work replay,
memory write, daemon start, native login change or context injection is needed
to read this startup data. Only the short-lived existing observer proxy closes.

Source qualification covers current corrections and progress after voice, whole
source bounds/cursors, changed-owner refusal and prior-voice seed preservation.
The actual receiving owner read both current native history and newer canonical
integrating updates without opening voice or making a paid/model request. A
three-visit mounted fixture retains the actual wrapper/source/projection path;
its Core observer and speech are synthetic. This is prepared source, not receiving
selection or semantic/physical acceptance. Actual useful speech, inverse chronology,
repeated replacements and the full original roadmap remain open.

## Historical result transport

The native client-delegation mode now has a source-prepared return path for work
that outlives a voice connection. This is not provider stored-session forking or
proof of semantic/physical continuity. The existing persistent native thread owns
identity, memory and work. A fresh native voice visit carries only the previous
native visit ID and a flat historical-work scan cursor, never a copied transcript
tree, another work submission, old audio or a new Responses reasoner.

The live return task alternates current work with one previous work origin. It
runs outside browser-control handling, at most once per500ms, only while the
authorized finite native visit is open. Discovery stays within the existing
512-record/32MiB journal limit and rotates through all eligible owner-matched
closed or explicitly reviewed disconnected visits; a large retained backlog therefore increases scan latency rather
than creating unbounded concurrent readers. No periodic/background attention is
installed. The existing native route/result/page limits remain unchanged, including
the source-compatible older-worker pages described below.

Before a historical result can return, its exact retained original/delegation,
native acknowledgment, current canonical revision and character offset are
rechecked. A flat origin claim records the destination visit/key before the
destination append intent. Trusted append acknowledgments remain in that
destination; subsequent replacements resolve the reference rather than repeat
the fragment. A partial two-file commit, missing destination, unknown write or
known stopped append stays held. No inference, old wire command, media or work
is automatically replayed. Claims are at most128 per origin inside the unchanged
256KiB record/32MiB journal bounds; capacity refuses before another append.

Historical returns use a new event ID with `delegation_id: null`, preserving the
old client delegation only in the local source association. OpenAI documents null
delegation commentary for application-provided context in its
[language/greeting guidance](https://developers.openai.com/api/docs/guides/live-prompting#language-and-pronunciation),
and coherent bounded commentary/thinking chunks in
[client delegation](https://developers.openai.com/api/docs/guides/live-delegation#client-delegation).
Using this unscoped context channel for an earlier native result is an application
integration choice; the documentation and synthetic ACKs do not prove actual
semantic incorporation, correct spoken continuation or hearing.

Historical return fragments now identify the original connection's UTC opening
date. The native voice brief treats their first-person wording and relative time
as belonging to that earlier encounter, follows the current topic, and never
turns a retained result into a claim of newly performed work. This addresses an
observed fresh-visit transcript that restated an earlier result as a current
action. It preserves the canonical text, cursor, result availability and exact
append/replay fences. An opening date supplies chronology, not authorization or
proof that a result is still applicable. Source qualification is not a verified
spoken correction; the next genuine trial must check that distinction.

Nine renewal-component tests cover three successive connections, exact long-result
cursors, restart/new admission, flat scan persistence, unknown append and partial
commit preservation, current-source and actor refusal. The mounted API journey
also closes the original native voice, introduces a late worker result and returns
it to a fresh connection without another original, ASR or native dispatch. These
checks use synthetic native/provider peers. Real first-use identity/memory/work,
speech/interruption, repeated physical renewal and semantic checkpoints remain
unfinished; this source extension has not been selected on a receiver.

### Coalesced native context during an active visit

The trusted public-native transcript receiver now feeds the existing semantic
producer during the active voice visit, rather than waiting only for delegation
or Close. After retained language reaches4096UTF8bytes or128delta events, the
existing foreground loop can schedule one owned sync, no more often than once
per10seconds. There is no idle sync, external timer or permanent listener. The
unchanged600second capture bound limits this cadence; complete before-delegation
and closing-tail synchronization remain supported.

Each sync retains exact ordered source ranges through the same native `sync`
operation and `prepare_continuation` contract. The native producer still owns its
existing16KiB preparation threshold,8KiB target and bounded semantic cadence.
These byte/event counters coalesce transport; they are not provider token usage
or a replacement for the existing64k/48k limits. No separate model, ASR, work
submission or guessed checkpoint is added. Trusted fragments arriving during a
sync keep their own counter watermark and journal references.

Slow metadata does not occupy browser/control handling. Close stops scheduling
new syncs and continues provider finalization. Setup, work preparation, result
reads and context syncs share one50second cleanup drain instead of consecutive
waits. The existing actor and voice-admission ownership remain held until actual
owned tasks and late native I/O settle, even after handler cleanup times out.
A failed or unconfirmed sync stops further attempts and keeps its projection
closing for explicit recovery; Close does not retry that source write. Independent
native work is never cancelled by this metadata lifecycle.

Synthetic mounted tests cover active retention before work/Close, slow sync with
responsive finalization, adapter failure and actor exclusion after cleanup expiry.
Source tests verify byte/event cadence, exact speaker ranges, late deltas and
unknown-receipt preservation. Actual native three-visit/source/startup-seed
qualification remains separate from real reasoning, speech and phone acceptance.
This section describes the candidate source; current receiving selection belongs
in the shared service record.

### Older canonical worker results

The native source reader now advertises `result_pages: "v1"` in owned input
traces and `foreground_trace_results: "v1"` in voice capabilities. Existing
`input trace ID` keeps its latest-eight-per-instruction bound. Each route adds
`results_cursor`; `input trace-results ID INSTRUCTION BEFORE` reads at most eight
older canonical deliveries for that same original and instruction. A negative
cursor or unrelated instruction refuses. `input trace-result ID delivery:UUID`
rechecks one exact association independently of the latest page. All three reads
reuse the existing owner/entry authorization, request links, canonical revisions,
freshness and target availability. They dispatch no work or recognition.

The public native return task reads at most one older instruction page per
foreground poll after checking current results. It retains at most five flat
instruction cursors in the original pipeline, without copying result text. A page
advances only after its eligible fragments are acknowledged; existing unknown
append, exact offset and historical forwarding fences still apply. A completed
scan remains complete until the latest-page cursor changes. Each older result is
rechecked by the exact association reader and its canonical revision before any
context append, including after connection replacement. Older native readers
without the advertised capability retain their existing latest-page behavior;
there is no fallback work submission or unbounded history scan.

This is source preparation, not receiving selection or proof of useful spoken
incorporation. Actual memory/hearing, repeated physical renewal and full original
roadmap acceptance remain open. Synthetic tests cover later-page return, exact
revision changes, foreign bindings, nonadvancing cursors, retained cursor reads
through a fresh journal reader, and no repeated native work.

#### Corrected results after an acknowledged partial

A long worker result may become noncurrent while its remaining text is waiting.
Before continuing that tail, the return task checks the existing owned trace or
its exact result lookup. An available matching source explicitly marked
`current=false` or `correction_pending=true` does not block discovery of the new
current result. The old acknowledged fragment, revision and continuation cursor
remain intact; no old context event or native work is replayed.

This applies only after every earlier context append is confirmed. An unknown
append still holds the return. Missing/unavailable source metadata, a foreign
binding or an unsupported exact lookup do not prove supersession. Every new
fragment still uses the ordinary fresh canonical revision/association checks.
Synthetic tests cover the live visit, paginated association, a fresh journal
reader after replacements, unknown injection and foreign/missing-source refusal.
They do not establish actual spoken incorporation or human hearing.

### Explicit replacement after a disconnected native visit

A known-created native voice whose local capture has ended can offer a manual
replacement even if the trusted `session.closed` event was lost. This follows
OpenAI's [failed-connection recovery guidance](https://developers.openai.com/api/docs/guides/live-conversations#recover-from-a-failed-connection).
The existing authenticated socket acquires the app's human voice lease before
offering review. No other app voice can be active. The offer contains only the
old visit ID and a revision of its journal plus retained provider sources.
The next explicit Reconnect action submits that review on a new admission;
it never retries automatically or requests microphone access while offering review.
A changed source, owner, binding, unknown creation POST, incomplete replacement
claim or current capture refuses before another call. Responses/stored-fork
behavior stays unchanged; this path is for the separately selected native mode.

Review records a flat old-to-new reference before admitting its destination.
An interrupted two-file commit stays held. The old record remains `created`,
with unconfirmed final usage; it is not forged into `closed`, deleted or exempted
from storage reservations. A later genuine provider finalization can still
record actual usage. Retired transports cannot be attached/recreated through
their old call receipt. Existing originals, ASR/work intents, canonical-source
checks and unknown append holds remain unchanged. Observed independent native
work may return through the existing flat late-result route without resubmission.
The unchanged record/source/total bounds still limit retained disconnected visits.

Synthetic journal, mounted authenticated socket, browser and native-result
journeys cover review before permission/POST, stale/foreign/unknown refusal,
partial admission, genuine later usage and once-only late results across another
replacement. They do not establish semantic history restoration, real repeated
speech, physical reconnect/hearing or settlement of an older provider bill.

### Prepared native semantic-context source adapter

The native `foreground_public_live_transcripts=v1` capability admits the optional
`live_transcript` provenance on existing context-sync sources. Input and output
fragments keep distinct `transcript_input`/`transcript_output` roles. They retain
the original text, speaker, provider event/session identity, exact event hash and
fractional provider timestamps, with `transcript_context_only` authority and an
explicit partial/interrupted disposition. They create no canonical human original,
ASR request, work admission or playback/hearing receipt. Their complete typed
envelope stays in the existing language field so older projection readers keep
its bytes instead of dropping an unknown document field. The existing native
source revisions,64KiB batch,2MiB document/64MiB aggregate and4096source bounds
include this evidence. A changed source refuses atomically; a late source changes
the reconnect revision without reopening work or authorizing a stale seed.

For ordinary subword deltas, compact `transcript_context` journal blocks preserve
the exact concatenated language and a flat span table: speaker, provider start/end
times, cumulative UTF8 text end, and exact source-record end offset. One immutable
journal range/revision/hash references original event IDs and individual hashes;
the raw source journal remains authoritative. Boundaries are storage chunks, not
inferred utterance ends. The actual71second trial contained146transcript deltas
for798UTF8 text bytes; copying a full session/event envelope per delta would cause
context pressure from bookkeeping. A matching synthetic146delta case retains all
spans in three blocks below16KiB. Block validation rejects UTF8 splits, omitted
text, reordered source offsets, mixed authority and changed immutable evidence.

`PublicLiveContextHistory` wraps the existing NativeHistory/NativeContext outbox
interface and public visit source journal. It supplies one bounded complete
source block per native sync and counts escaping/provenance within the language
budget. Before native retention, one constant batch intent freezes its byte range,
hash and source ID; only matching native receipts commit the source-offset cursor.
A lost receipt followed by new deltas reconciles the old block first, then admits
a distinct block. No second transcript database or copied archive is
created. Lost native source-retention receipts can reconcile the same immutable
IDs, as in the existing NativeContext contract; this is not replay permission for
uncertain work, ASR, provider commands or context appends. Canonical assistant
outboxes and other voice modes retain their previous path. Partial source-file
writes keep the cursor before the incomplete record and require review.

The source lifecycle now mounts this adapter for the separately selected native
backend. Admission requires the actual interpretation, context, resume and public
transcript capabilities plus callable Python adapters and the existing native
history. It registers the same semantic producer, catches up only explicit native
ancestors, and supplies a complete native resume as a developer startup message
before microphone permission or a paid creation. The existing600second clock
includes context preparation. A frozen source reference precedes native open;
changed or unknown opens remain held. Native preparation syncs current sources
before its one original work handoff and carries the exact dialogue/generation
reference. No transcription fragment becomes canonical human speech or new work.

Context calls retain the authenticated voice maintenance lease through an owned
late thread, with two concurrent calls and finite owner waits. Native closure
waits for preparation; an unsettled interpretation leaves that projection closing
for the next explicit owner rather than closing over its future original. This
does not settle provider usage, replay work or reopen an uncertain provider write.
Responses and other voice modes retain their existing lifecycle.

Source and synthetic qualification are not receiving acceptance. Native startup
seeds retain their complete existing24KiB bound and the entire creation request
must fit32KiB; no tail is clipped to make admission pass. The provider's separate
startup token limit still applies and needs actual semantic qualification. Real
memory/tool execution, repeated useful speech/renewal and physical hearing remain
open. Follow OpenAI's
[transcript provenance](https://developers.openai.com/api/docs/guides/live-migration#preserve-context-and-apply-corrections)
and [saved-context](https://developers.openai.com/api/docs/guides/live-delegation#keep-the-conversation-context-in-your-application)
guidance when qualifying the lifecycle.

### Shared canonical fragments after voice renewal

Several admitted originals can be covered by the same native answer. In a fresh
voice connection their old delegation IDs no longer need separate provider
responses. Repeating the same source/revision/offset once per old delegation
therefore duplicated historical context, as observed in retained real journals.
Current-connection delegations still receive their own scoped responses.

The historical return path now validates the requesting original and current
canonical association first, then reuses an exact existing acknowledged append.
It adds one bounded flat origin claim with `shared_delegation`, pointing directly
to the actual target visit and append key. It copies neither text nor an ACK,
creates no alias chain, sends no second event and dispatches no work. The original
append row remains unchanged. Each original retains its own ordered cursor;
missing/changed destination rows and unconfirmed matching appends stay held.
The existing128-claim/256KiB-record/32MiB-journal bounds still apply.

After such a shared claim is written, web rollback must retain a compatible
`openai_live_native_results.py` reader. The older reader refuses that association
rather than resolving it; do not clear claims or replay work to bypass refusal.
No real journal is migrated or deduplicated retroactively. Synthetic tests cover
shared results across multiple replacements/restart, long fragments, unknowns,
changed receipts, unrelated pending fragments, fresh native/worker association
and unchanged current-connection delegation replies. Transport evidence does not
establish semantic incorporation, memory lookup or human hearing.

### Encoded reply playback and avatar activity

Conversation's existing encoded-reply HTML media element can expose its decoded
audio through `captureStream` (or `mozCaptureStream`). That optional stream reuses
the existing outputless RMS worklet; the media element remains the only player.
Five transient jaw levels use the same quantization as live voice. No provider,
microphone, stored PCM, speech synthesis or new playback destination is added.

Pause, mute, ended, source replacement and the existing explicit player Stop or
capture hold retire the cosmetic stream/observer and clear the jaw. Late setup
and callbacks cannot publish to its successor. Observer setup retains the existing
five-second bound and600-second worklet ceiling. Each retired capture stream's
owned tracks stop; the original media element keeps its playback and cursor.
Unsupported browsers/native media proxies keep sound without the optional jaw
signal; observer failure cannot stop or retry speech. Actual encoded Chromium
sound/silence/pause/resume/mute/source replacement and delayed-setup fixtures
qualify that boundary, not physical hearing, Android proxy support or phonemes.


### Continuous public-native transport renewal

`openai_live.continuous_renewal = true` explicitly enables the native backend's
planned physical-transport replacement. It does not select that backend, change
voice/account/model, enable background capture or renew any existing call after
deployment. The default is false; Responses and old clients retain their finite
visit behavior. Each physical visit still admits 300–600 seconds and its own
PCM/source/storage bounds. A logical foreground capture keeps one microphone
permission and WebLock until Stop or a concrete failure/capacity refusal.

The browser requests graceful close 120 seconds before the physical deadline.
It keeps the WebRTC/data channel and trusted receiver alive while the predecessor
closes. Existing source seals/preparation settle before planned close; explicit
Stop takes precedence. `session.closed` confirms provider finalization only.
`successor_ready` is emitted separately, after owned native context closes,
in-flight context work settles and the old application lease is released.
Both current authorization and the exact frozen owner are rechecked. Native work
keeps its original ownership and is never replayed to prepare the successor.

The server records one same-process readiness token and claims the exact sole
successor before writing its admission. Lost receipts, partial admission writes,
service restart, changed binding, unconfirmed context/provider close, non-planned
hangup or a provider `content` closure do not authorize automatic replacement.
Original uncertain receipts and existing history/capacity bounds remain; there
is no retry, counter refill or fallback. A partial claim blocks fresh admissions
until its actual outcome is reconciled through supported owning recovery.

The microphone remains owned through the handover. Raw speech during graceful
close is retained as an interrupted prefix of the old visit, never replayed as
newly heard speech. Recorder/output transports are then replaced; preparing the
successor can leave an audible listening gap. This is not gapless duplex audio.
The browser waits at most 85 seconds for readiness, then pauses for review.
Stop, hidden-page teardown and binding changes prevent a late successor.

Source/fixture qualification is separate from receiving adoption and real audio.
A finite provider journey should use an explicitly synthetic microphone, at most
two physical calls and 660 seconds total, a corrected fact before the handover
and semantic readback afterward, followed by Stop. Retain both finalization and
original-audio receipts; never replay a completed call to repair its verifier.
Human hearing and phone/OS acceptance remain distinct.


Receiving qualification, 8 November 2026: source `a4fc9d8` (PR803, merge
`6ad0e7fc`) passed seven applicable CI checks, the mounted receiver API/lifecycle
fixtures on all three original receivers, and actual receiving asset/health/auth
checks. The three receivers adopted the compatible implementation; only the
requesting CompAII receiver enables continuous renewal. Other pairs keep their
own finite policy. Keep the803 renewal-claim reader/API on rollback; disabling
this feature does not erase old claims, originals or uncertain outcomes.

One finite public-provider journey used the existing configured GPT-Live project
and Cedar, one synthetic microphone permission, the actual native owning writer
and a synthetic Core harness. The first call confirmed476 usage seconds, the
successor15; these are separate cumulative provider totals, not latency or an
invoice. The successor recalled the corrected fictional project Faro/nine after
the planned handover. Both provider closures were confirmed, Stop left two calls
with no third opening, and17 originals/15,768,490 bytes matched their retained
hashes. Both decoded output streams had nonzero PCM peaks. No physical microphone,
human hearing, native reasoning/compaction or mobile-background proof follows.

The raw verifier exited unsuccessfully: it queried `getStats()` on the already
closed predecessor and treated unavailable byte statistics as zero audio. Its
failed result remains retained. The existing on-track decoded PCM observations,
trusted output transcripts and finalization/original receipts established the
outcome without another provider call. Read transport statistics before retiring
a peer; missing post-close statistics are unavailable, not zero delivery. Two
pre-provider fixture errors (wrong executable, missing explicit synthetic voice
metadata) were corrected before any paid creation; their original failures stay.
One peer's daemon-reload client timed out after its manager loaded the new unit.
Recovery observed that completed reload and performed only the unattempted start;
a later missing verifier variable was repaired by observation alone. No stop,
reload, selector, native input or provider action was replayed.
