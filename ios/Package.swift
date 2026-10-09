// swift-tools-version:5.9
import PackageDescription

// KYVONKit: the API client (no UI). KYVONApp: the SwiftUI screens, built on KYVONKit.
// The iPhone/iPad app target lives in project.yml (XcodeGen) and only adds the @main entry
// point, entitlements and Info.plist keys. All assistant logic stays on the server.
let package = Package(
    name: "KYVON",
    platforms: [.iOS(.v16), .macOS(.v14)],
    products: [
        .library(name: "KYVONKit", targets: ["KYVONKit"]),
        .library(name: "KYVONApp", targets: ["KYVONApp"]),
    ],
    targets: [
        .target(name: "KYVONKit"),
        .target(name: "KYVONApp", dependencies: ["KYVONKit"]),
        .testTarget(name: "KYVONKitTests", dependencies: ["KYVONKit"]),
    ]
)
