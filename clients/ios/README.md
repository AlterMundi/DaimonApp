# iOS native audio preparation

The existing native-client plan selects an equivalent iOS client. This package
starts its audio core with the same 24 kHz mono PCM16 span contract as Android's
`PcmPlaybackQueue`: SHA256 integrity, exact sequence/source offsets, at most
32768 bytes per chunk, 30 seconds queued, 128 source identities and 512 live
spans. Default lifetime is 300 seconds; an explicit duration may reach 600.
Flush retires sound and source identities without resetting sequence or lifetime.
Scheduling/submission never becomes a played receipt. The eventual native driver
must provide its current owner's actual playback observations and fence late
callbacks by owner and playback epoch, including after pause, flush or stop.

The class belongs to one serial output owner. It performs no I/O, capture,
provider call, authentication, lifecycle management or background activation.
Five XCTest scenarios cover partial submission/playback, source offsets/flush,
atomic integrity/sequence/position refusal, queue/source limits and the complete
ten-minute lifetime across a flush. CI uses the existing public repository's
standard macOS runner, two compiler jobs and a ten-minute deadline. No dependency
package or signing identity is fetched. Scratch output belongs to the disposable
runner; no generated audio or new retained cache/artifact is uploaded.

This is not an installable app. Continue with the native AVAudioEngine/session
driver, WKWebView's exact-origin/main-frame bridge and shared-login shell,
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
