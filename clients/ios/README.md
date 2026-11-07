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

This is not an installable app. Continue with actual AVAudioEngine/device and iOS AVAudioSession acceptance,
WKWebView's exact-origin/main-frame bridge and shared-login shell,
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
