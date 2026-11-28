# Shadow project checkpoint

This candidate implements the first shadow project link from
[Matrix #497](https://github.com/AlterMundi/daimon-matrix/issues/497) and
[the project contract roadmap](https://github.com/AlterMundi/daimon-matrix/pull/571).
The worker controller advertises `project_checkpoint_shadow` for an owned
enrolled topic. Select the topic's existing Gateway workspace. These
operations do not inject context, start a turn, or dispatch an effect.

| Action | Arguments and return |
| --- | --- |
| `workspace` | No additional arguments. Returns the current claim or null if there is no permanent workspace. |
| `projects` | Exact `workspace` claim and optional `before` cursor. Lists each authorized project/repository's latest shadow link. Use `nextBefore` for the next page. |
| `read` | Exact `workspace` claim and workspace-relative `checkout`. Select `project` and `repository` for an exact link. Returns its latest verified revision or null if absent. An unfiltered read selects the most recently changed link. |
| `apply` | Workspace-relative `checkout` and a `delta` with a stable `operation` UUID, `expected_revision`, `workspace`, `link`, `sources` and optional `work`. Returns `accepted`, `retained`, or `conflict` with the observed revision. |

The link takes distinct project and repository UUIDs, a stable private `git:`
locator and a full lowercase Git commit ID. Links accepted before a separate
repository UUID was supplied use the project UUID as their repository ID.
Updating one repository leaves the other links in the topic available. The caller resolves it to an available checkout
within the claimed workspace. The locator matches the checkout's unique
`remote.origin.url` after the `git:` prefix. Use an absolute local origin
or a remote address without credentials. Relative filesystem origins can
change meaning when a checkout moves. For an unshared repository
with no remote configuration, select `git:local:<repository UUID>` and keep
that ID in the checkout's local `daimon.project-id` Git configuration.
Gateway checks the existing workspace marker, repository identity and full
commit object. It neither fetches nor modifies the checkout. A checkout can
move within the same workspace.

Use one to eight exact sources. An `observer` source carries `native`,
`revision` and `source_revision` from an existing retained Observer card.
A `conversation` source carries `source` and `revision` from the canonical
general-conversation reader. For a worker, the retained presentation source
must address that topic. For a link-only checkpoint, at least one source must cite the exact
proposed link in an original line of the form `Project link: {"project":"…","repository":"…","locator":"…","commit":"…"}`.
Observer uses only its cited support entries for this comparison. The owning
readers decide source access again
during apply, read and exact repeat.

A repository checkpoint may include a `work` array with up to eight
`{kind, text}` entries. The kinds are `decision`, `dependency` and
`next_action`. Each entry fits 480 UTF-8 bytes and the entire delta still
fits 4096 bytes. With work, cite the exact link and ordered array together
on one retained line, `Project checkpoint: {"link":{…},"work":[…]}`.
Once a repository has recorded work, updating it requires citing the work
to retain, replace or explicitly clear with an empty array. Old link-only
checkpoints remain readable. The project catalogue projects only repository
metadata. The owner-scoped read and the selected cold startup expose the
cited work with the original source references. The work text is historical
context and does not authorize actions.

The current execution and workspace claim
are revalidated after Git inspection. This keeps Git outside the SQLite
writer transaction. The prior revision comparison and insert are atomic.
The persisted attribution identifies the paired owner and originating local
turn. A duplicate returns the same revision and original attribution.

The store fixture uses isolated SQLite and local Git. It covers a
non-code revision, a staged edit, exact repeats, parallel proposals, an absent commit, reopening the store and moving the
checkout. It refuses a different repository with the same commit and an
unrelated evidence citation. It also checks a missing or wrong workspace
marker and refuses the read and repeat when the cited card retires while the
worker is still authorized.

Run `python3 -B tests/project_checkpoint_shadow_io.py <gateway binary>`
for the receiving controller check. It uses a synthetic Codex peer, the
actual workspace adoption command, canonical general-conversation delivery,
and the real worker controller. After a human correction supersedes the
cited source, its read and exact repeat fail while the workspace remains
accessible. The fixture verifies one retained revision and zero duplicate
dispatches. It uses no model or external network.

## Selected cold recovery

The shadow read and apply actions leave startup unchanged. After qualifying
a set of links, call `select_recovery` with the current `workspace`, entries
in `projects` containing `project`, `repository`, `revision` and a workspace-
relative `checkout`, and selected routed instruction UUIDs from the topic
in `effects`. The checkout selection is stored separately from immutable
repository revisions. A newer commit for a selected repository requires a
current selection. Revisions to other repositories do not invalidate it.
Select what fits the startup context and use the paged catalog to find the
rest. The startup byte bound does not limit how many links a topic retains.

The existing paired-human Codex and Claude startup routes read this selection
from the same Gateway store. They check the current workspace claim, exact
Git object and retained citation before including project data. A stale
selection supplies an unavailable notice without the old content. Native
startup treats the checkpoint as historical data. This does not grant
permission to dispatch earlier instructions.

For each selected routed instruction the reader checks the owning Gateway
journal. A matching result must be canonically correlated to the original, report
coverage, and remain current after corrections. Gateway checks the existing
delivery and result journal, including results published from later turns.
The view carries the native turn's terminal completion and the canonical
request outcome separately from transport acceptance. Without it, recovery retains the same
original ID with `unresolved` and the observed transport phase. A transport
acceptance is not a result, and a retained result is not proof of an external
effect described in its text. The reader never runs an effect or changes its
receipt.

The signed loopback test uses the existing
`FOREGROUND_TEST_CODEX_WEB_ROUNDTRIP` and
`FOREGROUND_TEST_TELEGRAM_CODEX_ROUNDTRIP` profile with
`FOREGROUND_TEST_VERIFIED_PROJECT_ROUNDTRIP=1`. It checks three selected
repositories from two projects and both receipt outcomes in actual Claude
provider input and Codex historical context. Add
`FOREGROUND_TEST_CLAUDE_COLD_PROJECT=1` to move the exact preceding Claude
transcript out of the fixture's native history directory. A new paired-human
input must recover in a distinct native session, with the same selected
revisions and effect receipts, one loopback provider call, and no duplicate
dispatch of the original effects. The run then verifies that the existing
Codex session can read both retained Claude exchanges and the same checkpoint.
The fixture uses Claude Code 2.1.332 and Agent SDK 0.3.332 with a loopback
provider and a synthetic Codex peer. Live adoption remains separate.

Add `FOREGROUND_TEST_CODEX_COLD_PROJECT_REFUSAL=1` to that profile to return
Codex Core's missing-rollout error on the exact saved thread. Gateway
recognizes it only from the metadata resume reply, with the native invalid
request code and the exact requested thread ID. A later failure or a refusal
for a different thread cannot qualify the original for cold continuation.
The original stays retained and unsent. On an existing routed paired-human
Codex startup with verified project context, Gateway records the refusal
against the exact original and local execution. It binds the observed
predecessor and the verified checkpoint digest and retains the event in
the owner audit. The existing owner input status exposes
`recoveries[].codex_recovery = "missing_native_history"` for the current
route. Reading this status does not reserve a successor or authorize another
submission. The fixture restarts Gateway and verifies the same receipt,
generation and preserved native binding, with no fresh thread or turn.

On the existing authenticated paired-human retry, Gateway reserves the
successor against the same instruction. It verifies the checkout outside the
owner transaction and rechecks the current source, native binding and checkpoint
digest when requeueing. If the original native thread resumes, the existing
submission path runs. If metadata resume definitively reports missing history,
Gateway records the creation attempt before `thread/start` and records the
returned candidate ID before allowing the original input on the same native
connection. The release check still requires the current source and matching
checkpoint. This first turn carries the checkpoint and the unchanged receipt
references. The canonical result returns through the original Conversation
route.

A lost `thread/start` acknowledgment leaves one held creation attempt. The
owner input status lists it under `codex_recovery_holds`, with no repeatable
route. Add `FOREGROUND_TEST_CODEX_SUCCESSOR_LOST_ACK=1` to withhold that
acknowledgment in the fixture and verify that duplicate requests and a Gateway
restart create no second thread or turn.

Gateway selects the successor only after that exact instruction has a
native acceptance and a completed turn with a recorded final item. The
existing writer commits completion and the predecessor-to-successor edge
together, advancing the native pointer while retaining the topic generation.
Earlier originals, questions and receipts retain their native identity and
existing disposition. This does not move a native goal to another thread.
A source-bound checkpoint can still read the exact cited Observer or
Conversation revision from a sealed predecessor in the same generation.
Historical citation access does not allow work to be submitted to the old
binding. An ordinary replacement, clear or grant revocation still fences
the earlier generation.

### Native Codex successor boundary

Run `python3 -B tests/codex_project_successor_io.py <native Codex binary>`
to exercise the actual App Server with a disposable profile and loopback
Responses fixture. A metadata-only `thread/start` returns an ID, but even
the same connection's `thread/resume` rejects that ID until the first user
turn materializes the rollout. The first turn can use the existing connection
and carry the checkpoint under the untrusted context field. On a subsequent
connection resume loads the materialized successor and its one saved turn.

The fixture verifies one new original and one unchanged checkpoint at
inference. The checkpoint contains both a retained result and an unresolved
original, with their distinct IDs. It records elapsed first-turn time, loopback
requests and the token count from the successor turn's native usage event. On
Codex 0.167.0 (native executable SHA-256
`522cbdabe0c746fb127e4fa037f07f5a67f8b8e53efb0ca9b1cb28c4689a7b50`),
the reference run took 235 ms with one loopback request and 218 simulated
tokens reported by Core. No real provider or production conversation was used.

This constrains the Gateway successor writer. Reserve the attempt before
native creation and retain the returned ID. Do the first submission on the
connection that created it, after checking the current owner, generation and
checkpoint. A metadata acknowledgment alone cannot select the successor as
a resumable conversation. If that connection is lost before materialization,
retain the observed stages and original rather than using resume failure as
permission to create or send again.


## Holodeck topic-room catalogue

The existing authenticated Session Workspace reader accepts
`GET /api/interaction/sessions?projection=holodeck`. An optional `room`
parameter selects one current room by its returned opaque logical topic
reference. Both reads require the existing workspace grant, recheck it
after the current owned inventory is read, and return private non-cacheable
responses. A missing, inaccessible or retired room does not resolve. The
reference identifies the logical topic across native harness changes; it
does not designate an admission destination or confer permission.

The projection contains title, general-conversation designation and whether
a direct Conversation destination is available. Room selection supplies
situated context to general Conversation by default. The projection makes
no input selection and does not switch a human into direct mode. It omits private histories,
routing revisions, native IDs and workspace paths. It works before any house
or custom spatial layout exists. Holodeck may use the room reference to
present a default space, but reuses canonical Conversation to read and send.
Authorized project links require their own current reader; an absent project
projection is not evidence that the topic has no linked projects.
