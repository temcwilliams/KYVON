# KYVON - Project Status

Status after implementing the full roadmap (Phases 1-16). Everything below describes what exists **in
this repository, on the local branch `kyvon/full-roadmap`**. It has not been pushed and has not been
deployed. Where something was not (or could not be) verified, it says so.

## At a glance

| | |
|---|---|
| Backend | Flask app factory, ~12,000 lines in `kyvon/`, SQLite via SQLAlchemy 2 + Alembic (9 migrations) |
| Web app | Plain ES modules + service worker, ~3,900 lines |
| Tests | ~1,000 (pytest); ~96% line coverage of `kyvon/`; no test touches the network |
| Static checks | Ruff (lint + format), bandit, pip-audit: clean |
| Verified live | Real gunicorn process + real HTTP smoke test (24/24); UI exercised in the in-app browser (sign-in, streaming chat, tool use, approval card, memory, admin, phone layout) |
| **Not verified** | Any real Groq / Google / Hermes / push-service call; service-worker registration; microphone capture; the whole native iOS app; Docker build; CI on GitHub; the VM |

## Architecture

```
Browser / installed PWA / (native app)        HTTPS via Cloudflare Tunnel
        |  cookie session (web) or bearer token (native)
        v
gunicorn (1 worker, 4 threads, :8080) -> Flask create_app()
  api/v1       validation (Pydantic), auth guard, rate limits, CSRF + origin checks, JSON errors
  services     chat turn, context builder, memory, tasks, calendar, automation, settings, ...
  tools        registry + executor (validation, approvals, timeouts, audit)
  agents       bounded loops with allow-listed tools
  automation   scheduler thread + runner
  integrations Groq, Google Calendar, Open-Meteo, Nominatim, Logseq folder, Hermes, Whisper, Web Push
  SQLite       data/kyvon.db (+ backups/)
```

A chat turn, the data model and the differences from the original design are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ("As built").

## Completed phases

| Phase | What now exists |
|---|---|
| 1 Foundation | App factory, typed config, SQLite + Alembic, single-owner auth (hashed device tokens, cookie + CSRF), `/api/v1`, ES-module web client, gunicorn/Docker/systemd files, CI |
| 2 Conversations | Persisted conversations (create, list, rename, archive, delete), ownership, message status/model/tokens, bounded context (tokens + count), rolling summary, LLM titles, SSE streaming that saves partial text on disconnect |
| 3 Memory | Categories, importance, soft delete, duplicate detection, secret refusal, relevance retrieval (lexical, behind an interface), "what do you remember", full CRUD API + panel |
| 4 Tools | Registry, strict schemas, risk classes, approvals (expiring, atomic, deduplicated), worker-thread execution with timeout/retries, untrusted-output labelling, full audit in `tool_runs` |
| 5 Tasks + Calendar | Tasks with priorities, due dates (time zones), recurrence; Google Calendar via OAuth+PKCE, encrypted tokens, list/create/update/delete with approvals |
| 6 Agents | researcher, planner, productivity, memory_curator, diagnostics; depth/step/tool/time limits, cancellation, stored traces, approvals surface in the main chat |
| 7 Hermes | Optional OpenAI-compatible backend used as the `hermes` agent; same allow-list, approvals and audit; unconfigured = feature simply absent |
| 8 Logseq | Sandboxed Markdown graph: search/read automatic, create/append/journal/replace need approval, no delete, backups on overwrite |
| 9 Automation | Reminders and scheduled prompts (once/daily/weekly/monthly/interval), CAS-claimed scheduler, retries, auto-off after 3 failures, run history, inbox |
| 10 Personalization | Validated settings, compact profile block, unit/time-zone handling, integration switches enforced server-side, assistant can *propose* changes |
| 11 PWA | Manifest + icons, service worker (shell only, never the API), connection state, responsive/accessible layouts, push subscriptions and a self-implemented Web Push sender |
| 12 Native iOS | Swift package (API client, SwiftUI screens, Keychain, location, dictation, push registration) + XcodeGen spec |
| 13 Voice | Whisper via Groq (validated uploads), device text-to-speech, interruption and state handling, works without voice |
| 14 Observability | Request ids, JSON logs, error records + repair notes, health/readiness, owner admin API + panel, diagnostics tools/agent |
| 15 Security | Rate limits, origin check, redaction, SSRF/redirect controls, HSTS/CSP, regression suite, [docs/SECURITY.md](docs/SECURITY.md) |
| 16 Production | backup/restore/doctor commands, graceful shutdown, systemd + backup timer + Cloudflare example, generated configuration reference, deployment guide |

## Database

`users`, `api_tokens`, `conversations`, `messages`, `memories`, `tool_runs`, `tasks`, `calendar_accounts`,
`oauth_states`, `agent_runs`, `automations`, `automation_runs`, `notifications`, `push_subscriptions`,
`error_records`. Timestamps are UTC; user data carries `user_id`; migrations `0001`-`0009` (a test verifies
migrations and models agree and that downgrade/upgrade round-trips).

## API

`/api/v1` - auth, chat (+stream), conversations, memories, tasks, calendar, tools/tool-runs (approvals),
agents/runs, automations, notifications, settings, integrations, logseq (read-only), push, voice, admin, health.
The catalogue of tools is `GET /tools`. Routes: `kyvon/api/v1/`.

## Tool system

Named tools with strict input schemas and four risk levels. Read tools run automatically (external content is
labelled untrusted); own-data writes (tasks, renames) run automatically; external effects, deletions, and
model-initiated memory/settings/automation changes wait for the owner's approval. Unknown tools, bad JSON,
invalid or oversized arguments are rejected and audited. See [docs/SECURITY.md](docs/SECURITY.md).

## Agents, Hermes, Logseq, automation, PWA, native client, voice

- **Agents:** see the table above; the main assistant delegates with `delegate_to_agent`. No coding agent by design.
- **Hermes:** treated as a model endpoint, never as a way to run commands. If the configured endpoint has its own
  shell tools, KYVON cannot restrict them: only point it at a model endpoint.
- **Logseq:** the KYVON database stays the source of truth; Logseq is read/search plus approved writes.
- **Automation:** runs inside the web process (single worker). Missed runs older than 12 h are skipped.
- **PWA:** installable; offline shows the app shell and a banner (chat needs the server).
- **Native client:** source only. See [ios/README.md](ios/README.md).
- **Voice:** dictation needs HTTPS and microphone permission; replies are spoken by the device.

## Security model (summary)

The model is never trusted to authorise anything and everything it reads is data. Single owner, hashed
revocable device tokens, CSRF + origin checks, rate limits, strict validation, no code execution or free file/URL
access, SSRF-safe outbound calls, encrypted OAuth tokens, redacted logs. Full list and residual risks:
[docs/SECURITY.md](docs/SECURITY.md).

## Testing

`pytest -n auto` (~1,000 tests, ~90 s): unit, API, authentication, database/migrations, tool and agent tests
with a fake model, mocked Google/Hermes/push/speech services, frontend sanity checks (references, ids, unsafe
patterns), a security regression suite (walks every route), operations tests (backup/restore/doctor), and one that
boots a real gunicorn process. `scripts/smoke_test.py` checks a live server. External services are never called.

## Local development

See the README. Common commands: `flask --app wsgi kyvon doctor`, `pytest -n auto`, `python scripts/gen_config_docs.py`
(after adding a setting), `python scripts/make_icons.py`.

## Production deployment (existing Ubuntu VM)

Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). In short: back up, pull, `pip install`, create `.env` (mode 600) with
`GROQ_API_KEY`, `KYVON_ENV=production`, `KYVON_PUBLIC_URL`; run `doctor`, `db-upgrade`, `create-user`,
`import-memories`; install `deploy/kyvon.service`; keep port 8080 and the Cloudflare Tunnel; enable the backup timer.
**Nothing has been run on the VM, and its Git remote has not been checked.**

## Credentials and setup you still need to do

| Feature | What you must provide |
|---|---|
| Core | `GROQ_API_KEY` (already have) |
| Owner login | `flask --app wsgi kyvon create-user` |
| Google Calendar | Google Cloud OAuth client (Web application), Calendar API enabled, redirect URI `<KYVON_PUBLIC_URL>/api/v1/calendar/callback`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `KYVON_ENCRYPTION_KEY` |
| Logseq | `KYVON_LOGSEQ_DIR` pointing at your graph folder on the VM |
| Hermes | `KYVON_HERMES_URL` (+ key/model) of an OpenAI-compatible endpoint |
| Web Push | `flask --app wsgi kyvon generate-vapid-keys` and set the three values |
| iOS app | Xcode, an Apple Developer account, an APNs key (and server-side APNs sending, not written) |

## Known limitations (not hidden)

1. **Never run against the real services:** Groq streaming/tool-calling shape, Google Calendar, Hermes, Web Push
   (Apple/Google/Mozilla), Whisper. Their request/response handling follows the documented APIs and is tested against
   fakes; expect small surprises on first contact.
2. **Native iOS app is unbuilt.** The local Swift toolchain cannot compile Foundation (compiler/SDK mismatch) and Xcode
   is absent. APNs sending is not implemented.
3. **Service-worker registration** could not be exercised (the in-app browser refused it); the script parses and runs.
4. **Web Push encryption** was checked by round-trip and against the RFC 8291 example inputs, not against a live push
   service.
5. **Login throttle behind the tunnel is per username**, not per client (all requests look local). Restart or
   `set-password` clears a lockout.
6. **One worker only:** the scheduler, rate limits and login throttle are in process memory.
7. **Memory retrieval is lexical**; paraphrases with no shared words are missed.
8. **A fooled model can still say wrong things**; the defences stop it from *acting* without approval.
9. Long agent runs can outlast Cloudflare's ~100 s idle limit; the reply is saved and appears on reload.
10. Conversation text is stored unencrypted in SQLite (protect the disk and `data/`); it is also sent to Groq, and
    audio to Groq Whisper.
11. Weather codes 56/57, 66/67, 77, 85/86 show "Unknown conditions" (kept from the prototype).
12. The GitHub repository and local folder are still named `jarvis-assistant`.
13. Two status endpoints exist (`/status` for the SYSTEM button, `/admin/status` for the owner) by design.

## Future ideas that are genuinely not built

Embedding-based memory search; APNs delivery and a shipped native app; server-side text-to-speech and wake word;
a sandboxed coding agent; passkeys / 2FA; multi-user and Postgres (would need shared rate-limit/scheduler state);
Apple Calendar and e-mail integrations.
