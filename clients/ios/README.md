# iOS native audio preparation

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
one-day test CA is added only to that simulator; production app TLS policy and
existing device/keychains are unchanged. The fixture sends synthetic PCM through
the actual WebView/bridge/engine, checks played receipts and pause/resume/flush,
attempts iframe reservation, then navigates outside the application path. No
microphone, provider, human voice original or real shared-login account is used.
It starts the fixture once, waits at most35seconds for its terminal receipt and
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

The normal JS bridge and native Beacon capability stay off. Continue with the
closed per-document adapter and actual capture/duplex compatibility before
advertisement. Physical phone/music/hearing, shared login, distribution/signing
and the full original goal remain open.

The common simulator fixture also reuses the90second observation bound for its
single CA-admission operation, already qualified in PR728source816fd9a andd1f1f4b.
The previous30seconds had timed out before app installation; actual successful
admission needed84.88seconds. This carries only that tested fixture correction,
not the separate capture implementation/review. No uncertain CA operation is
retried and no production TLS policy or existing device trust is changed.


### Qualification TLS isolation after PR731's CA timeout

Sourceb5c440b passed28Swift cases (zero failures,1.638s), actual iOS SDK app build
and all five general checks. RuntimeCI42390310788 failed during90second fixture
CA admission before app install/launch; runtime listing took77.63s and boot103.1s.
Shutdown/delete/server cleanup passed. That outcome is not Beacon playback proof
and the terminal operation was not replayed.

The disposable fixture no longer mutates the simulator trust store. Only the
qualification bundle compiles `Qualification/FixtureTrust.swift`. After its one
install, the fixture copies two bounded public DER anchors to that exact app's
container. For localhost443 server-trust challenges only, the test delegate uses
Apple's SecTrust SSL hostname/chain validation with the fixture anchor exclusively
and network fetching off. It must first reject the same chain for another hostname
and an unrelated anchor. Other hosts/auth methods retain default WebKit handling.
Missing anchors, invalid chains and repeated failed challenges are refused.

This is a test-only provisioning replacement, not production certificate pinning,
a TLS bypass, login or relaxed application origin/bridge admission. CI also builds
the normal app without that extra source and checks its symbols exclude the helper.
No root certificate is installed in system/device trust. Both one-day public anchors,
private signing files, container, server and disposable simulator stay within the
existing job/deletion bounds; nothing is uploaded. The native receipt must include
the positive chain and both negative trust results before PCM playback acceptance.
This fixture no longer qualifies system-trust-store installation; normal shared
SSO/account and physical device trust remain separate acceptance requirements.

Apple contracts: [custom trust anchors](https://developer.apple.com/documentation/security/configuring-a-trust)
and [WebKit authentication challenge handling](https://developer.apple.com/documentation/webkit/wknavigationdelegate/webview(_:didreceive:completionhandler:)).
