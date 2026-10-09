# App Store submission pack

**Draft by an AI assistant, not legal advice.** Apple has no downloadable "forms": the paperwork is the
questionnaires inside App Store Connect, plus a privacy policy URL. This file holds ready-to-paste answers
based on what the app and server actually do. Check each answer against Apple's current wording when you fill
it in, because Apple changes these questions, and have a lawyer review the policies in `docs/legal/`.

The app has **never been built into an installable app or run on a device**. CI compiles the Swift package,
nothing more. Treat everything below as preparation, not proof that review will pass.

## 1. What you must do outside the code

| Step | Notes |
|---|---|
| Join the Apple Developer Program | Paid, yearly. Needed for signing, TestFlight, push, and the App Store |
| Register the bundle ID | `app.kyvon.KYVON` (change `PRODUCT_BUNDLE_IDENTIFIER` in `ios/project.yml` if taken) |
| Build and sign | Needs Xcode on some Mac (yours can't run it): a borrowed or cloud Mac, or a CI build with signing set up |
| Test on real devices via TestFlight | Before submitting |
| Host the privacy policy at a public URL | The default link in the app is the GitHub page; a stable site you control is better. Update `LegalLinks` in `Theme.swift` |
| Fill in the `[BRACKETS]` in `docs/legal/` | Name, contact, governing law |
| Take screenshots | iPhone 6.9" (or 6.7") set, and iPad 13" set because the app supports iPad |
| Enable push (optional) | Needs an APNs key, and server-side APNs sending, which is **not written** |

## 2. The biggest review risk: a reviewer needs a server

KYVON only works with a KYVON server. App Review must be able to use the app, so you must provide a **demo
server address and demo credentials** in the review notes, and keep that server running during review. A
server on a temporary "quick tunnel" address is not suitable: its address changes. Use a fixed HTTPS hostname.
Without a working demo the usual outcome is rejection under Guideline 2.1 (completeness), and a thin-client
app may also be questioned under 4.2 (minimum functionality). The app does real work (chat, tasks, memory,
approvals, voice), so explain that in the notes.

## 3. Listing text (draft)

- **Name:** KYVON
- **Subtitle (30 chars):** Your personal AI assistant
- **Category:** Productivity (secondary: Utilities)
- **Promotional text:** A personal assistant that runs on your own server. Chat, tasks, memory, and reminders, with your approval before it acts.
- **Description:**
  KYVON is a personal AI assistant that works with a server you run. Ask questions, keep a to-do list,
  set reminders, and tell it what to remember. It asks your permission before it changes anything outside
  itself, like a calendar event.

  - Chat with replies that stream in as they are written
  - Tasks with due dates and repeats
  - Memory you control: it saves only what you ask, and you can delete anything
  - Reminders and scheduled results in your inbox
  - Dictate messages by voice
  - Approve or decline every action before it happens

  KYVON needs a KYVON server that you or someone you trust runs; it does not include one. Replies are written
  by an AI provider your server uses and can be wrong, so check anything important.
- **Keywords (100 chars):** assistant,AI,tasks,reminders,notes,memory,productivity,chat,voice,planner
- **Support URL:** [A PAGE WITH CONTACT DETAILS]
- **Privacy policy URL:** [PUBLIC URL OF docs/legal/PRIVACY_POLICY.md]
- **Copyright:** [YEAR] [YOUR NAME]

## 4. App Privacy ("nutrition label") answers

Apple's rule: you declare data that **you or your third-party partners** collect from the app. The developer
does not operate the server and receives nothing, so a "Data Not Collected" answer is arguably correct. The
safer choice, and the one the bundled `PrivacyInfo.xcprivacy` takes, is to declare the data the app sends off
the device, because the server may be run by a third party. **Decide this with your lawyer**, and keep the
label and the manifest consistent.

If you declare (matches `PrivacyInfo.xcprivacy`): for each item, **linked to the user: yes; used for tracking:
no; purpose: App Functionality.**

| Apple data type | What it is here |
|---|---|
| User Content: Other User Content | Chat messages, tasks, memories |
| Audio Data | Dictation recordings |
| Location: Coarse Location | Approximate location, if allowed |
| Identifiers: User ID | Username |
| Identifiers: Device ID | Push token (only if push is used) |

Other answers: **Tracking: No. Third-party advertising: No. Analytics: No.** Required-reason API: UserDefaults
(reason CA92.1), already declared.

## 5. Export compliance (encryption)

The app uses only Apple's standard HTTPS and Keychain, no custom cryptography. That is normally **exempt**:
`ITSAppUsesNonExemptEncryption = false` is set in `project.yml`. Confirm Apple's questionnaire agrees with
your situation.

## 6. Age rating

Answer Apple's questionnaire honestly. The app has no violence, gambling, or mature content of its own, but it
is an AI chat assistant whose replies are generated by a model, so expect Apple's questions about AI-generated
and unrestricted content to push the rating up (**12+ to 17+**); do not claim 4+ for an open-ended chatbot
unless the questions allow it.

## 7. Account deletion (Guideline 5.1.1(v))

The app does **not** let people create accounts: the owner account is created on the server. Apple's account
deletion rule applies to apps that offer account creation, so it should not apply. Deleting a device's access
(sign out, which revokes its token) is in Settings. If you later add sign-up in the app, you must add in-app
account deletion.

## 8. AI and personal data (Guideline 5.1.2(i))

Apple requires telling people when personal data is shared with third-party AI and getting their permission.
The app shows a consent screen on first launch (`ConsentView`) naming the AI provider and what is shared, and
asks again if `consentVersion` is raised. Keep that text accurate if providers change.

## 9. Review notes (template)

> KYVON is a client for a self-hosted assistant server. To test, open the app, accept the data notice, enter
> the server address **[DEMO HTTPS URL]**, and sign in with username **[DEMO USER]** and password
> **[DEMO PASSWORD]**. The demo server is online throughout review. Try: type "add a task to buy milk", then
> open the Tasks tab; type "remember that I like tea", then open Memory; ask something that needs an action
> (for example "create a calendar event tomorrow at 3pm") to see the Approve/Decline card. Dictation needs the
> microphone permission. Notifications are optional and not required.
> The app contains no ads, analytics, or in-app purchases.

Use a **throwaway** demo account that holds no real data, and change its password after review.

## 10. Pre-submission checklist

- [ ] Developer Program active; bundle ID registered; app record created in App Store Connect
- [ ] `[BRACKETS]` filled in `docs/legal/`; policies reviewed by a lawyer; URLs live and reachable
- [ ] `LegalLinks` point to the final URLs
- [ ] Built and run on a real iPhone and iPad; consent, sign-in, chat, tasks, memory, inbox, settings, dictation all exercised
- [ ] Demo server on a fixed HTTPS address, with demo account and review notes
- [ ] Screenshots for each required device size
- [ ] Privacy label matches `PrivacyInfo.xcprivacy` and the policy
- [ ] Age rating and export compliance answered
- [ ] If using push: APNs sender written and tested; entitlement set to `production`
