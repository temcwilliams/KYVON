# KYVON

A personal AI assistant: chat, memory, web research, and location/weather awareness, with a web
client that works on iPhone and iPad. Flask backend, SQLite database, Groq for the model.

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)
- Deploying: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- Current status and known issues: [KYVON_STATUS.md](KYVON_STATUS.md)

## What it does today (Phase 1)

- Chat with a Groq model (`openai/gpt-oss-120b`), using the KYVON persona.
- Memory: say `remember ...` (or `don't forget that ...`, `keep in mind that ...`). The newest
  20 memories are included in every reply.
- Web research: start a message with `web ` to use Groq's `groq/compound` search model.
- Location and weather from the browser's GPS (OpenStreetMap Nominatim + Open-Meteo).
- Voice input where the browser supports it.
- Single-owner sign-in. Each device gets its own revocable token.

Tasks, calendar, conversation history, tools and agents are planned for later phases.

## Run it locally

Requires Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

cp .env.example .env          # then put your real GROQ_API_KEY in .env
.venv/bin/flask --app wsgi kyvon db-upgrade
.venv/bin/flask --app wsgi kyvon create-user      # prompts for a username and password
.venv/bin/python app.py                            # http://localhost:8080
```

Browser geolocation and voice input need HTTPS (or `localhost`).

If you have a memory file from the prototype (`data/kyvon_memory.json`), import it once:

```bash
.venv/bin/flask --app wsgi kyvon import-memories
```

The command is safe to repeat and never modifies the JSON file.

## Administration commands

`flask --app wsgi kyvon <command>`

| Command | Purpose |
|---|---|
| `db-upgrade` | Apply database migrations |
| `create-user` | Create the owner account (only one is allowed; no public sign-up) |
| `set-password` | Change the password and sign out every device |
| `revoke-tokens` | Sign out every device |
| `import-memories` | Import the prototype's JSON memories |

## Configuration

Environment variables (or a `.env` file; real environment variables win). See
[.env.example](.env.example) for the full list.

| Variable | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | (required) | Never commit it |
| `KYVON_ENV` | `development` | `production` marks auth cookies Secure |
| `PORT` | `8080` | |
| `KYVON_DATA_DIR` | `data` | Database, error log, legacy memory file |
| `DATABASE_URL` | `sqlite:///<data dir>/kyvon.db` | |
| `KYVON_TOKEN_TTL_DAYS` | `30` | |

## Development

```bash
.venv/bin/pytest          # tests (no network; the model is faked)
.venv/bin/ruff check .    # lint
.venv/bin/ruff format .   # format
```

Layout:

```
kyvon/            backend package
  api/            HTTP layer: /api/v1 routes, validation, errors, auth guard
  services/       business logic (chat, memory, auth, environment, status)
  llm/            model provider seam (Groq) and prompts
  integrations/   Nominatim and Open-Meteo clients
  models/         SQLAlchemy models
  cli.py          administration commands
migrations/       Alembic migrations
web/              the web client (plain ES modules, no build step)
tests/            pytest suite
docs/             architecture, roadmap, deployment
```

## API

All endpoints are under `/api/v1`. Everything except `GET /health` and `POST /auth/login` needs
a device token (`Authorization: Bearer ...`) or the web client's session cookie. Errors look like
`{"error": {"code": "...", "message": "..."}}`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness (no auth) |
| `POST /auth/login` | Sign in; returns a device token (or sets a cookie with `"cookie": true`) |
| `POST /auth/logout`, `GET /auth/me` | Sign out; current user |
| `GET /auth/tokens`, `DELETE /auth/tokens/<id>` | List and revoke devices |
| `POST /chat` | `{"message": "...", "environment": "..."}` |
| `GET /memories` | Saved memories |
| `POST /environment` | `{"latitude": ..., "longitude": ...}` → location and weather |
| `GET /status[?deep=1]` | Diagnostics (`deep` makes one model call) |
