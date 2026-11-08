# Voice workshop receiving integration

DaimonApp owns implementation. The maintained Voices v2 contract selects a direct
voice → Play → change → Play → save a named configuration → reopen loop. It
supersedes the historical A/B-first UI. Reuse the existing avatar workshop,
shared authentication, actor document, speech renderer/cache and voice admission.
Resolve actual installation through Shared Resources `interaction-current.md`.
Source qualification does not establish provider access or human listening.

## Choose, listen and save

The workshop offers receiving-configured compatible voices, delivery presets and
an optional delivery description. Each voice's explicit Play uses that voice and
the current delivery/text. Editing alone generates nothing. Expression buttons
reuse the authored workshop gallery cue IDs (welcome, joy, curious, calm, sleep,
sad, anger, uncertain and focus). Each has a separate Play; choosing a cue alone
only changes the sample text. These are artistic examples, not sensor states or
a change to the live avatar. A separate text field has its own Play button.

Each Play freezes one exact profile, delivery and phrase. Text must be nonempty,
at most40words/1024UTF8bytes; reject visibly before a paid attempt, without
truncation, a fixed substitute or a native delegation. Existing Markdown spoken
projection remains part of the speech renderer. The phrase is developer-framed
preview content, not authority to execute tools or replace identity instructions.
A completed exact cached sample plays again without synthesis. A changed phrase,
voice or delivery requires another explicit Play. Only one generation is pending
per panel/actor; older playback stops and at most two audio object URLs are kept.
A browser refusing autoplay leaves the verified sample ready for explicit Play.

Save uses a bounded name (80Unicode characters/320UTF8bytes), immutable revision,
exact API/model/voice, delivery, parent, timestamp and digest. A name is app
metadata, not a provider voice ID or cloning request. Reopening a saved voice
restores its exact identity/delivery/name before Play. Legacy unnamed revisions
stay readable. A lost Save ACK reads the same revision ID; it never repeats the
write. Explicit Use is separate: it selects the next own logical voice chat.
Save, audition and reopening never select a voice, provider, avatar or account.

New logical visits copy the selected compatible revision once. Ongoing visits,
reviewed disconnections and physical replacements keep their frozen choice,
including when another saved voice becomes active. Wrong owners, stale selection,
corrupt profiles and incompatible API/model choices refuse before paid creation.
The saved delivery is voice-only guidance within the existing8KiB instruction
bound; native identity, language, name pronunciation and execution remain intact.

## Receiving capability and actual access

The initial transport is GPT-Live; ordinary Conversation speech retains its
separate Realtime route. API identities are not silently pooled or substituted.
The current configured voice is always first. Additional documented GPT-Live
identities require an explicit receiving `voice_studio.voices` list, qualified
for that project's account. The list is bounded by the maintained public model
catalogue; it performs no provider/custom-voice or entitlement discovery.

A real configured-source preview ended without a confirmed session start/audio.
A distinct candidate-source single sample retained `model_not_found`; a bounded
project-model metadata read also omitted GPT-Live while listing the existing
Realtime speech model. These outcomes do not establish provider acceptance or
hearing. Keep both attempts and their uncertain final usage without replay.
A supported transport/account decision remains separate from this UI change.
Do not silently change Avatar, its configured model, accounts or live captures.

Failed transport receipts retain fixed local failure classifications and
allowlisted provider codes. Raw provider messages, headers, credentials and
request payloads are excluded. Optional diagnostics do not authorize retry,
retirement or a retroactive diagnosis for older receipts without them.

Official capability/lifecycle references:
[voice options](https://developers.openai.com/api/docs/guides/live-conversations#voice-options),
[WebSocket startup and close](https://developers.openai.com/api/docs/guides/voice-websockets#connect-a-server-to-gpt-live).
Regional voice influences are not evidence of pronunciation or account access.

## One-preview lifecycle, bounds and recovery

The existing account `voice_previews` allocation now supports a single `sample`
slot and custom passage through `prepare_sample`, immediately followed by the
explicit Play's render. There is no user-facing Prepare or comparison selection.
Legacy A/B rows remain available for truthful inspection/cleanup; they are not
new default interactions and are not rewritten. Exact source/profile/generation
bind each attempt. A lost preparation response is observed under its original
identity, without another allocation or automatic generation.

The same four-row/two-slot ceiling (at most8legacy slots),64actors,32combined
visual+voice revisions,8MiB actor document and32MiB aggregate limits remain.
A full library may reclaim only an exact settled task-owned single-sample row
under the existing retirement claim/locks before new allocation. Unknown/active
attempts and human originals stay protected; capacity refusal starts no provider.
Account selection and frozen visits are unaffected by disposable sample cleanup.

The renderer still has one primary GPT-Live WebSocket with synthetic silence,
no microphone/Responses/native tools and no fallback. The provider attempt is
30seconds including finalization, at most5seconds close drain,35seconds worker
wait,45seconds render HTTP, <=30seconds mono PCM16/24kHz audio and8MiB. A confirmed
`session.closed` with final usage is required for successful cache proof. Unknown
closure remains unknown and cannot regenerate or be disguised by a new ID.

Stop/Close sends at most one cancellation to the owned pending generation.
Close immediately releases the panel/audio and ignores late replies. A cached
read cannot cancel another unstarted attempt. Actor changes clear private labels,
drafts and playback; late old-account reads cannot repopulate them. Hiding the
page stops playback. The existing owner/CSRF checks, HTTP admission, actor lease,
shared synthesis capacity and receiving fingerprint apply before every attempt.
A changed catalogue does not erase old journal identities or account outcomes.

## Entry, appearance and acceptance

Each existing shared-login Conversation accepts
`?view=conversation&client=standalone&workshop=voice`. Its writable own-actor
binding opens this same panel once. No new app/login, grant, media store,
automatic provider request or microphone permission is introduced.
Spanish browser language selects Spanish labels; other browsers keep English.
The existing Home appearance applies to all controls/surfaces. Support320/375px,
keyboard focus, readable text, touch targets and reduced motion. Earlier samples
and optional details live behind a disclosure, outside the child's primary loop.

Qualification must exercise custom Unicode and expression Play, exact identity
and text, inert changes, named Save/reopen/lost ACK, explicit Use, cached playback,
unknown generation/prepare, Stop then Close, late replies, actor isolation and
capacity cleanup/refusal. Reuse valid unchanged lifecycle/store evidence.
Report source tests, receiving delivery, finite provider audio, human listening
and child/device acceptance separately. The full original App goal remains open.


Retained `model_not_found` diagnostics appear beside the current sample and in
its history in Spanish/English. This is account/model unavailability, not a
playback-device diagnosis or a confirmed audio result. Reading that same sample
never creates a replacement generation. Generic uncertain samples keep their
existing status and retirement protections. Choosing an available workshop engine
and actual provider audio/hearing remain separate from this presentation fix.
