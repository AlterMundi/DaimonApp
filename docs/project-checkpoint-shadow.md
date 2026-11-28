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
lowercase Git commit ID. In this cut the caller explicitly resolves the
locator to an already available checkout within the workspace. Gateway verifies
the exact commit object locally without fetching. It allows the checkout to
move within that workspace. It does not initialize, clone or modify a repo.

Use one to eight exact sources. An `observer` source carries `native`,
`revision` and `source_revision` from an existing retained Observer card.
A `conversation` source carries `source` and `revision` from the canonical
general-conversation reader. For a worker, the retained presentation source
must address that topic. The owning readers decide source access again
during apply, read and exact repeat. The current execution and workspace claim
are revalidated after Git inspection. This keeps Git outside the SQLite
writer transaction. The prior revision comparison and insert are atomic.
The persisted attribution identifies the paired owner and originating local
turn. A duplicate returns the same revision and original attribution.

The shadow fixture uses an isolated SQLite store and local Git. It covers a
non-code revision, a staged edit, exact repeats, competing proposals, an absent
commit, reopening the store and moving the checkout. It also checks failed
reads with an unrelated owner and after retirement of the cited native source.

This slice does not select the checkpoint for native startup. Use separate
receiving evidence for the live worker surfaces, general-conversation audience
revocation, and both directions of cold harness recovery, including unresolved
effect receipts.
