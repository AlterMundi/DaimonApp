# Playback-responsive avatar capability

This is the receiving contract for the existing shared workshop, not a requirement
that every avatar have a face. It resolves the App791 editor handoff. A mouth,
shell hinge or other artist-selected expressive region can use the same opt-in.
No phoneme/viseme alignment is supplied. An audio meter is a separate feedback
surface and does not prove that an avatar region moved.

## Existing runtime and coverage

| Saved representation | Playback response today | Required editor action |
| --- | --- | --- |
| `model/v1` with `ascii-avatar-model/v1` vector nodes | Optional articulated region | Author the anchor and visible descendants below. Preserve eight required cues. |
| `model/v1` with `ascii-avatar-model/v2` vector/raster nodes | Same optional articulated region | Preserve the atlas, clipping, poses, hierarchy and optional sleep cue. |
| Custom model without the anchor | Authored animation only | Keep unchanged unless its artist opts in. Never infer a jaw from pixels or names. |
| Built-in `surface/v1`, `surface/v2`, storybook/precision masters | No playback-region hook | Author an explicit compatible model or propose a focused renderer adaptation; do not claim automatic coverage. |
| Flat text/image or image-art design | No independent articulated region | Keep static/authored animation. Separate parts and an artist-selected region are necessary for articulation. |
| Nonfacial or deliberately static design | No region required | Preserve that choice. Lack of lip motion is valid, not an import failure. |

`fresh()` starts with `avatarModel: null`. Gallery proposals and choosing a stock
body deliberately clear the previous custom model. They must not retain another
character's anchors or advertise inherited lip motion. A stock renderer version
alone is not a capability declaration.

## Inert opt-in; no new saved schema

Use existing node fields in the validated model. Add an invisible `path` named
`anchor-mouth`, with `fill: null`, no stroke, an artist-selected `pivot`, and an
optional existing parent. Parent only the visible pieces that should react under
that node. The anchor alone has no visible output. Its descendants must retain
visible geometry in the intended cues and the large/compact crops. An example
hinge at `[288,350]` is:

```json
{"id":"anchor-mouth","type":"path","path":[["M",288,350]],
 "fill":null,"pivot":[288,350]}
```

The name is a compatibility identifier, not a demand for facial anatomy. Existing
64-node, eight-parent, geometry and upload limits apply. Reparenting changes
hierarchy: inspect every cue before saving; do not guess pivots or overwrite an
artist's tracks. Opting out removes/reparents the authored region deliberately,
not by deleting unrelated geometry. Import, export and save/reopen must retain
these existing fields through the canonical validator.

The existing model renderer clamps finite playback level to 0..1, quantizes it
to five steps, and adds at most 12 master pixels of Y translation and .035 radians
at the hinge, composed with the authored tracks. Nonfinite values become zero.
Level zero reproduces the authored cue/frame; the saved JSON, atlas and selected
cue remain unchanged. The mounted renderer validates into a transient clone and
accepts `setSpeechLevel(level)`; its boolean reports a repaint change, **not** a
capability or visible-effect certificate. Do not use that return value to label
an avatar as fully qualified.

## Audio and lifecycle ownership

Use the current Conversation `outputLevel` -> `AvatarWorkshopUI.speechLevel` ->
`renderer.prepare().setSpeechLevel` -> `renderAvatarModel` path. Feed observations
of actual decoded/playing output, never received/queued audio, microphone input,
transcript activity or guessed speaking state. Keep the existing player and
bounded observer; no second audio destination, capture, recognizer, provider,
per-frame inference or saved audio is required.

Silence, Stop, pause/mute, retired view, hidden page, wardrobe and reduced motion
clear or suppress the transient response. A retired callback cannot reopen it.
Cosmetic observer failure leaves ordinary playback working. A renderer supporting
the anchor does not establish that every speech engine/device supplies its signal.

## Editor handoff and acceptance

Reuse the current model importer, canonical validator, immutable revisions,
account bridge and explicit Use operation. Do not add another runtime/store or
automatically activate a modified design. Preserve a saved neutral pose and keep
preview speech level transient. Offer opt-in and neutral/static choices in plain
product language; avoid diagnostic capability flags in the normal gallery.

For each supported representation, record source/render checks separately from
these actual account journeys:

1. Create/import an explicitly authored region, preview every relevant cue and
   both crops, Save, reopen, and export/reimport without metadata or hash loss.
2. Explicitly Use that immutable revision. Verify the selected account/version;
   an uncertain Save/Use outcome must be observed rather than replayed.
3. Play actual speech through the selected engine; observe visible descendants,
   then silence, Stop, pause/resume, hidden page, wardrobe and reduced motion.
4. Confirm a legacy/static/nonfacial choice retains its artwork and other tracks.

Synthetic Canvas success proves local rendering, not real create/save/reopen/Use,
phone hearing, character quality or universal fleet coverage. Do not inspect
private child designs to establish a generic contract. Public inert fixtures are
sufficient for source work; real paired acceptance remains explicit.

## Maintained source and current evidence

- `dashboard/web/avatar-workshop/renderer.mjs`: transient design and level setter.
- `dashboard/web/avatar-workshop/skills/ascii-avatar-author/scripts/model-runtime.mjs`:
  shared validator, hierarchy and output-level transform.
- `dashboard/web/avatar-workshop/experiments/school-avatar-quest/model.mjs` and
  `surface-renderer.mjs`: defaults/proposals, representation routing and cache.
- `dashboard/web/avatar-workshop.js` and `conversation.js`: current mounted signal
  and lifecycle suppression; `docs/interaction-avatar-workshop.md` documents the
  decoded-output observer and compatible rollback.
- `tests/avatar_layer_model_browser.cjs`: actual Canvas raster jaw, legacy no-op,
  nonfinite-level reset, source immutability and independent parts. On the retained
  App879 baseline these mouth assertions pass; the subsequent unchanged narrow
  fullscreen equality assertion fails. This is not a full-suite pass.

Oliva's authenticated static inspection of overlay863 identified the missing
stock/default coverage correctly. The present contract preserves the existing
runtime rather than inventing automatic anatomy. Editor implementation and real
account/device acceptance are not established by that inspection or this guide.
