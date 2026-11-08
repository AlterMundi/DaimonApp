# Heartbeat header observation and controls gap

The heart beside the daimon name reads the existing configured owner console's
`heartbeat status` through the authenticated Interaction adapter. It creates no
producer, scheduler, inference, native input, resource grant or provider change.
Status reads reuse visible foreground app refresh, coalesced to at most one per
10seconds; manual Refresh reads once. No new background poller is installed.

Click, context menu, touch long-press500ms, Enter/Space or Shift-F10 open the same
menu. Escape/Close restores focus. Paused, unconfigured, unavailable and error
stay distinct. The heart pulses only when the backend explicitly reports
`operational=true` and admission/configuration/error observations do not contradict
it. An open admission gate or a running execution is insufficient. Operational
evidence expires after15seconds or tab hiding; failed reads clear it. Reduced
motion replaces the pulse with a steady labeled heart.

The menu distinguishes an expired observation window, a stopped/capacity-limited
observer, an expired inference window and exhausted inference allocation. These
known dependency states cannot pulse even if a contradictory positive flag is
present. Unknown dependency states stay unavailable. When supplied by the owner,
the menu shows the last source-check outcome/time and the previous successful
source-check time after a failure. Different or unconfirmed global/lane generations are labeled.
An unfinished source check states that completion was not observed; it does not
claim that an old process is still running. These source timestamps never prove
native action, reply delivery or current operational readiness.

Selected per-body receiving state belongs in the owning current service record.
An older backend without conditional capabilities leaves control rows disabled
with explanations; a compatible selected backend enables the explicit controls
below. Configuration never activates resources. Messaging is the initial lane;
Issues, Sensory, Tasks and Bitácora remain unsupported/off until separately
qualified. Missing operational proof keeps the pulse unavailable, independently
of whether conditional controls are supported.

Matrix owns the shared generation-aware global/lane control contract and receiving
activation. Once selected, the App can bind those actual commands and observed
states under its existing authenticated actor/CSRF controls. This UI release does
not complete lane enable/pause, Core adoption or actual operational acceptance.
Preserve current work, providers, all other goal states and the original voice
roadmap. Software delivery uses the normal all-receiver route and actual evidence;
source/browser checks alone do not establish served or human-phone acceptance.

## Prepared conditional App integration (not receiving activation)

The App POST on the same heartbeat route requires the existing authenticated
paired actor, same-origin boundary and session CSRF token. Interaction-only
paired devices may use it; monitor-only credentials remain read-only. Payloads
are closed and limited to `set_paused` or `set_lane_paused` for `messaging`.
Generations are nonnegative safe integers; paused is a boolean. The adapter
reads current owner status before sending, requires the advertised
`telecodex.heartbeat-controls/v1` capability and the relevant conditional flag
and action, and refuses unsupported lanes or stale revisions. It uses the
existing owner console, never another scheduler/control service:

- Global: `heartbeat pause GENERATION` or `heartbeat resume GENERATION`.
- Messaging: `heartbeat pause-lane messaging GLOBAL_GENERATION LANE_GENERATION`
  or the corresponding `resume-lane` command.

The receiving native handler must check both revisions atomically before fences
or cancellation; the App preflight is not a replacement for that check. Earlier
readers without the capability leave the UI disabled and receive no write.
A rejected, interrupted or unconfirmed write causes a status read, never an
automatic retry. Only the person's next explicit action can send another command.
A successful lane selection does not resume the global gate, create resources,
change providers or establish operation. Other lanes stay disabled even if the
backend supports additional internal sources. Configuration is not exposed.

This source preparation does not select native/Core code, restart services or
activate heartbeat. Resolve actual served versions and per-body native support
through the owning current service record; source capability is not selection.

### Fresh native operational observation

The owner status emits `operational` and one nonaccumulating
`operational_evidence` observation. This source successor must still be selected
on the receiving bodies; older backends supply no positive proof.

```json
{"operational_evidence":{"schema":"telecodex.heartbeat-operational/v1",
  "generation":4,"observed_at_unix_ms":1794093000000,
  "valid_for_seconds":15,"operational":true,"reason":"ready",
  "lanes":{"messaging":{"generation":2,"operational":true}}}}
```

A positive observation requires the actual existing maintenance task handle to
be live and a successful selected Messaging check performed since that loop
started. The last check must match both exact generations. Source freshness is
bounded by two configured check intervals plus15seconds, allowing the existing
serial bounded recovery pass; stale, interrupted and failed checks remain
unavailable. The existing cadence, check ceiling and expiry do not change.

Both finite windows must be current, sufficient unreserved inference capacity
must remain and observation capacity must be available. An unresolved pending
attention return cannot report idle readiness. The existing writer lease must
still be held by this live loop. Through the existing
native connection, the owner reads the serving Core's explicit
`initialize.boundedIdleTurn` support advertisement and `thread/read` for the
selected existing thread. It verifies identity, actual model/provider/effort,
idle status and direct-input readiness. It sends no resume, turn, malformed
mutation probe, provider request or reservation. Missing support on an older
Core stays unavailable. A busy native conversation is explicitly waiting.
These checks establish current readiness, not a promise of provider success or
future delivery. Genuine useful work and its receipts remain separate evidence.

After the bounded native read, the owner rereads its generations, windows,
resources and entry binding. Changed controls/bindings refuse positive evidence.
The frontend requires the matching evidence document and both generation values,
rejects future or older-than15second observations, and expires its pulse at the
earlier native observation deadline or either finite window. Re-reading an old
proof cannot extend its lifetime. Tab hiding and failed reads clear the pulse.
Only fixed reason classifications are exposed; arbitrary private native/adapter
errors are not copied into status.

The producer separately retains one replaceable `last_check` with sequence,
generations, start/completion milliseconds and outcome, plus the last successful
check time. A failed read uses `matrix_inbox_unavailable`; an interrupted check
may remain `in_progress`, which never claims that an old process is still alive.
The existing256KiB producer cap includes this record. These source timestamps
alone still do not prove operational readiness, native action or reply delivery.

## Versioned native control successor

### Explicit owner renewal of an expired window

Observation and execution have independent finite policies. Initial
`configure-producer` selects its own 30–3600 second cadence, 1–1024 lifetime
checks and deadline within seven days, even when the execution account is absent,
expired, exhausted or unavailable. Global/lane pause and source-binding fences
still apply. Successful authenticated inbox pages and source-check observations
are retained under the existing caps; unavailable execution resources prevent
offer-cursor advancement and native-return reservation. Later authorized
execution sees the same original sources, without replaying them as new messages.
Neither configuration nor an empty check spends inference attempts.

The owner can independently renew an expired observation deadline:

```
heartbeat renew-observation GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS [MAX_CHECKS]
```

This requires the exact paused global generation and a new deadline within seven
days. It preserves the check ceiling/count, cadence, original sources, pending
returns (including uncertainty), cursors, resource contract and reservations.
Without `MAX_CHECKS`, exhausted observation capacity refuses renewal. An explicit
owner-selected successor may supply a nondecreasing **absolute lifetime ceiling**,
leaving 1–1024 remaining checks after the existing count. For example, count120
and ceiling240 permit another120 checks; the count remains120. Unused predecessor
capacity is included in that remaining total, never added again. The predecessor
must be expired or check-exhausted; this can succeed a check-exhausted window before
its deadline without clearing source/receipt capacity failures. This is an explicit
finite model-free operating-policy grant, not inferred permission or an account
refill. Its receipt retains the old/new ceiling. One replaceable receipt makes an
exact lost-ACK repeat idempotent at the same paused generation. A separate Resume
is required. This command is owner-console only and absent from model actions.
It grants no execution permission, retries or automatic future renewal.

The owner console additionally supports:

```
heartbeat renew-window GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS
```

Use only under an explicit owner-selected new operating window. Read status,
pause at its exact generation, and supply the observed common resource/producer
expiry. The predecessor must be expired and the new window must end within seven
days. Matching producer/resource deadlines change in one transaction. An already
longer independently authorized observation deadline stays unchanged; otherwise
select a sufficient observation window before renewing execution. The account ID, lifetime reserved
attempts, request/execution limits, producer check ceiling/count, cadence, source
bindings, cursors and pending identities remain unchanged. Exhausted capacity,
changed bindings and unresolved/uncertain native work refuse the operation.

An exhausted pending return proven never submitted can receive one additional
admission of that same original. Its lifetime attempt count advances; the existing
resource account charges any new native execution normally. The current renewal
receipt identifies that source and exact next attempt. It cannot grant another
automatic retry, refill an account or revive accepted/uncertain work.

Renewal leaves global/lane pause states unchanged. Explicit resume is separate;
it reconciles only proven-unsent pending generations. The model-accessible
`heartbeat_control` actions cannot renew windows. The `window_renewal` status
field retains one replaceable current receipt; inspect it after an uncertain
console result instead of inventing another command. Exact repeats at the same
paused generation observe the retained operation without another renewal.

This source support is not receiving selection or authorization to extend a
particular expired operating contract. Operational evidence and the useful
message/action/reply/narration/pause journey remain separate requirements.

The source successor adds `controls.schema=telecodex.heartbeat-controls/v1` with
`conditional_global=true`, `conditional_lane=true` and explicit `actions` in
status. These describe supported writes, not operational proof or receiving
selection. The old selected reader may omit them. A UI must not infer support
from a release label, `admission_paused=false` or a configured producer.

The same scoped `heartbeat_control` handler accepts:

```json
{"action":"set_paused","paused":true,"generation":7}
{"action":"set_lane_paused","lane":"messaging","paused":false,"generation":2,"global_generation":7}
```

Both global and lane revisions are checked atomically before any write or
owned-execution cancellation. A stale page must refresh; it must not silently
retry its intent with a newer revision. Unsupported lanes cannot be activated.
Resources/cursors are conserved and no account or producer is created by these
commands. Bare owner `pause` remains the unconditional emergency control.

Owner console equivalents are `heartbeat pause GLOBAL_GENERATION`, and
`heartbeat pause-lane LANE GLOBAL_GENERATION LANE_GENERATION` or
`heartbeat resume-lane LANE GLOBAL_GENERATION LANE_GENERATION`.
Existing explicit owner commands remain compatible. The source change does not
add a web write endpoint, operational evidence, Core adoption or activation;
those remain actual receiving integration work.

## Source health does not request inference

An inbox read failure or recovery updates the bounded source observation and
last-check/last-success status only. It does not create a heartbeat offer,
reserve an execution or wake a model. A genuine unreviewed source can still
create an offer after recovery. Existing health-only returns and seen cursors
remain historical evidence; changing this policy never refunds reservations,
rewrites an original or resets the resource account.

Receiving evidence found one useful Eko message execution and three separately
accepted, reviewed health-only batches. Each reserved its12-attempt allowance,
exhausting the original48-attempt peer contract. Those are reserved maxima,
not measured tokens or money. The implementation removes those automatic
health-only batches rather than replenishing their account or moving the same
work into another inference loop.


## Continuous owner-selected messaging

An explicit ongoing-operation request may replace the pilot's lifetime with
`heartbeat continuous GENERATION ATTEMPTS_PER_HOUR` on the existing owner console.
Pause first and use the exact current global generation; resume explicitly afterward.
This command is not a model tool, does not enable another lane, and refuses an
unresolved native execution, changed generation or replacement rate. Exact repeats
retain the selected hourly window and every reservation. No far-future timestamp,
new contract UUID, daily counter reset or automatic renewal job is involved.

The original pilot contract and historical reservations are preserved. Remaining
pilot capacity is consumed first and never refilled; finite review purposes can
still constrain their admission to that remaining original balance. A recurring
ledger separately counts every new complete execution against its
hourly allowance before provider I/O, retaining cumulative reservations across
hour boundaries and restarts. Clock rollback cannot reset the current hour. Each
execution keeps its existing attempt, complete-request byte and time limits. An
exhausted hour reports `rate_limited`; bounded model-free checks continue, originals
remain pending, and useful attention becomes eligible when the next hour has capacity.
Continuous operation is not unlimited inference. Pause/conditional lane controls
and the existing owner/service stop paths remain available.

The existing producer retains its cumulative check count and source frontiers,
without the pilot's absolute expiry or cumulative check ceiling. Idle checks and
health failure/recovery never start a model. Operational evidence still requires
the actual live loop, current owner, eligible native entry/profile, capacity and
fresh exact-generation source check; its proof expires after15seconds. A continuous
mode label or open gate alone cannot pulse the heart.

Continuous cache retention keeps eight completed and reviewed heartbeat batches,
eight resolved incoming-original projections (`recipient_copy_proved` or explicit
`no_reply`), and64 own-body echoes. Unreported/native-unresolved batches and
pending, deferred, merely submitted or uncertain replies are preserved. Retirement
never changes accounting or the persisted native inbox frontier. Old pages cannot
reintroduce a retired projection. Canonical signed Matrix originals/authoring/
delivery receipts and native conversation turns remain in their owning journals;
this is bounded projection retirement, not history deletion or task completion.
The existing16batch/256original/4MiB limits still refuse genuinely unresolved
backlog, rather than discard it. Older finite policies retain their prior behavior.

Use `matrix_response` action `no_reply` with the exact original/revision and a
bounded reason only when neither a response nor further work is needed. It sends
nothing, creates no response intent, and cannot replace a submitted/uncertain
intent. Keep real pending work explicitly deferred. `heartbeat_reported` remains
review acknowledgment and must not be used as proof that peer work is completed.
Rollback to a finite-only reader stops continuous attention; do not restore an old
journal or pretend that its expired pilot became a current allowance.
