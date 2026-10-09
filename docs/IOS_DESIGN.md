# KYVON for iPhone and iPad: design

Status: **designed and written, never compiled or run.** There is no Xcode and no working Swift toolchain
on the machine this was written on, so every claim below about how the app looks and behaves is intent,
not observation. The visual mockups were reviewed in chat; they are not committed.

## Principles

- **A thin client.** All assistant logic, memory, tasks and approvals live on the server. The app calls the
  same `/api/v1` as the web app and never decides anything for itself.
- **Approvals stay visible.** Anything KYVON wants to do that changes something outside itself appears as an
  approval card inside the chat, and as a badge on the Chat tab. Nothing happens until Approve is tapped.
- **Status is never colour alone.** Errors, overdue tasks and approvals carry an icon and words as well as colour.
- **Dark only, native controls.** System lists, forms, swipe actions, pull to refresh, Dynamic Type and VoiceOver
  labels throughout; the shared look is in `Sources/KYVONApp/Theme.swift`.

## Structure

| Tab | Screen | Calls |
|---|---|---|
| Chat | Streaming conversation, stop button, dictation, inline approval cards; chat list in a sheet | `/chat/stream`, `/conversations`, `/tool-runs/pending`, `/voice/transcribe` |
| Tasks | Overdue, to do and done sections; add, complete, reopen, swipe to delete | `/tasks` |
| Memory | Search, add, swipe to delete; footer explains that only requested memories are saved | `/memories` |
| Inbox | Reminders and scheduled results, unread dot, mark all read | `/notifications` |
| Settings | Account and server, response style, tone, units, spoken replies, sign out | `/settings`, `/auth/logout` |

First run shows two setup screens: the server address (https only, except localhost), then sign-in.
Only the per-device token is kept, in the Keychain.

## Not in the app yet

Calendar view, automations list, agents, and admin screens exist on the server and in the web app but have no
native screen. Push notifications need server-side APNs sending, which is not written (see `ios/README.md`).
