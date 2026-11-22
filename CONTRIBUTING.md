# Contributing to the maintained fork

Use English for code, documentation, issues, commits and PRs. Link an implementation PR to its owning repository issue and, when applicable, the Matrix parent. Preserve upstream's MIT license and propose focused, generally useful changes upstream after qualification.

Before integration, require passing checks for the final changed behavior. Independent review is required for new token handling, changed ingress durability or session-binding semantics, migrations and changes to an existing authority contract. Nicolas's recorded operational delegation authorizes requested same-actor service composition through the existing writer; preserving authentication, tokens, sessions, grants and private-state contracts does not require another external approval. Verify the concrete own/foreign/anonymous, current-selection and receiving boundaries instead. Keep new identities, authority changes and migrations within their applicable review requirements. Never describe self-review or runtime checks as an independent review.

Reuse a coherent passing CI baseline for unchanged behavior, naming its exact source and the subsequent delta in the PR. Recheck corrections against affected invariants instead of restarting unrelated audits or compatibility suites. Read and report infrastructure/provisioning failures separately; never describe them as passed tests. An unrelated runner prerequisite does not invalidate retained evidence or become a deployment gate for unchanged features.

Run cargo fmt --all --check, locked text-only tests and clippy; optional audio changes must also pass locked all-features tests/clippy. Relevant CI qualifies Linux/macOS text builds with the committed toolchain. Test actual SQLite transactions/restarts, loopback HTTP and native App Server attachment where relevant. Unit tests alone do not prove live Telegram or native model delivery.

Lifecycle fixtures wait for the exact persisted outcome or transport receipt they
assert. An idle session or terminal local audio state does not prove a later
journal commit or upload acknowledgment; use bounded observation of that boundary
instead of a sleep or an unrelated presentation flag.

Parallel load and control-flow fixtures use synthetic workers with zero inference.
When semantic qualification requires a real model, start with Luna low and move
to Sol low or medium only when the case requires it. Preserve ordinary human
session model defaults. Reuse retained outcomes instead of repeating paid work
to repair a test verifier.

Keep credentials, numeric human allowlists, body bindings, private endpoints and conversation databases local. No changes may silently reuse another bot's polling consumer, import unrelated native history, replace owner identity/authentication or introduce Matrix polling/autonomous peer replies. A human-authorized listener starts only through an explicit local setup action.

Document exact deployment reference/hash, feature set, local prerequisites, health checks and rollback. Preserve input journals/offsets and report ambiguous effects honestly. Operational progress belongs in issues or project context, not durable personal memory.
