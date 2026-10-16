// swift-tools-version: 5.8

// AppleProductTypes is how Swift Playgrounds describes an app: name, icon, permissions.
import PackageDescription
import AppleProductTypes

let package = Package(
    name: "KYVON",
    platforms: [
        .iOS("16.0")
    ],
    products: [
        .iOSApplication(
            name: "KYVON",
            targets: ["AppModule"],
            bundleIdentifier: "app.kyvon.KYVON",
            teamIdentifier: "",
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .bolt),
            accentColor: .presetColor(.cyan),
            supportedDeviceFamilies: [
                .pad,
                .phone
            ],
            supportedInterfaceOrientations: [
                .portrait,
                .landscapeRight,
                .landscapeLeft
            ],
            capabilities: [
                .outgoingNetworkConnections(),
                .microphone(purposeString: "KYVON records your voice only while you hold dictation, and sends it to your own server to be transcribed."),
                .locationWhenInUse(purposeString: "KYVON uses your approximate location for local weather and the right time zone.")
            ],
            appCategory: .productivity
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: "."
        )
    ]
)
