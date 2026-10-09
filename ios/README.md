# KYVON for iPhone and iPad

A native client for the KYVON server. It is a **UI and device layer only**: chat, memory, tasks,
calendar, tools and agents all run on the server, and the app talks to the same `/api/v1` the
web app uses. Nothing here duplicates assistant logic.

| Piece | What it does |
|---|---|
| `Sources/KYVONKit` | API client (no UI): login, streaming chat (SSE), approvals, tasks, memory, notifications, push-token and location upload, voice upload. Token in the **Keychain**. |
| `Sources/KYVONApp` | SwiftUI screens and device services (location, dictation, push registration). Five tabs: **Chat** (streaming, inline approval cards, chat list), **Tasks**, **Memory**, **Inbox**, **Settings**; plus server-address and sign-in setup screens. `Theme.swift` holds the shared look. See [docs/IOS_DESIGN.md](../docs/IOS_DESIGN.md). |
| `App/` | The `@main` entry point, Info.plist keys and entitlements for the iOS target. |
| `project.yml` | XcodeGen spec that generates the Xcode project. |

## Status (read this first)

**None of the Swift code has been compiled or run, including the redesign.** It was written on a Mac whose Command Line
Tools compiler does not match its SDK (Swift cannot even build Foundation there) and without
Xcode, so neither `swift build`, `swift test` nor an iOS build was possible. The code was
desk-checked, and the pieces most likely to break are small and isolated, but expect to fix a few
compile errors the first time you build it. The unit tests in `Tests/KYVONKitTests` (SSE parsing,
login/token handling, error mapping, streaming decode, approvals, uploads) are written to run with
`swift test` once you have a working toolchain; they have never been executed.

- Push notifications need an Apple Developer account (APNs key) and a server-side APNs sender, which
  is **not implemented yet**: the app registers its device token with the server (stored in the
  `push_subscriptions` table), but the server cannot deliver to it until APNs sending is added.
  Reminders always appear in the app's inbox when the app is opened.

## Compatibility and App Store

Supports **iOS 15 and later** (iPhone and iPad). Screens use `NavigationStack`/multi-line fields on iOS 16+
and fall back to older equivalents on iOS 15. The package builds on macOS 12+ only so CI can compile it.
Going below iOS 15 would mean rewriting the streaming client, which needs `URLSession.bytes`.

App Store preparation (consent screen, privacy manifest, icon, policies, submission answers) is in
[docs/appstore/APP_STORE_SUBMISSION.md](../docs/appstore/APP_STORE_SUBMISSION.md) and
[docs/legal/](../docs/legal/). The policies are drafts for a lawyer to review, not legal advice.

## Build it

1. Install Xcode 15 or newer and XcodeGen: `brew install xcodegen`.
2. `cd ios && xcodegen generate && open KYVON.xcodeproj`
3. In *Signing & Capabilities* choose your team. (Push Notifications and Background Modes >
   Remote notifications are already declared; enable them for your App ID.)
4. Run on a device or simulator. Enter your server address (for example the Cloudflare Tunnel
   URL, `https://…`), then sign in with your KYVON username and password. The password is sent once
   to `/auth/login`; only the returned per-device token is stored (Keychain, this device only).
   Revoke a device any time from the web app or with `flask --app wsgi kyvon revoke-tokens`.

## Security notes

- The server address must be `https://` (plain `http://` is accepted only for `localhost`/`.local`
  during development), so credentials never cross the network unencrypted.
- The token is stored with `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` and never logged.
- Location is requested only while the app is in use and at city-level accuracy.
- Voice recordings are uploaded to your own server for transcription and deleted from the device
  immediately; no on-device recognition or third-party SDK is involved.
- Background capability: only remote-notification wake-ups. iOS does not allow an app to keep a
  connection open in the background, so the app refreshes when opened or when a notification arrives.

## Test

```bash
cd ios && swift test    # needs a toolchain that includes XCTest (Xcode)
swift build             # compiles both libraries on macOS
```
