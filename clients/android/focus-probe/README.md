# Bounded cross-UID audio focus fixture

This optional Android application exists only for emulator instrumentation.
`settings.gradle` includes it with `-PfocusProbe=true`; the ordinary release
build does not include or depend on it. No production Java, assets, version,
manifest or signing policy is changed. The main app requests the fixture control
permission only through its debug manifest overlay.

The probe holds media/music focus and runs an actual looping AudioTrack in a
bounded foreground service under a different UID. It requests pause-when-ducked,
pauses on transient loss and resumes only on the real system focus gain. Test
broadcasts carry UID/counters/playback head; the target checks two speech
utterances, partial focus loss and resumed frame advance. Both components are
signature-protected and built with the same CI debug signer. There is no network,
microphone, storage, user-data or provider access, no retained media, and a
30-second service stop bound. Instrumentation also stops it in `finally`.

Build the probe and app debug/test APKs in one Gradle invocation so they share
the debug signer. CI installs the probe first, then calls the existing decoder
helper with the app APK directory and probe APK path. Artifacts expire after
one day; bounded logs retain seven days. Do not sign/distribute this as the
Daimon client or infer YouTube Music/physical-device acceptance from OS callbacks.
