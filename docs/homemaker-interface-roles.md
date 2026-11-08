# Homemaker interface role adapter

Work in progress, 6 November 2026. Not a deployed receiving selection.

`web/interface-appearance.js` contains the deterministic derivation from Homemaker
`public/lib/interface-roles.js`, wrapped as a classic local browser asset. Keep
that source in sync; it is a derived consumer, not another appearance authority.
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

Pending: full controller journeys, first-paint and actual receiving-release
qualification. Do not deploy current upstream wholesale over the selected
receiving version merely to adopt this frontend patch.

Follow-up qualification: reproducible synthetic consumer test now covers initial
missing source, light/dark updates, invalid update retention, authored opt-out
and restoration of pre-existing inline overrides including priority. This found
and fixed retained derived colors when returning to authored policy. Existing
dashboard bootstrap tests also pass. Controller-specific draft/file/audio
journeys and first paint remain unqualified; no deployment occurred.

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
