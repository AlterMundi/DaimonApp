# Owner-local session preferences

`session-preferences CONFIG inspect|set JSON` is the finite local adapter for the
same session `model` and `reasoning_effort` fields used by `/model` and `/effort`.
It neither submits a Telegram command nor bootstraps/restarts a listener or native
App Server. It opens the existing receiving database without migrations or an
application-instance claim. This permits a next-turn selection during an active
collector without cancelling that turn. It is not a current-turn model switch.

Use the receiving owner's private configuration and the installed adapter:

```sh
session-preferences CONFIG inspect '{"chat_id":CHAT,"thread_id":TOPIC,"native_thread":"NATIVE"}'
```

For `set`, include the identical binding plus `expected` containing the complete
inspection result, and explicit `model` and `reasoning_effort`. The transaction
checks the current allowed creator, exact native thread, non-fresh binding and
complete prior preference/revision before atomically selecting both fields. It
records before/after in the existing private audit log. It changes no job, goal,
account, tier, pause, native history or other session. The receiving configuration
and database must be existing regular owner-only files; no caller-supplied owner,
SQL or new database is accepted. A named model selection does not prove account
availability or effective native execution.

After selection, inspect the same binding and retain the readback. After an
unknown outcome, inspect before doing anything else; never blindly replay. A
known stale-preference refusal requires a fresh inspection and reassessment.
The next actual native turn's configured-model receipt proves effective use;
selection alone does not. No extra turn is needed solely to establish it.

Build and qualify using the repository's pinned Rust toolchain and existing
Cargo target directory:

```sh
cargo test --locked --bin session-preferences
cargo clippy --locked --bin session-preferences -- -D warnings
cargo build --locked --bin session-preferences
```

Install only the finite adapter when this is the needed capability. The main
listener does not need replacement. Keep installation reference/digest and actual
selection receipts in the owning private operations record. Binary rollback
changes this adapter only; restoring an old preference requires a new conditional
selection, never a database rollback.
