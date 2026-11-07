# Voice studio receiving integration

DaimonApp owns implementation; Voces owns the attributed product candidate.
Continue inside the existing avatar workshop and shared account authentication.
This source adds the existing-workshop Voice panel and its authenticated adapter.
It is not deployed or listening-qualified; bounded auditions remain unfinished.
The first adapter targets public GPT-Live Avatar. Ordinary Conversation speech
keeps its current Realtime route; API-specific voice identities are not pooled.

Voice revisions now share the existing atomic account document, lock and quota
with visual revisions. They use a separate `voice` namespace and generation;
voice data never enters ascii-avatar-model/v1 or ascii-quest-design/v2. The
combined visual and voice revision count stays within32 and the existing8MiB
actor/32MiB aggregate limits. Quota refusal keeps prior selections; no recorder,
provider call or automatic deletion is added by revision actions.

A revision retains an exact OpenAI API/model/voice reference, delivery instruction
at most1024UTF8bytes, parent, timestamp and digest. Save does not select. Exact
save readback under the original revision ID does not replay a mutation. Explicit
selection uses the current generation and the authenticated adapter's actually
compatible profiles. Foreign, stale or incompatible actions keep the old pointer.
The store returns a copy for a newly created logical conversation. Updating the
account selection cannot change that copy or the visual selection.

## Account actions and frozen conversations

The Voice panel lives in the existing workshop wrapper, preserving the original
editor and visual selection. It shows the current receiving-configured identity,
current A and editable B, delivery starting descriptions, immutable Save and
separate Use on next conversation. It performs no broad account catalogue or
entitlement discovery. Existing workshop owner/CSRF checks authorize its exact
`avatars/voice` endpoint; read-only monitors and foreign actors cannot use it.
Save/Use outcomes are reconciled through reads under the retained revision and
expected generation. A lost response never starts another automatic write.

New clients explicitly mark a new logical voice start. It reads the selected
revision once, before microphone permission or paid creation. Physical reconnects
supply their owned previous visit, retaining that exact voice snapshot across
repeated replacements. An explicitly reviewed disconnected visit supplies its
own snapshot. The reference is flat, not a nested voice archive. Wrong owners,
changed API/model/voice or corrupted snapshots refuse before paid creation.
Legacy clients keep the configured default delivery and cannot silently consume
an account selection intended for the new studio. Native context, identity,
language, name pronunciation and execution instructions stay in the base brief;
the saved delivery is appended as voice-only guidance within the existing8KiB
instruction bound. It is not a SOUL or execution-policy replacement.

Opening/editing/saving requests no microphone or audio. Existing connections
cannot change through a workshop pointer update. Studio changes are not yet
served and no per-pair defaults or provider flags were changed by preparation.

## Preview transport source

The source renderer now supports the same GPT-Live API through one primary
WebSocket, using the existing speech intent/cache/audio reservation. It sends
only synthetic silence and developer-attributed preview text, with client
delegation and no native work or Responses tools. It never opens a microphone.
A greeting is seeded and appended once after startup as the official guide
recommends. Input/output share PCM16/24kHz; model, voice and final session ID
must match. The deadline is30seconds including finalization, with at most5seconds
of close drain,40words and the existing8MiB audio bound. Wave output is at most
30seconds. Captions are not certified word alignment or human hearing.

There is no per-utterance completion event. A full passage caption plus a quiet
audio interval requests close; otherwise the generation deadline requests close.
A valid `session.closed` with final usage is required before a successful cached
preview. Missing/changed output, cancellation and unknown closure never start
another session. Expired auditions can refuse regeneration while ordinary speech
retains its existing explicit-render contract. The transport itself creates no
new store or provider defaults. This is source/synthetic qualification only.

References: [GPT-Live conversations](https://developers.openai.com/api/docs/guides/live-conversations),
[primary WebSocket lifecycle](https://developers.openai.com/api/docs/guides/voice-websockets?api=live).

## Remaining comparison and acceptance

The source workshop now exposes the authenticated preview adapter and explicit
Prepare comparison, Generate A/B, cached Play, Stop generation/playback and Retire
controls. The account-document batch layer freezes A/B and the same passage before
any attempt, with at
most4batches/2slots per actor. Existing64actor and document/audio limits remain;
new preview job metadata therefore has at most512jobs. Batch identity includes
its monotonic generation. Exact prepare readback never replans or changes A;
a started slot can only be observed after restart, never launched again.
Cancel preserves in-flight attempts and marks unstarted slots as unsent.

Retirement first persists its claim, then removes only the exact known-completed
preview cache bytes/job. Unknown or active attempts remain. A partial deletion
or final metadata failure retains `retiring`; only that cleanup can continue.
Old generation requests cannot reallocate retired batches or regenerate audio.
The cleanup reuses the speech job locks, verifies source/header/audio hashes and
never touches human originals, ordinary speech jobs or selected voice revisions.

The internal preview CLI reuses the speech renderer and the existing capacity
semaphore. Its runner bounds stdout at64KiB and owns only its isolated process
group, with a35second wait and5second termination drain. SIGTERM cooperatively
requests a graceful Live close; an unresponsive owned process is terminated.
The runner validates the returned cache ID, source hash, WAV bytes/format and
30second duration. Tests exercise the actual subprocess/cache-hit and cancellation
while an unrelated process remains alive. No real provider was contacted.

The exact `/api/interaction/avatars/voice/previews` endpoint reuses workshop
owner/CSRF authorization. Generation acquires the existing HTTP voice admission
and actor voice lease, using the same semaphore as ordinary TTS. A receiving
configuration fingerprint prevents old attempts or cleanup from being rerouted.
Only current configured GPT-Live profiles and the existing approved project key
reference/cache are accepted; arbitrary renderer input is not exposed.

A lost generation response only reads the retained cache/outcome. Unknown or
expired jobs cannot regenerate. Closing waits for an active generation to stop;
actor reset discards client state, and each server-owned attempt remains bounded.
Playback starts only on explicit Play, keeps at most A/B object URLs for the
selected batch and revokes them on close, actor change or batch change. Hiding
the panel or page stops playback. Recorded usage and first-audio timing are
reported separately from unmeasured live-conversation latency and hearing.

Mounted synthetic tests cover owner/CSRF isolation, maintenance and capture
exclusion before intent, exact cache readback without another worker, lost worker
responses, unknown outcome retention, configuration drift and owned cancellation.
The actual Chromium editor verifier additionally exercises synthetic preview
routes: no generation on open/save/use, explicit A/B, recorded playback controls,
lost B response without retry, keeping A while B is generated and refusing
retirement of the unknown B. It also checks1200/375/320 layouts. These UI fixtures
are separate from mounted API/cache ownership tests; none contacts a provider.

Paid comparison remains explicit and bounded: two compatible identities at most,
the same passage of at most40words,30seconds/16MiB each, retained uncertain result
and no automatic provider retry. Use the existing bounded media cache if audition
media is implemented; no separate store or login. Recorded previews are not live
conversation latency measurements. Actual listening, mobile and receiving delivery
remain separate acceptance.

Qualification covers real actor-document save/reload, exact readback,
immutable revisions, isolated actors, stale generations, incompatible selection,
frozen copies, shared visual/voice capacity and failed-write preservation. It
calls no real provider. Mounted API-to-provider fixtures prove delivery selection
and legacy-client behavior; three physical journal successors preserve A before
a new logical start takes B. Actual Chromium verifies the existing editor plus
Voice Save/Use, lost save-ACK readback, account isolation and1200/375/320px layouts.
These checks do not prove paid audition quality, hearing or physical devices.
