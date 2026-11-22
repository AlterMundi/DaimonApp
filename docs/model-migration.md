# Owner-local bridge model migration

Use the receiver's Unix account and the same native home, proxy environment and
configuration as its running shared App Server bridge. The command is for
shared OpenAI receivers. It reads account identity, rate-limit metadata, the
advertised model catalogue and exact native thread bindings. Native config is
resolved in the topic's saved workspace, or the bridge default workspace for
new sessions. Catalogue checks establish selection compatibility. Inference
remains subject to provider availability and limits.

For an ordinary single topic, use its existing `/model` control. For a scheduled
migration of persisted selections, prepare a fresh private plan and inspect the
eligible and deferred sets before applying it:

```sh
python3 -B scripts/model_migration.py --config "$receiver_config" \
  --plan "$private_plan" --replace old-model=new-model \
  --exclude-native-thread "$preserved_thread"
python3 -B scripts/model_migration.py --config "$receiver_config" \
  --plan "$private_plan" --apply --exclude-native-thread "$preserved_thread"
```

Repeat `--replace` for explicitly selected non-overlapping replacements. With
no replacement specified, the built-in mapping selects the 6.2 successors of
older Sol and Astra models. Existing choices outside the mapping stay as they
are. Keep the plan in owner-private storage for the operation. Retire the
disposable plan through the owning operation after verifying its outcome. Plans
from earlier draft schemas must not be applied with the maintained command.

Application rechecks native compatibility for each planned change and fails
the transaction if the config, database identity, binding, workspace, settings
revision, reasoning effort or model selection changed. A repeat with every
target already selected returns `already-selected`. The migration advances the
ordinary settings timestamp alongside `sessions.model` to invalidate old plans. A turn that
already captured its settings keeps them. Observe a later ordinary turn before
claiming the new selection was used. A deferred row stays available for a new
scope decision; a failed plan must not overwrite a concurrent selection.

Bridge defaults are separate. The bridge copies `codex.default_model` and
`codex.default_reasoning_effort` into new sessions. An explicit saved selection
still applies to an existing session. When the bridge default is absent, Codex
resolves the native model. Verify the intended default on the exact candidate
TOML before the existing receiving config writer selects it:

```sh
python3 -B scripts/model_migration.py --config "$candidate_config" \
  --verify-default "$expected_model"
```

The default check is read-only. The result is on-disk qualification, with
runtime loading unobserved. Use the receiving maintenance path to adopt the
candidate while preserving active writers, then verify loaded defaults and the
next ordinary use separately. This command makes no config, account, goal or
service changes.
