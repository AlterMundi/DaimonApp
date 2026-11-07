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

## Remaining comparison and acceptance

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
