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

A compatible child advertises `features.avatarMicrophone: true` on `ready`.
A host may request `avatarMicrophone: true` independently on `connect`. The
optional `avatar-microphone` message uses the same actor, frame, visit and
binding envelope. Its only additional field is a scalar `level` rounded to
quarters. Ordinary Conversation capture with live PCM provides the level
from its existing local meter. No new capture, permission, media callback
or background timer is opened. Nonzero samples are capped at ten per
second, and a zero clears the previous sample on capture stop, hide,
disconnect or opt-out. The receiver must expire silent or stale samples
locally and must not infer that the mic is active from the capability.
No waveform, text, draft, device ID or capture status crosses the frame.
Continuous engines and recorder fallback with no existing level source
continue without this optional presentation.
