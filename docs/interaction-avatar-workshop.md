# Shared avatar workshop receiving adapter

Nicolas selected integration into the existing DaimonApp goal on6November2026.
Oliva authored the original handoff for Ani. The pinned MIT implementation is
ASCII-Interfaces e86b940, handoff990dce9; module hashes and the original license
are retained in `dashboard/web/avatar-workshop/PROVENANCE.json`. Only the selected
model/design validation and rendering dependency closure plus the authored firefly
example are included. School media, viewer state, private histories and credentials
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
versions remain readable. Explicit export/removal UI and its acceptance remain
unfinished; no historical avatar is removed by this component.

Seven actual-Node/storage tests cover a catalogue design and custom firefly,
save/reload/edit/use, prior-avatar preservation, account isolation, immutable
lost-ACK readback, generation conflicts, parent identity, quota refusal and unsafe
file rejection. Five additional mounted tests cover grants/CSRF, save/reload/use,
foreign account refusal, access revocation after commit and oversized input.
They use a test authorizer with the actual grant allowlist and storage validator;
real Home-cookie/device and receiving delivery acceptance remain separate.
Still implement the existing workshop editor/storage bridge,
large/compact/colour renderer use, preview/use/
cancel, image fallback, simultaneous object/detail controls, import/export and
touch/keyboard/reduced-motion acceptance. Artistic cues must remain authored
choices rather than agent/microphone/emotion measurements. Native designPack
qualification, school/Oca/child/device acceptance and the full original goal stay
open. No voice/default/heartbeat/native-display flags change from this preparation.
