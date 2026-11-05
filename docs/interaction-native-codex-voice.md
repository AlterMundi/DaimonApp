# Independently selectable native Codex voice

This opt-in Avatar engine uses the existing native Codex App Server and its
ChatGPT sign-in. It is separate from the Qwen/Gemini engine. Application tests
are not production or physical-hearing acceptance.

## Receiving checkpoint —5 November2026

CompAII ITACA now exposes the separately selectable mode in UI `0976269baac7`,
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
Recent history reads return at most8visits. Recovery reads/uploads use current
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
