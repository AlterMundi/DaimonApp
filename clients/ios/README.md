# iOS native audio preparation

## Encoded-source preparation

`VerifiedEncodedAudioSource` supplies the decoder-worker boundary corresponding
to Android's `VerifiedAudioBuffer`: ordered SHA256-verified chunks of at most
32768bytes, one flat8MiB buffer, and verified terminal length/digest before EOF.
A missing prefix waits within the existing30second/145second decoder bounds;
close or invalid input wakes readers and permanently retires that source.
Those bounds govern decoder waits, not a media upload or network request.
Caller-owned and returned data cannot alter retained bytes. Flat storage avoids
per-chunk metadata growth for small valid chunks.

`EncodedSpeechDecoder` consumes that verified source using Apple's sequential
MP3 stream parser and converter. It emits at most8192bytes of24kHz mono PCM16
per callback, within the existing default300/explicit600second PCM bound. Packet
sizes/counts, format and conversion/drain work are bounded; bad input, consumer
failure or source close retires the single-use decoder. Whole-stream EOF still
requires the terminal digest. Prefix PCM is provisional decoded preparation,
not a completed source or played/heard receipt. Tests reuse the existing Android
MP3 fixture, including actual packet splits and decode before terminal bytes.

The parser/converter acquires no audio device/session. The existing iOS bridge
still accepts PCM/Beacon only. Native decoder/playback wiring, encoded admission
and background/media controls remain necessary before advertising parity;
normal native capabilities stay off. A completed-buffer player is not a
replacement for progressive decoding. Future loading/muted validation must not
call `AVAudioPlayer.prepareToPlay()` before explicit source-qualified playback:
[Apple documents its session activation](https://developer.apple.com/documentation/avfaudio/avaudioplayer/preparetoplay()).
The [stream parser contract](https://developer.apple.com/documentation/audiotoolbox/audio-file-stream-services)
requires ordered file bytes and parser cleanup, not a second network transport.

## Existing PCM and app preparation

The existing native-client plan selects an equivalent iOS client. This package
prepares its audio core with the same 24 kHz mono PCM16 span contract as Android's
`PcmPlaybackQueue`: SHA256 integrity, exact sequence/source offsets, at most
32768 bytes per chunk, 30 seconds queued, 128 source identities and 512 live
spans. Default lifetime is 300 seconds; an explicit duration may reach 600.
Flush retires sound and source identities without resetting sequence or lifetime.
Scheduling/submission never becomes a played receipt. The eventual native driver
must provide its current owner's actual playback observations and fence late
callbacks by owner and playback epoch, including after pause, flush or stop.

The queue belongs to one serial output owner. `PCMPlaybackDriver` adds that
main-actor owner, an absolute nonrenewable deadline and at most eight scheduled
buffers. Native callback receipts advance only a contiguous completed prefix;
flush/close invalidate the epoch before unscheduling. Pause retains the queue
and needs explicit resume. Device failure closes without replay. The host supplies
its owned audio-session activation/deactivation closures; a failed activation
must clean up its own partial session change. Idle/paused/closed output releases
its own holder. Host lifecycle/interruption/route changes must close the driver.

`ApplePCMOutput` uses AVAudioEngine/AVAudioPlayerNode with mono24kHz float buffers
converted from the exact signed little-endian PCM16 bytes. It requests
`.dataPlayedBack` completion and dispatches it back to the owner; no stop or
unscheduling occurs inside an audio-thread callback. Manual/offline playback
cannot emit a played receipt. This package makes no microphone, provider,
authentication or background activation request.

Five queue XCTest scenarios cover partial submission/playback, source offsets,
atomic refusal, queue/source/span bounds and ten minutes across flush. Five more
check the actual Apple buffer conversion and synthetic device callbacks for
ordered receipts, stale epochs, pause/eight-buffer bounds, expiry and failure
without retry. These tests do not establish actual device playback or session
policy. CI uses the existing public repository's standard macOS runner, two
compiler jobs and a ten-minute deadline. No dependency package or signing identity
is fetched. Scratch output belongs to the disposable runner; no generated audio
or new retained cache/artifact is uploaded.

`AudioSessionOwnership` prepares one shared session with at most two independent
holders. A stale release cannot deactivate a fresh owner. Failed activation gets
one owned cleanup attempt; failed cleanup/deactivation remains unconfirmed and
blocks new owners until exact explicit recovery. Four synthetic-session tests
cover these transitions without an audio device.

The iOS-only `IOSSpokenAudioSession` supplies `.playback`/`.spokenAudio` ducking
and deactivation notification to other apps. It closes prepared as well as active
outputs on background, interruption begin or selected route loss/change. Returning
to the foreground allows a later explicit start; no notification resumes sound.
One instance belongs to the app, not one per buffer. This is a spoken-output
policy, not a duplex capture policy or background entitlement. Actual session,
route and music behavior is not qualified by source/SDK compilation.

CI also compiles every source against the actual iOS Simulator SDK with an iOS17
minimum target and signing disabled (a transient library, not an application).
This catches iOS-only API/type errors that a macOS package build cannot observe.
Neither the dylib nor build cache is uploaded; the ten-minute job bound remains.

The prepared `InteractionWebViewController` embeds the existing hosted Conversation
and shared-auth navigation using persistent WKWebsiteDataStore. Its injected
source must be the existing app-bundled Android `native-audio.js`, not a downloaded
script or a new fork. The wrapper keeps native capabilities off and encoded
playback in the existing browser path until the iOS journey is qualified.
A valid app home is HTTPS without credentials/query/fragment/nonstandard port.
Only exact-origin `/interaction/` main frames can send the closed PCM contract;
SSO/external pages have no native bridge. Other HTTPS links open externally only
from a deliberate link navigation. The server still owns login, actor and grants.

Per-document UUIDs fence callbacks and commands across navigation, even when
page-local PCM serial IDs repeat. At most16retired documents are retained per
controller; thereafter no native admission occurs until an explicit new view.
The controller closes output on navigation, WebContent termination and leaving
its visible/foreground lifecycle. It never replays a page/input/media submission.
Three Foundation tests cover selected-home/page boundaries, closed message fields
and numeric/bool refusal. SDK compilation checks the iOS-only WKWebView types;
the current receiving qualification below owns actual injection/iframe/native runtime evidence.

`App/AppDelegate.swift` now prepares the scene-based UIKit application: existing
shared-session ownership, native home entry, persistent home selection and the
hosted Conversation controller. `build-simulator.sh OUTPUT` builds an ad-hoc
simulator bundle with the exact existing native adapter and its checked SHA256.
It refuses an existing output directory; bundle bytes stay below16MiB. This is
not device signing or an IPA/TestFlight release.

`--qualification` builds a separate fixture-only bundle ID and finite page-start
hook that are absent from the normal app. `test-simulator.py --app BUNDLE` creates
one disposable installed iOS simulator and a loopback-only HTTPS fixture. Its
one-day public test anchors are copied only into that app's container and consumed
by the separate qualification-only TLS helper; system trust stores and normal
app TLS handling remain unchanged. Wrong-host and wrong-anchor validation must
fail before accepting the exact localhost chain (details below). The fixture sends synthetic PCM through
the actual WebView/bridge/engine, checks played receipts and pause/resume/flush,
attempts iframe reservation, then navigates outside the application path. No
microphone, provider, human voice original or real shared-login account is used.
It starts the fixture once, waits at most65seconds for its terminal receipt and
never relaunches on timeout. Teardown removes that device, server, CA and state.
CI replaces the redundant standalone SDK library build with this application
build and journey under the same ten-minute cap. No app/certificate/audio artifact
is uploaded. App code e8eac0a passed macOSCI42380042745 (17cases) and the actual iPhone16/
iOS26.2 simulator journey:28800played bytes, pause/resume/flush, iframe unable to
reserve native output, and native facade absent outside the app path. App build,
exact adapter, install/launch and scoped terminate/shutdown/delete/server cleanup
all passed. This is synthetic PCM/device evidence, not physical hearing, capture,
duplex voice or real shared-login/passkey acceptance. The native capabilities
remain off for normal users until those missing paths qualify. CI also follows
changes to the shared Android adapter; documentation-only changes need no new
native execution.

Final head9fa7cfc did not reproduce that journey in CI42380585273: launch
observation timed out and no terminal fixture receipt arrived. Device/server
cleanup passed; the failure remains unresolved. The fixture now allows90seconds
for the one launch observation and retains a bounded test-only startup stage,
loopback request observations and a three-minute native log on failure. It never
relaunches an uncertain start. These diagnostics are absent from pilot builds.

This is not a device-distributable iOS app. Continue with actual AVAudioEngine/device and iOS AVAudioSession acceptance,
actual WKWebView bridge/document injection and shared-login shell acceptance,
foreground capture/route/interruption/return handling, progressive/background
speech, native Beacon and actual simulator/device acceptance. Reuse the hosted
Conversation, account grants and existing wire contract; do not create another
login, editor or server. No iOS capability is advertised by this package.
Distribution, signing and physical iPhone acceptance remain unqualified.

References:

- [Selected client plan](../../docs/interaction-native-clients.md)
- [Apple playback completion types](https://developer.apple.com/documentation/avfaudio/avaudioplayernodecompletioncallbacktype)
- [Swift Package Manager](https://docs.swift.org/main/documentation/packagemanagerdocs/)
- [Standard GitHub runner contract](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)


## Native Beacon DSP preparation

BeaconSynth ports the existing Android six-carrier synthesis without adding
partials, texture, a provider or a state observer. Frequencies/pulses/depth are
fixed per owner; weights stay within one normalized mix, and level stays<=0.8.
Transitions retarget current values. Identical observations cannot restart phase
or an unfinished ramp. A selected fade reaches exact silence; input arrays cannot
mutate the owner's state. Audible carriers must stay below0.45of the sample rate.
PCM16 rounding preserves Android's half-toward-positive-infinity rule.

Six new XCTest scenarios check spectrum/mix, chunk and refresh invariance,
selected breathing, retarget/fade, atomic invalid controls and a PCM SHA256 from
the actual existing Java BeaconSynth. The two-second reference includes six
components, breathing, retargeting, duplicate controls and fade. Java generation
used only disposable local classes, removed after producing the digest; no audio
artifact, mic, provider or live observer was retained. Sourceb7b7155 passed23XCTest cases and the actual iOS app build in
CI42386636123, including the Java/Swift PCM digest. The runtime journey then
failed after an unconfirmed90second launch and no page receipt; cause remains
unknown. Termination was unconfirmed, but shutdown/delete/server stop were
acknowledged. That journey did not exercise this unwired DSP core and is not
recorded as a native Beacon playback pass.

`BeaconPlaybackDriver` now prepares foreground output through the existing
ApplePCMOutput and IOSSpokenAudioSession. One reschedulable monotonic timer and
at most two40ms PCM buffers bound pending output; controls replace current targets
without accumulating work. Only a contiguous actual played-callback prefix can
report sound. A two-second callback stall closes the owner without retry. Frame
validity is at most20seconds and gain cannot refresh it; stale weights fade to
zero over one second. The nonrenewable two-hour deadline includes a final350ms
fade and an independent sample-production ceiling. Quiet output releases only
its own shared-session holder; host route/interruption/foreground-exit closes it
without automatic resume. The combined speech/Beacon owner count stays at two.

Five new synthetic-device tests cover queue/callback ordering, stale/gain/fresh
controls, independent speech ownership, absolute lifetime, failure and no retry.
The qualification-only app probe uses the actual native output/session to require
played callbacks, stale quiet, fresh resumption, selected gain-zero quiet, gain
restoration and host foreground-exit closure. It runs once with a12second bound,
requests no microphone/provider/observer and does not expose a new JS command.
Its receipt is required before the existing PCM WebView journey. This exercises
host foreground-exit policy, not an actual OS background transition or physical
hearing/music/route acceptance. SDK/runtime outcomes must be recorded separately.

The native Beacon capability stays off. The prepared closed per-document adapter
now reuses the existing beacon_begin/frame/level/stop contract. Continue actual
bridge/runtime and capture/duplex compatibility qualification before advertisement. Physical phone/music/hearing, shared login, distribution/signing
and the full original goal remain open.

Historical CA provisioning used a90second observation bound, qualified in
PR728source816fd9a andd1f1f4b after a30second timeout and an84.88second successful
admission. PR731 subsequently timed out even at90seconds before installing the
app. That system-trust-store provisioning is now removed from this fixture as
described below; its outcomes remain historical evidence, not a command to repeat.
The separate capture implementation/review is not included.


### Qualification TLS isolation after PR731's CA timeout

Sourceb5c440b passed28Swift cases (zero failures,1.638s), actual iOS SDK app build
and all five general checks. RuntimeCI42390310788 failed during90second fixture
CA admission before app install/launch; runtime listing took77.63s and boot103.1s.
Shutdown/delete/server cleanup passed. That outcome is not Beacon playback proof
and the terminal operation was not replayed.

The disposable fixture no longer mutates the simulator trust store. Only the
qualification bundle compiles `Qualification/FixtureTrust.swift`. After its one
launch, the fixture supplies two bounded public DER anchors through qualification
arguments. No app-container lookup/copy is needed to provision those public data. For localhost443 server-trust challenges only, the test delegate uses
Apple's SecTrust SSL hostname/chain validation with the fixture anchor exclusively
and network fetching off. It must first reject the same chain for another hostname
and an unrelated anchor. Other hosts/auth methods retain default WebKit handling.
Missing anchors, invalid chains and repeated failed challenges are refused.

This is a test-only provisioning replacement, not production certificate pinning,
a TLS bypass, login or relaxed application origin/bridge admission. CI also builds
the normal app without that extra source and checks its symbols exclude the helper.
No root certificate is installed in system/device trust. Both one-day public anchors,
private signing files, server and disposable simulator stay within the
existing job/deletion bounds; nothing is uploaded. The native receipt must include
the positive chain and both negative trust results before PCM playback acceptance.
This fixture no longer qualifies system-trust-store installation; normal shared
SSO/account and physical device trust remain separate acceptance requirements.

Apple contracts: [custom trust anchors](https://developer.apple.com/documentation/security/configuring-a-trust)
and [WebKit authentication challenge handling](https://developer.apple.com/documentation/webkit/wknavigationdelegate/webview(_:didreceive:completionhandler:)).


Source339c266 passed28Swift cases, both actual iOS SDK builds and the normal-app
helper-absence check. RuntimeCI42391234480 installed the app in27.74seconds but
then timed out reading its data container in30seconds before launch. Shutdown
and delete were unconfirmed; the server stopped. There was no TLS/audio runtime
receipt. The current fixture removes that unnecessary prelaunch read/copy: its
single launch carries only two bounded public DER anchors as base64 arguments,
parsed only by the qualification source. Keys never leave disposable runner state;
production bundles still compile no fixture helper. All old outcomes stay retained.


Source68c7fca passed28Swift cases (zero failures,1.689s), both actual SDK app
builds and normal-app helper absence inCI42391956558; all five general checks
passed inCI42391956382. Runtime installed in51.62seconds, but the one launch
observation timed out at90seconds. No page request, stage read or application log
established launch, TLS checks or new Beacon playback. Termination was unconfirmed;
shutdown/delete/server stop were acknowledged. Cause remains unknown; do not
classify this as a TLS or audio failure, retry the terminal launch or advertise
native capability. PR731 remains open pending actual new output qualification.
The earlier successful PCM baseline does not cover this new Beacon driver/probe.


## Prepared closed Beacon bridge

The existing `audio` handler now accepts only the closed Beacon commands from the
same exact main-frame origin/page/document checks as PCM. Beacon UUIDs are canonical
and separate from PCM IDs. One controller admits at most128distinct starts and
never reuses an accepted ID, including across document changes. A duplicate/new
begin cannot replace another current owner. Explicit Stop, page navigation,
WebContent loss and foreground exit close the exact Beacon owner without replay.
Speech and Beacon continue to use independent holders in the existing shared
session; no extra login, provider, observer or entitlement is introduced.

A frame is at most4096UTF8 bytes, six strict finite non-boolean numeric vectors,
normalized active weights, valid frequencies/ramp/depth/level and an exact safe
integer absolute uptime deadline in milliseconds. It is converted to seconds
without manufacturing a new lifetime. The native driver enforces its20second
maximum and stale fade. Gain commands cannot include or renew a deadline. Replies
bind to the accepted owner and document; played events still require actual device
callbacks. The existing adapter is reused unchanged; normal capability is false.

Three additional Foundation tests exercise independent identities/closed fields,
absolute expiry/numeric refusal and deadline-free gain. The actual simulator
fixture additionally requires JS Beacon played/stale-quiet/fresh/duck-quiet events,
PCM completion while Beacon remains selected, and a native refusal of a previously
closed ID. This is a new required journey, not a claim that it has passed. The old
srcdoc iframe probe remains non-proof of frame-handler admission; actual receiving
frame/capture qualification and independent boundary review remain required.


Source6bdcd10 passed31Swift tests (zero failures,1.642s), both SDK apps and normal
helper absence inCI42393067284. Runtime launched in16.06s, served the actual HTTPS
Conversation, then expired its20second page-readiness loop at16:52:59 before the
page finished loading at16:53:03. No Beacon probe or JS audio journey ran. Native
termination/shutdown/delete and fixture server stop were acknowledged. This is a
measured fixture-readiness failure, not a Beacon playback failure or pass.

The fixture now has a40second absolute monotonic page-readiness deadline, checked
again on late JS evaluation completion without renewal. The outer terminal-receipt
observation is65seconds, allowing that cold page load plus the existing12second
native probe and bounded JS/PCM journey. The job remains capped at ten minutes;
there is one launch and no timeout relaunch. Retirement qualification now waits
for the native closed receipt before testing the same ID's refusal. Normal app
behavior and audio/provider/TTL/lifetime bounds remain unchanged.


## Current source qualification —2c021f1

CI42393667849 passed31Swift cases (zero failures,1.609s), both actual SDK app
builds and normal-helper absence. Actual iPhone16/iOS26.2 runtime passed: native
Beacon34560played frames with stalequiet/fresh/duckquiet/restored/host-foreground
closure; exact valid TLS chain plus wrong-host/alien-anchor refusals; unchanged
system trust; JS Beacon played/quiet/played/quiet; retired-ID refusal after native
close; PCM28800played bytes with Beacon retained and pause/resume/flush; outside
facade absent. Terminate/shutdown/delete/server cleanup were acknowledged. No
microphone, provider, observer or human original was used. GeneralCI42393667873
passed all five applicable checks. Earlier failed/unconfirmed outcomes stay above.

The source still needs independent native-message-boundary review before merge.
Normal capability remains off; actual OS background, physical hearing/music/routes,
capture/duplex compatibility, shared login/account, signing and phone delivery are
not established by this synthetic runtime. The old srcdoc non-reservation result
still does not prove actual frame-handler admission. The full original goal stays
open; this record does not grant production selection or peer activation.


## Integration with the current App source —10 November 2026

The existing PR731 preparation is composed with the current App source rather
than implemented again. All executable iOS/fixture/workflow and shared-adapter
bytes remain identical to the previously qualified runtime2c021f1 (documentation
heade0ab9a2); only guidance changes. NativeCI42393667849 is still an observed
success; the later documentation-head installation failure remains a separate
failed observation. No old simulator operation or unknown launch is replayed.

Nicolas's instruction0a39d043 requests delivering prepared work without waiting
for another independent review. This source-only integration uses the retained
concrete qualification and does not claim an independent boundary review occurred.
Normal capabilities stay OFF, and there is no signing, installation, production
activation or device/hearing acceptance. Keep the exact origin/frame/document,
retired owner, finite-buffer/deadline and lifecycle boundaries above.

### Composed-source observation —10 November 2026

NativeCI42775240916 on a305ad4 passed the Swift suite, both SDK builds and normal
fixture-helper absence. The new simulator installed in47.05s, but its single
launch acknowledgment timed out at90s. The additional65s observation yielded no
terminal page/native result, no loopback page request and no application log;
container read and termination remained unconfirmed. Shutdown and deletion were
acknowledged and the fixture server stopped. No launch was repeated. Cause is
unknown; this is not a new Beacon/audio pass or a diagnosed code failure.

The prior successful runtime42393667849 remains the behavioral qualification of
these exact25 executable/fixture/workflow/shared-adapter files. The canonical
lineage alignment and this outcome record change no such bytes, so no additional
simulator launch is requested for them. Preserve both outcomes, ordinary capability
OFF and all physical/account/signing/distribution gaps. General checks on a305ad4
passed scope, routing, speech, dashboard and Matrix execution; its text job was
still running when this record was written and is not described as green.


## Prepared foreground duplex capture

The iOS-only native-capture.js hook wraps the existing shared adapter, without
changing Android or the hosted recorder. Before getUserMedia it acquires one
UUID-owned native session holder. WebKit and the OS still prompt; only the selected
HTTPS main-frame microphone request can reach that prompt, never camera/iframe or
SSO. The closed reply handler accepts only begin/end with canonical document and
owner UUIDs, with at most128 nonreusable capture identities per controller. This is ownership, not permission or proof of recording.

A duplex holder selects playAndRecord/voiceChat before microphone permission.
PCM output joins that same mode and cannot deactivate it when becoming idle.
Mode stays frozen while any holder remains; starting capture during existing
spoken-only playback refuses before asking permission, instead of changing an
active audio graph. The composed host reserves at most one capture and two output holders; output-only
ownership retains its existing two-holder bound.
A capture stop is requested after600seconds without a validated physical successor,
route/interruption/background, explicit
track stop or page exit. Native cancellation requests actual WebKit microphone state none;
only its observed completion releases that exact session holder. Unknown stop or
session-deactivation outcomes stay held, never retried by refresh. A late device
permission closes its returned tracks after the old capture epoch has ended.
Returning foreground never resumes an old capture or sound.

Synthetic Node checks cover explicit track stop (which emits no ended event),
concurrent requests, late native/OS grants, permission refusal and lifecycle.
Foundation cases cover frozen mode/independent capture-output holders and the
closed native contract. These are not real microphone, permission, WebKit duplex,
route/interruption or phone acceptance. Native audio capabilities remain off;
no production build, provider call, entitlement or distribution is selected.
Apple references: [voiceChat](https://developer.apple.com/documentation/avfaudio/avaudiosession/mode-swift.struct/voicechat),
[media permission delegate](https://developer.apple.com/documentation/webkit/wkuidelegate),
[actual capture stop](https://developer.apple.com/documentation/webkit/wkwebview/setmicrophonecapturestate(_:completionhandler:)).

The first duplex source9eacc4b passed20Swift cases, Node capture races and the
actual iOS app build in CI42382542969. Its runtime stopped before installation
at the fixture CA admission30second timeout; shutdown/delete/server cleanup
passed. Two consecutive runs hit this same prerequisite. The fixture now gives
that single certificate operation90seconds, without retrying an uncertain write
or weakening TLS/PCM assertions. Runtime capture/permission acceptance is pending.

The extended simulator fixture tests the actual with-reply capture bridge from
its own same-origin iframe (must refuse), then reserves one main-frame duplex
session across real PCM playback/idle/pause/flush. It never requests getUserMedia
or changes a microphone permission. This checks session/bridge coexistence only;
actual microphone permission, audio input, duplex processing and physical hearing
remain unqualified. Source20tests/SDK evidence is separate from this runtime result.

Extended fixturea251f42 reached the actual app in CI42383442620 but received no
capture iframe reply. Its srcdoc frame was incompatible with the shell's
HTTPS-only navigation contract. The probes now load distinct same-origin HTTPS
child documents and require their own submission/reply receipts before proceeding;
no production navigation or frame authorization policy was widened. Earlier
srcdoc non-reservation does not prove the native handler saw a frame request.


### Capture and Beacon composition — 2026-11-10

The existing capture preparation is composed with the selected Beacon preparation.
Both speech and Beacon join the frozen duplex mode while capture is held. Output
idle/close cannot release capture; ending capture cannot deactivate a remaining
output. Interruption, background and navigation request actual WebKit capture stop
before releasing its owner, and prevent new output admission during that stop.
The capture deadline remains600seconds and normal native capability flags remain
off. No production configuration, permission, entitlement or provider changes.

The combined fixture reserves capture without requesting a microphone, then plays
Beacon and PCM concurrently, checks stale/fresh Beacon controls and capture
ownership across PCM idle, and ends its own resources. Foundation regressions
cover three-holder coexistence, frozen mode, exact release and unknown final
deactivation. Combined Swift/SDK and Node checks passed; simulator app execution
remains unqualified (terminal outcomes below). Earlier separate capture and
Beacon qualification does not establish qualification of this composition, actual
microphone input or physical device/hearing acceptance. Source delivery follows
Nicolas's direction to integrate prepared work; no new independent review is
claimed.

The first combined run42781912791 stopped during Foundation test compilation:
the Beacon test device still implemented the previous activate() signature. Its
fixture now implements activate(mode:); no runtime activation logic was changed
by that correction. SDK/app installation and simulator were not reached. The
corrected combined qualification remains pending; this failure is retained.

Corrected combined source7f6bdefa passed36Swift cases (zero failures), Node
capture races, both SDK apps and normal fixture-helper absence. Main CI42782144174
passed. Native42782143985 stopped before app installation: bootstatus exhausted
its120second observation while the simulator reported data migration/system-app
startup. Shutdown/delete and the one server TERM/exit observations were also
unconfirmed. No app, bridge, microphone or audio acceptance follows.

The fixture cleanup now retains its one TERM result and independently observed
process exit without masking the original journey failure or retrying a signal.
Three synthetic regressions cover unknown signal/exit, acknowledgment without
exit and already-exited ownership. Simulator deadlines, single launch, normal
TLS/capability policy and runtime audio code remain unchanged.

PR728 source68ec4e61 integrated asb1478e10 on10November. Behavior/fixture/workflow
bytes match08fa2267; the final source-only delta refreshes the roadmap pointer.
Main42783379023 passed; native42783379080 passed36Swift cases, three cleanup
cases, Node capture races and both SDK builds/helper absence. The simulator booted
but installation90s and exact installed-app lookup15s were unconfirmed, before
any app launch or audio receipt. Shutdown/delete and fixture server exit were
confirmed. No install/launch was repeated or deadline expanded. Normal flags stay
off; integration does not activate, sign, distribute or establish physical
microphone/device/hearing acceptance. Master qualification is automatic and its
result is tracked separately in the receiving cockpit; no manual rerun.

### Logical capture across physical Public Live handovers

The prior unconditional600second microphone deadline could end a logical voice
conversation even when Public Live had successfully renewed its physical
transport while retaining that microphone. The selected page now reports its
exact physical visit after the existing source-bound creation answer and remote
SDP installation, before entering Listening. An initial connection binds identity
without extending time. Only a new successor of the current physical ID advances
the native session lease by600seconds; duplicates and retired/stale predecessors
cannot rearm it. At most512 distinct physical IDs are retained per capture.
This is page/owner bookkeeping, not independent proof of a provider session.

The existing microphone/permission/recording owner stays unchanged. A handover
requires active WebKit capture; the initial identity-only bind does not assume
WebKit's capture-state observation has already advanced. Stop, background, expiry,
changed binding and unknown link outcomes fence later activity. A stale queued
deadline cannot close a newer lease generation. A lost native acknowledgment is
not retried. Server admission, context, physical600second, recording/storage and
provider bounds remain unchanged; no fallback or new permission is added.

Node regressions reproduce the missing link on the previous source, then pass
initial/delayed/refused ownership, exact microphone retention across successor,
Stop-before-ack, duplicate/stale/foreign and uncertain-result cases. Foundation
regressions cover the closed IPC fields, predecessor CAS, duplicate generations,
retired IDs and512-ID limit. Exact Swift/SDK and synthetic bridge checks passed;
active-microphone handover and physical hearing remain unqualified.

PR848 source43f8a950 merged80b6561c. Native42787218013 passed40Swift cases,
both SDK apps/helper absence and the actual iPhone16/iOS26.2 simulator fixture:
28800PCM played bytes,35520Beacon frames, capture identity/duplicate admission,
inactive successor refusal, iframe/outside/TLS boundaries and confirmed owned
cleanup. It requested no microphone; active-capture renewal is not demonstrated.
Main42787217947 passed. Android build and its13instrumentation cases passed, but
the decoder command ended255 after its OK output; the ending command/cause is
not established and that overall job remains failed. Android product source is
unchanged. The compatible optional Public Live client is HTTPS-byte-verified on
all7 existing receivers; source integration/web selection does not activate, sign
or distribute an iOS native build. Normal native flags remain OFF.
