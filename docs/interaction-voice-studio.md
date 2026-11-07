# Voice studio receiving integration

DaimonApp owns implementation; Voces owns the attributed product candidate.
Continue inside the existing avatar workshop and shared account authentication.
This source is an unfinished foundation, not a served editor or provider trial.

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

## Remaining adapter and interface work

No voice HTTP endpoint, user control, audition or active route consumes this
foundation yet. Do not label it available. The adapter must derive exact supported
profiles from receiving configuration/capabilities, with no account entitlement
inferred from a voice name. Reuse the existing workshop owner/CSRF checks; do not
accept a browser-supplied account or arbitrary provider profile.

Add Voice inside the existing workshop wrapper. Preserve current A and candidate
B, delivery descriptions, immutable Save and separate Use on next conversation.
Keep the previous selection on cancel/error/unknown ACK and reconcile the same
revision through reads. No microphone or provider call on open/edit/save.

Public Live currently has physical visits and continuation ancestry, but the
studio needs an explicit frozen voice choice across physical replacement/manual
reconnect. Complete that contract before exposing Use: a new logical conversation
may read the selected revision once; its physical successors keep that snapshot.
The account pointer must never silently alter an existing connection or renewal.
Preserve owner identity, pronunciation/accent, native execution and sourced returns.

Paid comparison remains explicit and bounded: two compatible identities at most,
the same passage of at most40words,30seconds/16MiB each, retained uncertain result
and no automatic provider retry. Use the existing bounded media cache if audition
media is implemented; no separate store or login. Recorded previews are not live
conversation latency measurements. Actual listening, mobile and receiving delivery
remain separate acceptance.

Qualification currently covers real actor-document save/reload, exact readback,
immutable revisions, isolated actors, stale generations, incompatible selection,
frozen copies, shared visual/voice capacity and failed-write preservation. It
calls no provider and does not prove the remaining interface/session contract.
