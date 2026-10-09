# KYVON privacy policy

*Draft for legal review. Effective date: [DATE]. Developer: [YOUR NAME OR COMPANY], [CONTACT EMAIL].*

## What KYVON is

KYVON is an app for iPhone and iPad (and a web app) that connects to a **KYVON server that you, or someone
you trust, run**. The app is a client: your chats, tasks, memories and settings are stored on that server, not
on servers run by the developer.

## What we collect

**The developer of the app does not collect, receive, sell or share your personal data.** The app contains no
advertising, no analytics, no tracking and no third-party SDKs. We do not run the server the app talks to.

## What the app handles, and where it goes

When you use the app, the following is sent **to the server address you enter**:

| Information | Why | When |
|---|---|---|
| Username and password | To sign in. The password is sent once; the app then keeps only a revocable token for this device, stored in the iOS Keychain | When you sign in |
| Messages you type or dictate, and the replies | To run the assistant | When you chat |
| Voice recordings | To turn speech into text | Only while you use dictation |
| Approximate location | For local weather and your time zone | Only if you allow location access |
| Tasks, memories, reminders, settings | To provide those features | When you use them |
| Push notification token | To deliver notifications (when your server supports it) | If you allow notifications |

The app also stores on your device: the server address, your sign-in token (Keychain), and a record that you
accepted the data-sharing notice.

## Services your server may use

The server operator chooses which services the server connects to. In the default setup the server sends data
to these third parties, which have their own privacy policies:

| Service | What it receives | Purpose |
|---|---|---|
| Groq | Your messages and the context needed to answer; voice recordings; web search questions | Writing replies, speech-to-text, web research |
| Open-Meteo | Coordinates | Weather |
| OpenStreetMap Nominatim | Place names or coordinates | Place lookup |
| Google (only if you connect Calendar) | Calendar requests made with your permission | Reading and changing your calendar |
| Apple, Google or Mozilla push services | A notification delivery token and the notification | Push notifications |
| An AI endpoint configured by the operator (optional) | Messages for that assistant | Optional extra assistant |

Before any of this starts, the app shows you a notice and asks you to agree. If you do not agree, the app does
not connect to a server.

## Who is responsible for your data

The person who runs your KYVON server decides how long data is kept and which services it uses, and is
responsible for it. If that is you, you control everything: you can delete conversations, memories and tasks
in the app, sign out a device (which revokes its token), or delete the server's database. If someone else runs
your server, ask them for their privacy practices.

The app can be used with a server run by the developer only if the developer announces one and publishes its
own policy; this policy does not cover that.

## Keeping data safe

The app only connects over HTTPS (plain HTTP is allowed only for local-network testing). Passwords are never
stored on the device. Servers store passwords hashed and tokens hashed. No system is perfectly secure, and the
security of your data on the server depends on how it is set up.

## Children

KYVON is not directed to children under 13 (or the minimum age in your country), and we do not knowingly
collect their data.

## Your rights

Depending on where you live (for example under the GDPR or the CCPA), you may have rights to access, correct,
delete or export your data. Because your data lives on your server, you can usually exercise these directly in
the app or with the server operator. You can also contact us at [CONTACT EMAIL] with questions about this
policy.

## Changes

If this policy changes in a way that affects what happens to your data, the app will ask for your agreement
again. The current version is always at [PUBLIC URL OF THIS PAGE].

## Contact

[YOUR NAME OR COMPANY]
[CONTACT EMAIL]
[POSTAL ADDRESS, if required where you operate]
