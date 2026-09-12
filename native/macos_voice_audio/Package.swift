// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DarwinVoiceAudio",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "darwin-voice-capture", targets: ["DarwinVoiceCapture"]),
    ],
    targets: [
        .executableTarget(
            name: "DarwinVoiceCapture",
            path: "Sources/DarwinVoiceCapture"
        ),
    ]
)
