# Session workspace

The collapsible rail is the normal owner-scoped navigation and audio-filter
surface (#602–#605). It reuses the observer, retained Conversation inputs,
current native session bindings and existing device-local Mute/Solo preferences.
Opening a conversation or technical view performs read-only I/O; it does not
start a native/model process, enroll a router target or acknowledge work.

## Input and navigation

- No pin sends new input to the integrating Conversation. A pin selects a current
  owned session through its native-issued `session:ID` source and revision.
- Opening another session temporarily selects it. Back restores the explicit pin
  that existed before opening it. Opening Conversation temporarily selects the
  integrating conversation; Back still restores the pin.
- The message bubble freezes the latest retained assistant message, using
  `session:ID/ROW` with a revision bound to the destination and exact immutable
  native message. The integrating Conversation uses its existing contextual
  `native:ROW` reference instead. New messages do not retarget a clicked reply.
- One-shot replies take precedence over the default target. Text freezes its
  target before asynchronous image/file preparation; ordinary voice freezes it
  before microphone permission. A later navigation or pin change cannot mutate
  the original, retry or recorded question scope. A stale pin is refused without
  silently falling back to integration.
- Direct text/ordinary voice use the existing original journal and worker
  admission/start/steer path, including busy workers, without an integrating
  model turn. Avatar remains independent of this default target.

Pins and expanded views are bounded, in-memory client intent. They are cleared
on binding/authentication changes, not saved as transcript data. Back does not
clear the composer draft or an already frozen recording. Audio filters retain
only their existing binding-scoped preferences. Per-update audio controls remain
as a fallback when the complete workspace is unavailable; they are hidden only
when the grouped rail controls are active.

## Status and permissions

The authorized inventory retains all owned sessions within the existing128-session
bound. The rail shows sessions active within24hours, with fresh running/tool/active-
goal sessions first, then recent conversation activity. A fresh currently working
session counts as active now even if its last conversational message is older.
An old hidden row does not clear an explicit pin, recording or draft. Observer
refresh time alone never qualifies an idle session as recent. Existing
fresh observer facts show work, tools, active/blocked goals and human action.
Stale/unknown facts are explicit and color is accompanied by text/icons.
`result_available` means a retained final assistant message exists in that current
native session. It is not evidence that the human has reviewed it. Review status
remains unknown unless its owning journal supplies a review state; no artificial
read/hearing receipt is created by opening the rail.

Both workspace metadata and selected history require the existing explicit
`workspace_access` grant for restricted shared-Home/Companion devices. Monitors
remain denied. Native ownership, current generation and stop/admission epochs
are revalidated on capture and dispatch. A grant loss removes selected history
and blocks new direct input, while keeping the ordinary integrating Conversation
and draft available. It does not sign out the entire app or replay originals.
An older compatible listener can expose metadata without pin references.

## Selected native history

`GET /api/interaction/sessions/{opaque_id}` reads only the selected owned native
root. It resolves the current native index, confines the regular rollout to its
sessions root, checks the file header/native identity, and rechecks actor, config
and session binding after I/O. No client path, descendant traversal, model RPC,
transcript corpus, persistent browser history or independent poller is added.
Existing Conversation refresh events refresh the selected view.

The ordinary view exposes retained harness user/assistant messages. **Input** is
an honest harness-role label: it can contain attributed context and is not a
claim that every byte is direct human speech. The terminal-symbol view adds
available function/custom tool calls, outputs and exposed reasoning summaries.
Private assistant analysis, encrypted reasoning, developer/system messages and
unavailable event types are not exposed or reconstructed. This is a view of
available events, not a promise of complete CLI reproduction.

Reads use a 1-MiB target window (plus at most one crossing record), at most
80 exposed records, a 2-MiB hard record bound and a 512-KiB response budget.
Initial/backward pages retain the latest fitting events; forward pages retain
ordered deltas, so opening a view does not start behind an old event backlog. Text parts contain at most 16,000 Unicode
characters and retain stable event identity. Continuations require the exact
file revision and complete record boundary. Appends preserve the revision;
file replacement/truncation refuses the old cursor. An incomplete final record
stays behind the cursor until its newline arrives. Oversized records refuse
explicitly instead of producing a non-progressing clipped cursor.

The client retains at most 240 event nodes and 4 Mi UTF-16 code units of displayed
content, with bounded text continuation. Older removed events remain in native
history and can be paged again. Switching session/view, losing the grant or
resetting the binding clears this window. The shared adaptive header reacts to
intentional scroll in either conversation view, never programmatic follow alone.

## Qualification and receiving

- `tests/dashboard_session_view.py`: complete/partial append, replacement,
  symlink/cursor refusal, bounded long Unicode records and private-analysis
  exclusion.
- `tests/dashboard_sonic.py`: actual owner/grant/HTTP selected-history reads and
  revocation; no native process opened by observation.
- `tests/session_workspace_ui.js` and `tests/conversation_ui.js`: pin/expansion/
  Back, exact reply, old-history races, audio filters, grant loss, frozen text/
  voice targets during attachment preparation and stale-target refusal.
- `tests/session_workspace_http_io.py BINARY`: actual native listener/controller,
  SQLite and HTTP plus synthetic ASR/native peers. Text and recorded voice start/
  steer a busy unregistered worker without integrating work; exact latest-message
  replies retain their original source. This uses zero models.
- `tests/session_workspace_browser.js`: shipped shell/assets in Chromium with
  synthetic HTTP fixtures, desktop/mobile, draft preservation, text targeting,
  exposed technical events, grouped audio, header intent and grant-loss recovery.
  Set `PLAYWRIGHT_MODULE` to an existing installation and
  `QUALIFICATION_OUTPUT` to a new absolute directory. Its one server/browser
  close at completion; screenshots/report are limited to 4 MiB. No providers,
  private production transcripts, actual microphone or physical hearing claim.

Source qualification is separate from receiving adoption. The receiving native
composition must preserve its current heartbeat/continuity features, and the
browser must have its actual selected workspace grant before this becomes a
usable feature. Real device/voice, repeated continuity, useful latency and the
broader roadmap remain required acceptance; tests do not close those obligations.


Receiving checkpoint —5November2026: workspace613 is selected with the separately
qualified phone614/615 fixes, native590-compatible sourceb5d300a9 and
UIb7092302eace. The explicit shared-Home owner workspace grant is enabled; this
does not alter Companion/monitor grants or enroll another user. Combined native
all-feature568 tests (one ignored), clippy, exact staged text/recorded-ASR voice,
archive-hold/restart and desktop/mobile Chromium journeys passed. Actual owner
metadata and public assets were observed after adoption, preserving live
collectors, Core, goals and all other settings. Human browser/device acceptance
remains pending. Retain the compatible native workspace/hold reader on web
rollback; old strict readers are not a rollback for held originals. Exact
selection, rollback and remaining acceptance live in the Shared Resources
Interaction receiving guide and the receiving owner's local operations record.

The compact session toolbar sits below the reading area, immediately above the
input dock. Its menu opens upward within that area on desktop and mobile, without
shifting the conversation or input. The destination remains beside the menu
control. Compact-header mode also hides the pending/status lane; reverse scrolling
restores it without changing its content or pending tasks.
