# Canonical hosted Conversation surface v1

Contract for the existing Holodeck integration. Conversation owns its shell,
composer, audio/transcription, cues, attachment writer, local recovery, original
submission and progress. The host never copies these modules or submits a second
native original. All source, frame and actor checks are mandatory.

Configure `[conversation_surface] parent_origins = ["https://selected-parent"]`
on each actual paired Conversation receiver. No wildcard, path or arbitrary
query-selected origin is allowed. Load that receiver's registered Home entry:
`/interaction/?view=conversation&client=standalone&surface=holodeck&surface_parent=ENCODED_ORIGIN&surface_visit=UUID`.
Keep the iframe mounted while draft/capture/upload is active. Set iframe
`allow="microphone"`; the parent must delegate microphone only to this exact
receiver origin. Reuse shared Home sign-in; never transfer cookies/CSRF to parent.

Every postMessage has `schema:"conversation.surface/v1"`, `type`, `visit`,
`channel`, `actor`, and `binding`. The child creates a fresh channel UUID per
document. Both sides require exact event origin, actual parent/frame window,
visit/channel, current authenticated actor and current binding. No `*` targets.
Parent must compare actor with its own server-verified paired human, not a label.

1. Child sends `ready` after shared authentication and binding discovery.
2. Parent replies `connect` with the exact envelope. No user action is admitted
   through the surface until that handshake completes.
3. Synchronously at original-ID/binding allocation, BEFORE calling any async
   image/file preparation or microphone permission, child sends `prepare` with a fresh `request` UUID,
   canonical original `id`, `modality:"text"|"audio"`, and attachment capacity.
   The initial request has `files:[]` internally; the returned context is appended
   to the actual user references after their preparation. Final combined count
   and bytes are checked again before any original write. It sends no human text, audio or private history. ID and binding are
   allocated/frozen BEFORE asynchronous file/context/permission work.
4. Parent captures one immutable machine situation for that actor/ID at this
   boundary, and uses its existing UID-guarded bridge/provider file writer to
   retain `holodeck-situation.json`, schema `holodeck.native-situation-source/v1`,
   with exact `human_input_id`, `speaker`, observation and existing native-world
   descriptor. This is evidence, never human speech or new authority. Preparation
   MUST NOT submit/steer a native original.
5. Parent replies `prepared`, echoing the exact envelope/request/id and `file`:
   `{file_id,sha256,name,mime,size}`. Only one JSON context file, at most64KiB.
   Use `error` (plain bounded message) for refusal. There is one30s wait, no
   automatic repeat after unknown preparation. Preserve retained parent outcomes.
6. Child attaches that frozen regular fileRef through existing files/input/voice
   routes. Existing provider/native writers verify stored bytes/hash, grants,
   original identity and binding; browser context is never authority. User files
   are limited to7/40MiB-minus64KiB. Edited dictation additionally reserves its two
   existing original-audio/transcript slots. Context remains part of the same
   local recovered original and is not prepared again when retrying that original.
7. Child sends `status` with canonical original `id`, `phase` and `busy` only.
   It never forwards chat bodies, transcript, audio, attachments or credentials.
   Native result/world admission remains the existing owner's verified status;
   this UI notice alone proves neither completion nor native execution.

Bindings/authentication changes invalidate in-flight preparation. Parent cannot
set draft, start microphone, auto-submit, select a session, replay or resume work.
No background recorder, provider call or new login is created. Iframe reload is
not safe while capture/upload/unknown submission is unresolved; normal existing
recovery rules remain authoritative. Real device/hearing acceptance is separate.

The hosted frame presents the general conversation and the human's original
inputs. It omits independent session reply cards and the workspace switcher.
Replies from the general conversation, the same input writer, draft recovery
and situated attachments continue through the shared component.

### Conversation text drafts

The canonical composer saves ordinary typed text immediately in the current
browser tab for reload recovery. Within the same authenticated receiver binding,
its last saved revision also follows the human across Conversation clients,
including Holodeck. The normal input reader carries the draft when requested,
and its separate same-origin, CSRF-protected draft write compares revisions.
Simultaneous edits are kept visible in the local composer and require an explicit
choice before replacing the other copy. A confirmed original clears only its own
matching draft. After a reload with an unconfirmed write, check the original ID
before attempting to send the same text again. Draft changes never submit an
original or send data to the host. Attachments, draft routing, microphone and
provisional transcripts retain their own lifecycle. Server drafts expire after
seven days and are limited to 32 KiB per authorized actor and binding, with at
most 128 retained revisions across those keys (one current revision per key).
Tab recovery retains up to four recent bindings, with the same seven-day limit.
The send response settles the draft using its exact original ID within the
current submission. A later status read can settle it using the matching native
entry, and a history row can do so under its verified page binding when it
belongs to the current entry.

## Additive source-only discard notice

`type:"discard", id, reason:"capture-cancelled"|"preparation-failed"` uses the
same exact v1 origin/frame/actor/binding/visit/channel envelope. No human content
is included. It is emitted at most once for a source preparation when the local
canonical component knows its original writer was NEVER attempted: cancelled
recording/permission or failed file/image/context preparation before the original
POST. It may precede an in-flight/unknown machine-file preparation response.

Immediately before an original text/voice POST, the component permanently fences
discard for that original in this document. Unknown/failed/lost-ACK writes never
emit discard. Recovery without local proof also never infers a safe discard.
There is no source notice on ordinary held recording review or native work failure.

The host must compare the original ID with its retained actor/binding/source, use
the existing owner bridge lookup and retire ONLY a machine-source reservation
when that supported lookup permits it. Keep every canonical file and any retained/
uncertain original. A discard notice is not original absence, original cancellation,
native completion or human approval. Missing/in-flight source responses require
the host's bounded graceful retirement, never replay. A changed frame/binding does
not permit sending an old source notice under the new identity. Normal non-hosted
Conversation retains its existing capture/submission behavior.


An authenticated host can opt in to the cosmetic avatar playback signal with
`features.avatarPlayback: true` on `connect`. The child publishes
`avatar-playback` on the same bound channel using only the rounded 0–1 output
level from the existing playback observer. It sends silence on pause, hide or
disconnect. The parent expires old levels locally. This signal carries no
audio, transcription, microphone input, or turn activity.

## Owner-local machine source receipts

A receiving Holodeck bridge can prepare a bounded source through the existing
owner-local control socket. `input context capabilities` identifies the
current binding and the `owner-journal/v1` protocol. `input context reserve`
accepts the original UUID, that binding, observation UUID, exact source digest
and up to 48 KiB of source JSON encoded as base64. It returns a receipt UUID.
`input context status` verifies the retained bytes and returns metadata.
`input context read` selects the exact bound and sealed original and can return
the observation JSON to an authorized local caller. Neither operation starts work.

The native text and ordinary voice writers can select that UUID through
`machine_source` (`x-machine-source` at the ordinary voice HTTP boundary).
SQLite matches the original, current owner, session, native
thread, binding and admission epoch. It seals the receipt in the same
transaction that inserts the original and its ingress order. The entry binding
remains stable through first native-thread establishment. Retained status
checks the original’s actual thread, and voice recovery reloads the server-side
receipt for that same original. The receipt
uses a separate table and leaves all human attachment slots available. A
retry must select the same receipt. A legacy capture with no selected receipt
retires its pending offer. The owner status command reads only the matching
current Conversation and returns receipt and digest metadata. The independent
retained lookup can show the receipt for an exact owned original after a binding
change. The source speaker is an assertion from the owner-local producer. A
receiving integration must verify the actual registered speaker before offering it. The seal is
evidence of canonical retention. Delivery and permission for any subsequent
Holodeck action still require independent proof.

New reservations carry an owner-journal `reservation_order`, allocated
in the same transaction as the receipt and its immutable bytes. The number
orders reservations inside the current journal. It is independent of
capture timestamps, world event sequences, canonical admission and native
delivery. An exact retry preserves it. Expiration does not reset the
sequence. A new reservation after expiration receives a new number. The
reducer must distinguish an originally frozen observation recovered after
expiration from a genuinely later observation before using order to
advance a baseline. Older receipts omit it and remain readable. The semantic reducer
must treat receipt order as belonging to a journal incarnation, and a
native-accepted receipt of unknown order as a barrier to an existing
baseline. A restored or replaced journal requires a fresh full baseline.

Pending reservations are capped at 32 per Conversation and expire after
24 hours. Opening the journal or submitting another validly encoded offer
sweeps expired pending bytes. The sweep survives a subsequent refusal. The
payload budget is distinct from human attachments. It allows at most 512
inline sources per session and 1,024 in the receiving journal. An exact,
pending file-backed receipt from the previous draft can move to the journal
using the same pinned bytes, original and receipt. The native writer checks
the source again when sealing and rolls back capture if the bytes are unavailable.
Retained sources remain immutable. Before sustained activation, qualify their
owning archival route so the journal's sealed-source limit is recoverable.

The native receiver candidate chooses a full, unchanged, or delta delivery
for direct canonical Conversation. Each native input still identifies its
exact original, retained machine receipt and digest. A full delivery
includes the authorized snapshot and its semantic state. A delta includes
only changed sections relative to the explicitly named accepted original.
An unchanged delivery carries the source identifiers and the baseline
reference. It omits the snapshot and change data. Every full canonical
source stays available to its existing authorized audit and world routes.

Both direct start and steer bind their selected projection to the exact
execution and writer before native submission. The checkpoint advances at
`ConversationInputEvent::Accepted` with the matching native execution and
base. The generic Telegram receipt, canonical journal seal, queued phase
and later reply do not establish a baseline. If a checkpoint is lost, its
reservation floor survives. A late original carries its own historical
full view. Captures compare stable section fields, use half-meter cells
with hysteresis, and preserve a bounded recent-work window. Room or world
changes require a new full view. Writer restart, observed context
compaction and unprovable acceptance invalidate the reusable checkpoint.
Routed targets retain the full source and never establish a direct
checkpoint.

An affected patch that no longer matches its selected baseline is refused
before native submission. Its original remains available through the
existing retained-input controls. A qualifying full plan can survive an
intervening acceptance while its order is still current. The semantic
candidate is separate from activation. Retention and expired-source
ordering still require qualification before sustained receiving use.

The dashboard candidate negotiates the receipt path only when both the
canonical frame and the authorized Holodeck host advertise it. Each
original freezes its chosen mode. The legacy mode reserves one slot and
appends the full context file. The journal mode leaves the eight human
slots available and submits the receipt independently. Text and edited
dictation use the existing canonical input route, ordinary voice uses the
existing header, and local voice recovery stores the exact receipt with the
frozen original. Receipt-bearing recovery uses version 9 so older clients
cannot silently send an original without its receipt. A directly delivered
native question answer retains its existing native-answer behavior.

Controlled Chromium at desktop and narrow widths exercised old and new
frame modes, separate text and audio receipts, eight attached text files,
and uncertain text acknowledgment recovery. The microphone fixture confirms
that edited-dictation recovery sends the same original and receipt without
repeating capture or preparation. The selected service remains on the legacy
path. Holodeck #19 owns receiving qualification and the conditions for
enabling the journal transport on the live pair.

Fable High reviewed the transaction boundary and identified the requirements
for idempotence, admission epochs, and an additive table. Opus 5.5 High
found that first-thread establishment and voice recovery could lose the
receipt. The corrected path follows the original’s stable binding and reads
the receipt back from the owner journal during recovery. Local SQLite tests
cover cold establishment before and after capture, voice restart recovery,
exact retries, missing source bytes, expiry and eight human files. The owner
command fixture also covers the full voice recovery command with a retained
receipt and distinguishes a legacy original from a sealed machine source.

For a sealed original, native start and steer project the retained observation
in a separate machine-evidence block. This applies both to the Conversation
entry and to a routed worker receiving the original. The original human text
and attachments retain their identity. The writer parses the exact retained
bytes as strict JSON and rechecks the receipt, binding, and digest at native
admission. If the source has changed or become unreadable, the affected input
fails admission. A failed routed source leaves other pending inputs available.

The controlled real HTTP test seals and recovers exact text and voice receipts
without creating a human attachments directory. It delays voice past newer
text and inspects the actual native protocol packets for both the general
Conversation and the routed worker using a simulated native engine. JSON
number tokens survive native projection without conversion. Source provenance,
native delivery and baseline eligibility remain independent.
