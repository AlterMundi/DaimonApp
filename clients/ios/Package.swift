// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DaimonNativeAudio",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "DaimonNativeAudio", targets: ["DaimonNativeAudio"])],
    targets: [
        .target(name: "DaimonNativeAudio"),
        .testTarget(name: "DaimonNativeAudioTests", dependencies: ["DaimonNativeAudio"])
    ]
)
