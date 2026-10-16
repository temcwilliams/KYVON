#!/usr/bin/env bash
# Builds ios/KYVON.swiftpm, a Swift Playgrounds app package, from the sources in ios/.
# Playgrounds wants a single app module, so KYVONKit + KYVONApp + the @main entry are merged into
# one target (the cross-module imports are dropped). Run from anywhere:  scripts/make_playground.sh
# Then open ios/KYVON.swiftpm in Swift Playgrounds (iPad or Mac) and press Run.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
ios="$root/ios"
out="$ios/KYVON.swiftpm"

rm -rf "$out"
mkdir -p "$out"

copy() {
  local src="$1"
  # Drop only the imports of our own modules; they no longer exist as separate modules.
  grep -v -E '^import (KYVONKit|KYVONApp)$' "$src" > "$out/$(basename "$src")"
}

for f in "$ios"/Sources/KYVONKit/*.swift "$ios"/Sources/KYVONApp/*.swift "$ios/App/KYVONApp.swift"; do
  copy "$f"
done

cat > "$out/Package.swift" <<'SWIFT'
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
SWIFT

count=$(ls "$out"/*.swift | wc -l | tr -d ' ')
echo "Built $out ($count Swift files incl. Package.swift)"
