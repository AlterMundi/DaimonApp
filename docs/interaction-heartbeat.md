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
The producer metadata cap includes this record (256KiB finite,4MiB continuous). These source timestamps
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

Continuous cache retention keeps at most eight completed and reviewed heartbeat batches,
eight resolved incoming-original projections (`recipient_copy_proved` or explicit
`no_reply`), and64 own-body echoes. Unreported/native-unresolved batches and
pending, deferred, merely submitted or uncertain replies are preserved. Retirement
never changes accounting or the persisted native inbox frontier. Old pages cannot
reintroduce a retired projection. Canonical signed Matrix originals/authoring/
delivery receipts and native conversation turns remain in their owning journals;
this is bounded projection retirement, not history deletion or task completion.
Continuous operation has128 retained-return slots and a4MiB producer document,
separate from the unchanged48 execution envelopes/hour,64 possible provider
attempts/execution and600second execution deadline. This accommodates more than
two full hours of exceptional retained outcomes; ordinary reviewed work rotates
indefinitely with at most eight reviewed details. Finite contracts keep their
original16-return/256KiB bounds. Metadata headroom is not spending authority.
The reviewed cache is reduced further if protected outcomes approach capacity.
Exact reported revision plus an observed terminal execution is required to retire
reviewed detail. Terminal proof is retained on the same return before its separate
execution cache can age out. Unknown, unreviewed and uncertain outcomes stay
intact; they are not replayed or falsely marked reviewed to create headroom.

The continuous128batch/256cursor/4MiB limits still refuse genuinely unresolved
backlog, rather than discard it. If every slot is protected, the owning unresolved
work must be reconciled; the producer does not silently drop it. Older finite
policies retain their prior behavior.

Use `matrix_response` action `no_reply` with the exact original/revision and a
bounded reason only when neither a response nor further work is needed. It sends
nothing, creates no response intent, and cannot replace a submitted/uncertain
intent. Keep real pending work explicitly deferred. `heartbeat_reported` remains
review acknowledgment and must not be used as proof that peer work is completed.
Rollback to a finite-only reader stops continuous attention; do not restore an old
journal or pretend that its expired pilot became a current allowance.

A failed or interrupted accepted attention may end before it can report review.
On the next model-free check, an exact heartbeat-owned terminal physical receipt
settles that admission as `attention_failed` or `attention_interrupted`. Its return,
originals and response uncertainty stay retained; no review, reply or completion
is invented. The attempted source revisions are fenced against automatic replay,
without refunding reservations. New genuine originals can still be admitted.
Unmatched, running and uncertain executions remain pending. A transferred
execution settles only after an exact terminal receipt for its original physical
turn; human successor turns and cancellation ownership stay unchanged.
Status retains `last_attention_failure` separately from present
operational readiness. This does not authorize a failed task retry.


## Native account-owner client preparation

The trusted native event callback may opt into `FundedInferenceAllowance` with
an already authorized journal cycle. The existing bounded start then sends
`providerReservationCycleId` to Core17; an older reader rejects it and there is
no ordinary-start fallback. Attempt-only `InferenceAllowance` keeps its existing
wire shape and does not become a monetary grant.

`turn/providerAttempt/reserve` is handled before ordinary turn-event filtering:
it may arrive before the start ACK and has no turnId. Match the selected thread,
canonical cycle/attempt UUIDs, original complete-request ceiling, attempt count
and absolute deadline before calling the host accounting owner. Only its explicit
`ProviderAttemptReserved(true)` authorizes the exact response. Duplicate attempts
or ordinals cannot call the owner again; a refusal/error fences subsequent
requests in that cycle. Cancellation and the original deadline remain effective
while the owner is pending. A late result cannot renew the horizon or create a
new attempt. No model tool, human question or account choice comes from the RPC.

The default App owner explicitly refuses financial reservations. This source
prepares the native client, not a configured account or receiving activation.
The provisioned consumer must use the existing Matrix `CycleContext`/schema5
journal and verified cost contract, retaining exact attempts and conservative
exposure across restart or lost responses. Local duplicate tracking is not that
durable ledger, and writing an authorization is not proof of provider usage.
Real account/route/exposure qualification, authenticated per-attempt usage and
credential/tool-route isolation remain necessary before monetary enforcement.


## Attributed Matrix messages in Conversation

The existing owner presentation accepts optional `inbox` and `responses` cursors
beside `delivery`, `native` and `matrix`. Native console form:
`presentation list|before DELIVERY NATIVE MATRIX INBOX RESPONSES`. Each source
has a stable ID and exact revision; pages contain at most eight sources per
cursor with `more`/oldest/newest continuation. Rendering reads the authenticated
owner/current-entry store only, with no Matrix transport I/O or new journal.
The existing bounded projection retention still applies; this is not a complete
archive of the SDK's canonical signed history.

Incoming `matrix-inbox:UUID` sources keep their original canonical revisions.
Their direction and sender label are presentation metadata, not revised offers.
Own `matrix-response:ORIGINAL_UUID` sources expose exact retained response text,
source author, original parent/thread/send IDs, and the actual retained native
outcome. A monotonic projection sequence in the existing handling record makes
later delivery/uncertainty changes discoverable even for older originals. Legacy
handling records remain readable before their next update. Updating that record
never changes or reoffers the incoming original. Submitted/uncertain intent is
not recipient delivery; a signed receiving copy is not comprehension, task
completion or human hearing. No-reply dispositions author no outgoing speech.

Conversation labels peer speech explicitly and exposes source/receipt details.
The same signed event shown through ordinary results, own response receipts or
inbox copies is represented once when those views meet. These raw message cards
do not automatically speak as the local daimon or trigger avatar reply animation.
Their Reply button retains a context-only source reference for discussion with
the paired human; it creates no peer destination, send, approval or replay.

Model-free source checks continue at the existing cadence while the entry is
busy, retaining attributed originals for Conversation without reserving inference,
advancing selected-offer cursors or marking them reviewed. Actual native attention
still requires a free entry; bounded heartbeat delivery refuses to steer an active
ordinary execution. This fixes source visibility starvation separately from the
remaining fair execution admission limitation. Native active goals may continue again at the same
terminal checkpoint, leaving no usable polling interval. Open continuous controls
therefore do not establish intake or fair admission under an always-active goal.
The existing native user-input queue does not carry the bounded application
context/allowance contract. Do not forge a user message, pause the goal, globally
withhold goals through maintenance, or borrow an active execution's unlimited
budget to make a readiness indicator positive. Fair per-entry checkpoint
admission remains part of the existing heartbeat/progress-review implementation.

## Finite selected progress review within standing messaging

The owner console's `heartbeat select-review GENERATION CONTRACT_JSON` selects
one initial report-review successor on the existing bound parent. It requires
an exact paused global generation, a paused Reports lane, no unresolved execution
or pending return, no prior review selection and no existing Reports sources.
For an existing production review, the same command updates only the selected
report files/pointers after pending returns have been reviewed. Purpose, cadence,
production funding and expiry/check policy must match the existing contract.
Checks, next-check time, resource reservations, source cursors and historical
returns are preserved. A finite pilot cannot be renewed through this operation.
Use this path when an owning project adds a current milestone/blocker field;
do not leave permanent review watching only obsolete initialization fields.
It changes no source frontier, seen revision, original check counter, native
binding, global/lane generation, goal, resource contract or historical reservation.
It does not resume either control. After selection, use the existing explicit
lane/global resume controls; pause the Reports lane to stop this review while
preserving Messaging.

The contract contains the actual retained `purpose` (`input_ref` and `channel`),
`reports` (the existing exact owner-file/JSON-pointer contract),
`interval_seconds` (900 through3600), `max_checks` (1 through96) and
`expires_at_unix_ms` (future and within24hours). Select milestone/blocker fields,
excluding a report's changing clock. This is deterministic source observation;
it does not certify that semantic review, child admission or delivery occurred.
A changed eligible batch carries this review's own exact human-purpose reader,
separately from standing Messaging's original. Empty checks reserve no inference.
One pending/uncertain return prevents another review. The existing native entry
worker remains the sole execution owner; there is no additional scheduler.

Review executions reserve only the original shared pilot balance, at most four
executions in total, without borrowing the recurring Messaging allowance. Other
Messaging work can consume that balance first. With the selected12-attempt
execution bound and48remaining, at most four executions remain shared; they are
not earmarked reviews. Reservations are charged before native/provider work,
never refunded after failure, uncertainty, restart, pause or expiry. The same
hourly bound also applies while continuous operation is selected. Exhaustion or
expiry stops new review admission and preserves standing Messaging. A review's
native deadline is capped by both the existing execution bound and review expiry.
There is no renewal/reset/replacement command for this selected review purpose.

Selecting review installs a resource-record compatibility marker before exposing
its sources. Strict older resource readers refuse that selected account instead
of interpreting Reports as standing-funded work. Keep a compatible reader when
rolling back software; preserve the current journal/account and later originals.
An unselected successor leaves the previous account representation unchanged.
Receiving selection and a useful native review must be verified separately from
source tests and metadata observation.

Finite Reports checks snapshot their selected fields even while ordinary native
work is busy. A changed relevant source retains one known-unsent metadata return
without an execution reservation or native/provider call. Existing bounded
known-unsent retry accounting is preserved. Idle recovery
checks current source/purpose/expiry and capacity, then makes the first actual
admission attempt. No second scheduler, fake human queue or busy-turn steering
is introduced. An unavailable report is a failed source observation with explicit
`selected_report_unavailable`, rather than a successful empty check.

A proved completed physical attention turn without `heartbeat_reported` retains
`accepted_terminal_unreviewed`, not a semantic review/task/delivery claim. Its
exact attempted source revisions are fenced from automatic replay, while new
originals may proceed. The same rule applies to transferred ownership only when
that original physical turn has an exact terminal receipt. It does not cancel,
resume or settle a later human successor. Status exposes
`last_completed_without_review`. Existing
reported-review semantics and bounded retention are unchanged. Unknown, running
or mismatched physical outcomes never authorize this settlement. This corrects
an observed Oliva deadlock at completed local581; do not forge its review mark.

### Production defaults and selected progress review

The owner-only `heartbeat production-defaults GENERATION SOURCE_JSON_STRING`
selects normal operating capacity after an exact global pause. Retain the actual
owner direction as operator provenance, never new speech from the receiving paired
human. Selection does not resume a control, reset an hour, refund history, change
an account or extend an already admitted native execution.

Production uses64 provider attempts and600seconds per new execution, keeping the
configured request-byte limit. Its recurring bound funds48 full new execution
envelopes/hour: at most3072 reserved possible provider attempts, shared by selected
work. Empty, unchanged and health observations use no inference. Reservations
are conservative upper bounds, not actual model calls, token use or money. The
service has no trial lifetime; existing pause controls remain available.

The immutable pilot contract, previous native allowances, lifetime/hour counters,
source frontiers and uncertain originals remain unchanged. Production's separate
`effective_execution` is the active envelope; the pilot's12/300 fields are not its
current limit. Historic smaller reservations stay charged in original attempt
units. Strict account readers require the compatible production reader on rollback.
Actual receiving failures exhausted12 attempts and the300s deadline; these are
observed reasons for selecting the supported production envelope.

A newly selected review specifies `production:true`, `max_checks:null` and
`expires_at_unix_ms:null`. It keeps its exact retained human purpose and owned
JSON-pointer sources, runs through the same parent at15minutes or slower, and
shares production funding. Unchanged projections stay model-free. Retiring the
purpose or pausing Reports/global stops admission. Legacy finite reviews retain
original pilot funding, per-execution limits, expiry and four-execution ceiling.
No other lane, scheduler or silent finite-review conversion is selected.

Canonical checks continue while busy. New attention and known-unsent recovery
observe native contention before spending an attempt; a free local slot alone is
not proof that native is idle. A known busy native defers admission without a
reservation. An unloaded cache retains the existing model-free resume path;
missing metadata is not a new permanent activation gate. Mandatory atomic native
admission still verifies readiness/profile and handles later races.

When that read observes `notLoaded` and a null direct-input capability, status
reports `native_idle_unloaded`, presented as ordinary waiting. A cold native cache
is not an explicit admission refusal. It does not pulse as ready, resume a thread
or spend an attempt merely for the indicator. Explicit false admission capability
still reports unavailable; the ordinary work path and atomic admission are unchanged.
For a raw diagnostic read, reuse the shared proxy's WebSocket transport, as the
runner does. Sending newline JSON directly to that proxy never initializes it
and is not evidence of a native outage. Ordinary status uses the existing CLI.

At an acknowledged physical goal terminal, eligible pending canonical attention
can release the completed ordinary collector. The existing parent then admits
attention through the normal native idle check. Without eligible pending work,
collection stays across the configured idle checkpoint. Exact terminal metadata
can reconcile a missed terminal without importing or retiring missing output.
No goal pause/edit, native interrupt or input replay is needed for this handoff.

Production selection retains one bounded recovery permission for an already
exhausted original proved never submitted. Its exact return ID/next attempt stay
in one account-sized receipt. Repeating selection grants no further attempt.
Admitted, uncertain and completed executions are excluded. Explicit resume still
reconciles only proved-unsent generations; no fictitious trial renewal is used.

During listener delivery, inspect actual owned execution before pausing admission.
Let admitted work finish; preserve its original allowance and terminal outcome.
Use the current conditional heartbeat controls around the selected handoff and
restore only that operation's unchanged pause. A queued attachment is not actual
collection. Its final proof must postdate the replacement listener's process start,
not the earlier whole-operation preparation timestamp.

Fresh canonical Matrix originals retained during busy work expose
`producer.unoffered_inbox` before any return or reservation exists. They can
release a finished ordinary collector when Messaging is enabled. Already
attempted source revisions and a paused Messaging lane cannot trigger that
handoff. Status reads only local retained metadata and perform no live inbox I/O.

## First activation and recovery after a native profile refusal

Provision the App and its native Codex package as a compatible release set.
A running upstream daemon does not establish support for
`turn/startBoundedIfIdle`; an actual unsupported-method reply is a package
compatibility defect, not missing human authorization. Reuse the qualified
complete native package and the existing scoped daemon update route. Do not
reenroll the being, collect fresh membership signatures or substitute accounts.

Initial producer/resource configuration now persists its existing paused
control at generation zero. Selecting continuous operation therefore needs no
redundant pause solely to materialize a database row. Activation still requires
explicit global/lane resume with current generations.

After fixing a native refusal, ordinary explicit resume also reconciles a
rejected heartbeat return when its exact source and native-thread execution
receipt proves terminal `not_submitted` with no physical turn. Recovery keeps
the original source identity, attempts, resource reservations and history; the
existing worker makes the next bounded admission attempt. A mismatched,
physically admitted or uncertain execution remains ineligible. Do not edit the
live database or manufacture a new message to get past a pending batch.

### Missed physical terminal callbacks

The existing serial maintenance pass observes at most one exact retained owned,
stopping or transferred physical execution with no terminal receipt. It reuses
the eight-second metadata-only native lifecycle reader; full output remains in
its existing collection journal. There is no new scheduler, input, goal mutation,
provider request, replay or inferred result/review. A complete native closure is
committed only while the whole original execution record still matches under
the owning store lock. A later pause/transfer/physical selection wins; missing,
active or uncertain native evidence stays retained. Transferred cancellation
ownership remains transferred after its original physical turn is observed.

This covers boundary-only routed/workflow collections after a lost terminal
callback or listener replacement. Their output is deliberately excluded from
ordinary full-history collection, so output recovery cannot be the only way to
release completed heartbeat execution ownership. Ordinary new attention still
requires current lane, source, native admission and resource checks.


### Additional periodic purposes in Reports

`heartbeat select-review-task GENERATION TASK_JSON` selects up to four bounded
periodic tasks on the existing production review. It does not replace its eight
report sources, original purpose, cadence, next check, counters or funding.
The task contains `id`, `purpose` (actual retained input reference/channel),
`purpose_revision` (empty on submission; the owner resolves it), and
`instructions` (at most8000bytes). Exact same selection is idempotent; changing
an existing task refuses. Global and Reports controls must be paused at the
exact generation with no unresolved native execution or unreviewed pending batch.
Restore only operation-owned unchanged controls afterward. No other goal changes.

The existing Reports tick creates one task revision per review check even when
file snapshots are unchanged. The task's own `heartbeat_source` reader exposes
its retained human original and instructions; the batch's other purpose grants
no substitute authority. Retirement of that task's original suppresses only its
new offers; other sources remain eligible. Pending originals keep their exact
identity across later checks/restarts; no second scheduler or quota reset exists.
New stored tasks require this compatible reader on rollback.

For institutional preservation, reconcile the mapped intake with a durable
per-file/revision cursor and bounded pages. Retain selected originals and upload
receipts in institutional Drive before any authorized disposable-cache cleanup.
A full local cache or editorial backlog must not discard originals or terminate
canonical preservation. Keep recording, publication and editorial selection
separate. The callback is ordinary authorized native work using existing Drive
tools, not live Drive I/O in model-free status/quiet checks. Actual reconciliation,
configuration and subsequent periodic execution require separate receipts.

Periodic task instructions evolve through the same owner with
`heartbeat replace-review-task GENERATION EXPECTED_TASK_REVISION TASK_JSON`.
Read the task revision from status, pause exact Reports/global controls, and
replace only an unchanged task with the same retained purpose. Selection refuses
unresolved executions and pending unreviewed originals. The transaction preserves
all source cursors, report contracts, cadence, counters and funding; stale
replacements never change state. Restore only operation-owned unchanged pauses.
A private viewer projection may be part of its explicitly selected human purpose;
read the owning snapshot schema and run its finite conditional refresh after
meaningful source changes. An unchanged refresh must not grow publication history.
