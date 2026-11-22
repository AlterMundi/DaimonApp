# Scoped original-audio handoff

An explicitly selected dialogue can preserve original incoming recordings and
actual generated speech for an archive consumer. This is a producer handoff,
not an archive assembler, transcription service or speech-regeneration job.
Default operation and all unselected conversations keep their existing retention.

Configure this optional table in the existing dashboard owner-local TOML:

```toml
[media_retention]
directory = "/private/selected-dialogue/producer-originals"
human_id = 100
chat_id = 100
topic_id = 1
native_thread = "11111111-1111-4111-8111-111111111111"
since = "2026-10-29T00:00:00+00:00"
max_bytes = 268435456
```

The exact authenticated human, entry and native thread must match certified
server provenance. The timestamp fences older committed human captures; it is
not permission to retrieve other history. Native renewal does not widen the
selected dialogue. The table stays local; portable source contains no actor
bindings. Enabling it records nothing by itself and starts no process or timer.
It applies to finalized recordings through the independent conversation composer
and its native presentation speech, not Telegram audio ingress, ambient microphone
input or another program's recording path.

Incoming originals are first synced to the existing bounded receiver capture
store. Selected media normally enters the archive handoff before native
submission. A compatible writer advertising `voice_original_hold:v1` may instead
persist an owner-selected `voice.preserve_original=true` with that exact capture
when handoff capacity is unavailable. Native ASR completion/restart then cannot
unlink it; a transcript alone is insufficient. Status/list cleanup requires a
verified matching archive receipt before retiring a held source, even if the
capture selection is later removed or changed. An unavailable archive therefore
need not terminate otherwise admitted incoming voice or the Avatar.

This reuses the existing256MiB/128-capture receiver store and256MiB/4096-entry
archive store; no new queue, higher cap, automatic exporter or eviction is added.
Both stores together remain bounded by their existing limits. If receiver space
is exhausted, new admission still refuses before ASR/work and the client keeps
its local recording. Pending handoff is surfaced separately from native message
acceptance. Older writers cannot defer handoff: a507 still refuses before native
admission while preserving the source. Human media's input ID joins the native
input journal; no failure or later retry authorizes another identity/work replay.

Speech reserves at most eight MiB before the renderer starts. Streamed bytes are
synced before being emitted; cancellation retains an explicitly incomplete prefix,
not a complete recording. If a WAV renderer wrote its exact identity-addressed
artifact before parent confirmation was interrupted, that original is retained
as unconfirmed/incomplete without another provider call. Protected audio is
independent of ordinary speech cache expiry. This proves generated/retained bytes,
never that a human heard them. Reused cached originals retain their source;
there is no automatic re-synthesis to recover missing bytes.

## Consumer contract and lifecycle

The directory is owner-private. Complete records are JSON named by a SHA256
receipt identity, with schema `telecodex.original-audio/v1`, speaker, MIME,
original source binding/ID, revision/offset when present, protection start,
`complete`, byte count, content SHA256, `reconstruction=false`, and
`playback=not_observed`. The content-addressed file named by `audio_sha256` is the
exact original. Consumers verify count/hash, retain provenance and import into
one owning archive. `complete=false` means an interrupted/unconfirmed prefix or
outcome; do not label it complete or invent duration. Actual speech reconstruction
for older missing audio is a separate archive action and must be labeled there.

`capture-*.part` plus `.reservation` are pending/uncertain writes. They consume
reserved capacity across restarts; do not mistake them for complete media or
remove them while a producer is active. A crash cannot turn a partial into an
acknowledged original. The consumer/operator may inspect and recover a known
finished prefix under its retained provenance, without replaying speech/input.

The hard receiving maximum is256MiB (including receipts/reservations), with4096
entries. No original is evicted to make room. A full or unavailable store refuses
new archive handoff/speech visibly; existing ordinary text remains usable.
Conservative synthesis reservations can refuse before actual bytes fill the cap.
An identical complete human handoff is reusable at capacity. Incoming captures
may use the compatible native hold described above; speech still reserves its
archive space before generation. Stop only the selected protection by removing its table and applying the existing web-only
configuration replacement at a safe voice boundary. Do not stop Codex/goals.
There is no implicit expiry: protection ends on explicit disable/dialogue close;
retained originals still require a verified consumer transfer and explicit
retirement. Backups and unfinished sources are not disposable cache.

The archive owner is responsible for its separately bounded final archive and
releasing producer copies only after verified incorporation. There is no new
background observer, public download route, authority grant or global retention
increase. Code rollback preserves the protected directory and journals; do not
restore databases, replay inputs or discard pending reservations.

## Qualification

`tests/dashboard_media_retention.py` covers exact scope, forward-only human
capture, actual renderer bytes, interruption after a generated WAV, actual
streamed bytes before emission and cancellation, cache pruning, restart retry,
capacity/lock errors, HTTP507 and retain-before-unlink. Providers are synthetic;
production installation and a new real selected recording are separate evidence.

## Native hold rollout and rollback

Select the hold-compatible native writer before its Python adapter. New flags
are server-selected from the authenticated archive scope, not accepted browser
metadata. An existing unheld capture cannot be upgraded while its ASR may be
running: archive failure still refuses that retry. The native transaction fences
this boundary even if two adapters race. The existing canonical capture owns
its persisted hold across retries;
a later owner request cannot downgrade it. Default/unselected originals retain
ordinary cleanup. Existing historical originals are not retroactively declared
protected or recovered.

Once held originals are written, old strict native readers that do not recognize
this optional field are not a compatible rollback. Keep the qualified compatible
native reader/cleanup fence selected while reverting web code/configuration if
needed. Preserve source bytes, journals, pending holds and actual work; never
restore an old database or old writer to remove the new protection. Retire a hold
only through the verified handoff/cleanup path. The separate archive consumer
still owns selection, institutional Drive transfer/readback and explicit archive
retirement; temporary producer capacity is not permanent archive storage.

`tests/conversation_voice_http_io.py --archive-hold` uses actual native ASR
completion and restart to verify the source survives archive capacity, receiver
capacity refuses before admission, exact retry creates no second ASR/work, and
later exact handoff permits cleanup. `--archive-legacy` verifies old-writer
refusal. All peers and transcription are synthetic; this is not phone acceptance.


## Full incoming capture store

The receiver's 128-original/256MiB admission refusal is a known storage failure
(HTTP507), not an uncertain native delivery. The browser keeps the same local
original and offers storage recovery guidance; Check delivery reads status only.
An archive handoff may already be full while the disk itself has ample capacity.
Do not diagnose this from filesystem free space or retry recognition/native work.
Inspect both bounded stores and their actual consumer incorporation receipts.
Preserve protected/uncertain originals and existing limits; retire producer copies
only through a verified owning archive transfer. Status and transcription success
do not establish that transfer or make an unhanded-off original disposable.
