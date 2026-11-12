# Fixed private projection from Reports

The optional `interaction.private_projection` selects one host-owned action for
an already authorized private view. It does not add a service, activation lane,
queue, timer, provider account or publication audience. It is disabled by default.
Use this when an isolated actor can reconcile selected inputs but must not receive
the publisher's credentials, store access or general loopback networking.

The existing `interaction_controller` operation `private_projection` accepts
`action: status`, or `action: run` with the exact current `return_id`,
`batch_revision`, `task_revision`, `snapshot_sha256` and
`reconciliation_sha256`. It accepts no executable, path, environment, destination
or audience. The configured task must be offered to that exact active Reports
execution, with its unchanged human purpose and current global/lane generation.
The selected reconciliation file must identify that return through the configured
JSON pointer and report `partial: false` through its configured partial pointer.
Only a running local/native execution with remaining allowance can
claim the action. Status reads the existing retained outcome; it executes nothing.

Example operator configuration (receiving paths are local, not shared bindings):

```toml
[interaction.private_projection]
task_id = "selected-private-intake"
command = ["/usr/bin/python3", "/SELECTED/refresh.py", "--snapshot-stdin"]
working_directory = "/SELECTED/READ-ONLY-CODE"
snapshot = "/SELECTED/INTAKE/source-snapshot.json"
reconciliation = "/SELECTED/INTAKE/cursor.json"
reconciliation_return_pointer = "/latest_check/heartbeat_return"
reconciliation_partial_pointer = "/latest_check/partial"
timeout_seconds = 20
```

Qualify the fixed command and its actual private audience before selection. Keep
its executable, code, imports, binding and custody outside actor-writable paths.
Use absolute canonical input paths: held-directory reads refuse symlinks in every
component. Give the actor only its selected intake/cursor writes, not publisher
custody or the whole Home store. This new configured action remains part of the
receiving identity; qualify its changed selection through the existing composed
receiver/access route, without dropping other fingerprint fields.

The command receives the pinned snapshot bytes on stdin, at most2MiB. Its stdout
must be one JSON object<=8KiB, with `source_sha256` identifying those exact bytes,
`state` equal to `unchanged` or `published_verified`, and the actual selected
`artifact_ref`/`version_ref` where applicable. Arbitrary stdout fields and stderr
are not returned. The command must not detach work or delegate to another service.
It has the smaller of its configured1–20seconds and the existing turn's remaining
allocation. The owned group is cleaned up before reaping its leader; pidfd exit
observation prevents PID reuse. Cancellation and outer controller timeout also
close that same group. Inherited per-process caps are at most1GiB address space,
20CPU-seconds and256descriptors; these are not aggregate actor cgroup limits.
The configured trusted helper must itself bound its children and publication
storage; resource actions do not become unmetered actor tools.

One bounded32KiB journal value retains the current and previous invocation against
the existing owner entry. An intent is committed before execution. The same return
cannot run twice, even if input changes. An unresolved intent/outcome holds later
actions instead of replaying an uncertain publication. The same confirmed input
under the same descriptor returns its existing result without a new invocation.
This journal does not change heartbeat reservations, budgets or goals. Native
returns and the Home publisher keep their original independent history.

On timeout, cancellation or a lost confirmation, inspect this exact invocation
and the existing Home/checkpoint state through the owning operator. Do not reset
this journal, infer non-publication or submit another action to hide uncertainty.
Automated reconciliation of such held outcomes is not implemented by this initial
operation; do not select it as an unattended production path until its required
owning readback/reconciliation has been qualified. Ordinary bounded Messaging and
Reports remain available independently of this optional operation.

## Existing Bitacora adapter

`scripts/bitacora_refresh.py` maintains the existing private desk refresh command.
Install it only through the owning desk's normal selection, preserving its current
project assets, Home identity and audience. `--project-dir` can select the existing
project code directory; its default is the installed script's directory.
Ordinary invocation still captures `source-snapshot.json`. `--snapshot-stdin`
consumes the controller's pinned input. Neither mode starts Drive acquisition.

The whole command uses one existing-project lock outside actor-writable inputs.
An anonymous host-owned temporary file reaches only the builder through its held
FD and disappears even on SIGKILL. The receipt's source hash/observation are from
that pinned input, never a later reread. Existing same-version checks, private
Home writer, unchanged-content suppression and protected byte verification remain.
This is not proof of human browser acceptance, a first automatic publication or
the full Matrix objective. Tests: `python3 -B tests/bitacora_refresh.py` and the
Rust `private_projection` cases. No real publisher or model is used by those tests.
