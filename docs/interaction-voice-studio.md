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
provider call, cache or automatic deletion is added.

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

The preview transport is not exposed by the workshop yet. Before enabling it,
retain bounded frozen A/B batch intents under the existing account document;
reuse the existing speech cache and reservation/cleanup, with an explicit cap
on preview receipts/jobs. Preserve unknown outcomes and generation-fence retired
batches. Wire the existing scoped voice exclusion and owned subprocess
cancellation/deadline into the authenticated route and UI. Do not enable a
button that can accumulate unbounded metadata or replay an expired/unknown job.

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
