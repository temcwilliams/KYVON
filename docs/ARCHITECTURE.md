# KYVON — Target Architecture

Status: **approved; Phase 1 implemented.** Sections 1-15 are the approved design. The [As built](#as-built-end-of-phase-1) section at the end records what was actually implemented and where it differs. Current state: [KYVON_STATUS.md](../KYVON_STATUS.md).

## Guiding principles

1. **Evolve, don't rebuild.** The existing chat, memory, web search and location/weather behavior is preserved and moved into modules. It keeps working at every step.
2. **API first.** The backend is a JSON API. The web UI is one client of it, and a future iPhone/iPad app is another.
3. **No global state.** Everything durable lives in the database. Each request is stateless apart from the DB.
4. **Small, boring tech.** Flask, SQLite (Postgres-ready), plain JS. Add complexity only when a phase needs it.
5. **Tools are the only way KYVON acts.** The model never claims an action it didn't perform. It reports real tool results.
6. **Single user first, multi-user-shaped.** All rows carry a `user_id`, so we don't have to retrofit it later.
7. **Provider-agnostic seams** (LLM, calendar, search) so Hermes or another model can slot in later. The provider stays Groq for now.

## 1. Proposed directory structure

```
kyvon/                          repo root
├── README.md
├── KYVON_STATUS.md
├── docs/  ARCHITECTURE.md  ROADMAP.md
├── .env.example                placeholders only
├── .gitignore
├── pyproject.toml              deps + tool config (or requirements.txt + requirements-dev.txt)
├── wsgi.py                     `app = create_app()` for gunicorn
├── run.py                      dev entry point
├── migrations/                 Alembic
├── kyvon/
│   ├── __init__.py             create_app() factory
│   ├── config.py               typed settings loaded from env
│   ├── extensions.py           db, migrate, limiter
│   ├── models/                 SQLAlchemy models (one file per aggregate)
│   │   ├── user.py  token.py  conversation.py  message.py
│   │   ├── memory.py  task.py  calendar.py  tool_run.py
│   ├── api/                    HTTP layer only: parse, validate, call service, serialize
│   │   ├── v1/  auth.py chat.py conversations.py memory.py tasks.py
│   │   │        calendar.py environment.py status.py
│   │   └── errors.py           uniform error envelope
│   ├── services/               business logic, no Flask imports
│   │   ├── auth_service.py  chat_service.py  conversation_service.py
│   │   ├── memory_service.py  task_service.py  calendar_service.py
│   │   └── environment_service.py
│   ├── llm/                    provider seam
│   │   ├── base.py             LLMClient protocol
│   │   ├── groq_client.py      current provider
│   │   └── prompts.py          system prompt builder
│   ├── tools/                  tool registry + tools
│   │   ├── registry.py  base.py
│   │   ├── memory_tools.py  task_tools.py  calendar_tools.py
│   │   ├── web_tools.py  weather_tools.py
│   ├── integrations/           external systems behind interfaces
│   │   ├── weather_openmeteo.py  geocode_nominatim.py
│   │   ├── calendar_google.py  (later) logseq/  hermes/
│   ├── agents/                 (Phase 6) runner, base agent, definitions
│   ├── web/                    serves the web client (thin)
│   └── utils/                  logging, time, ids
├── web/                        front-end (see section 10)
│   ├── index.html  css/  js/
└── tests/
    ├── unit/  api/  tools/  conftest.py
```

`app.py` stays runnable during migration (see section 14) and is removed only when the new package fully covers it.

## 2. Backend modules and responsibilities

| Layer | Responsibility | May depend on |
|---|---|---|
| `api/` | HTTP parsing, validation (pydantic schemas), auth decorator, response shape | services |
| `services/` | Business rules and orchestration. Pure Python and testable without HTTP | models, llm, tools, integrations |
| `models/` | Tables and relationships | extensions |
| `llm/` | Talk to the model provider. Build prompts. Normalize tool-call responses | config |
| `tools/` | Declare callable capabilities with JSON schemas, and execute them | services |
| `integrations/` | Wrap third-party APIs (weather, geocoding, Google Calendar) | config |
| `agents/` | Multi-step goal runners built on services and tools | services, tools, llm |
| `config.py` | Single source of settings | env only |

Rule: dependencies point downward. `api → services → models/integrations`. No service imports Flask, and no integration imports a service.

## 3. API endpoints (`/api/v1`)

All JSON. All routes except `/auth/login` and `/health` require authentication. Errors use `{"error": {"code": "...", "message": "..."}}`.

| Area | Endpoint | Purpose |
|---|---|---|
| Health | `GET /health` | Liveness, no auth, no LLM call |
| Status | `GET /status` | Authenticated diagnostics. DB/provider checks are opt-in via `?deep=1` |
| Auth | `POST /auth/login` | Password → access token |
| | `POST /auth/logout` | Revoke the current token |
| | `GET /auth/me` | Current user |
| | `GET/DELETE /auth/tokens[/<id>]` | List and revoke device tokens |
| Chat | `POST /chat` | Send a message (`conversation_id` optional). Returns assistant message and tool runs |
| | `POST /chat/stream` | Same, streamed via SSE (Phase 2) |
| Conversations | `GET /conversations`, `POST`, `GET /<id>`, `PATCH /<id>`, `DELETE /<id>` | Manage history |
| | `GET /conversations/<id>/messages` | Paginated messages |
| Memory | `GET /memories`, `POST`, `PATCH /<id>`, `DELETE /<id>` | View, edit, forget |
| Tasks | `GET /tasks`, `POST`, `PATCH /<id>`, `DELETE /<id>` | CRUD, `?status=&due_before=` |
| Calendar | `GET /calendar/events`, `POST`, `PATCH /<id>`, `DELETE /<id>` | Provider-backed |
| | `GET /calendar/connect`, `GET /calendar/callback` | OAuth flow |
| Environment | `POST /environment` | lat/lon → location + weather (existing behavior) |
| Tools | `GET /tools` | List available tools (debug/UI) |
| Agents | `POST /agents/runs`, `GET /agents/runs/<id>` | Phase 6 |

Legacy `/api/chat`, `/api/memory`, `/api/environment`, `/api/status` stay as thin aliases until the web client is migrated, then are removed.

## 4. Database / storage design

**Engine:** SQLite file at `data/kyvon.db` for development and single-user hosting (WAL mode). SQLAlchemy 2.x plus Alembic migrations, so switching to Postgres is a config change. Runtime data lives under `data/`, which is git-ignored.

```
users            id, username (unique), password_hash, created_at, settings_json
api_tokens       id, user_id, token_hash, name (device), created_at, last_used_at, expires_at, revoked_at
conversations    id, user_id, title, created_at, updated_at, archived
messages         id, conversation_id, role (user|assistant|tool|system), content,
                 tool_calls_json, tool_call_id, model, tokens_in, tokens_out, created_at
memories         id, user_id, content, category, source (user|model|import), importance,
                 created_at, updated_at, last_used_at, deleted_at
tasks            id, user_id, title, notes, status (open|done|cancelled), priority,
                 due_at, created_at, completed_at, source_message_id
calendar_accounts id, user_id, provider, external_account, credentials_encrypted, scopes, created_at
calendar_events  id, user_id, account_id, external_id, title, starts_at, ends_at, location, synced_at   (cache)
tool_runs        id, user_id, message_id, tool_name, arguments_json, result_json, status, error,
                 started_at, finished_at
agent_runs       (Phase 6) id, user_id, agent, goal, status, steps_json, created_at, finished_at
```

- All timestamps stored in UTC. The user's timezone lives in `users.settings_json`.
- Secrets in DB (OAuth refresh tokens) are encrypted with a key from the environment (`KYVON_ENCRYPTION_KEY`, Fernet).
- Soft-delete for memories, so "forget" is undoable and auditable. A hard purge is available.
- Data import: existing `data/kyvon_memory.json` is imported once into `memories` (see section 14).
- Later: SQLite FTS5 (or `pgvector`) for memory search. Embedding storage is deliberately deferred to Phase 3.

## 5. Authentication design

- **Single-owner mode first.** The first user is created via CLI (`flask kyvon create-user`). There is no public sign-up.
- Passwords are hashed with argon2 (or scrypt). Login is rate-limited.
- **Bearer tokens** are the primary mechanism, since they work identically for the web client and native iOS. Tokens are random 256-bit values, stored **hashed**, per device, revocable, with expiry and rotation. The web client keeps its token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie, so JavaScript never touches it. Native clients keep it in the iOS Keychain.
- CSRF protection applies only to the cookie flow (double-submit token). Bearer-header requests are exempt.
- Every query is scoped by `user_id`, enforced in the service layer.
- HTTPS is required in production (HSTS). CORS is an explicit allow-list from config.
- Later: Sign in with Apple / passkeys for the iOS app. The schema doesn't block it.
- Third-party credentials (Google OAuth) are separate from user auth and stored encrypted.

## 6. Conversation model

- A **conversation** is an ordered list of **messages** (`user`, `assistant`, `tool`).
- `POST /chat` with no `conversation_id` creates one and titles it (first message, later auto-summarized).
- **Context assembly** (in `chat_service`): system prompt (persona + rules) + relevant memories + environment block + last *N* messages within a token budget. Older turns are summarized (Phase 2) and the summary is stored on the conversation.
- **Tool loop:** call the model with the tool schemas. If it returns tool calls, execute them, store `tool` messages and `tool_runs`, and call the model again. The loop is capped (default 5 iterations) and every iteration is logged.
- The server-side clock provides the current time and timezone, so "local time" no longer depends on the weather API.
- The client sends only the new message and, optionally, an environment payload (lat/lon). The server builds the environment text itself, which closes the current prompt-injection hole where the client supplies raw prompt text.

## 7. Memory model

Three tiers, introduced gradually:

1. **Explicit memories** (Phase 1–3): facts the user asked to save. Stored in `memories`, with a `remember` tool replacing the keyword parser and the old prefixes kept as shortcuts.
2. **Retrieval**: rather than injecting the last 20, select relevant ones. Start with keyword/FTS ranking plus recency, and add embeddings only if needed.
3. **Proposed memories** (later): the model suggests memories, and the user approves them before they're stored (`source=model`, `status=pending`).

Rules: users can list, edit and delete everything. Every memory shows its origin. Nothing sensitive is stored silently. `last_used_at` records what actually influenced answers.

Logseq and other external sources import through the same `memories` interface with `source=import` and a stable external id.

## 8. Tool system design

```python
class Tool:
    name: str                   # "create_task"
    description: str
    parameters: JSONSchema      # generated from a pydantic model
    requires_confirmation: bool # side-effecting or destructive tools ask first
    def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult
```

- A **registry** holds all tools. `ToolContext` carries `user_id`, DB session, clock, and settings. Tools never read globals.
- The registry produces the provider's function-calling schema (`llm/` translates it into the Groq format).
- **Initial tools:** `remember`, `search_memories`, `forget`, `web_search`, `get_weather`, `get_current_time`, `create_task`, `list_tasks`, `complete_task`, `list_events`, `create_event`.
- **Safety:** arguments are validated before execution. Tools that change things outside KYVON's own DB (calendar writes, later message sending) return a *pending confirmation* result first, and only execute after the user approves. Read-only tools run without asking. Each run is logged in `tool_runs`. No arbitrary code execution, ever.
- The existing `web ...` prefix stays as a shortcut that invokes the `web_search` tool directly.
- MCP-compatible tool definitions are a future option, which is one reason for keeping schemas standard.

## 9. Agent / subagent design (Phase 6)

- An **agent** is a named profile: system prompt, allowed tool subset, model, step budget, and output type. It has no special powers beyond its tools.
- The **runner** executes a goal as a bounded loop (plan → tool call → observe → finish), persists each step in `agent_runs`, and supports cancel and timeout. It runs in a background worker (start with a thread pool or RQ/Celery only when needed).
- **KYVON (primary)** can delegate to subagents such as *Researcher*, *Planner*, *Scheduler* and *Inbox/Notes*. Delegation is a tool (`delegate(agent, goal)`), so it goes through the same logging and permission model.
- Agents get least-privilege tool sets. Confirmation rules from section 8 apply unchanged.
- **Hermes** integrates as an `llm/` provider or an agent backend behind the same interface. It is not started until approved.
- **Logseq** integrates as an `integrations/logseq` adapter, exposed as tools (`search_notes`, `append_to_journal`) and a memory import source.

## 10. Frontend / client architecture

- The front end lives in `web/` and is decoupled from Flask templates. It talks only to `/api/v1`, so it can be hosted by Flask (`static`) or separately.
- Keep it **plain ES modules, no build step** to start. Split `app.js` into `api.js` (fetch wrapper and auth), `chat.js`, `memory.js`, `tasks.js`, `voice.js`, `env.js`. Move away from inline `onclick` handlers. Render markdown safely (a sanitizer such as DOMPurify).
- Add a **PWA manifest and icons** so it installs to the iPad/iPhone Home Screen, and a responsive layout. Add tabs for Chat, Tasks, Calendar and Memory.
- Voice: browser speech recognition now, `speechSynthesis` for replies, and a server-side STT/TTS option later.
- The **native iOS/iPadOS app** (Phase 7) consumes the same API with the same bearer-token auth. Because the API is versioned and documented (OpenAPI, generated from the pydantic schemas), no server rework is needed. Apple Shortcuts can call the API directly for device actions.
- A build tool such as Vite is introduced only if the UI outgrows plain modules.

## 11. Configuration / secrets strategy

- `kyvon/config.py` reads environment variables (with `python-dotenv` in development), validates them at startup, and fails fast with a clear message. Classes: `Development`, `Testing`, `Production`.
- `.env.example` is committed with placeholders only. The real `.env` is git-ignored.
- Variables (placeholders): `KYVON_ENV`, `SECRET_KEY`, `KYVON_ENCRYPTION_KEY`, `DATABASE_URL`, `GROQ_API_KEY`, `KYVON_MODEL`, `KYVON_WEB_MODEL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_ORIGINS`, `LOG_LEVEL`.
- Production secrets come from the host's secret store (Codespaces secrets, Fly/Render secrets, or systemd env). They are never written to logs, prompts or API responses, and the prompt rule against revealing keys is backed by never putting keys in the model's context.
- `.gitignore` covers `.env*` (except `.env.example`), `data/`, `*.db`, `__pycache__/`, `.venv/`, logs, `*.pem`, and token files.
- Before the first commit of the new setup, run a secret scan (gitleaks) as a pre-commit hook.

## 12. Testing strategy

- **pytest** with an app-factory fixture, an in-memory SQLite DB per test, and a `FakeLLM` implementing the `LLMClient` protocol, so tests never call Groq.
- **Unit:** services, the prompt and context builder, the tool registry and arguments validation, and the memory parser.
- **API:** Flask test client for auth, chat (with FakeLLM scripted tool calls), CRUD and error shapes.
- **Integration adapters:** recorded HTTP fixtures (`responses`/`vcr`) for Open-Meteo, Nominatim and Google Calendar. Live tests are opt-in via a marker.
- **Characterization tests first:** before refactoring, pin the prototype's current behavior (memory prefixes, routing, error responses), so the migration can't silently change it.
- Tooling: ruff (lint and format), mypy on `services/`, and GitHub Actions running lint + tests on every PR.

## 13. Deployment strategy

**Decision (approved):** KYVON stays on the existing Ubuntu 24.04 VM (`/home/traxc93/kyvon-assistant`, systemd service `kyvon.service`, port 8080, Cloudflare Tunnel for HTTPS). No hosting migration.

- The app is host-independent: it needs Python 3.12, a writable data directory, and environment variables. Nothing in the code refers to the VM.
- Runtime: gunicorn (`wsgi:app`, one worker plus threads) started by systemd. Migrations run in `ExecStartPre`.
- A `Dockerfile` and entrypoint are included so the same build can move to another host later, without rewriting anything.
- Backups: `data/` (SQLite database, error log, legacy memory JSON) is the only state to back up.
- Procedure and rollback: [DEPLOYMENT.md](DEPLOYMENT.md).

## 14. Migration plan from the current prototype

Every step keeps the app runnable. Details are in Phase 1 of the roadmap.

1. Add `.gitignore`, `.env.example`, and lint/test tooling. Add characterization tests around today's `app.py`.
2. Create the `kyvon/` package with `create_app()` and `config.py`. Move the existing code into modules **without changing behavior**:
   - memory functions → `services/memory_service.py`
   - `get_location`/`get_weather` → `integrations/` + `environment_service.py`
   - `ask_kyvon`/`web_search` → `llm/groq_client.py` + `chat_service.py`
   - routes → `api/` blueprints, with the old `/api/*` paths kept as aliases
3. Introduce the DB and models. Import `data/kyvon_memory.json` into `memories` with a one-time script that keeps the JSON file as a backup.
4. Add auth, then lock down the routes and update the web client to log in.
5. Split the front end into modules under `web/` and switch it to `/api/v1`.
6. Remove the legacy `app.py` and the aliases, finish the KYVON rename, and delete `tasks.json` and the unused `REPAIR_LOG`.

Behavior changes are deliberate and listed in the PR: conversation history, server-built environment text, and a cheap `/health`. The model provider stays Groq with the current models.

## 15. Recommended implementation phases

See [ROADMAP.md](ROADMAP.md) for phase-by-phase scope, deliverables and exit criteria:

1. Foundation
2. Conversational Intelligence
3. Memory
4. Tools
5. Personal Assistant
6. Agents
7. iPhone/iPad
8. Automation and advanced capabilities

## Key decisions to approve

| # | Decision | Recommendation |
|---|---|---|
| 1 | Database | SQLite + SQLAlchemy + Alembic (Postgres-ready) |
| 2 | Auth | Single-owner, password login, per-device revocable bearer tokens |
| 3 | Structure | Flask app factory, blueprints, service layer, `kyvon/` package |
| 4 | Frontend | Plain ES modules in `web/`, PWA, no build step yet |
| 5 | Tool calling | Native provider function calling through a registry, with confirmation for side effects |
| 6 | Validation | pydantic schemas (also the source for OpenAPI) |
| 7 | Hosting | Container with gunicorn on Fly.io/Render or a Tailscale-reachable box |

## As built (end of Phase 1)

Implemented as designed unless noted.

**Structure**

```
app.py  wsgi.py  gunicorn.conf.py  Dockerfile  docker-entrypoint.sh  alembic.ini
kyvon/
  __init__.py            create_app() factory, Services container, security headers
  config.py              typed Settings (env + optional .env)
  db.py                  Base, UTC datetime type, engine/session, upgrade_database()
  cli.py                 flask --app wsgi kyvon <db-upgrade|create-user|set-password|revoke-tokens|import-memories>
  api/                   deps.py (session, auth guard, JSON parsing), errors.py, schemas.py,
                         v1/routes.py, v1/auth.py
  services/              chat, memory, memory_import, auth, environment, status
  llm/                   base (LLMClient protocol), groq_client, prompts
  integrations/          geocode_nominatim, weather_openmeteo
  models/                user (User, ApiToken), memory, conversation (Conversation, Message)
  utils/                 error_log, rate_limit
migrations/versions/0001_initial_schema.py
web/                     index.html, css/, js/ (api, auth, chat, env, memory, diagnostics, voice, ui, main)
tests/
```

**Endpoints implemented:** `GET /health`, `GET /status[?deep=1]`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `GET /auth/tokens`, `DELETE /auth/tokens/<id>`, `POST /chat`, `GET /memories`, `POST /environment`. The remaining endpoints in section 3 belong to later phases.

**Differences from the design**

| Design | As built |
|---|---|
| One route file per area | `routes.py` (chat, memories, environment, status) and `auth.py`; split when they grow |
| `memories.importance` column | Omitted until Phase 3 needs it |
| `messages` tool fields | Omitted until Phase 4; `conversations` / `messages` exist as schema only, unused until Phase 2 |
| `extensions.py` | Not needed; engine and sessions are created in the factory |
| `tool_runs`, `calendar_*`, `agent_runs` tables | Later phases |
| `KYVON_ENCRYPTION_KEY`, `SECRET_KEY` | Not needed yet (tokens are hashed, not encrypted); will return with Google Calendar |
| Legacy `/api/*` aliases | Not created. The web client moved to `/api/v1` in the same release |
| `web/` served by Flask | As designed (Flask serves `web/` at `/` and `/static`) |
| `flask kyvon create-user` | As designed, plus `set-password`, `revoke-tokens`, `import-memories`, `db-upgrade` |
| Status check | `GET /status` is cheap; `?deep=1` makes the one model call the prototype made on every check |
| Error envelope | As designed. Prototype's `"diagnosed": true` field was dropped |

**Behavior changes from the prototype (deliberate):** invalid input returns 400 (was 500); messages are limited to 10,000 characters; the SYSTEM button runs the deep status check while the automatic startup check does not call the model; the CSS/HTML no longer says J.A.R.V.I.S.; everything requires sign-in. The `remember that X` quirk (stored as `that X`) is **preserved** and listed as a known issue.

**Auth as built:** scrypt password hashes, `kyv_`-prefixed 256-bit device tokens stored as SHA-256, 30-day expiry (configurable), bearer header or HttpOnly `SameSite=Strict` cookie with CSRF double-submit for cookie requests, and a failed-login throttle (5 failures per 15 minutes per address+username, in memory).

**Testing as built:** pytest with a `FakeLLM` and injected HTTP fakes, so no test touches the network; migration/model drift check; CI runs lint, format check, tests, a fresh-database migration, a JavaScript syntax check, a Docker build, and a secret scan.
