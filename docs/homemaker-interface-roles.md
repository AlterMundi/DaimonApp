# Homemaker interface role adapter

Published adapter: PR753 with PR783's last-valid canvas correction. The owning
Shared Resources receiving record identifies actual installation; publishing
these changes alone did not select them on a receiver.

`web/interface-appearance.js` is the local deterministic interface-role consumer
of Homemaker's bounded appearance contract. Its historical header references
`public/lib/interface-roles.js`; the inspected current Homemaker source does not
contain that module, so that reference is not an upstream synchronization proof.
The maintained author contract is Homemaker's `docs/SHARED-DESIGN.md` and
`public/lib/appearance.js`. This adapter is not another appearance authority.
The adapter consumes existing computed bounded --dm colors after stylesheet load
and on home-style:resolved. It writes only --dm-ui presentation roles; it performs
no requests, polling, storage, session actions or provider calls. Authored pages
opt out. Invalid/missing input keeps last valid roles or the authored fallback.

Layout, controller DOM, native work and interaction handlers remain unchanged.
Warnings, positive states and destructive controls receive distinct readable
foregrounds rather than all inheriting one accent. Text is qualified against both
canvas and panel; irreconcilable opposing surfaces collapse the derived panel
without mutating the source recipe. This extends local presentation only; the
strict appearance/v1 transport schema is unchanged. Personal viewer resolution
still belongs to the existing authenticated authority, not this adapter.

The UI role derivation excludes artwork, ASCII glyph palettes, image data,
artId/revisions and mission evidence. These remain authored artifact content.
No avatar is activated by this change.

Do not deploy current upstream wholesale over the selected receiving version
merely to adopt this patch. Overlay only the asset registration, shell script,
derived role CSS and adapter, preserving receiving-local composer recovery and
each pair's authored/inherited policy.

Follow-up qualification: reproducible synthetic consumer test now covers initial
missing source, light/dark updates, invalid update retention, authored opt-out
and restoration of pre-existing inline overrides including priority. This found
and fixed retained derived colors when returning to authored policy. Existing
dashboard bootstrap tests also pass.

Canvas fallback correction: the derived background now participates in the same
owned-role mapping as foregrounds. Invalid provider updates therefore cannot
leak a raw canvas color around the retained last-valid text/panel mapping.
The authored transition releases this override with the other roles.

## Reproduce the receiving-material browser check

Use the existing Playwright installation and an actual selected web directory:

```sh
python3 tests/dashboard_appearance_browser.py \
  --web-root /path/to/candidate/dashboard/web \
  --homemaker /path/to/homemaker \
  --chromium /path/to/chromium \
  --output /chosen/evidence/browser-results.json
```

This serves the exact shell, styles and adapter from a loopback-only test server;
conversation controllers are deliberately removed. It verifies delayed provider
CSS before first paint, all catalog palettes at1440/375/320px, preservation of
existing DOM/draft/focus/selection, invalid canvas fallback and authored release.
It uses synthetic UI state and no accounts, models or provider calls. Existing
controller tests cover separate functional paths; this is not real-human or
authenticated end-to-end acceptance. The server and browser stop on success/failure.

## Receiving qualification —8November2026

The browser check preserves the adapter's original script position and appends
slow provider CSS at the end of head, matching the actual Home response. It
refuses shells missing the adapter rather than injecting it into an older shell.
Actual source and composed receiving materials passed39catalog transitions at
1440/375/320px with roles ready before first paint, last-valid canvas fallback
and authored release.

The existing full-controller Chromium fixture also accepts
`QUALIFICATION_APPEARANCE=1`. With `QUALIFICATION_COUNTDOWN=1` it qualifies palette
updates with a draft and prepared synthetic original file, then separately during
an active bounded synthetic recording. It preserves draft/selection/focus,
attachment DOM, destination/admission epoch and recording ownership, with no
upload or provider. Both inherited and authored policies passed; the selected
Root composition also passed. Existing10/5/3/2/1second warning signals remain
qualified. These fixtures do not prove authenticated viewer preference resolution,
physical microphone operation, human hearing or phone acceptance.
