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

### Operational evidence still required from the native owner

The producer status now retains one replaceable `last_check` with its sequence,
global generation, lane activation, start/completion milliseconds and outcome.
`last_success_at_unix_ms` records the last completed source check; it stays
unchanged after a failed read. Older producer documents report these fields as
null until a new check. A failed inbox read uses the fixed
`matrix_inbox_unavailable` classification, without retaining arbitrary adapter
error text. A late page rejected after pause or a generation change
cannot complete the earlier observation. An interrupted check can therefore
remain `in_progress`; its timestamp and generation must be inspected rather than
interpreting the word as a current live process. The existing 256KiB producer
document cap includes this record; it is not an accumulating event log.

These are source observations only. They neither demonstrate a useful native
action/delivered reply nor grant operational readiness. The following additional
readiness evidence remains required.

Proposed exact additional status field, to agree and qualify before consumption:

```json
{"operational_evidence":{"schema":"telecodex.heartbeat-operational/v1",
  "generation":4,"observed_at":"2026-11-06T12:00:00Z",
  "valid_for_seconds":15,"operational":true,
  "lanes":{"messaging":{"generation":2,"operational":true,"reason":"ready"}}}}
```

The native owner must derive this observation from the selected producer's
actual bounded readiness (registered/live loop and fresh successful check),
valid unexpired finite resources with remaining admission capacity, and the
selected native execution primitive's actual availability for this actor/entry.
The global fence and each claimed lane must be enabled at the exact returned
generations. Missing, expired, exhausted, unavailable or errored dependencies
must return false with a bounded reason; an idle ready loop can be operational.
An active execution, configured producer, open gate or successful control ACK
alone cannot supply this proof. Evidence lifetime is at most15seconds; stale
or mismatched generations cannot pulse the heart. This is a proposed contract,
not a claim that the currently selected backend emits or proves it. The existing
App state reader still waits for explicit owner-derived `operational=true` and
rejects contradictory status; this preparation adds no synthetic positive proof.

## Versioned native control successor

### Explicit owner renewal of an expired window

The owner console additionally supports:

```
heartbeat renew-window GENERATION PREVIOUS_EXPIRY_MS NEW_EXPIRY_MS
```

Use only under an explicit owner-selected new operating window. Read status,
pause at its exact generation, and supply the observed common resource/producer
expiry. The predecessor must be expired and the new window must end within seven
days. Both deadlines change in one transaction. The account ID, lifetime reserved
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
