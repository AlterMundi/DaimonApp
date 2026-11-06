# GPT-Live workflow and practice comparison — 4 November 2026

Human-selected direction: adapt DaimonApp to the best evidenced conversational
workflow, rather than forcing GPT-Live through the existing Qwen/Gemini adapter.
This records the design, bounded native qualification and prepared application
integration; it does not declare production adoption. Diagnostic limits remain unchanged.
The [roadmap](interaction-roadmap.md#current-refinement-toward-an-approachable-avatar--4-november-2026)
owns implementation and family-pilot acceptance; this note records the rationale.

## Selected next step —5November2026

Nicolas2a453b61 explicitly moves the provider comparison forward now, closing the
Qwen iteration without claiming its sustained phone/hearing acceptance. Preserve
those pending checks in the roadmap/issues; do not prolong Qwen as a prerequisite.

Reuse the existing Codex/ChatGPT WebRTC investigation before requesting separate
credentials. The retained [18October actual comparison](https://github.com/AlterMundi/DaimonApp/issues/118#issuecomment-6243154764)
connected through native login and independently transcribed a spoken correction.
Today's loaded App Server read reports ChatGPT/Pro; no current voice session was
opened by that metadata check. CLI feature selection and the experimental native
protocol are not current account entitlement. No token was exported or treated as
an API key, and no active native conversation was changed.

Current [official WebRTC guidance](https://developers.openai.com/api/docs/guides/voice-webrtc)
continues to require project access for public GPT-Live applications. The native
Codex route is separate. Source inspection and the retained comparison agree that
`clientManagedHandoffs` controls response forwarding, not admission of backing
work. Evaluate native handoff ownership directly: it can use the intended persistent
Codex backend. That flag alone does not prove how work is admitted, persisted or
charged; this is a measurement requirement, not a reason to reject native handoffs.
The [App Server interface](https://developers.openai.com/codex/app-server)
is the supported rich-client boundary, with explicit experimental opt-in where
needed. Current receiving access/bridge qualification is the next concrete step.

## Architecture comparison reopened —Nicolas1eb74b0e,5November2026

Nicolas6ea37cd3 subsequently requires an additive implementation: keep the
existing Qwen/Gemini route operational and make native OpenAI a separate mode
that the person can select. Comparison does not authorize replacing defaults or
removing the current provider machinery. Freeze the chosen engine and source
binding for a voice visit. Switching ends only that visit's media/control path,
preserves originals and accepted backend work, and requires an explicit new
activation. A failure must not silently switch providers. Back-port a better
OpenAI workflow to the others only after the comparison supports doing so.

Our present foreground/integrator separation is not a superiority claim or a
requirement to recreate that implementation. All current reasoning uses Codex;
first evaluate OpenAI's native voice/handoff architecture on a persistent Codex
thread. A native backend handoff may be exactly the desired operation, rather
than an unwanted second agent. Preserve real task ownership, original history,
identity, correction semantics and visible results; their implementation can move
to native mechanisms when those provide the better experience.

Compare three concrete candidates before selecting the bridge:

| Candidate | Starting point | What must be demonstrated |
| --- | --- | --- |
| Native Codex WebRTC voice | Existing native login, persistent Codex thread, provider-owned voice handoffs and streamed backend returns | Same CompAII/integrating ownership; explicit behavior with active work; recoverable history/originals, questions, tools/artifacts, interruption and reconnect; observed native turns/cost rather than treating all backend work as a defect |
| Public GPT-Live with Responses delegation | The official recommended starting point when managed requests and supported backend tools fit | Actual project access; identity/history and existing work continuity; available local/native capabilities, result presentation and total cost |
| Public GPT-Live with client delegation | Our application supplies context and backend execution | Use only for demonstrated requirements the other routes do not cover; do not choose it merely to preserve our existing custom machinery |

Current [official delegation guidance](https://developers.openai.com/api/docs/guides/live-delegation)
recommends starting with Responses delegation for managed requests, and choosing
client delegation for custom workflows or result review. Both retain application
responsibility for permissions and business/task records. The earlier unconditional
client-delegation selection above was superseded by this human correction.
Backend model selection remains independent of the spoken voice model.
[Official overview](https://developers.openai.com/api/docs/guides/live).

Prefer the documented WebRTC media/data-channel architecture for the browser,
with server-owned credentials and a sideband for backend event handling and
steering where needed. Compare it with a primary WebSocket only for a concrete
requirement. Do not retain our server-PCM transport merely because it exists.
Retain durable input/result ownership and recoverability as product requirements,
while redesigning their transport-specific implementation where necessary.

## Decisions from inspected sources

### Durable public creation and trusted sideband —6November2026

`LiveCreations` now supplies the creation journal that the earlier transport
required. It binds the authenticated service's frozen human/entry/thread snapshot
and exact offer/session-spec digest to one app UUID. Intent is fsynced before the
POST. An identical retry, including from a new process, only reads the retained
answer; changed offers, specifications or owners cannot reuse the record. Process
loss, lost response or failed receipt commit remains uncertain and cannot start
another call under a different ID for that human. A definitive rejection remains
distinct. Filesystem locks cover only local commits, never provider network I/O.

The optional mounted route now freshly authorizes/rechecks the current owner
and acquires the existing cross-mode voice lease before microphone permission.
Its one admission freezes the600second/PCM budget through negotiation and
capture; creation or a browser retry cannot reset it. Public project access
remains separate from Codex login. No receiving account/default change is
selected by this source integration.

The journal allows at most512records/32MiB and two unsettled public creations;
records are at most256KiB. Uncertain/active attempts reserve full receipt capacity
before any POST, with atomic-write headroom. Interrupted write fragments count
toward capacity. At the limit, refuse new calls before billing; never evict
uncertain receipts, original media or work. Retain confirmed receipts until their
owning lifecycle supports verified retirement; no automatic cleanup is installed.
SDP answers stay in owner-only local records, not public diagnostics or model
context. Request instructions/offers are identified by digest, not copied into
every receipt.

The [official sideband route](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)
attaches to the exact retained session ID, escaped as one URL component, using
the separately configured project key. It creates no new session and sends no
`session.start`. One bounded reader exposes provider events as source data;
the application still owns transcript persistence, tools and each delegation.
Reflected audio is not automatically stored or mistaken for microphone delivery
or human hearing. Events/commands are bounded to1MiB; connection establishment
has a5second bound and socket operations a shared0.5second timeout, avoiding
competing reader/writer timeout changes. A failed command write is unconfirmed,
not automatically retried; reading can continue to observe its eventual outcome.
This guard is per connection, not a durable command/delegation ledger.

Detaching only closes this control socket; it does not send `session.close` or
cancel accepted work. The [provider close contract](https://developers.openai.com/api/docs/guides/live-conversations#usage-and-graceful-close)
requires needed Responses work/results/continuations to finish before close,
because closing cancels queued Responses. The mounted integration enforces
that sequencing for observed managed Responses and refuses close while a known
function result or client continuation is outstanding. It does not execute those
functions, infer their completion or cancel application-owned work.
Only a trusted server-side `session.closed` for the retained opaque ID records
voice finalization here. Missing voice usage stays unconfirmed separately from
known closure; cumulative snapshots are not summed. Keep the provider event ID;
a later matching final observation can resolve missing usage without losing the
original closure source or downgrading known usage. Neither closure nor voice
usage marks native tasks, questions or backend token accounting complete.

Qualification:24synthetic HTTP, filesystem, subprocess and socket tests include
new-process exact receipt readback, competing writers, pre-POST process loss,
lost response, receipt-write failure, changed owners/requests, capacity, exact
sideband attachment, terminal session matching, usage uncertainty and detach
without closing work.35unchanged native-history tests pass on lockedPython3.11.
These are component boundaries, not actual public access, provider behavior,
authenticated browser recovery, media continuity or family-pilot acceptance.

### Mounted public comparison —6November2026

The default-off `openai_live` configuration mounts authenticated WebRTC admission,
trusted sideband, visit status/source pages and exact-original retention. The
browser exposes **OpenAI · GPT-Live comparison** only with the capability enabled,
inside **Under the hood**. Qwen/current voice and OpenAI · Codex voice remain
separate choices; capture freezes the choice and never silently falls back.
See [configuration and operating limits](interaction-public-gpt-live.md).

The browser installs the data channel before its offer, waits for ICE gathering,
and waits for the matching `session.started` plus a connected peer before showing
Listening. The server attaches its trusted event reader before returning the SDP
answer. Transcript fragments retain exact spacing/order; visible groups are
presentation only, not inferred utterance boundaries or dispatched requests.
One-second PCM fragments and sealed originals reuse the existing20MiB/128-record
browser store; engine tags isolate recovery without adding another quota.

Trusted meaningful events are fsynced before forwarding, bounded to2MiB/8192events
per visit inside the existing32MiB aggregate journal. Admission reserves source
headroom. Paginated source reads expose64events/64KiB at an exact file revision;
no source log is automatically copied into a model prompt. Repeated cumulative
usage replaces its previous snapshot. Graceful close stops capture, waits up to
30seconds for known managed work, sends one durable close command and records
only trusted finalization. A disconnected browser detaches control and preserves
uncertain work; shielded bounded cleanup releases its media lease even under
ASGI cancellation. Uncertain creation/finalization prevents another billed visit.

Synthetic qualification includes the real mounted app/Companion authorization,
streamed original upload/revocation, browser lifecycle races and shipped Chromium
shells at desktop/mobile sizes with synthetic audio. The ordinary native Codex
browser journey also passes. These checks make no provider request and establish
neither public account access nor hearing/task quality. The owner-bound transcript viewer now restores existing source pages without
voice activation; failed reads retain cursor/dedupe and require an explicit retry.
Semantic checkpoint/renewal/reconnect, integrating memory/work/tools,
artifacts/questions and family-pilot acceptance remain unfinished. Do not present
this isolated Responses comparison as the full CompAII conversation.

### Provider-stored continuation option —6November2026

The public comparison now has an owner-selected stored-fork path, default off and
requiring explicit permitted project storage. It follows OpenAI's WebRTC fork
workflow rather than reconstructing a nested startup prompt: one new SDP offer,
one trusted closed parent, a flat source/configuration reference and a new child
ID for media/control. Known pending/client requirements or changed policies block
admission before the microphone. The existing fresh-call digest contract remains
compatible; an uncertain fork never retries as a fresh session.

Component25/mounted23 synthetic tests cover the encoded source route, new child
ID, one root plus repeated continuations, wall-clock reversal, changed/nonstored
parents, pending work, missing responses, cross-process exact readback and known-child recovery after
the closed parent becomes unavailable.
These prove protocol/journal construction, not actual project storage, semantic
recall, backend/tool inheritance, useful speech or hearing across forks. The
[current contract](interaction-public-gpt-live.md#optional-provider-stored-continuation)
retains those gaps and OpenAI's storage/data-policy prerequisites. Ordinary
provider defaults, current native/Core work and diagnostic bounds are unchanged.

### Instruction delivery and the public transport boundary —6November2026

Two additional native controls used the same isolated owner/thread, not human
captures or production defaults. Moving the sole owner brief to `prompt` while
omitting automatic startup context still produced the canonical identity answer
Soy ChatGPT. A distinct prompt-only control word was unavailable when asked by
voice. Effective-cwd native config read exposed no nonempty realtime model,
backend-prompt or startup-context override. These results do not identify which
layer drops/overrides the instructions or prove an immutable model restriction.

A separate test sent one documented `session.instructions.append` event over
the existing native media data channel. It received `invalid_request_error` /
`invalid_value`, without the matching acknowledgement. No synthetic question was
then submitted and no uncertain append was retried. This is one rejected event
shape on the native route, not a claim that the entire public API is unsupported.
Terminal originals/receipts and negative outcomes remain retained. No tested
identity/model/context change was selected. Keep the665 runtime and full roadmap.

The [official prompting split](https://developers.openai.com/api/docs/guides/live-migration#review-both-prompts)
puts conversational identity in frontend instructions and procedures/tools in
the backend. The [public WebRTC connection](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live)
starts with JSON at `POST /v1/live/sessions`, not the Realtime calls endpoint or
the native Codex payload. `dashboard/openai_live.py` prepares that separate
transport: owner-only instructions, explicit Responses backend/model/tools or
client delegation, negotiated media, opaque session ID and SDP answer. Responses
remains the first public comparison; client delegation is explicit when existing
native execution ownership requires it. The old `OpenAIDialogue` Realtime adapter
is not this implementation and is not silently promoted.

Owner-selected provider options remain intact: startup voice/custom voice,
role-bearing initial input, frontend event permissions, acknowledgement pacing
and Responses reasoning/output/tool choices are not reduced to the old adapter's
feature set. They remain inside the bounded owner-only JSON configuration; the
browser cannot supply or override that specification.

This transport is **not mounted or selected**. It uses a separately configured
private project-key file, never discovers/reuses Codex login files, and refuses
login-token/JSON material. One POST has no automatic retry, redirect or endpoint
fallback. Lost, malformed, oversized,5xx or timeout results remain unconfirmed;
numeric HTTP rejection and unknown creation are distinct. The creation owner
must persist its intent before calling; an in-process attempt guard is not a
durable admission journal. Response storage is at most128KiB; offer64KiB,
owner instructions8KiB and complete session configuration32KiB. Synthetic HTTP
tests cover these boundaries without asserting account access or model behavior.

Remaining public integration: existing authenticated/frozen input and durable
creation ownership, original-media/history recovery, sideband/transcript events,
graceful close/final usage, existing result/question presentation and preservation
of native work when voice ends. Establish actual project access through its
supported credential route only when that integration is ready; none is currently
configured. Then qualify instruction readback, a grounded task/backend return,
provider-managed long-session behavior and useful speech through replacements.
No token export, API-key request, provider call or receiving change follows from
this prepared transport. Do not count it as a working public Avatar.

### Provider-managed lifecycle and durable voice instructions —6November2026

The current [GPT-Live session guide](https://developers.openai.com/api/docs/guides/live-conversations#manage-longer-conversations)
describes provider-owned background summarization and engine replacement inside
a session, preserving original startup instructions. It documents a128k default
window, replacement above90%usage and up to8192tokens of restored recent/summary
history. Important facts and outstanding operations still belong in the application.
Its usage example includes `context_window.usage_ratio`; the actual native Codex
cases retained `audio_duration_ms` instead. These are different contracts: do not
assign public GPT-Live limits or hidden-engine behavior to native Codex without
observing that boundary. Unknown native headroom remains unknown.

Prefer that documented provider lifecycle where available. Do not add an elapsed-
audio threshold, custom summarizer or application turn/delegation loop merely to
imitate it. Native backing compaction is a separate asynchronous operation; its
ACK is not a voice-engine renewal or a semantic recall proof. Keep source-linked
originals/corrections/questions/work in the existing ledgers and qualify actual
continued speech separately from provider/internal context acknowledgments.

Inspection of native sourcef7f163c6 found distinct placement paths: developer
`initialItems` are history; per-session `prompt` becomes voice instructions, with
an explicit configured backend-prompt override taking precedence. The previous
app supplied its owner brief in initial history, preserving native prompt and
handoff behavior. A bounded trial removed that initial brief and used `prompt`
instead. The loaded executable's experimental schema advertises the field, but
the native transcript read Soy ChatGPT for a short identity question. The session
event exposed no instructions for prefix verification. No two-replacement phase
was reached. This does not establish where the request was ignored or overridden.

The trial was not selected: keep663's qualified initial owner brief. Schema/ACK
acceptance is not semantic application; do not duplicate the brief or copy the
native default prompt into an application-owned shadow template to make a test
pass. Preserve the negative original/output and receiving schema evidence.
Further native instruction/pressure parity requires actual application evidence,
not public-GPT-Live assumptions. No native build, config/provider/default change,
credential handoff or model-attention mechanism follows from this investigation.

### Native lifecycle boundary inspection —6November2026

This retains the pre663 inspection;663 subsequently added qualified reactive
transport recovery, without establishing provider-internal pressure/rotation parity.
Reuse retained measurements before opening another provider session. Three
existing actual-native cases already contain bounded numeric projections of
`session.usage.updated`. The sustained case retained24samples from14600ms to
360000ms of audio; its24sample collector saturated, so it does not cover the
whole540second case. The later availability/recall cases retain three more
samples. Their observed numeric usage field is `audio_duration_ms`, with no
numeric limit fields. This is audio accounting, not established context-token
headroom. The projection deliberately excludes nonnumeric content; an empty
numeric limit object does not prove an unlimited account or absent server limit.
No new model, capture or provider call was needed for this inspection.

The [official App Server API overview](https://learn.chatgpt.com/docs/app-server#api-overview)
documents backend compaction as an asynchronous operation with progress events;
it does not establish native realtime renewal semantics. Inspection of Codex
sourcef7f163c6, separately from receiving binary acceptance, found:

- `protocol_frameless_bidi.rs` does not forward usage updates, and Core's
  `RealtimeEvent` has no usage-pressure variant. The app also ignores browser
  native data-channel payloads. Do not invent a token threshold from elapsed audio
  or carry Qwen's accounting into native Codex as if the protocols were identical.
- `RealtimeConversationManager::start` drains a previous connection before a new
  one starts. Stop is thread-scoped; it has no generation comparison. A stale app
  cleanup must never stop its successor. Existing lease/epoch/closure fences stay.
- `realtimeStartInstructions` and `realtimeEndInstructions` render developer
  context when the native mode changes. They are not a checkpoint request, task
  admission, durable semantic-summary receipt or proof of compressed voice state.
- The current app starts a new capture clock and native visit for an explicit
  reconnect. It has no separate logical microphone admission with replaceable
  physical generations. Its source/restoration/result ledgers qualify manual
  recovery; they do not implement automatic pressure-driven renewal.

For application-owned transport replacement, preserve the original microphone
admission/expiry/PCM allowance, retained originals and canonical transcript. Use
supported quiet/closure evidence before retiring old callbacks and installing a
successor; source-linked continuation and backend task ownership remain separate.
Provider-managed internal engine replacement does not invoke these client steps
or require the app to pause its ongoing audio stream.
Waiting for every accepted background task is not a renewal barrier: retain its
exact source references and independent return intent instead. No new executor,
provider fallback, fresh microphone permission or renewed600second allowance is
implied. A late result remains owned by the existing native conversation.

Obtain pressure/commit evidence from the native provider boundary; unknown
headroom stays unknown. Budget the successor packet against native initial-item
limits, keeping identity, human corrections, unresolved questions and work-source
references without embedding old envelopes or full result bodies. A compacted
backing thread and a physically replaced voice connection need separate observed
outcomes. Qualify two automatic switches, useful audio after each, a corrected
fact, an unresolved question and a delayed native result inside the same original
admission. Hard-expiry, stale generation, new input, incomplete originals and
uncertain checkpoint/source writes must preserve recoverable state. Current
64k/48k diagnostics,600second visits and storage bounds remain unchanged.

### Receiving native WebRTC qualification —5November2026

The existing loaded Codex0.163 owner accepted two WebRTC connections using its
existing ChatGPT authentication. No API key was supplied or extracted. Both used
one persistent, test-owned native thread, synthetic Spanish audio, muted Chromium
and the native default automatic handoff/return path. No production thread,
provider selection, service or diagnostic limit changed. This establishes current
native access for this receiver; public GPT-Live API entitlement remains separate.

The initial spoken request asked Codex to read two values in a fixture file and
write their sum, unit and control word to a result file. Voice emitted one native
delegation and the same thread started a real backend turn. A fixture bug placed
Playwright's timeout options in the argument position, leaving its default30second
timeout; the browser closed early. The accepted backend survived voice closure and
completed. Its final answer claimed the result was saved, but its only command
read the input and no result file existed. Keep this negative task outcome; a
native final answer is not proof of the claimed effect.

After correcting the browser wait, the second connection resumed that same
native thread with its own startup history. A new synthetic spoken correction
reported the missing file and asked for a real write and verification. It did not
replay the original request. One further native handoff wrote and read the file;
direct inspection confirmed `43 semillas cedro`. Voice then returned that exact
result. The retained remote Opus recording is290,405bytes, decoded successfully,
and browser WebAudio observed nonzero signal. The browser exited normally and
native voice closure was observed. Physical hearing and independent audio
transcription were not performed; this is not phone acceptance.

Both native turns are terminal-completed in the same persisted history. Four
backend model responses consumed cumulative135,821reported tokens, including
135,589input/112,384cached-input and232output tokens. The last response included
34,157input tokens,33,792cached. These are native backend counters, not unique
context size or a complete voice bill. Voice usage updates remained partial and
did not account for that backend work; do not infer free execution or a total
price from them. The sizeable ordinary Codex context is a concrete efficiency
question even when much of it is cached; no relative cost advantage is established.

This supports implementing the native Codex rich-client route first, not wrapping
GPT-Live inside the Qwen manual-turn adapter. Use the existing shared App Server
and the selected integrating thread; do not spawn another owner. Browser WebRTC
owns media, while the application retains authorized thread selection, native
event subscription and the presentation of pending work, questions and artifacts.
The first application integration must demonstrate original/correction retention,
existing-work admission, role-appropriate context size and same-thread reconnect.
Native transcript history alone does not establish retention of original media,
and a model assertion alone must not mark a task's effect verified. Preserve the
existing journal requirements without mandating their present transport plumbing.

One bounded fixture and its retained failed fixture observation occupy
approximately2.3MB locally. Keep it through native integration qualification; then
retain reports, code and the tiny verified artifact, retiring disposable synthetic
media. Do not retire production originals or native history. No public transcript
or institutional archive of this synthetic media is needed.

### Separate native-client implementation checkpoint

`dashboard/codex_voice.py` prepares native owner control independently of
`native_dialogue.py`, `qwen_dialogue.py` and their manual PCM/renewal loop. It
connects only to the existing private App Server control socket, resumes an
already authorized thread, selects native WebRTC with native startup context
and automatic handoffs, and observes only that thread's bounded completed
transcript/control events. It creates no thread and supplies no credentials,
custom backend prompt, model override, text turn or PCM to the native owner.

An application lease shares the current provider route's active-session capacity,
binds one native client, and fences repeated/stale activation. Native Core itself
replaces existing voice on start and its stop API selects a thread without an
atomic generation condition. The application lease does not exclude independent
CLI clients; activation must account for that native ownership limitation.
Queue overflow retires event delivery while keeping explicit stop control usable.
A start acknowledgement is not provider readiness, and a stop acknowledgement
is not closure: pending-open cleanup waits for its generation; closing waits for
the native close event or reports uncertainty without repeating a write. Neither
voice stop nor connection cleanup interrupts an accepted backend turn.

The candidate's actual receiving test made one further synthetic connection on
the retained fixture thread. With native default startup context/prompt, it
correctly recalled the previously verified file/result, with one new completed
backend turn and no tool execution or result-file modification. Remote Opus
159,001bytes decoded with nonzero WebAudio signal. Its fixture closed the control
reader after the stop ACK before recording the close notification; a subsequent
read of the retained native realtime item proved that exact voice generation
ended. Do not repeat the work to repair this observation. Final client-only
claim and close-wait corrections are covered by synthetic regressions rather
than another provider call.

Seventeen transport/ownership/cleanup/context tests pass on Python3.13 and locked3.11;
the unchanged mounted provider route's68tests and browser native/fullscreen
state suites also pass. Independent review found and verified the duplicate
claim and overflow-stop corrections. These checks do not activate the feature.
Preserve the current route and defaults while completing application integration.

The application boundary reuses shared voice authentication and active-mode
capacity. An owner-local capability read freezes the enrolled integrating thread;
an attachment command validates the same owner/binding and exact current physical
turn, then reuses the existing collector. Both refuse retained Stop/maintenance
holds. Capability is a point-in-time read; activation must recheck it immediately
before starting voice. Existing collectors are observed,
concurrent attachment is fenced by the maintained collector admission, and stale
or completed writers cause no kickoff. This supplies native dynamic tools and
questions through the existing collector rather than a second tool dispatcher.
The official [App Server contract](https://developers.openai.com/codex/app-server)
documents persisted dynamic tools and server requests. Source inspection confirms
outstanding requests are replayed to the attaching subscriber; actual combined
tool/voice reception still requires qualification.

`codex_voice_history.py` prepares a bounded projection of completed native
transcript sources and microphone-original receipts. Core history remains
canonical; this projection is never another copy of model context. Generation
IDs fence transcripts, exact recording retries verify protected bytes, and
archive-pending recovery never invokes ASR or submits native input. Bounds are
512visits/32MiB metadata,64KiB per visit,256 transcript items,32 original chunks
and at most600seconds of16kHz mono PCM per visit; the existing shared256MiB/128
original store remains unchanged. Byte accounting includes deterministic raw
originals left by a failed metadata commit. No automatic retirement is added.
Capacity refusal preserves existing originals and requires explicit recovery.

Seven persistence tests and an actual owner-IPC/SQLite journey with synthetic
native work qualify restart, exact-byte recovery, concurrent collector attachment
and unchanged native input/goal counts. Independent review found the interrupted
metadata-accounting gap, now covered by a regression. Existing provider68tests
and streaming40tests pass after extracting shared authentication. No new real
provider call was needed. The selector, authenticated WebRTC application endpoints,
capture-only browser recovery and transcript timeline are now wired, disabled by
default. The [operator contract](interaction-native-codex-voice.md) records the
configuration, bounds and rollback. Production629 remains unchanged.

Thirteen mounted API tests cover fresh auth/CSRF, frozen binding, owner holds,
closure uncertainty, late admitted work, cancellation during open/start and
actual TCP disconnect while terminal reconciliation is still pending.
After observed native closure, one bounded current-turn read reconciles accepted
work with the existing durable collector; browser closure does not cancel it.
Owner-selected identity digests and source observation times are retained.
Browser tests cover stale sockets and delayed permission/storage completions.
Actual Chromium checks the shipped shell at390x844 and1280x800 with synthetic
RTC/owner responses, real WebAudio/IndexedDB, and failed upload followed by
same-original saving. The ordinary session-menu journey also passes. Screenshots
were inspected; browser errors were empty. These are zero-model qualifications,
not actual provider integration or phone/hearing acceptance.

Native and ordinary browser originals share the existing20MiB/128record budget,
transactionally enforced across separate recovery keys. Completed transcript visits
are never recursively serialized into reconnect context. Prior source02d9dd64
CI41990799341 passed; the application delta needs its own final CI and combined
native tool/voice/identity qualification before receiving activation.

### Actual application boundary observation —5 November2026

One new test-owned Luna-low thread used the candidate application API, browser
client and existing native login for two WebRTC visits. Synthetic speech was the
only input; no physical microphone or production conversation was used. The voice
read back CompAII's name and a unique word supplied only through its owner-selected
identity item. Browser WebAudio measured nonzero remote signal. Both microphone
WAV chunks have protected byte/digest receipts. One actual dynamic controller
capabilities call passed through the existing owner collector; its completed
native answer is retained after browser closure.

The journey is **partial**, not reconnect acceptance. The verifier used an async
browser polling predicate that advanced before the intended tool-ready boundary;
the retained native rollout places the only backing task after the first close.
The second visit ended on “Bien, lo verifico” before the useful conclusion. One
visit's projection still said active when the fixture stopped. Preserve those
observations; do not infer useful continuity from two connections, speech energy
or the committed backend result alone. A new zero-model TCP test independently
confirms that client disconnect can finish reconciliation and commit terminal
metadata; it does not explain this fixture's unfinished projection by itself.

Keep the accepted native work and originals. Do not rerun the original qualifier.
The next semantic follow-up must observe the existing result, with no repeated
capabilities request, wait for useful spoken return and committed visit state,
and preserve the actual request/closure chronology. The fixture remains below
32MiB with a256KiB report bound; after qualification retain compact reports and
native history, retiring only generated synthetic media. No provider default,
production service, original history or diagnostic limit changed.

The inspected native startup-context builder explicitly excludes AGENTS, repo
memory instructions and memory summaries. Do not claim that the foreground voice
inherits CompAII's identity merely by resuming its backend thread. The initial client
used a bounded owner-selected identity/capability item through native V3
`initialItems` with the `developer` role. The6November instruction-placement
probe above failed actual identity verification and was not selected. Keep the
qualified initial item, native startup context and handoffs; this does not
fabricate human speech or start a new backend turn.
The item is optional and capped at8192UTF-8 bytes. Synthetic wire tests and
independent review qualify construction/refusal, not actual provider uptake.
The application caller loads it from the owner's private selected context, never
a browser prompt override. Actual provider uptake remains part of the combined
qualification.

| Evidence | What changes in our design | What still needs qualification |
| --- | --- | --- |
| Official migration guide: continuous audio, no Realtime manual commits/response triggers; Live lacks the same spoken-response completion event | Build a Live lifecycle adapter instead of subclassing the Qwen turn loop. Drive speaking state from actual playback, not a guessed final transcript/response event. | Browser playback, interruption and bounded recording boundaries under continuous input. |
| Official client delegation: notification carries an ID/offset, not task text; transcripts can be fragments or mistaken | Assemble the request from source-linked transcript ranges and application context. Carry corrections and pending work with their IDs; never dispatch a fragment merely because it arrived. | Exact-source admission when a delegation overlaps unfinished or corrected speech; late returns and superseded requests. |
| Official migration/return guidance: backend tasks can outlive voice; spoken and quiet updates are distinct | Preserve ongoing work across disconnects; send useful verified results for speech and quiet state separately. Do not narrate every tool step. | Reconnect checkpoint/delta hydration and human hearing, separately from receipt of an appended update. |
| OpenAI Live Console, pinned source below | Inspect separate browser/server startup, generation guards, backend event ownership, bounded delegations/tool rounds and terminal cleanup. Use it as a comparison fixture, not a second production app. | Its README explicitly leaves end-to-end compatibility verification open; no deployment acceptance transfers to us. |
| Travizm's protocol notes, pinned source below | Useful developer-reported traps: wrong event families, delegation without task text, injection ACK versus audibility, interruption versus work cancellation. Check each against current official schemas. | The author's October wire observations are not our current account test or a universal protocol guarantee. |
| InteractionBench, submitted2November | Evaluate timing, task correctness and grounded continuity together. Fast speech alone does not establish useful interaction. | Published system comparisons include client/network effects; no ranking transfers directly to our Spanish/device setting. |

Official primary references, retrieved4November2026:

- [Migration](https://developers.openai.com/api/docs/guides/live-migration):
  workflow/prompt separation and the continuous audio versus Realtime lifecycle.
- [Delegation and tools](https://developers.openai.com/api/docs/guides/live-delegation):
  transcript/offset assembly, delegation IDs, quiet/spoken updates and late work.
- [Session management](https://developers.openai.com/api/docs/guides/live-conversations):
  context and connection lifecycle; do not assume a replacement inherits state.
- [Voice evaluation Cookbook](https://developers.openai.com/cookbook/examples/audio/voice_agent_evaluation):
  use as the evaluation-design reference, not evidence that we ran its benchmark.

Inspected implementations and research:

- [OpenAI Live Console](https://github.com/openai/openai-live-console/tree/5f64ecb3009d8274da9953c825d469ea6b6b67c3),
  especially `server/session.ts`, `client/session.ts` and README. Read selected
  startup/control sections; no whole-repository audit or execution. Publication
  date not established by this read; revision retrieved4November.
- [Travizm protocol notes](https://github.com/Travizm/dsh-openai-live/blob/6f78ffc2355d24dcf6ed4fac2a77959d2a674d53/docs/protocol.md),
  author-reported wire observations dated7/15October, retrieved4November. Treat
  its account/billing assertions separately from protocol observations; they
  are not a source of permission or proof of our access.
- [He et al., InteractionBench](https://arxiv.org/abs/2611.02430),
  submitted2November2026. Abstract inspected; the full harness and experiments
  were not reproduced. It is an evaluation lead, not an implementation choice.

## Current receiving comparison checkpoint —5 November2026

Repeated synthetic native application connections now return the corrected word.
After an explicitly clarified result question, native handoff returned useful
retained capability information in speech without rerunning its tool. A silent
visit and a misheard question remain negative observations, not successful runs.
The exact compatible native composition also passed spoken recall and original
retention. See the [native mode contract](interaction-native-codex-voice.md) for
qualification and remaining activation/phone/long-term continuity gaps.
The compatible app/native pair is now receiving-selected as a separate choice
in UI0976269baac7. Default providers and bounds are unchanged; actual phone/hearing
and sustained continuity remain unqualified.

## Reuse, replace and measure

Preserve shared identity/access, exact human-source/correction history, ongoing
work, permissions and useful results/questions. Reuse existing native mechanisms
where qualified; our present journal/bridge/viewer implementation is not mandatory.
Replace provider-specific assumptions: manual audio commits, response-end
events, synchronous tools, a prompt containing every backend tool procedure,
and reconnection that starts with unrelated recent excerpts.

The first integrated comparison must cover a natural greeting, an unfinished
sentence, correction during a delayed request, an interruptible spoken return,
one useful artifact, a pending question, a provider renewal, and reconnect to
the acknowledged checkpoint. Record first useful audible response, interruption
to quiet, output queue age, result correctness, missed/duplicate actions,
continuity and total voice/backend cost. Use the existing Qwen journey as a
comparison, not a template that dictates Live's protocol. Do not create a new
worker hierarchy or provider-owned memory store to imitate a demo.

## Prior work, acquisition gaps and retention

The retained15/18October integrating-conversation research already considered
Qwen Live Harness, JarvisBench, lab task/social dialogue, native Codex WebRTC and
client delegation. Its existing map and original source retain their historical
dates, audience and unresolved experiments. This note adds current migration
decisions; it does not publish that private corpus or treat its map as fresh
independent validation.

Selected X lead: OpenAIDevs post2098099372999446590. Direct public retrieval
returned403; no post/thread body was inspected. Existing subscription search
configuration permits long automatic retries and has no verified source-linked
retrieval; no paid fallback or speculative model call was started. Do not quote
or claim lessons from the inaccessible post.

Selected YouTube lead: OpenAI, “Discoverability widgets with GPT-Live,”
[video QUOwyLwoykU](https://www.youtube.com/watch?v=QUOwyLwoykU), search metadata
dated8July2026. One bounded no-media subtitle discovery request was blocked by
a sign-in/bot challenge. No captions or video content were inspected; metadata
alone does not establish widget behavior. Relevant talks/demos remain an
acquisition gap before claiming a complete community/video review.

Keep this brief, selected pinned links and acquisition outcomes. Do not retain
full platform mirrors, download media, export cookies, install search watchers
or accumulate per-query logs. Revisit a missing source through an already
authorized working reader when it can resolve a concrete implementation choice.
No inference, provider switch, limit change or new recording occurred here.
