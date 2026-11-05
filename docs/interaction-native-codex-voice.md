# Independently selectable native Codex voice

This opt-in Avatar engine uses the existing native Codex App Server and its
ChatGPT sign-in. It is separate from the Qwen/Gemini engine. Application tests
are not production or physical-hearing acceptance.

## Initial receiving activation —5 November2026

CompAII ITACA first exposed the separately selectable mode in UI `0976269baac7`,
web source `a96d1910`, merged PR632. Its native receiving composition `d35949a5`
retains selected heartbeat, Matrix, held-original and workspace behavior. Actual
idle-scoped delivery preserved44session bindings, four active successor collectors
and their goal definitions, the existing Core and native configuration. Only the
owner's `codex_voice` configuration section was added; Qwen/Gemini and ordinary
conversation defaults remain unchanged. Current-owner capability, public shell,
exact native/browser assets and local health passed. No provider call, voice
session or microphone capture accompanied activation.

Choose **OpenAI · Codex voice** before entering Avatar. Engine selection remains
frozen during a visit. The existing mode stays available; no automatic fallback.
This is receiving delivery, not sustained phone/hearing acceptance or complete
long-term continuity. Keep those gaps explicit. Roll back the web/configuration
at voice idle while retaining the compatible native reader and current journals.

## Configuration

Keep existing voice defaults. Configure this only on a receiver whose native
owner supports `input voice native capabilities`, `input voice native current`
and `input voice native attach` version v1:

```toml
[codex_voice]
enabled = true
session_seconds = 600
voice = "cove"
identity_file = "/absolute/private/owner-voice-brief.txt"
```

The owner-selected UTF-8 brief uses existing private-file checks, is nonempty
and at most8192bytes. Identify the being, its voice-facing role and native
capabilities; request brief natural speech. Avoid copying full history or wording
that makes internal procedures sound like phrases to recite. Its SHA256 is retained
per visit. A native developer initial item preserves the native prompt, model,
tools and automatic handoffs. No browser prompt override or credential extraction.

Use [the versioned role template](templates/native-avatar-voice-brief.txt) as a
starting point for the owner-selected brief. Render only its being, human and
short identity fields into the existing private file; never load another being's
identity or bulk history. Version3 separates tool decisions, waiting/evidence,
speech and continuity. A request needing a real read/action must invoke the
provided native handoff in the same turn; an acknowledgement is not execution.
An already verified result can be recalled without repeating its tools.

This follows the tool-eagerness and preamble principles in the official
[voice prompting guide](https://developers.openai.com/api/docs/guides/voice-prompting).
That guide describes public Realtime models; it does not establish the identity
or settings of Codex's native frontend. This adapter retains the inspected native
contract and prompt rather than sending a public GA session schema to it.

Native V3 automatic backing responses use `codexResponseHandoffMode=commentary`
and `delegationAckFiller=false`, while `clientManagedHandoffs=false` preserves
native execution ownership. The selected Core must support these start fields;
another receiver's capability label alone does not establish that compatibility.
This is a native channel selection, not client-owned delegation, a manual turn
loop, a replacement native prompt or an ordinary model/default change.

In one bounded actual application case, version3 plus these native options read
a selected historical test source and spoke the correct new code only after
source verification. After confirmed closure and a second native voice generation,
it recalled that code without another source command. Both generations retained
their original recordings (1,611,182bytes total), complete transcripts and useful
remote audio (peaks0.269/0.255; positive RTP audio energy). This establishes that
case, not universal factual waiting, long sustained renewal, arbitrary tools/results,
independent output ASR or physical phone/hearing. The separate compaction result
below qualifies one further replacement, not sustained continuity.

Negative controls remain: acknowledgement filler alone permitted early invented
facts; an earlier mounted role merely promised a lookup without invoking it.
Standalone analysis-only media controls did not qualify useful audio; a tiny
nonzero peak with zero RTP energy is insufficient. Native V3 `appendText` mapped
to context append, not an acoustic question/response trigger in the actual test.
Do not replay accepted questions to repair a verifier or generalize those
observations into a provider outage. The successful case used the mounted
application's actual media, original-retention and reconnection paths.

The browser defaults to the existing provider. Explicitly choose
`OpenAI · Codex voice` before entering Avatar. Freeze engine and enrolled
integrating thread per visit. Disable switching during capture. Failure or loss
of capability never silently falls back or changes selection. Ordinary
conversation work and the Qwen/Gemini configuration remain intact.

The shared application lease bounds both engines' active capacity. Native start
can replace existing voice; native stop is thread-scoped without a generation
condition. The application lease does not exclude an independent CLI client.
Resolve this ownership limitation before activation; do not start another native
owner or change ordinary model defaults to qualify it.

## Media and accepted work

An authenticated control WebSocket exchanges one SDP offer and answer. Media
flows directly through WebRTC, with the native-required `oai-events` data channel
negotiated before the offer. Core owns handoffs; the browser sends no commands on
that channel. The application sends no manual PCM, text turn or
response request to the provider. Shared auth, Origin, fresh action token and
owner binding are checked before native start and throughout the visit.

Native handoffs create work in the persistent thread. Exact observed turns
attach through the existing durable collector. After observed voice closure,
one bounded current-turn reconciliation attaches any already accepted writer.
Tools/results continue independently of the browser. A stop acknowledgement alone
is not closure. Missing closure or failed collection retains review state;
cleanup never cancels accepted work or replays its original request.

Duration stays300–600seconds. The actual native fixture exposed a reconnect
continuity gap: it accepted a new control word, then answered with the old word
after reconnect, even though the final question was transcribed correctly.
Native working-thread startup context alone did not preserve inline voice turns.

Restore recent completed voice transcripts through the native V3 `initialItems`
contract, alongside native startup context. Keep their actual user/assistant roles
and order; a bounded developer provenance item identifies them as history, not
new work. No `appendText`, `turn/start`, repeated tool request or app-owned
compaction worker is used. The window contains at most32complete source items
and18432UTF-8 bytes including source references. All initial text, including the
identity brief and provenance, is bounded to28672UTF-8 bytes. Each retained visit
stores source IDs, SHA256 values, digest and omission flag, never a copy of a
previous startup envelope. Empty reconnects cannot recursively grow context.
Older omitted history remains retained, but this window does not claim complete
long-term recall. ASR sources are not proof of the precise words a person heard.

A separate durable transcript-completeness marker is committed only after
observed native closure and successful event drain, before releasing voice
ownership to a successor. Backend collector status remains separate. Failed
source writes, uncertain closure or interrupted cleanup block automatic restore
with an explicit reconciliation message. Before refusing a new visit, the app
can reconcile from the exact enrolled native rollout: current owner checks before
and after, nofollow/nonblocking regular-file open, inode/header identity, and an
unchanged indexed path. A bounded4MiB tail must contain that generation's complete
start and closure plus every source. Existing source words cannot be rewritten;
missing items are inserted in canonical order. A source digest records recovery.
Absent, changed or out-of-window closure remains an explicit review requirement.
Older visits without the marker use this same path; their display state is not
proof of completeness. Short history/original commits serialize with a two-second
lock-acquisition bound; contention never repeats a protected body/provider call. Cancelling
before `voice.start` is attempted records an empty, confirmed-not-started outcome
and permits another visit. Original bytes and accepted backend work are preserved.
Actual canonical recovery found six prior closed generations/13transcripts.
One new same-thread spoken question returned the corrected word with nonzero
remote audio; its original upload exposed a concurrent metadata-lock rejection.
The bounded lock fix was followed by another actual visit: both original chunks
were retained, but there was no useful output before the finite observation ended,
and the user transcript completed during close. Keep both results; repeated useful
audio/return acceptance remains open. The terminal fixtures must not be replayed.
Unit and synthetic-browser success do not establish sustained semantic acceptance.

## Receiving composition qualification —5 November2026

Later actual synthetic WebRTC connections recalled the corrected word, and a
distinct clarification returned the prior useful capability result through one
completed native handoff with no repeated tool. A misheard earlier noun did not
qualify that result question. Preserve the silent observation above as unresolved.

The receiving-native candidate `d35949a5` adds only the two owner-control source
files to selected `81538275`; its existing heartbeat, Matrix, held originals and
workflows remain present. Locked all-feature build, formatting, text checks
(569passed/1ignored), text clippy and exact owner IPC/SQLite collection passed.
Focused review found no material defect. The exact composed executable and app
then received a new spoken question, returned the corrected word with nonzero
remote audio, closed and retained its458796byte microphone original. No new
backend work or tool call accompanied that clarification. The first composition
probe had closed on an answer to a partial question; it did not establish failed
recall. Subsequent qualification waited for the requested semantic answer.

These test-owned observations use synthetic media and existing native login.
The prepared candidate was subsequently receiving-selected through the existing
idle-scoped route, as recorded above. The prior production633 web/native selection
remains the software rollback; current journals, held originals, enrolled threads
and work are preserved rather than restored.
Phone hearing, sustained use and complete long-term recall remain unqualified.

## Native tail persistence and compaction observation —5 November2026

PR637 is receiving-selected over native632 in the same UI0976269baac7; only the
Python native-start field and owner voice briefv2 changed. Existing native/Core,
configuration, providers/defaults, work and storage/diagnostic bounds remain.
One deployment helper failed before selecting code or identity; it restored the
previous web. A separately guarded continuation verified that unchanged frontier
and completed selection. Its terminal receipt is retained; neither helper is a
retry surface for human input.


The installed Core's own generated experimental schema advertises
`flushTranscriptTailOnSessionEnd`. Native start now enables this supported path.
An actual synthetic voice visit introduced a new fact, repeated it in audio,
closed and retained its original. The native backing history then contained the
source-marked `transcript_tail_flush` fragment before closure, with no new backend
inference or tool call. Native persistence supplements the application's recent
role-bearing source window; it does not replace it.

One distinct test then invoked supported native compaction on that idle test
thread and waited for completion. A new voice question, with application history
omitted, returned the old value despite correct transcription. Preserve that
negative observation; do not repeat compaction to make the verifier pass. The
failed visit closed with its originals retained. A later read of the committed
compaction replacement history still found the new fact. Thus the compaction
record did not discard it; that visit did not qualify automatic retrieval into voice.
Native startup alone is not
qualified as the long-term voice memory bridge. Inspected source excludes
contextual user fragments from its recent-turn section, advertises that memory
summaries are excluded, and bounds the rendered terminal transcript tail to4KiB.
These source constraints identify gaps to address; they do not by themselves
prove which stage lost the new fact in the actual test. A distinct subsequent
question explicitly asking to review the conversation used a completed native
handoff and returned the new value in audio, with no app history initialItems and
no repeated tools. Its original was retained. The voice brief now describes its
partial memory and asks it to consult the backing conversation rather than guess
when reviewing earlier conversation. This qualifies that retrieval case, not
complete long-term coverage of all inline speech. No existing diagnostic,
visit or storage bound was increased. Do not remove the flat application restore
window or claim complete long-term continuity based on a compaction ACK.

## Qualified code recall after native compaction —5 November2026

A distinct subsequent case used the selected version3 owner brief and native
commentary settings on the existing idle synthetic test thread. It invoked the
supported [`thread/compact/start`](https://learn.chatgpt.com/docs/app-server#api-overview)
once, waited for the completed native turn and inspected the newly committed
`compacted` record. Its replacement history retained the previously verified
code. A fresh mounted voice visit then answered the code-recall question correctly
without repeating the source command or dynamic tools. Recent application
user/assistant restore items were omitted; canonical native context and source
location hints remained available. The complete transcript, closed visit and
779,650-byte original receipt were retained.

The sole assistant utterance named the correct code and remote audio peak was
0.293. The question transcription changed "ya" to "de A", preserving the code-recall
intent. This is a bounded digital observation with no independent output ASR or
physical hearing; RTP energy was not sampled during the answer in this case.
The earlier failed compaction/correction case above remains negative evidence.

The backing model's last pre-compaction request reported68,233 input tokens;
the first subsequent request reported37,449. These are different requests, not
a controlled cost comparison. Cached input also changed67,456 to11,648, so the
smaller active input does not establish a cheaper first request. A compaction
checkpoint's zero input counter is not evidence that compaction was free. These
numbers concern the test backing model, not the realtime frontend's context
capacity. Canonical journals remain append-only: model compaction does not free
archive storage. Repeated renewal, corrections/questions and late result delivery
still need their own evidence; no production context, visit or storage bound
changed.

## Late tool result across native voice replacement —5 November2026

A bounded subsequent application case made one new actual read-only capabilities
call on the existing synthetic native thread. The fixture held its one response,
closed the first voice visit with its transcript and original confirmed, started
a new native voice generation and released that exact response once. A fixture-only
marker appended to the authentic tool response distinguished result delivery
from guessing or replay; it was not a production capability or human instruction.
The native task completed. A distinct spoken question about the pending result
then received the correct marker, spoken digit by digit, without a second tool
call. Remote peak0.347 and inbound RTP energy0.217 establish useful digital
signal for that answer. Both visits closed with complete transcripts and original
receipts, including the second visit's two ordered recording chunks.

No unsolicited answer arrived during the12-second observation before the status
question. The trace contained a standalone `session.context.appended` event;
the installed Core routes standalone backing output through the selected
commentary channel when the replacement generation has no active handoff.
This is consistent with context availability without a speech trigger, not proof
that every delayed result will remain silent or that a longer timeout fixes it.
Native result survival and status-request retrieval are qualified in this case;
spontaneous late-result presentation remains OPEN. Reuse the supported native
speech/attention primitives for that gap rather than replaying a user request,
repeating the tool or adopting a client-owned manual delegation loop.

The original browser verifier expired because it accepted numerals/cardinal
Spanish but not digit-by-digit Spanish. Its failed report is preserved. Semantic
adjudication used the retained answer, native final message, audio measurements
and committed original/closure receipts; no provider input was repeated to repair
the verifier. There is no independent output ASR or physical hearing acceptance.

## Source-linked predecessor result offers

The native application carries exact pending work references across voice visits
on the same authenticated entry/thread. It does not infer that a task was caused
by nearby speech. At reconnect it uses the supported
[`thread/turns/list` and `thread/items/list`](https://learn.chatgpt.com/docs/app-server#api-overview)
reads to select a completed task and its own final-answer item, restricted to the
exact turn. Commentary, another turn's message and task acceptance do not qualify
as a completed result. Native automatic handoff ownership remains unchanged.

The browser sends a transport-only `ready` receipt after WebRTC connects. A
predecessor completion can then be presented through native `appendSpeech`,
without another acoustic question, backend turn, tool invocation or client-managed
delegation. The notice identifies the exact turn and full-text revision. Its
meaning and excerpt fit in480 UTF-8 bytes, leaving room for the native prefix:
the inspected V3 writer splits standalone context at500bytes. For a partial
excerpt it asks for an availability offer rather than guessed missing details.
This is assistant presentation context, never a fabricated human utterance.

Before submission, the existing visit journal retains the task/item/revision and
presentation intent. An ACK means native acceptance, not semantic delivery or
hearing. Missing ACKs are not automatically replayed on another connection. The
journal holds source references rather than another copy of task output. At most
32pending tasks/offers/outcomes fit in a visit under the existing512visit/32MiB
history bounds. Native failed/interrupted outcomes stop accumulating as pending;
they do not become successful-result offers or delete the original task. A task
outside the bounded native read window remains unresolved, not guessed.

An optional result-read failure keeps useful voice running and is not polled
again during that visit. An unconfirmed speech submission keeps its retained
intent without replay. Binding/grant checks remain mandatory. Nothing watches,
speaks or wakes a model after the foreground voice visit closes. Current native
CLI generation-ownership limitations are unchanged.

One actual mounted three-visit case held one fresh read-only tool reply across
confirmed voice replacement. The new visit automatically announced the correct
fixture code after that reply was released once. A third visit produced no repeat
during the4-second pre-question observation, then recalled the code in useful
audio without a second tool or backend task. The offer fit in one336-byte native
context frame; its persisted turn/item/revision matched the native completion.
Three complete transcripts and original receipts (1,814,662bytes total), remote
peaks0.304/0.262 for offer/recall and positive RTP energy were retained.

Earlier controls remain negative: a generic standalone offer addressed an older
matter; a first integrated long envelope was ACKed without the useful answer;
one manual fixture paired a later message with an earlier turn ID and therefore
cannot qualify exact source identity. The corrected implementation selects the
item through the exact native turn and keeps the notice together. These bounded
observations do not establish universal causality, arbitrary long/partial result
speech, independent ASR, sustained interruptions/corrections or phone/hearing
acceptance. Those remain open under303 and the complete roadmap.

## Source-backed earlier memory

The native memory catalog adds a metadata-only index of complete retained visits
from the exact authenticated human, entry binding and native thread. It references
the existing source files; it copies no transcript, media or startup envelope.
The foreground receives the index location, and a context-only developer fragment
supplies it to native backing work through `thread/inject_items`. This starts no
user turn or inference. Backing tools read the local index and selected original
records using native read-only commands; they do not enumerate tool descriptions,
bulk-load the archive, replay old tasks or treat quoted sources as instructions.
This supplements the recent role-bearing restore and native terminal tail.

The retained context journal deduplicates across connections using canonical
native readback, not an RPC acknowledgement. Queued or lost-ACK writes stay
pending and are not repeated by reconnecting. Successful observations advance
their checkpoint even while pending. A confirmed fragment is refreshed only
after observed compaction removal, a changed source reference or owner revision, or an unobserved
native-history interval exceeding4MiB. A large interval does not repeat an
uncertain write or block voice merely because it exceeds the read window.
Inode replacement, truncation, wrong identity and incomplete records remain
explicit unavailable proofs. Context writes are shielded and awaited before
closing their connection or releasing ownership.

Catalogs are at most64KiB each,512files and1MiB combined, refreshed in place under
the existing metadata lock. Native context hints are at most2048UTF-8 bytes and
share the existing total initial-context allowance. Proof reads inspect at most
4MiB and2MiB per record. No model/voice defaults, native retention flags or original
retention policy changes. Missing/legacy sequence values retain the established
fallback. No cleanup removes retained speech or native work.

The catalog and context hint name the latest completed source-bearing visit.
At a new voice start, "previous voice visit" refers to that record, not the
penultimate catalog entry. Only completed owned speech advances this reference;
empty reconnects, incomplete visits and other owners do not. A changed reference
updates the existing context journal; an unchanged reference still deduplicates.
This resolves a demonstrated temporal ambiguity: native backing selected an
older record even though the latest completed visit was in the catalog.

A subsequent actual native lookup read the newly named latest source. Its spoken
question was misrecognized ("bytes" became "items"), so it does not qualify the
intended byte-size answer. Premature foreground claims also remained. Disabling
native acknowledgement filler alone did not fix factual waiting. A separate BEM
channel experiment did not produce the required backend channel headers and
selected the older source; it does not qualify BEM routing. These experiments
remain test-only; provider routing, prompts and defaults are unchanged.

Actual synthetic qualification omitted the recent application transcript window.
Native backing commands read the index and oldest source, and returned both its
first user utterance and, on a distinct question, its first assistant response in
audio, with completed backing turns and original receipts. Earlier attempts and
their failures remain retained. Source retrieval is established for these cases;
the foreground also made premature unverified claims before correcting itself
with the source result, even after an explicit wait instruction. That behavior is
an open interaction defect, not qualified factual waiting or full long-term
continuity. Phone/hearing, repeated physical renewal and useful latency remain
separate unfinished acceptance. Do not infer completion from catalog readback.

## Original recovery and bounds

Capture starts before enabling the WebRTC microphone track. Raw microphone WAV
chunks are stored locally first, then uploaded to a capture-only endpoint.
The separate `codex_voice` recovery key shares the existing combined20MiB and
128record browser budget with ordinary capture, enforced transactionally.
Chunks are normally30seconds; server limits are32chunks,120seconds per chunk,
and600seconds cumulatively per visit. Two uploads can be admitted concurrently,
with30second and3,840,044byte streaming limits each. Metadata limits are512visits,
32MiB overall,64KiB and256transcripts per visit. Existing protected-original and
selected-archive bounds are unchanged. No automatic original retirement.

`Retry saving` verifies and saves the same visit/ordinal/bytes. It never performs
ASR, submits ordinary input, opens voice or repeats a handoff. `Save audio`
exports the local copy. `Discard local copy` removes only that browser copy and
does not cancel server work. Failed persistence retains a local recovery action.
History reads return at most8visits per page, with a cursor scoped to the current
human and conversation binding. **Earlier voice conversation** reads older retained
visits through that same store; loading history never starts voice, ASR or native
work. Sequence ordering keeps older pages stable as new visits arrive. A failed
read exposes retry at the same cursor. A view reset or changed binding rejects
late responses, and older-page insertion preserves the reading position without
consuming a click as header-scroll intent. All existing512visit/32MiB bounds and
original-retention rules remain unchanged. Recovery reads/uploads use current
shared auth and binding even while work is held; they cannot start/attach work.

## Qualification and rollback

Run native API, transport, history, collector IO, browser voice and microphone
suites. `QUALIFICATION_CODEX=1` selects the native journey in
`tests/session_workspace_browser.js`; RTC/owner responses are synthetic. Inspect
narrow and desktop screenshots and browser errors. Keep the ordinary session
journey as regression. The [practice comparison](interaction-gpt-live-practices.md)
distinguishes retained actual primitive evidence from application acceptance.

Before receiving activation qualify the exact app/native pair, native tools and
questions after browser closure, same-thread reconnect, original receipts and
actual identity uptake. Record deployed source/native hashes separately from
phone/hearing observations. Do not request a human test of locally prepared code.

To disable future activation remove `enabled = true` through the existing
configuration route at voice idle. Preserve metadata, originals, input journals,
active collectors and native work. Keep the compatible native reader on web
rollback; do not restore a database, replay media or retire history.


## Sustained corrections and microphone deadline

The5November receiving-qualified644 source was exercised on the existing actual
native test thread for540.16seconds, followed by one canonical compaction and two
explicit new microphone visits. Eight spoken questions preserved two corrections
(Aurora/4, then Aurora/5, then Brisa/5), identified CompAII and Avatar correctly,
and recalled the final facts after both replacements. All three visits closed
with complete transcript barriers;22 original recording receipts total19071946bytes.
Three decoded16kHz mono output masters retain540.16,24.917375 and10.069375seconds.
Independent configured Whisper ASR on two selected output clips recognized
“Aurora a las5” after compaction and “Brisa a la5” after the final replacement.
These are machine transcripts, not physical hearing acceptance.

This case uses ordinary app context restoration. It does not isolate backend-only
recall, arbitrary long tasks, simultaneous handoffs and speech, noise or phone
behavior. A broad compaction substring flag is not factual proof; exact source
item IDs and output indexes resolve visit attribution where the fixture's question
visit field precedes the first caption. The retained adjudication records those
limits without replaying the terminal case.

A separate deterministic client regression reproduced a capture clock mismatch:
the recorder budget started before SDP, while planned closure was scheduled
after SDP. With7seconds of negotiation, the recorder could expire before the
ordered finish/flush path. Schedule planned closure when capture starts,2seconds
before its unchanged hard limit, allowing the existing1second finish-ACK window.
The regression checks confirmed flush and original retention without a manufactured
unconfirmed tail. This repairs the native client deadline; it does not establish
the cause of historical Qwen phone failures. The600second complete microphone
visit budget remains unchanged; this is not automatic microphone renewal.
