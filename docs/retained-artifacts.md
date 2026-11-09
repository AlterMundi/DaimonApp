# Retained generated files

An actual native execution writes deliverables in its existing turn output
folder. With `interaction.artifact_store` configured, Telecodex registers a
separate durable byte-copy job at each canonical final response, even when a
continuous goal execution remains active. Jobs are keyed to that actual native
response, rather than only to the longer collector execution. The native
conversation can accept its next input while files wait for storage. Restarting
resumes only copying; it never repeats native work or a user message.

```toml
[interaction.artifact_store]
directory = "/absolute/private/generated-files"
retention_hours = 24
max_file_bytes = 67108864
max_total_bytes = 536870912
```

The directory must be private, owned by the service account and dedicated to
this receiver database. It is bound to that database; a different receiver
cannot adopt the same directory silently. Configure large output storage on the
host's established data filesystem. The output anchor is captured before native
execution and checked again when copying, including after restart. Each new
response freezes its bounded filename/metadata selection: files added later
cannot be attributed to an earlier response, and changed files are refused.
Unchanged already retained files keep their original attribution and are not
published again with every goal continuation. At most ten
top-level regular files are considered per execution, with configured byte limits.
Symlinks, directories, hard-linked files and replaced output directories do not
become downloads. Copied bytes are hashed and frozen under content-addressed
names. The registry binds each reference to its actual native item, source
execution, human and logical session audiences; model-supplied paths provide no
file authority.

Files appear alongside their canonical reply as they become available. Pending
copying and partial failure are visible. File arrival, expiry or failure does not
change the spoken text revision or restart narration. Generated file bytes are
separate from transient ASR/TTS audio handling. Canonical transcripts and metadata
remain retained. Payload expiry is checked before and during download; expired
stored blobs are collected on subsequent file storage operations. Original turn
outputs remain preserved for recovery; this is not a blanket workspace deletion
policy.

The source session can access its files. An integrating conversation gains access
only through instructions actually accepted by that execution and covered by the
recorded native result. A goal collector instead uses its acknowledged native
execution and the exact original conversation input frozen with its canonical
final item. A later direct-surface selection does not grant another conversation
access. Already retained goal files are recovered from that existing proof when
read; no goal, model work, copying or publication is repeated. Logical session ownership continues across supported
native renewal; the old physical thread need not remain current. Owner or
audience changes deny access. Downloads return attachments, never inline active
content or public links, and verify the immutable size/hash again. The browser
checks the received hash before offering the download.

Owner-authenticated conversation access can retrieve files. Device credentials
require a separate explicit file entitlement; old credentials default to no file
access, and monitor-only credentials cannot gain it. Owner-local commands:

```sh
python3 -m dashboard.companion --config dashboard.json enroll --help
python3 -m dashboard.companion --config dashboard.json artifacts GRANT_ID --allow
python3 -m dashboard.companion --config dashboard.json artifacts GRANT_ID --deny
```

Use the existing supported enrollment arguments and `--artifact-access` for a
new selected conversation device. Changing this one entitlement does not replace
its credential, extend its lifetime or authorize other controls. Inspect metadata
through `presentation artifacts list` and `presentation artifacts detail UUID`
on the existing owner control socket. HTTP GET endpoints are
`/api/interaction/artifacts` and `/api/interaction/artifacts/UUID`.

With both retained storage and selected topic projections enabled, generated
files use the same canonical publication queue as text. Frozen bytes are uploaded
to their source topic using the existing photo/audio/video/document policy. A
canonical artifact/destination identity owns one publication, including after
restart; a lost acknowledgment remains uncertain and is not retried automatically.
The primary web return and later native inputs remain independent of this upload.
Text and files retain separate per-topic leases in that same queue, so slow
uploads do not hold later text. A short plain caption identifies the file and
its original canonical answer. Two upload buffers are allowed at once,
independently of native worker slots.

A direct turn using these explicit features defers its source-file upload to that
same queue rather than also uploading its mutable workspace copy. Without the
selected features, ordinary file handling stays on its existing path. Registry
eligibility never intercepts direct input or consumes the router worker quota.
Canonical text projections and file copying are separate from admission and never
consume another model turn. Native compaction, real
receiving adoption and subjective phone experience require the integrated
qualification campaign; fixture passes alone do not certify them.

Focused automated evidence is in `tests/artifact_access_http.py`,
`tests/artifact_return_io.py`, `tests/artifact_projection_io.py`, the artifact Rust tests and the generated-file
cases in `tests/conversation_ui.js`. The process fixture checks actual private
file bytes through the bridge and authorized HTTP route, blocked storage with
same-session successor admission, restart without native replay, partial refusal,
stable spoken revision, scoped grants and source renewal. Its native peer is
synthetic and uses no model.

The source-projection fixture holds an actual multipart upload while admitting
the next input to that same session, checks original text/image bytes and media
fields, loses one ACK and restarts the bridge. It waits for retained publication
outcomes, then verifies no native work or file upload is replayed.

Continuous-collector adoption migrates legacy one-job-per-execution records
transactionally without dropping their outcomes. Keep a compatible native reader
after that migration; a web/UI rollback must not reinstall the older job writer.
Original audio and artifact bytes remain retained. Delivery and hearing still
require actual observations; a local path written in Markdown is not an attachment.


## Explicit retained-output recovery

An output created before storage was configured may lack a durable copy job.
An owner can recover selected existing bytes through the same native writer:

```sh
telecodex --control OWN_RECEIVER_CONFIG input artifacts recover '{"binding":"CURRENT_BINDING","local_turn":5,"directory":"/own/workspace/.telecodex/turns/5-11111111-1111-4111-8111-111111111111/out","output":{"native":"EXACT_NATIVE","turn":"EXACT_TURN","item":"EXACT_FINAL_ITEM"},"files":{"drawing.png":"EXACT_SHA256"}}'
```

This is an explicit owner association with an actual completed final in the same
logical conversation; it does not claim historical automatic capture. The selected
output directory must belong to that execution under its own current workspace.
Descriptor-relative reads reject symlinks, hard links, changed bytes and unexpected
owners. Current owner/grant/generation and the canonical final are checked in the
same transaction that registers the existing copy job. Copying verifies the frozen
SHA256 again. Existing jobs keep their original immutable selection. No native
turn, prompt, image generation, email, topic publication or original input is replayed.
The operation is owner control, not an additional browser/device write capability.
Inspect the existing artifact list for actual availability afterward.

PNG, JPEG and WebP attachments up to8MiB offer **View image** in their original
reply. They use the same authenticated immutable download and full hash check;
no public link or external viewer is created. At most four previews/16MiB stay
open per page, sharing the existing two-download limit. Close, removed replies,
expiry, binding reset or file-access revocation releases their object URLs.
Other files keep the existing verified download/Android Save behavior.
