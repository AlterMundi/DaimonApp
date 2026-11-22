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

Inventory `interaction.observer_model` and
`interaction.observer_reasoning_effort` on the configuration selected by the
running listener. These settings apply to observer synthesis independently of
the bridge default and source-thread model. An explicit observer selection
needs its own model and effort check against the receiving account and the
effective provider used for the temporary synthesis workspace. When updating
it, retain the selected effort, existing summaries and in-flight work. A
listener that freezes this configuration at startup still needs compatible
runtime adoption. Use the next ordinary observer request to verify use.

For receiving qualification, identify the executable of the actual running
native daemon and confirm that it resolves to the currently selected package
in that receiver's Codex home. Run as the same owner, with the same effective
profile, account, provider, endpoint and reasoning effort. Record the selected
package identity alongside the version. Two copies can report the same version
and still be different builds. A bootstrap launcher may still resolve to the
onboarding package after a daemon update.

An ephemeral CLI check using the exact package can confirm inference with
that executable and configuration. Use native and application receipts for
claims about normal listener admission, delivery and use. If a probe fails,
retain its diagnostic privately and distinguish the selected model from a
provider response. Use the owning bundle maintenance route to replace a stale
bootstrap launcher. Keep the native daemon selection and the bootstrap
selection explicit in the receiving record.

For a listener that loads its configuration at startup, compare the running
process start with the selected file change. If the process predates the
change and has no supported reload, adopt at the next compatible maintenance
window. Use the existing admission and idle-work checks for a listener
restart. A zero busy-row count alone does not fence incoming work.
When the bridge has no explicit model default, qualify the receiving native
configuration instead of restarting the listener just to refresh a default
it does not set.

Check `codex.session_profiles` for explicit per-topic model selection.
The receiver resolves the selected profile from
`<native-home>/<profile>.config.toml` when it prepares the native turn.
That profile takes precedence over the bridge row, and the subsequent native
observation can write the profile's model back to the row. When it pins a
predecessor model, first qualify and update the selected profile with the same
provider, route and effective reasoning effort. Then reconcile the bridge
selection and verify the next ordinary turn through its native metadata.
A cold thread can still report its previous model before admission.
Keep its history and goal state intact and use the normal receiving surface
for adoption.

A direct terminal client can keep a predecessor selection in an already
loaded thread even when the same thread's bridge row has moved. Read the
native origin, status and model, and verify the latest ordinary turn on the
surface that admitted it. Preserve an active turn. Reconcile the native
selection when the owning surface can change future turns safely, and confirm
its subsequent ordinary use.

For a loaded native subagent, check its parent binding and the server's
`thread.canAcceptDirectInput` capability before attempting a settings update.
An idle subagent with direct input disabled still belongs to its parent.
Verify the parent's current selection and any explicit agent-role model in
the owning configuration. Preserve the child's retained settings and work.

A null bridge model is not proof that an existing native conversation follows
the current global default. After a native-default upgrade, inspect its bound
thread. For this case prepare with `--include-inherited`: the plan freezes the
actual observed native model and maps that role to its successor. It never
assumes a model from a missing native observation. Application rechecks that
native selection as well as the bridge's null model, workspace, binding, effort
and revision; a later native choice refuses before the SQLite transaction.
The write pins only the qualified next-turn model. Busy state, current captured
turn, provider, effort, original input and history remain untouched. v3 plans
carry `inherited_source_models`; old draft/v2 plans must not be replayed.

For explicit saved model choices whose native thread has not been bound yet,
`--include-unbound` qualifies the selected workspace/provider, active hosted
account, target catalog and effort without creating a thread. It preserves
force-fresh state and exclusions, and freezes the absent binding in the ordinary
session compare-and-swap. A null unbound model remains unknown and is deferred.
The option is retained in v4 plans; older plans keep their original executor.

A configured provider alias can use the native OpenAI catalog only when it has
the same hosted ChatGPT account, OpenAI name, Responses wire API, required OpenAI
auth and no endpoint, credential, header, catalog, capability or other override.
Transport booleans do not change this account/catalog equivalence. Any other
provider remains deferred. Neither alias qualification nor migration changes a
provider, endpoint, account or reasoning choice. A changed built-in OpenAI
endpoint/catalog, a local catalog file or a non-default ChatGPT origin also
prevents alias equivalence. Inherited qualification compares the frozen model
against the same thread observation used for provider qualification; this is
not an atomic lock on a concurrently operated native thread.


### Export availability for a native default

Run this from the receiving owner account, using its configured native bridge:

```sh
umask 077
python3 -B scripts/model_migration.py --config /owner/bridge.toml \
  --observe-family receiver-id > /owner/model-family-evidence.json
```

The output is one `cluster.model-family-evidence/v1` workload for the native
default in the configured workspace. It confirms the same hosted ChatGPT
account and effective settings, looks up the advertised models and existing
reasoning effort, and emits opaque contract and revision fingerprints.
Configured catalogs, noncanonical routing and unrecognized aliases are
refused. The producer starts no native thread or turn and writes no preferences.

Use the emitted document as the private input to Cluster's existing finite
Sysops pass. A newer model remains a candidate until the owner qualifies that
exact release against the current revision. This command does not apply a
selection or schedule a pass. An availability refresh cannot refresh an
existing qualification.

### Apply a qualified native family successor

Use the receiving owner command when the exact newest compatible release has
a fresh, independently retained qualification for the observed predecessor
and configuration. Pass one private, mode-0600 family evidence document and a
new intent path in the existing private operation directory.

```sh
python3 -B scripts/model_migration.py --config /owner/bridge.toml \
  --apply-family receiver-id --family-evidence /owner/qualified-family.json \
  --family-intent /owner/native-family-selection-intent.json
```

The command re-reads the canonical hosted catalog and compares the receiver,
route, account-bound contract and exact predecessor revision. It refuses a
missing or stale qualification, ambiguous latest version, inherited reasoning
effort or an effective model selected outside the native user layer. The native
writer changes only the model key with its actual user-layer version fence
through a defaults-only batch with reload disabled. Codex serializes these
configuration RPCs within the same app server. Coordinate any direct file
editor or separate server that writes the same user file before selecting a
successor. The command then verifies the effective configuration and account. Saved bridge
sessions, loaded turns, provider calls and schedules are outside this operation.
A selected default still needs a subsequent ordinary native usage receipt.

Retain the intent if the writer or readback fails. Inspect the effective user
configuration and its revision before any further operator action. Reusing the
intent path cannot submit another write. Use a distinct private intent only for
a separately qualified, newly authorized operation. Keep previous model and
revision in the owner's maintained operation record for compatible recovery.
