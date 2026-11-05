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
inherits CompAII's identity merely by resuming its backend thread. The client now
supports a bounded owner-selected identity/capability item using native V3
`initialItems` with the `developer` role. This preserves native prompt, startup
context and handoffs; it is not fabricated human speech or a new backend turn.
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
