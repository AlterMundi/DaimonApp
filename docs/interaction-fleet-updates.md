# Shared application receiving updates

Nicolas54cf48b4 requires ordinary shared updates to include all registered living
DaimonApp receivers without another distribution request. Resolve the existing
paired-App/Shared Resources receiving records and actual physical placement;
never use old Source containers or a hardcoded historical host list as targets.
A common source release may have different receiver configuration and compatible
backend composition. This is fleet coverage, not a simultaneous global restart.

Reuse the existing immutable release directories, local maintenance/unit writers,
source qualification and current owner journal. Prepare one qualified release,
compare each selected source/reader/locked environment, reconcile owner changes
into common code or explicit existing receiver configuration, and apply at that
receiver's safe boundary. For logical voice changes, qualify the view lifetime as
well as the transport: a current renewal engine alone does not establish that its
receiving view honors the admitted untilStop lifetime. Native changes use the supported collector-preserving
handoff; a web-only change does not restart native work. Preserve paused/blocked
goals and uncertain inputs. Never clear journals or replay a command to manufacture
convergence. Reuse actual outcomes after a failed verifier.

For collector-preserving listener replacement, snapshot every owned goal's
identity, revision, pause state and accounting, but enumerate turns only for
currently loaded owned threads (`thread/loaded/list`, then `thread/turns/list`).
Reading every historical unloaded rollout adds latency without identifying more
live collectors. Keep both enumerations bounded; native task-lifetime admission
remains authoritative for Core maintenance. This observation neither resumes a
thread nor establishes global idle. If preparation expires before any selector
write, inspect that retained outcome and current preimage before continuing the
known-unstarted operation with the same qualified artifact.

Native selectors may use a symlink. Compare the effective existing ExecStart
argument with the process executable's resolved identity and qualified digest;
conditionally replace that actual argument, rather than searching the unit for
the resolved target pathname. Keep source-manifest cache exclusions identical at
preparation and selection: ordinary `__pycache__`/`.pyc` files do not change the
qualified package, while every selected source/asset must still match. Retain
failed preflight receipts and use a separate known-unsent continuation. After a
selection times out during observation, inspect that original installed outcome;
never rerun selection just to obtain a successful verifier exit.

Apply the short path to the whole delivery, from preparation through installation
and verification. Reuse qualified unchanged packages and observed receipts rather
than adding another build, review or approval gate. A task's clean checkpoint
does not reserve native idle: active goals may immediately continue. When selected
maintenance needs that boundary, prepare the existing finite owner-scoped
pause/restoration transaction before pausing eligible goals, then perform the
handoff and verify conditional restoration. Preserve prior pauses, blocked goals,
later human direction and accounting; do not use maintenance holds as evidence
of useful heartbeat availability. An expired uncertain transaction remains
historical evidence after a later explicit goal control supersedes its authority;
it must neither be replayed nor block a freshly observed operation forever.

Keep one deployment checkpoint containing each actual receiver, prior/current
selection, exact source/assets/reader/configuration preservation, adoption outcome,
rollback and concrete pending reason. Verify own actor/grant and private API refusal
as the actual service user. A source publication, health read or message is not
receiving adoption. Open browser tabs continue until their ordinary reload; this
requirement adds no forced reload, automatic microphone switch or model wakeup.

Current common-code integration preserves Eko's separately selected opened-view,
pin and all/recent preferences using the same bounded opaque preference record.
The recent24hour default remains; an explicit receiver profile can choose all.
Selected local improvements must survive rather than be replaced by the author's
moving checkout. Only reviewed source/code goes across receivers: never copy a
being's identity file, API key, browser profile or private memory. Native Avatar
and new provider billing remain OFF on a receiver unless separately selected.

`/tribe` is the foundation scope of paired/sharing daimons and humans. Source/Weave
can carry attributed offers/evidence and local decisions; owning application
maintenance performs the software effect. See Matrix's tribe-updates runbook.
No parallel chat-based deployment registry, second login or generic automatic
adoption framework is introduced by this requirement.

Initial6November preflight found CompAII web678/native668, Eko's newer local
1109321 continuity composition and Oliva's older543/508 composition. These are
observations, not full parity. Resolve the current receiving record before
applying a release; app/native reader compatibility and owner overrides must be
qualified for each of those existing profiles. Full fleet completion remains
open until actual receiving adoption, not just this common-code preparation.

Public native voice qualification must load the receiving `Provider` and verify
its callable `conversation_foreground_interpret`, as well as the native writer's
`gpt-transcribe/v1` capability. A6November real generated-audio trial reached
completed ASR but found that method missing from the selected web composition;
native capabilities and synthetic mounted providers had not exposed the omission.
Preserve receiver-local adapter edits when composing the qualified method. Refuse
before paid creation if either side is unavailable; do not replay held ASR/media
or infer that a retained native-write intent was sent.


The shared avatar workshop additionally requires Node20+ on the actual web
service PATH. Run staged WebRTC/Avatar Node lifecycle fixtures with that same
PATH and consuming UID too; a shell PATH can miss an already installed runtime.
Keep any unchanged external fixture dependency beside the test, outside the
selected web package. Qualify the pinned inert-design validator as that service user,
including catalogue/custom save/reload/use in temporary synthetic-account storage,
before selection. A root-only executable check or installed package alone is not
consuming-process acceptance. Keep a required body-local PATH entry in the
existing service configuration and its retained preimage; do not introduce a new
login, change providers or activate an avatar during software delivery. See
[workshop receiving](interaction-avatar-workshop.md#receiving-selection-6november2026).
Before selecting a composed workshop, verify its complete adapted bytes with
`python3 -B -m dashboard.avatar_workshop_provenance --root STAGED_WORKSHOP`.
A stripped receiving package can omit the development checker; run the maintained
checkout's checker against that root instead of installing it into the service.
Checking only the newly changed files or copying `PROVENANCE.json` is insufficient:
a prior incomplete copy can omit the pre-paint presentation script or its cosmetic
appearance bridge while constructors and changed-asset hashes still pass. Inspect
any retained difference, preserve actor data and restore only the selected source;
do not replay an earlier selection to correct a preparation/verifier error.


## Voice admission during web maintenance

The current web reader uses one persistent empty owner-only lock at
`<state_dir>/voice-admission/.lock`. After the existing actor/CSRF/binding checks,
all voice WebSocket modes take a shared OS lock before opening a provider,
preparing microphone admission or submitting work. Unauthenticated transports
cannot reserve it. The lock follows the connection and its owned late setup/
cleanup; it is not a model lease, scheduler or native work cancellation.

Use `scripts/interaction_web_maintenance.py` to run the existing scoped web
operator. Supply the actual selected private config, the local health URL from
that service unit, its OS service UID (not a Telegram/human ID), and the finite
operator command. The helper acquires an exclusive nonblocking lock, matches the
running server's `X-DaimonApp-Voice-Admission` header to that exact lock, rechecks
config bytes, then transfers the lock through exec. Its existing Linux timeout
bounds execution to180seconds by default, at most300, with5seconds to terminate
owned children. No deployment target, service, source or provider is chosen here.

```sh
SERVING_PYTHON scripts/interaction_web_maintenance.py \
  --config SELECTED_PRIVATE_CONFIG \
  --health-url SELECTED_LOCAL_HEALTH_URL \
  --owner-uid SERVICE_UID --seconds 150 \
  -- SERVING_PYTHON EXISTING_SCOPED_WEB_OPERATOR
```

Before stopping the web, run the candidate imports and application-constructor
qualification with the interpreter and locked environment from the actual service
ExecStart, as its consuming user. The maintenance wrapper's interpreter does not
select the interpreter of the command after `--`; use the explicit serving Python
there too. For `python -m uvicorn`, the selected working directory can provide
the App while PYTHONPATH keeps stable dependencies and an older fallback source.
Do not require the working directory to appear there: preserve those prefixes,
prove the candidate module import as the consuming UID, and CAS-edit the current
selector before exact served-asset readback. Complete dependency/constructor checks before the stop. If a new owner
binding requires a post-migration constructor check, preflight the unchanged
imports before stopping and retain the exact migration phase separately.

If an operator fails after stopping the web, inspect its retained phase, current
selector, unit, process and configuration before acting. Continue only the missing
steps with the serving interpreter; never rerun completed authority, grant or
journal migrations. Restore service availability before unrelated qualification
or fleet work. Preserve the original failure and a separate recovery outcome.

Receiving-profile reconciliation must respect disabled optional services. A
receiver without companion device access has `Grants.root is None`; it has no
device grants to enumerate or reauthorize. Likewise, absent Traffic configuration
has no Traffic journal to migrate. Verify the actual enabled components before
stopping, preserve disabled settings, and reconcile only their existing same-actor
journals. Do not create a grants directory or enable a service to satisfy an
operator assumption.

If reconciliation already adopted Alerts/menu fingerprints before encountering a
disabled component, verify those exact new fingerprints and compare preserved
menu fields with the retained preimage. Skip the absent component and continue
the missing constructor/start/health steps. Keep the failed receipt and a separate
forward-recovery receipt; do not rerun the completed journal migration. The
7November peer delivery exercised this case with companion disabled and no
Traffic configuration; native work and receiver provider choices were preserved.

Exit75 means voice owned the lock and the operator was not started. Exit78 means
reader/state/config qualification failed before execution; inspect that mismatch.
A deadline/nonzero result after execution is the operator's actual outcome, not
permission to retry. Keep its intent, phase and receipts and inspect selected
state. Preserve the previous selectors/unit/config, goals, libraries, original
media and unresolved work. Never unlink, replace or reset the lock file. It is
constant-size; the kernel releases owned locks when their processes end.

Hold the fence through the existing idle/unsettled-source checks, selection,
web restart and final health/assets/owner verification. Those checks remain
necessary: the fence is not proof that an earlier provider call or native write
was settled. It does not exclude independent native CLI voice or turn the
thread-scoped native Stop into a generation CAS. It changes no capture duration,
provider/default, account/permission or resource-activation policy.

An older running reader without the matching header does not support this
exclusion, even if a newer candidate or leftover file exists. Qualify its initial
bootstrap through the current observed-idle route and record that limitation;
do not silently bypass or pretend it had atomic admission exclusion. Once the
reader is selected, ordinary later updates must use the shared fence. Publication
or source tests alone do not establish receiving/device acceptance.

## Collector verification after a listener replacement

A failed `attach-active` command must retain its actual stdout/stderr. It is not
proof that the native turn stopped or that attachment should be repeated. Read
the current physical turn and the retained collector/admission records first.
Startup recovery can already own a replacement collector. Later accepted routed
input can also own the same physical turn through an ordinary worker rather
than an explicit attachment. Preserve that input and its publication authority;
do not create another attachment or repeat the input to repair the verifier.

For the selected physical turn, verify either a fresh current collector receipt,
or a current running worker with an accepted source correlated to that exact
native turn after the replacement. A running local row or an owner-command ACK
alone is insufficient. If the native turn has finished, observe its retained
terminal/result path instead. Keep the failed operator receipt and record the
separate verification outcome; never rerun its completed selection phases.

## Matrix profile changes and same-scope web companions

A running web PID is not proof that its receiving authority still matches a
changed native profile. `Provider` freezes `receiving_authority` at construction;
Alerts/menu/Traffic also retain their qualified binding. Adding or changing
Matrix transport fields can therefore require requalification even when the
paired human, allowlist, accounts and resource grants are unchanged.

Use the exact retained native-profile preimage from that update. Compare its
normalized `receiving_authority` to the actual current profile as the service
user. A Matrix-only transition must differ only in the intended
`interaction.matrix_transport`, `matrix_inbox_channel` and `matrix_targets`
fields. Unexpected authority differences stay explicit; do not reset credentials
or silently accept a broader scope.

Reuse the receiver's existing same-scope companion requalification and voice
maintenance fence. Qualify current `Provider`, `dashboard.alerts.Receiver` and
`dashboard.traffic.Traffic` constructors with isolated temporary state first.
Require actual journal/menu/Traffic bindings to match the exact previous proof.
Then stop only web, retain one bounded operation preimage, conditionally update
only those binding references, and verify every delivery attempt and other state
field is unchanged. Reconstruct as the service user, reload web and verify the
actual authorized owner API. Preserve native/Core/Sessions, original journals,
provider choices and uncertain effects; never recreate a journal or replay input.
Exact routes/preimages belong in the receiving operator binding, not this guide.

Edit only an owned, delimited section of a shared operator note. Another task may
have appended current receiving evidence between older headings; replacing a
whole prefix can discard it. Retain other sections and distinguish this source
publication from actual receiving adoption.

### Native package copy within the existing handoff window

A bounded v2 handoff keeps its original absolute deadline (at most300 seconds).
After natural-idle maintenance, installation may use at most140 seconds and only
the time left after reserving66 seconds for stopped recovery. A real725MiB Eko
package copy exceeded the former15-second substep cap; the operator restored the
previous complete selection and retained that terminal receipt. Inspect its
actual selection/process state before a corrected successor; never replay its
intent. The finite window, natural-idle requirement and no-input-replay policy
are unchanged. Native-only delivery leaves the listener/web and voice settings
running.

Collector verification must use a receipt after the replacement listener actually
started, not the earlier whole-operation preparation timestamp. Keep the failed
verifier/queued attachment when its physical writer ended; inspect the current
writer without repeating selection or attachment. The existing recovery loop can
reconcile a current collector from exact terminal lifecycle metadata and current
goal state. This does not import or retire missing output, replay input, change
a goal or start a second scheduler. Full output recovery keeps its original
bounds and checkpoint.

Before recording a remote launch intent, materialize and read its complete public
payload and entry script. A local missing-file error while evaluating subprocess
arguments proves no transport invocation; retain that failed intent and continue
only the known-unattempted remote action with a separate recovery receipt. A
transport timeout is different: inspect the original remote process/receipt and
never use this local-preflight recovery rule to replay an uncertain launch.

### Completing a basic child receiver's native voice configuration

A basic text/Avatar receiver can have current client assets while retaining an
older Python native-voice backend. Before enabling continuous native voice,
qualify the composed backend rather than accepting assets/constructor health as
proof of renewal. The current contract includes `openai_live_api`,
`openai_live_visits`, `openai_live_native_session`, `integrator_startup` and the
owner-bound `Provider.public_live_integrator_context` reader plus its existing
`scripts/activity_indicator.Native` observer allowing `thread/items/list`. Verify
the real same-owner paginated read before microphone or paid creation; importing
the reader and exercising it with a fake transport misses a stale observer fence. Reuse published
qualified components and preserve unrelated local Provider behavior. The API
requires that reader before paid creation; continuous renewal also needs the
finalization/context-readiness methods on the retained visit store.

Use the existing selected child account custody and private brief/ASR bindings;
never substitute Codex OAuth for its API key. Both raw file-only and completed
Live-only profiles retain their distinct existing routes. Include the declared
`websocket-client` dependency in the consuming interpreter's actual search path.
For fixture imports of command-line `scripts/interaction_asr.py`, include its
scripts directory as the CLI does; a package-style import failure is not evidence
that the actual command lacks a dependency. Mounted qualification must preserve
the serving dependency prefix in PYTHONPATH as well as the candidate source.

Retain one private preimage/proposal pair. Under the existing voice fence, check
all selected native work idle, preserve actual goals/revisions and native binary,
and apply only the required configuration and coherent web delta. Preserve Codex
and Matrix processes, identity/grants, journals, original media and later owner
changes. A listener restart is distinct from restarting its native Codex backend.
Verify consuming-user constructors, loaded capabilities, own Home entry, anonymous
and foreign refusal, selected assets and unchanged goal/accounting. A first-sound
probe is separately bounded to one new provider session per selected actor; an
existing equivalent attempt must be inspected instead. Stop explicitly, retain
unconfirmed final usage without refund/retry, and distinguish decoded technical
audio from sustained family/device/hearing acceptance.

The browser `openai-live.js` is also part of that coherent closure: current HUD
assets and a renewal-capable server do not prove the selected client renews its
physical visit. Qualify the actual served client with the lifecycle/source/
recording-recovery suite; keep the same microphone, per-visit upload locks,
confirmed-close/context-readiness barriers and unchanged bounds. A short first
answer demonstrates audio, not continuous renewal.

Sideband source requests can precede WebRTC's connected callback during healthy
activation. Reserve the same bounded source request and wait for that owned
activation's readiness; confirm raw bytes only afterward. Stop or failed/retired
activation rejects that wait. Duplicate requests reuse one prefix/upload; they
never create another voice call or bypass binding, capture or source checks.

### Adding the portable Conversation descriptor

Select the already-qualified App publisher with the existing collector-preserving
native handoff. Resolve each real Home pairing and registered Interaction route;
configure only that pair's publication surface/audience and private owner signer.
A descriptor is public verification metadata, never proof of a message delivery or
permission to replace an older ambiguous publication. Matrix selects its signed
policy through its separate existing writer; this App update does not reload it.

Adding interaction.matrix_publication changes the current Provider authority
fingerprint. Reuse same-scope companion requalification, preserving attempts,
menu/Traffic state and unexpired devices through their supported reauthorize
operation. Qualify all selected constructors before stopping, then use the voice
admission fence while selecting configuration and compatible code. Preserve
Core, native threads, goals/accounting and exact current collectors; inspect a
failed final verifier instead of repeating a completed binary/config selection.

Inspect the actual serving Provider presentation_list publications argument and
the mounted HTTP reader, not only the repository ancestry or browser assets.
The10November original-three check found matching Conversation JavaScript but
older Provider/API functions. Composing just those two qualified814 reader deltas
preserved the current artwork, voice/storage fixes and other receiver code. The
exact staged reader plus full-audio binary passed the real owner socket/SQLite/
authenticated HTTP publication fixture with the installed compatible Matrix SDK.
Source publication, actual native status, current reader and the later Matrix
publication/receiving journey remain separate observations.

## Served UI fingerprint

The human-selected small `ui` hash uses the existing client-build label on
Sessions, Conversation, workshop navigation and enabled App-hosted Pulso. It
hashes actual public frontend bytes, including the selected immutable workshop
assets; publication metadata and catalogue versions are not UI fingerprints.
The parent page pins its workshop/gallery imports to that exact selected public
release, preserving the label and any already loaded editor across a later
publication. The workshop reuses the parent label rather than rendering a second
version mechanism. Pulso uses the same label/hash helper over its actual shell
and externalized CSS/scripts. Private reports, actor data and authentication are
not inputs. Keep existing per-pair routes and shared authentication; this change
does not create aliases, grants, polling, synthesis or new application entries.
Standalone pages served by Home remain with their owning publisher.

Retained pre-voice Sessions/Pulso sidecars can use the same
`dashboard.client_build` formatter without replacing their backend with the
current Conversation app. Keep their two-asset Sessions shell, renderer and
existing private configuration; stamp the existing header marker with
`fingerprint(index_bytes, [('app.js', js_bytes), ('style.css', css_bytes)])` and
reuse `CSS` on the existing stylesheet. An enabled Pulso adapter uses the same
shell/external-asset stamping described above. Qualify imports and configured
Pulso construction as the consuming user before selecting the immutable successor.

Inspect the actual factory/service contract first: retained uvicorn factories
read `TELECODEX_DASHBOARD_CONFIG` from their existing environment, not a presumed
`--config` argument. A retained Pulso may select its immutable source through an
existing `current` symlink; use that owning conditional selector instead of
rewriting an unrelated unit or creating another alias. Preserve the original
configuration, audience and main Conversation/native service invocations. These
non-voice sidecars need no voice-call restart; a known-unselected preflight failure
can continue the same frozen candidate after correcting its operator metadata.
