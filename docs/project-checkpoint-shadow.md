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
| `read` | Exact `workspace` claim and workspace-relative `checkout`. Returns the latest verified shadow checkpoint or null if none exists. |
| `apply` | Workspace-relative `checkout` and a `delta` with a stable `operation` UUID, `expected_revision`, `workspace`, `link` and `sources`. Returns `accepted`, `retained`, or `conflict` with the observed revision. |

The link takes a project UUID, a stable private `git:` locator and a full
lowercase Git commit ID. The caller resolves it to an available checkout
within the claimed workspace. The locator matches the checkout's unique
`remote.origin.url` after the `git:` prefix. For an unshared repository
with no remote configuration, select `git:local:<project UUID>` and keep
that UUID in the checkout's local `daimon.project-id` Git configuration.
Gateway checks the existing workspace marker, repository identity and full
commit object. It neither fetches nor modifies the checkout. A checkout can
move within the same workspace.

Use one to eight exact sources. An `observer` source carries `native`,
`revision` and `source_revision` from an existing retained Observer card.
A `conversation` source carries `source` and `revision` from the canonical
general-conversation reader. For a worker, the retained presentation source
must address that topic. At least one source must cite the exact proposed link
in an original line of the form `Project link: {"project":"…","locator":"…","commit":"…"}`.
Observer uses only its cited support entries for this comparison. The owning
readers decide source access again
during apply, read and exact repeat. The current execution and workspace claim
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

The shadow operations do not select the checkpoint for native startup.
Live worker surfaces and cold recovery in both harness directions, including
unresolved effect receipts, still need separate receiving evidence.
