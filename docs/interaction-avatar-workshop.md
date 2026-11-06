# Shared avatar workshop receiving adapter

Nicolas selected integration into the existing DaimonApp goal on6November2026.
Oliva authored the original handoff for Ani. The pinned MIT implementation is
ASCII-Interfaces e86b940, handoff990dce9; module hashes and the original license
are retained in `dashboard/web/avatar-workshop/PROVENANCE.json`. The original wardrobe editor, model/design validator, rendering dependency
closure and authored firefly example are included. The receiving adaptations
are listed separately from pinned original hashes. School media, viewer state, private histories and credentials
are not part of this source selection.

`avatar_workshop.py` prepares durable per-account versions in the configured
App state root, which belongs to one receiving being. Its HTTP adapter is now
mounted in source through the existing App shared login/Companion grants and
CSRF. It derives the actor from that session and refuses monitor access to the
version library. This has not been selected on a receiver.
An actor ID in an imported design or browser request is never authoritative.
This adapter creates no account, grant, provider session or peer activation.

The original `model.mjs` validator normalizes `ascii-quest-design/v2` and its
distinct inert `ascii-avatar-model/v1` extension. It is invoked only for a manual
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
file rejection. Five additional mounted tests cover grants/CSRF, save/reload/use,
foreign account refusal, access revocation after commit and oversized input.
They use a test authorizer with the actual grant allowlist and storage validator;
real Home-cookie/device and receiving delivery acceptance remain separate.
The mounted browser adapter reuses that editor inside a same-origin dialog,
with a closed parent-message contract. The parent owns existing authenticated
API calls and CSRF; credentials never enter iframe URLs or messages. Catalogue,
custom model, image conversion, eight authored expressions, colour, large/compact
previews, per-expression object plus floating detail and editable export/import
remain the original implementation. Account listing contains summaries; a design
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
image fallback, simultaneous object/detail persistence, actor isolation, reduced
motion and375/320layouts passed in Chromium. Run it with the existing installed
Playwright module (`PLAYWRIGHT_MODULE`) and browser (`CHROMIUM_EXECUTABLE`); it
owns one temporary server/browser/state root with a120second cap. Optional
`WORKSHOP_SCREENSHOT` writes one selected PNG; it creates no HTML artifact or
private data publication. Source API/storage suites remain ordinary CI.

The receiving UI/HTTP implementation is source-only, not a deployed workshop or
real shared-Home/multi-user/device acceptance. Node20+ availability, account-bound
save/reload/use on each living receiver, physical touch/hearing and school/Oca/
child acceptance remain open. Native designPack qualification and the full
original goal remain open. No voice/default/heartbeat/native-display flags change.
