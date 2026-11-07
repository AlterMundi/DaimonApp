"""Refuse an emulator run if its exact web fixtures are missing or stale."""
from pathlib import Path
from zipfile import ZipFile

root = Path(__file__).resolve().parents[2]
app = Path(__file__).resolve().parent / "app"
with ZipFile(app / "build/outputs/apk/androidTest/debug/app-debug-androidTest.apk") as tests:
    for name in ("webrtc-native-audio.js", "voice-output-pcm.js"):
        assert tests.read("assets/" + name) == (root / "dashboard/web" / name).read_bytes(), name
with ZipFile(app / "build/outputs/apk/release/app-release-unsigned.apk") as release:
    assert not any("assets/" + name in release.namelist() for name in (
        "webrtc-native-audio.js", "voice-output-pcm.js"
    )), "Qualification scripts must not become installed application assets"
print("Exact web audio fixtures packaged in test APK only")
