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
3. Before each original, child sends `prepare` with a fresh `request` UUID,
   canonical original `id`, `modality:"text"|"audio"`, and remaining attachment
   capacity. It sends no human text, audio or private history. ID and binding are
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
