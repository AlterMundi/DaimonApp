# Fixed private projection from Reports

The optional `interaction.private_projection` selects one host-owned action for
an already authorized private view. It does not add a service, activation lane,
queue, timer, provider account or publication audience. It is disabled by default.
Use this when an isolated actor can reconcile selected inputs but must not receive
the publisher's credentials, store access or general loopback networking.

The existing `interaction_controller` operation `private_projection` accepts
`action: status`, `action: inspect` with the exact unresolved `invocation`, or `action: run` with the exact current `return_id`,
`batch_revision`, `task_revision`, `snapshot_sha256` and
`reconciliation_sha256`. It accepts no executable, path, environment, destination
or audience. The configured task must be offered to that exact active Reports
execution, with its unchanged human purpose and current global/lane generation.
The selected reconciliation file must identify that return through the configured
JSON pointer and report `partial: false` through its configured partial pointer.
Only a running local/native execution with remaining allowance can
claim the action. Status reads the existing retained outcome; it executes nothing. Inspect invokes only the fixed adapter's `--inspect-stdin` mode with its retained input; it cannot publish.

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
its executable, code, imports, publisher staging, binding and custody outside actor-writable paths.
Use absolute canonical input paths: held-directory reads refuse symlinks in every
component. Give the actor only its selected intake/cursor writes, not publisher
custody or the whole Home store. The full configured action remains part of each native invocation's retained
identity; an unresolved invocation cannot be inspected through another descriptor.
This native-only helper does not change the dashboard's actor, audience, data or
control endpoint. Web identity excludes this one implementation descriptor while
retaining every other receiving fingerprint field. Qualify the composed receiving
selection through the existing owner route.

The command receives valid UTF-8 JSON snapshot bytes on stdin, at most2MiB. Its stdout
must be one JSON object<=8KiB, with `source_sha256` identifying those exact bytes,
`state` equal to `unchanged` or `published_verified`, and the actual selected
`artifact_ref`/`version_ref` where applicable. Arbitrary stdout fields and stderr
are not returned. The command must not detach work or delegate to another service.
It has the smaller of its configured1–20seconds and the existing turn's remaining
allocation. The owned group is cleaned up before reaping its leader; pidfd exit
observation prevents PID reuse. Native/execution cancellation observed by the action
closes that same group. The fallback controller's outer response timeout can occur
while its independently bounded action finishes: a missing reply never establishes
failure or permits replay. Inherited per-process caps are at most1GiB address space,
20CPU-seconds and256descriptors; these are not aggregate actor cgroup limits.
The configured trusted helper must itself bound its children and publication
storage; resource actions do not become unmetered actor tools.

One bounded32KiB journal value retains the current and previous invocation against
the existing owner entry. One separate existing-journal row retains at most2MiB of
exact unresolved input, atomically with its intent. Status never returns that input.
Successful observation/CAS settlement removes the copy in the same transaction.
No per-attempt queue or new table is created. An intent is committed before execution. The same return
cannot run twice, even if input changes. An unresolved intent/outcome holds later
actions instead of replaying an uncertain publication. The same confirmed input
under the same descriptor returns its existing result without a new invocation.
This journal does not change heartbeat reservations, budgets or goals. Native
returns and the Home publisher keep their original independent history.

On timeout, cancellation or a lost confirmation, use status and inspect for that
same named invocation. Inspect reads the retained bytes, not the mutable intake.
It compares the fixed adapter descriptor, renders the input in protected staging,
checks the selected private Home object/checkpoint and verifies authenticated
served bytes. A matching view may settle the intended effect while preserving
that execution of the original invocation was not established. Missing/mismatching
checkpoint information remains explicit; it cannot substitute for served proof.
Conflicting/unavailable evidence stays held, with its input, and is never a new
publication attempt. A stale inspection cannot settle a later invocation or
downgrade an already verified result. One nonqueued action/readback at a time
bounds host concurrency. Ordinary Messaging/Reports continue independently.
Actual receiving qualification is still required before selecting this optional
controller action for unattended production.

## Existing Bitacora adapter

`scripts/bitacora_refresh.py` maintains the existing private desk refresh command.
Install it only through the owning desk's normal selection, preserving its current
project assets, Home identity and audience. `--project-dir` can select the existing
project code directory; its default is the installed script's directory.
Ordinary invocation still captures `source-snapshot.json`. `--snapshot-stdin`
consumes the controller's pinned input. `--inspect-stdin` only renders/compares and
verifies serving; it never calls the publisher or writes the projection checkpoint.
These modes do not start Drive acquisition.

The whole command uses one existing-project lock and bounded `.projection-render`
staging outside actor-writable inputs.
An anonymous host-owned temporary file reaches only the builder through its held
FD and disappears even on SIGKILL. The receipt's source hash/observation are from
that pinned input, never a later reread. Existing same-version checks, private
Home writer, unchanged-content suppression and protected byte verification remain.
This is not proof of human browser acceptance, a first automatic publication or
the full Matrix objective. Tests: `python3 -B tests/bitacora_refresh.py` and the
Rust `private_projection` cases. `python3 -B tests/heartbeat_review_io.py BINARY
--projection` exercises the existing Reports controller path, including retained
unknown input, read-only settlement and duplicate suppression, with a synthetic
native peer and fixed test helper. No real publisher or model is used by those tests.

The optional actual-native qualification reuses the same production Reports
selection and runs the complete Core CLI against a local Responses stand-in:
`python3 -B tests/heartbeat_native_io.py APP_BINARY CORE_CLI --native-cli
--projection`. It checks delivery of the matching Reports hint, exact task
reader, retained-input recovery, controller result delivery and ordinary contact
after pause. Its fixed test helper does not publish Home content or use a real
provider account; production model uptake remains a separate receiving effect.

The host-only selection preserves existing Alerts/Traffic journals, browser and
companion scopes. It does not grant the dashboard a private-projection endpoint.
The native action still checks its exact owner, active Reports task/return,
allocation and full descriptor. Never clear delivery state or weaken unrelated
receiving fields to adopt it.


A private Reports actor can select its tool/path ceiling through
`matrix_transport.native_attention_host_restrictions.reports`. This root-only
selection leaves Messaging and delegated work on their existing global/default
profiles. Keep mutable intake and cursor files in a selected writable task
directory, separate from read-only publisher code, receipts and credentials.
Atomic replacement needs directory write permission; granting only a file is not
a substitute. A configured profile is not evidence of constrained native use.
