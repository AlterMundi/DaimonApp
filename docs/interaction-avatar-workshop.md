# Shared avatar workshop receiving adapter

## Original source and adapted-byte verification

The selected author source is ASCII-Interfaces
`5967ee3c0295bd60cc04297a5030da653651f766` (Enchanted Archive), following
`4acdb30f85848933d2c50c9557bbc2fc7d51ec9d`. All39 original hashes and the
separate44-file App receiving inventory retain Ani/Oliva attribution.
The authenticated account adapter and saved artwork remain App-owned.
Automatic publication/consumer delivery, compatibility, retention and recovery
are documented in [shared application updates](shared-application-updates.md).

After changing vendored workshop files, refresh only that adapted inventory in
the development checkout, then run its existing validator/store tests:

```sh
python3 -B -m dashboard.avatar_workshop_provenance --update
python3 -B -m dashboard.avatar_workshop_provenance
python3 -B tests/dashboard_avatar_workshop.py
```

Use module execution: running a file directly inside `dashboard/` can shadow the
standard-library `operator` module with the existing local `operator.py`.
The helper changes only `receiving_hashes`; the existing tests refuse changed,
missing or unlisted files and verify retained upstream provenance. It performs
no network, account, avatar or provider operation and adds no runtime admission.
Its atomic metadata replacement preserves a previous hardlinked release;
refreshing an unselected candidate must not edit the selected base inode.

The8November check found six stale adapted hashes after the compact-preview,
hand-anchor and mechanical-mouth changes. Corrected source metadata matches all36
actual selected files on all three original receivers. Those immutable receiving
directories retain their historical metadata file; verification is retained
externally, with no rewrite/restart merely to relabel the same deployed bytes.
Future candidates should take the corrected source metadata alongside the exact
adapted files. This establishes source provenance, not new phone/School/art or
human-hearing acceptance.

## Playback-driven mechanical mouth

An optional invisible `anchor-mouth` path node opts a model into local jaw
motion. It uses existing inert node fields: `fill: null`, no stroke, an authored
hinge pivot and parent. Reparent only the intended lower-shell/jaw parts beneath
it. It adds no format, normalization, saved default or implicit emotion mapping.
The renderer accepts a transient level in five steps0/.25/.5/.75/1 and adds at
most12master pixels of opening and .035radians of rotation at the hinge, on top
of the selected authored pose. Level0 preserves the original drawing exactly.
Models without the explicit invisible node remain unchanged. The saved design,
atlas, nine artistic cues and body/head/hand/finger tracks are never rewritten
by playback. The actor still saves and uses an immutable version explicitly.

The public GPT-Live frontend observes decoded remote output, not input audio,
transcript deltas or completion guesses. Browser playback keeps its existing
HTML audio owner; an outputless local worklet emits only100ms RMS observations
and retains no PCM. Android reuses its existing PCM worklet and selects the
corresponding bounded level only after actual native playback-progress evidence,
not when bytes are received or queued. At most32small RMS ranges are retained;
old source IDs, pause/mute and closed output discard cosmetic observations.
The existing300–600second output bound is unchanged. Observer preparation/resume
has a5second bound; observer failure closes only that cosmetic branch, never
starts a second player/provider or stops the existing browser player.

Avatar pause, reduced motion, hidden pages and the wardrobe suppress live mouth
motion; resuming restores the current account-scoped output level even if it
has not changed. Silence and output closure restore the authored pose. This is an audio
amplitude approximation, not phoneme/viseme alignment or proof of human hearing.
Native Codex WebRTC also observes its decoded remote track through the same
outputless worklet. Its existing HTML audio remains the only player. Track
replacement, physical renewal and closure retire the old observer; a delayed
preparation cannot attach to a successor. Mute/pause and silence clear the
transient level, and an unavailable cosmetic observer leaves voice running.
This adds no microphone, ASR, native handoff, provider session, renewed allowance
or durable audio. Legacy speech paths do not acquire the output-level signal
merely because their custom renderer supports the optional anchor.

`QUALIFICATION_CODEX_ACTIVITY=1` in the existing
`tests/session_workspace_browser.js` drives the shipped native engine with a
synthetic660Hz remote track through real Chromium audio/worklet code, while a
different local input tone continues. It checks output/silence/pause/resume;
the native engine regression separately covers same-peer track changes, two
physical renewals, retired callbacks, late observer preparation and optional
observer failure. Synthetic sockets do not prove provider or physical-device
acceptance. Receiving state remains in Shared Resources, not this source guide.

[Official GPT-Live migration guidance](https://developers.openai.com/api/docs/guides/live-migration#adapt-the-connection-and-audio-lifecycle)
requires client-side playback tracking and supplies no spoken-response-end event.
Synthetic PCM/Canvas qualifications must stay distinct from physical phone,
artistic and human-hearing acceptance. No real audition is needed for these
local rendering/ownership checks; preserve all retained samples and unknowns.

## Inspect a saved revision at Conversation size

In the existing workshop, **Ver junto al nombre** is available after saving or
reopening a clean immutable revision. The parent reads that exact actor-owned
record, verifies its ID and canonical SHA256, and renders it beside the current
companion name using the installed renderer and compact frame dimensions.
This is a read-only preview: no Save, Use, active/editing pointer, generation,
voice preference or ledger mutation. Unsaved changes disable the entry.

The preview runs at most one local animation cycle (up to120frames); reduced
motion starts still and offers an explicit Animate once button. Closing it,
leaving the workshop, switching to Voice or changing account removes it;
backgrounding stops its timer. Delayed reads cannot reopen a closed preview or
cross the captured account/iframe binding. A changed record digest refuses.
No providers, external assets or animation calls to a model are involved.

The bridge accepts only `preview` with `{id: revisionUUID}`. Its reply contains
`id`, `sha256` and `view: compact_header_preview`; it is display metadata, not an
authoritative review, child contribution, mission receipt or achievement. School
still needs its actual retained mission/space/actor binding and private-workspace
return. A general wardrobe preview does not create that authority.

The mounted browser qualification uses synthetic actors and actual editor,
storage API and Canvas renderer. Run with `COMPACT_PREVIEW_ONLY=1` through
`tests/dashboard_avatar_workshop_browser.py`, selecting the existing Playwright
module and Chromium executable via their documented environment variables.
It checks immutable readback, no writes/activation, finite animation, reduced
motion, short-phone controls, hash mismatch and delayed old-account refusal.
This does not establish physical-device or artistic acceptance.

## Exact saved-design export for an authorized host

`GET /api/interaction/avatars/{revision UUID}?format=canonical` returns the
unchanged UTF-8 canonical design saved by the selected workshop validator.
Its SHA256 equals the normal immutable record's `sha256`; the quoted ETag is
`sha256-<digest>`. The default `format=record` response remains unchanged.
The same actor/grant checks apply before and after reading. Responses use
`private, no-store`, never a shared cache or an unauthenticated download link.
This read changes no revision, editing/active pointer, generation or ledger.
An invalid digest, missing/foreign revision or changed access returns no design.

The School host must first resolve its existing retained mission request,
selected space/daimon and authenticated actor. It can read the immutable record
and its canonical export, compare the digest, and retain those exact bytes in
the already authorized private learner workspace. Browser/imported references
are not authority; this API accepts no learner, workspace path or destination.
Reopened workshop/compact-preview evidence and genuinely attributed child
participation remain separate requirements for the owning School ledger.
Export or Save alone does not activate an avatar or earn an achievement.
Actual mission entry/return and child receiving acceptance remain pending.

Nicolas selected integration into the existing DaimonApp goal on6November2026.
Oliva authored the original handoff for Ani. The pinned MIT implementation is
ASCII-Interfaces 4acdb30, handoff990dce9; module hashes and the original license
are retained in `dashboard/web/avatar-workshop/PROVENANCE.json`. The original wardrobe editor, model/design validator, rendering dependency
closure and authored firefly example are included. The receiving adaptations
are listed separately from pinned original hashes. School media, viewer state, private histories and credentials
are not part of this source selection.

`avatar_workshop.py` prepares durable per-account versions in the configured
App state root, which belongs to one receiving being. Its HTTP adapter is now
mounted in source through the existing App shared login/Companion grants and
CSRF. It derives the actor from that session and refuses monitor access to the
version library. Receiving selection is recorded below.
An actor ID in an imported design or browser request is never authoritative.
This adapter creates no account, grant, provider session or peer activation.

The original `model.mjs` validator normalizes `ascii-quest-design/v2` and its
distinct inert `ascii-avatar-model/v1` and backwards-compatible raster-layer
`ascii-avatar-model/v2` extensions. It is invoked only for a manual
save/import through the fixed local Node entry, never as a rendering loop or
imported program. Node20+ is a receiving dependency: at most two validators,
four seconds each,64MiB JS heap,1MiB input and512KiB canonical output. Missing or
failed validation preserves the previous selection. The same canonical string
and SHA256 used by the original workshop remain attached to each immutable
version; validation and actual rendered geometry remain separate checks.

Each account document atomically retains its flat version list, generation and
two pointers. Saving or selecting an editing revision does not change the active
avatar. Explicit use selects an existing saved revision with an exact generation;
a stale action refuses rather than overwriting a later choice. Repeating the same
save ID with the same canonical content reads the retained result without changing
pointers, even after a later selection. A different payload cannot overwrite that
revision. Child versions preserve their design identity and an owned parent.
The existing private-file reader, atomic writer and finite metadata lock are reused.

Bounds are32versions/8MiB per account and64account files/32MiB committed data per
App authority. One atomic replacement can temporarily add at most8MiB, for a40MiB
data ceiling plus small lock/filesystem overhead. Capacity refuses further writes;
there is no implicit deletion, media retirement or unbounded log. Existing saved
versions remain readable. The reused editor exports editable JSON, SVG and ASCII and imports inert
models/designs or bounded images. Explicit version removal remains unimplemented; no historical avatar is removed by this component.

Seven actual-Node/storage tests cover a catalogue design and custom firefly,
save/reload/edit/use, prior-avatar preservation, account isolation, immutable
lost-ACK readback, generation conflicts, parent identity, quota refusal and unsafe
file rejection. Six additional mounted tests cover grants/CSRF, save/reload/use,
foreign account refusal, access revocation after commit and oversized input.
They use a test authorizer with the actual grant allowlist and storage validator;
real Home-cookie/device and receiving delivery acceptance remain separate.
The mounted browser adapter reuses that editor inside a same-origin dialog,
with a closed parent-message contract. The parent owns existing authenticated
API calls and CSRF; credentials never enter iframe URLs or messages. Catalogue,
custom model, image conversion, eight authored expressions, colour, large/compact
previews, per-expression object plus floating detail and editable export/import
remain the original implementation. Editable JSON export uses compact serialization
so a valid bounded design does not exceed the import limit just from indentation. Account listing contains summaries; a design
is loaded only when editing or using that version. No IndexedDB becomes authority.

Saving updates only the editing pointer. Use pre-renders the saved candidate
with the same renderer, then conditionally activates its exact generation before
replacing the previous portrait. A refusal keeps the previous portrait. Unknown
write outcomes require a fresh state read, never an automatic replay. Cancel does
not change the active pointer or discard saved revisions; unsaved edits receive
the original discard prompt. Editing controls start inert while the account
loads, preventing a late initial read from overwriting an early import. Back can
close an editor that has not loaded yet. Artist cues do not consume activity/mic
state; the existing operational captions remain independent.

The compact conversation canvas renders the original12-frame models locally at
at most one frame per180ms plus rendering time, with one resize observer. Hidden
documents, the open editor, manual pause and reduced motion suspend ambient
animation. A resize redraws a still frame. The dialog uses receiving appearance
roles without recolouring authored art;320/375layouts retain the original tabs,
keyboard controls, touch targets and local reduced-motion alternatives.

`tests/dashboard_avatar_workshop_browser.py` runs the actual shipped editor and
Canvas2D renderer against mounted App endpoints and real temporary account files.
It uses synthetic authorizers, not Home cookies or actual paired actors. Catalogue
and custom-model save/use/reload, prior-avatar preservation, activation refusal,
image fallback, simultaneous object/detail persistence, editable JSON export/import
roundtrip, original keyboard tab navigation, actor isolation, reduced
motion and375/320layouts passed in Chromium. Run it with the existing installed
Playwright module (`PLAYWRIGHT_MODULE`) and browser (`CHROMIUM_EXECUTABLE`); it
owns one temporary server/browser/state root with a120second cap. Optional
`WORKSHOP_SCREENSHOT` writes one selected PNG; it creates no HTML artifact or
private data publication. Source API/storage suites remain ordinary CI.

## Explicit reply artwork cues

The selected custom portrait can follow the same optional artistic rest cue as
new canonical replies. ConversationCompanion remains the single admission point:
source kind, revision/time ordering, duplicate rejection and selected expression
pack/catalog checks run before the custom renderer sees a cue. Microphone and playback retain their independent operational presentation.
Temporary evidence-driven reactions can override the authored cue as described below.
Operational captions and the header glow continue to describe their actual state.

The wardrobe uses only an existing `local/v1` gesture in the active saved design.
Native `focused` maps to `focus`, and `delighted` to `joy`; supported gallery keys
can match an admitted per-being pack cue directly. `listening` and `speaking`
have no invented wardrobe mapping. Missing/unmatched hints or gestures restore
the design's saved default. This does not expand the native hint vocabulary or
claim lip sync, emotion detection, all-nine automatic expression selection or
new artwork for a flat image.

Cue selection changes only the renderer's validated in-memory copy. No Save,
Use, account generation, stored revision, API call, provider attempt or atlas
allocation is triggered. The existing one-frame timer, pause, reduced motion,
editor/background suspension and compact/large rendering remain in force. An
arriving hint can update a still expression while animation remains paused.
Actor reset clears transient selection; source/catalog reset restores the saved
default. A hint received before active-art loading is applied to that same loaded
candidate, without another fetch or selection write.

The focused Chromium case (`ARTISTIC_CUES_ONLY=1` with the existing browser
runner) uses the actual companion, raster renderer and mounted synthetic-actor
storage. It checks visible focus/default differences, old-source rejection,
operational separation, reduced motion, unchanged stored revision/pointers and
actor reset. Full editor/voice/save/reopen/cancel and isolation qualification
remains separate. Real phone and artistic acceptance are still required.

## Receiving selection —6November2026

All three registered living services now select the qualified31e70a0 common web
composition: CompAII on ITACA, Eko on MEDUSA and Oliva in its active ITACA KVM.
Compatible overlays preserve each receiver's local Matrix adapter and private
configuration. Actual local/public workshop entry and renderer bytes, existing
owner entry reads, foreign-account refusal and service continuity passed. The
13 storage/mounted tests also ran as each consuming service user with its actual
Node runtime. These tests use synthetic accounts and temporary design files;
no production account's avatar was saved or activated by qualification.

CompAII keeps its separately selectable native public voice comparison and prior
voice defaults. Eko keeps Avatar voice ON and Oliva OFF; OpenAI remains OFF on
both. Native/Core/Sessions processes and configuration stayed unchanged. Eko's
existing web service now receives its prepared Node22 runtime through a scoped
service PATH entry; CompAII and Oliva use their existing/installed Node20. The
actual service environment and consuming-user execution were checked. Node runs
only for bounded manual validation; it is never invoked per rendering frame.

Reload the ordinary authenticated Conversation and choose **Personalize avatar**.
The editor offers preview/save and an explicit Use action; saving does not replace
the current portrait. Keep the actual prior web selection as software rollback,
plus the owned service-unit/PATH preimage where applicable. Rollback preserves
all account versions, existing originals and native work; never restore databases,
delete personal designs or repeat an uncertain save/activation.

Real shared-Home-cookie save/reload/use, cross-device synchronization, physical
touch and school/Oca/child acceptance remain open. Native designPack qualification
and the full original goal remain open. Public served files and synthetic browser
journeys do not prove a human's successful use or authorize enabling another
pair's Avatar, voice, provider, heartbeat or native-display flags.

## Retained wardrobe source sync —8November2026

The initial sync selected Ani/Oliva ASCII-Interfaces e1ef54b, followed by4acdb30's
pillow refinement; original and adapted hashes stay distinct in PROVENANCE.json.
The six authored bodies support per-body
primary color, hex prop colors, three independent prop slots, eight acting hand
objects and nine artistic cues (including Sueño/pillow). The editor keeps the
current game-side tools, undo/redo and one-step surprise choices. Imported inert
models retain their existing eight-cue contract and calm fallback; no runtime
availability/quota event is guessed from model text. Confirmed native limits may
select the temporary sleep reaction described below.

The existing receiving storage bridge is unchanged: account/CSRF authority,
immutable revisions, lazy full-design reads, generation-fenced explicit use,
cancel, previous-art preservation and lost-ACK readback remain authoritative.
The editor is inert in the initial HTML until account bootstrap completes, so an
early import cannot race the lazy initial read. The original artifact's IndexedDB
store is not copied. No production account was written during qualification.

New design semantics survive the existing bounded Node validator: bodyColors,
hex prop colors and accessory/v1 are preserved instead of silently normalized
away. The renderer returns finite frame/cadence metadata on its existing paint
callback; the parent's single timer consumes12/48frame loops rather than
truncating current acting at12. Old12-frame designs retain180ms parent cadence;
new cadence is clamped80..320ms. Pause, hidden document, reduced motion and an open
editor continue to suspend ambient animation. Resize redraws the current frame.

Validation includes actual Node/account storage round-trip for six body colors,
sleep and pillow; mounted grants/isolation/assets; and actual Chromium current
editor→save→use→reload,48-frame rendering/loop closure and the retained custom,
image, cancel, failed-activation, shared appearance and320/375journeys. Actors
and account files are synthetic/temporary; voice checks use synthetic audio and
no provider. These source changes are not receiving-deployed or human accepted
merely because local tests pass. Preserve the dated receiving selection above.
School/Oca evidence integration remains owned by the school's pending contract.

## Raster part authoring — prepared receiving extension

The existing model import accepts `ascii-avatar-model/v2`. It retains path and
ellipse nodes and adds raster nodes: `rect: [x,y,width,height]` selects integer
pixels from one inline atlas; `bounds: [x,y,width,height]` places them in the
576 by720 drawing space. Optional `clip` is a3–64point closed polygon in drawing
coordinates. Node parent/pivot and the existing12-frame x/y/rotate/scale tracks
move each part independently. A cue pose can change its atlas rectangle, bounds
or clip. The eight v1 cues remain required; v2 also permits authored `sleep`
poses/tracks without changing v1 or inventing missing poses.

The atlas is at most256 by256 pixels, with1–256RGBA `#rrggbbaa` palette entries
and canonical base64 of exactly one palette-index byte per pixel. It contains
no URL, executable content, image decoder, SVG or asynchronous media request.
Existing64nodes,4096geometry-command/clip-point budget, depth8,128tracks/cue,
12frames/channel, transform limits and App import/storage quotas remain. One
WeakMap cache holds one decoded atlas per live normalized model; no extra timer
or persistent browser store is added. Saving remains separate from Use.

Reuse `skills/ascii-avatar-author/scripts/raster-model-author.mjs` to pack
transparent part canvases into this format. Its fixed216color palette plus
transparent index fits the existing256KiB model importer; it quantizes color
and binary alpha rather than claiming lossless source-image fidelity. Supply
separate torso, head, eye/shutter, mouth, arms, hands and individual finger parts,
with clean overlap pixels, pivots and authored cue changes. A flat PNG cannot
supply unseen joints or hidden surfaces. Cutting a portrait into rough rectangles
is a prototype, not accepted faithful articulation. Preserve the original art
and source hashes outside the model; import the prepared JSON through the
existing wardrobe. No separate editor, account or publication is required.

`tests/avatar_layer_model.mjs` checks bounds, rejected external/malformed pixels,
hierarchy/cue validation and canonical roundtrip. The durable storage suite covers
save/reopen/hash and actor isolation. `tests/avatar_layer_model_browser.cjs`
checks actual Canvas pose textures, head-relative finger movement, clipping,
sleep and unchanged pixels outside moving parts, plus the authoring packer.
These synthetic checks prove renderer capability, not completed character art,
deployment, live-avatar activation or human/device acceptance. Existing v1
example normalization remains byte-identical to the pre-extension result.

After the first v2 save, keep this compatible validator/renderer in any web
rollback; an older reader rejects the saved raster model. A software update
alone must not create a v2 production revision or change the active avatar.

## Portrait HUD controls

The shared portrait frame holds compact, labelled gear and pause/play icons on
its left edge. The existing editor and manual/reduced-motion/visibility pause
policy are unchanged. The pending/status row paints above overlapping artwork
and keeps its actions reachable; the scroll-compact header hides the entire
portrait frame. This is an incremental control/layout correction, separate from
the shared-world graphic study and any future world-engine implementation.

Earlier voice-page retrieval controls live under the existing diagnostic panel,
so the ordinary reading surface is free of engine-specific history buttons.
The original bounded retrieval and attributed transcript rows remain unchanged;
opening diagnostics and loading a page does not open voice or admit new work.

The selected portrait uses one stable interaction surface for both the built-in
and custom drawing. Click or Enter/Space opens the existing Avatar voice view;
that same surface moves into the view and returns on close. Gear/pause controls
are siblings, so editing or pausing does not start voice. The canvas and built-in
portrait share the top origin. While authenticated selection is unresolved, the
built-in drawing stays hidden instead of flashing before the custom revision.
An unavailable selection keeps the workshop retry/status path, without guessing
that the built-in avatar was selected. A failed read ends the busy indicator;
opening the workshop explicitly retries the selected revision. Ordinary binding
polls do not retry, and recovery never saves, activates or auditions a voice.
Successful readback clears the error; account reset removes the previous art.
Listening/speaking evidence lights the full header for either portrait; authored
expressions do not manufacture operational microphone state.

The standalone Conversation response selects its heading, feedback and layout
classes in the initial HTML, before deferred scripts or authenticated reads.
The separate Sessions entry retains its own shell. Inherited Home CSS remains
render-blocking; do not hide the application indefinitely while waiting for
appearance events or use appearance to admit access. Shared-auth attributes and
explicit inherited-style policy coexist on the same HTML element.


## Rejected preview starts

A model_not_found diagnostic is terminal only for the existing single-start Live
preview transport with a released connection, no session.started identity, no
audio/format and the matching frozen cache identity. That transport sends only
one session.start until startup; no commentary, silence or other command can
precede it. The new rejected_before_start outcome describes that rejected
request, not session.closed, a zero-charge claim, an attempt refund or a retry.
Other errors, missing diagnostics, started sessions, audio or unknown outcomes
stay held. Account/grant/config checks and the four-batch limit are unchanged.

The existing explicit retirement path verifies an exact hash of the rejected
state and absence of audio under its speech-job lock before cleanup. The original
uncertain batch without this proof remains. A later explicit Play prepares a new
identity after access is corrected; it never replays the rejected/uncertain one.
Old readers may show the new terminal state but cannot retire it; retain this
reader until a claimed retirement completes. Preserve an operator receipt of
the observed rejection and selected retirement, never invent finalization.

Confirmed session closure does not make an audition successful: the bounded
Live renderer retains its fixed provider/mismatch/no-audio classification in the
closed receipt too. Preview readback keeps that sanitized cause even when usage
and session.closed are confirmed. No raw provider message/credential is exposed;
closing does not authorize replay, regenerate audio or claim human hearing.

### Primary Live preview media

The primary WebSocket's `session.output_audio.delta` is ordered media without
`event_id`; see the official [LiveOutputAudioDelta schema](https://developers.openai.com/api/reference/resources/live/primary-websocket#session.output_audio.delta).
Process every chunk in order, preserving identical consecutive bytes. Keep
metadata event identity/digest deduplication separate. Existing startup model,
voice, format, frame count, PCM alignment/size, duration, close/finalization and
no-reconnect bounds remain. The post777 real attempt retained event_validation
and0PCM; this contract correction is source-qualified, not a claim that its
unretained specific event was recovered or that a new real sample succeeded.

## Held objects on an articulated custom model

Existing hand anchors remain rest-space points. To attach a hand-held object to
a moving hierarchy, author an inert `path` node named `anchor-leftHand` or
`anchor-rightHand`, parent it to the corresponding palm, and keep the matching
`anchors.leftHand`/`rightHand` point. A one-command path with null fill/stroke
provides an invisible attachment. The renderer applies that node's full existing
parent/pivot/track chain to the point for the selected cue/frame. This changes no
schema, saved normalization or storage; models without these explicit nodes keep
static anchors. All existing node/depth/track bounds still apply. Floating details
stay independent, so a held object and a floating symbol can coexist. Object
orientation retains the existing accessory drawing; this is position attachment,
not a grip, collision or finger-contact solver.

`tests/dashboard_avatar_hand_props_browser.cjs` checks actual composed Canvas
movement with a simultaneous stationary detail, nested parent rotation/scale and
legacy static anchors. Use the existing `PLAYWRIGHT_MODULE`/`CHROMIUM_EXECUTABLE`
settings. It owns a temporary local HTTP server/browser and makes no provider or
production storage calls. Physical touch and artistic contact remain separate.

## Temporary receiver reactions — Ani/Oliva iteration

The existing ConversationCompanion observer resolves temporary reactions before
its admitted reply cue (or the saved design default). This only calls the existing
in-memory renderer selector. It does not save, activate, change account generation,
choose an accessory, call a provider, or change task/microphone state. The authored
accessory remains selected and its existing expression interaction runs normally.
Unsupported custom-model expressions fall back through the existing renderer.

Priority: fresh observed integrator/worker execution or tools -> focused; actual
pending question or native waiting_for_human -> curious; native blocked -> uncertain;
all observed native sources explicitly usageLimited/budgetLimited -> sleep. A
single limited sibling, unknown/truncated sources, idle active goal, error,
paused goal or disconnected receiver must not imply exhaustion. Native limits
are usage/budget observations, not a claim of remaining model context tokens.

A fresh same-source active-to-complete observation yields delighted for1.6seconds;
initial or repeated complete snapshots do not replay it. A fully observed healthy
idle return from sleep yields welcome for1.6seconds. Work/questions/limits override
these brief pulses. Afterwards the admitted reply cue or saved default returns.
Freshness expires within20seconds (including source age) without another poll.
Account reset and pack replacement clear transition memory/pulses. Existing pause,
reduced-motion and hidden-view behavior remains. Native state is read through the
existing sonic observer even with sound disabled; no new polling route is added.

Qualified with synthetic observer transition/time tests and real Chromium
companion-to-custom-canvas checks, preserving authenticated revision bytes,
pointers/generation and zero write/provider requests. This is source qualification,
not receiving deployment or physical device acceptance.

## Expired audition audio is separate from its receipt

A rendered generation receipt remains historical evidence after the bounded
speech cache removes its WAV. The workshop must not keep advertising that row
as playable. Preview reads add `audio_state: expired` only when the owner-bound
cache identity, source-text hash, voice/language and stored audio digest/format
match the receipt, the cache records expiry, and the WAV is absent. A missing or
altered file alone is not proof of expiry.

This is a read projection: original render state, finalization, counters, saved
voice and avatar revisions remain unchanged. An exact retained-audio read (or
Render of an already-rendered row) returns no audio with that status instead of
starting synthesis. Retention finishing between the history view and the audio
read follows the same path. The client labels the sample Audio expired, removes
its Play action and explains the race without claiming playback or generating a
replacement. Unknown attempts and normal explicit retirement retain their
existing rules; expiry does not refill the four-batch allowance.

## Archive Enchanted receiving presentation

The wardrobe keeps Ani/Oliva's selected game composition: local Pixelify Sans and
Nunito fonts, shared SVG controls, the selected letter import tile, upright name
sticker, centered ascii-avatar.exe title and folder check, grouped retro sliders,
face-focused expression thumbnails and bounded desktop trays. The former slogan
is removed. Receiving material/text roles still follow the existing appearance
bridge; artwork retains its authored palette. Parent navigator-hud selection no
longer replaces this selected wardrobe with the superseded HUD skin. Its pre-paint
presentation script remains a valid served .mjs asset; the surrounding Conversation
and Voice workshop keep their independent current presentation.

This source update is independent of School mission integration. Save, compact
saved preview and explicit Use keep the current account bridge. Store, validator,
canonical revision identity, attached hands, output mouth activity and reactions
are unchanged. Only the two declared local font paths extend public asset serving;
private/arbitrary fonts and provenance stay refused. Font and icon license texts
remain bundled with the source. Receiving adoption and actual human visual/device
acceptance need separate evidence.

The Archive UI/header/artwork handoff objects retain their original snapshot
hashes. The complete `receiving_hashes` inventory is authoritative for current
bytes. PR771 is reused for the original Archive drawings and local fonts; the
receiving appearance CSS is separated from upstream archive.css so normal
maintainer stylesheet additions do not require another manual theme merge.
