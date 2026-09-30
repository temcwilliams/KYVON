# KYVON — Project Status

Updated at the end of **Phase 1 (Foundation)**. This replaces the original prototype audit; that audit is in git history (commit `6d6acb5`). Phase 1 is implemented and verified in the development environment but **has not been deployed** to the Ubuntu VM.

## Summary

KYVON is now a modular Flask application with a versioned JSON API, a SQLite database, single-owner authentication, and a separate web client. The prototype's behavior (chat, memory, web search, location, weather, voice input, diagnostics) is preserved. Tasks, calendar, conversation history, tools, and agents are not built yet. They are Phases 2-6.

## Architecture

```
Browser / future iOS app
        │  HTTPS (Cloudflare Tunnel) — cookie session (web) or bearer token (native)
        ▼
gunicorn (port 8080) → Flask app factory (kyvon.create_app)
   api/     /api/v1 routes, Pydantic validation, auth guard, JSON errors
   services/ chat · memory · memory_import · auth · environment · status
   llm/     LLMClient protocol → GroqClient (openai/gpt-oss-120b, groq/compound)
   integrations/ Nominatim (reverse geocode) · Open-Meteo (weather)
   models/  SQLAlchemy 2 → SQLite data/kyvon.db (Alembic migrations)
web/        plain ES modules (api, auth, chat, env, memory, diagnostics, voice, ui, main)
```

Details and the differences from the original design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ("As built").

## Current functionality

| Area | Status |
|---|---|
| Chat with Groq (`openai/gpt-oss-120b`), KYVON persona | Working |
| Memory: `remember …`, `don't forget that …`, `keep in mind that …`; newest 20 in prompt; newest 100 kept | Working, stored in the database per user |
| Import of the prototype's `kyvon_memory.json` | Working, idempotent, the JSON is never modified |
| Web research (`web …` → `groq/compound`) | Working |
| Location (browser GPS → Nominatim) and weather (Open-Meteo) | Working |
| Voice input (browser speech recognition) | Working where the browser supports it |
| Diagnostics (SYSTEM button) | Working; the deep check makes one model call |
| Single-owner sign-in, per-device tokens, revocation, sign-out | Working |
| Web client at `/` (same visual design, plus sign-in screen) | Working |
| Gunicorn, Dockerfile, systemd unit example | Written; gunicorn verified locally, Docker not built locally |
| CI (lint, format, tests, migration, JS syntax, Docker build, secret scan) | Written; **has not run on GitHub yet** (the branch has not been pushed) |
| Conversation history | Not built (Phase 2; tables exist, unused) |
| Advanced memory retrieval | Not built (Phase 3) |
| Tools / function calling | Not built (Phase 4) |
| Tasks, calendar | Not built (Phase 5) |
| Agents, Hermes, Logseq | Not built (Phase 6+) |
| Native iPhone/iPad app, PWA install | Not built (Phase 7) |

## Verification performed (development machine)

- `pytest`: 200 passed. `ruff check` and `ruff format --check`: clean.
- The prototype's 32 characterization tests and the old-vs-new parity tests passed against both implementations before `app.py` was replaced.
- Real migration run on a fresh database, owner created via the CLI, prototype-format memory file imported (2 entries, then 0 on re-import), JSON byte-identical afterwards.
- Gunicorn served the app; unauthenticated and bad-token requests returned 401.
- Web client exercised in a browser: sign-in, chat, memory save and view (cookie plus CSRF flow), diagnostics, sign-out returning to the sign-in screen. The model and weather were faked in that session.
- No secrets found in the tracked files or git history (pattern scan). `.env`, `data/` and `*.db` are ignored.

**Not verified:** a real Groq call and real Nominatim/Open-Meteo calls from the new code (no API key or live network use during development), the Docker image build, CI on GitHub, the iPad/Safari experience, and anything on the VM.

## Known issues and technical debt

1. **`remember that X` is saved as `that X`.** Preserved deliberately from the prototype; fix in Phase 3.
2. **Each chat is stateless.** No conversation history until Phase 2.
3. **The environment text is built in the browser and sent as-is** into the prompt. A signed-in user can put arbitrary text there. Phase 2 moves this to the server.
4. **The sign-in throttle is per process and per address+username.** Behind the Cloudflare Tunnel all requests come from 127.0.0.1, so five failures lock that username for 15 minutes for everyone (including you). `set-password` or a restart clears it.
5. **One gunicorn worker** by design (SQLite, in-memory throttle).
6. **Some weather codes are missing** (56/57, 66/67, 77, 85/86) and show "Unknown conditions". Kept from the prototype.
7. **Prototype memory timestamps** had no timezone; they are imported as UTC.
8. **Secure cookies:** in production mode the web client only signs in over HTTPS. Plain-HTTP testing needs `KYVON_COOKIE_SECURE=false`.
9. **No CORS and no PWA manifest/icons** yet. The API is same-origin only until the native app needs more.
10. **Unused schema:** `conversations` and `messages` tables are created but not used until Phase 2.
11. **Python 3.12+ required** (uses newer syntax). Ubuntu 24.04's default is 3.12.
12. **Geolocation and voice** need HTTPS on iOS; the tunnel provides it.
13. **Repository and folder names** still say `jarvis-assistant` (GitHub repo `temcwilliams/jarvis-assistant`, local folder). Renaming the GitHub repository is your decision; the code and UI say KYVON.

## Dependencies

- **Python:** Flask, SQLAlchemy 2, Alembic, Pydantic 2, Groq SDK, requests, python-dotenv, gunicorn. Dev: pytest, Ruff.
- **External services:** Groq API (needs `GROQ_API_KEY`), OpenStreetMap Nominatim, Open-Meteo (no key).
- **Runtime:** Python 3.12, SQLite. Deployment: systemd and Cloudflare Tunnel on the VM.

## Configuration

Environment variables or `.env` (never committed); see [.env.example](.env.example). Required: `GROQ_API_KEY`. Everything else has a default.

## Deployment

Target: the existing Ubuntu 24.04 VM at `/home/traxc93/kyvon-assistant`, systemd `kyvon.service`, port 8080, Cloudflare Tunnel. Procedure and rollback: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The VM has not been inspected or modified, and its Git remote has not been verified.

## Recommended next steps

1. Push the branch, confirm CI passes on GitHub, and open a pull request.
2. Deploy Phase 1 to the VM using [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), and check it from the iPad.
3. Then Phase 2 (conversation persistence, server-built environment, streaming) once you approve it. See [docs/ROADMAP.md](docs/ROADMAP.md).
