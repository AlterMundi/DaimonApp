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
