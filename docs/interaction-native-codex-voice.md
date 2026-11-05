# Independently selectable native Codex voice

This opt-in Avatar engine uses the existing native Codex App Server and its
ChatGPT sign-in. It is separate from the Qwen/Gemini engine. Application tests
are not production or physical-hearing acceptance.

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
flows directly through WebRTC. The application sends no manual PCM, text turn or
response request to the provider. Shared auth, Origin, fresh action token and
owner binding are checked before native start and throughout the visit.

Native handoffs create work in the persistent thread. Exact observed turns
attach through the existing durable collector. After observed voice closure,
one bounded current-turn reconciliation attaches any already accepted writer.
Tools/results continue independently of the browser. A stop acknowledgement alone
is not closure. Missing closure or failed collection retains review state;
cleanup never cancels accepted work or replays its original request.

Duration stays300–600seconds. Native context handling remains native: stored
visits never become a recursively serialized reconnect prompt. Completed
transcripts retain source IDs, voice generation and observation times. They are
not proof of the precise words a person heard.

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
