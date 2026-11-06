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

Current receiving status is paused generation1, with producer/resources
`not_configured` and no executions. The selected backend offers global
pause/resume but no lane control/status contract, no explicit operational proof,
and no generation-conditional global pause. The UI therefore leaves all control
rows disabled with explanations. Messaging is the initial intended lane; Issues,
Sensory, Tasks and Bitácora remain unsupported. No write endpoint is introduced
to simulate the missing backend behavior or silently activate resources.

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
activate heartbeat. Served release683 remains an observation-only release until
an independently authorized receiving update. Native conditional source was
inspected in the owning concurrent branch; source capability is not selection.

### Operational evidence still required from the native owner

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
