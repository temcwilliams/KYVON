# KYVON

A personal AI assistant you talk to from a browser, an installed web app (iPhone, iPad, desktop) or,
eventually, a native app. Flask backend, SQLite database, Groq for the language model.

- What exists, how it works, and every known limit: **[KYVON_STATUS.md](KYVON_STATUS.md)**
- Security model and review: [docs/SECURITY.md](docs/SECURITY.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)
- Deploying to the Ubuntu VM: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Settings: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

## What it does

- **Chat** with persistent conversations, streaming replies, a stop button, and context that stays within
  limits however long the chat gets.
- **Memory** you control: it only saves what you ask (`remember ...`), refuses to store secrets, retrieves only
  what is relevant, and lets you view, edit and delete everything.
- **Tools** with approvals: KYVON can look things up, check weather and time, manage tasks and reminders,
  read and change your Google Calendar, search and write your Logseq notes. Anything with an external effect,
  and anything that deletes, waits for your explicit approval.
- **Agents**: specialist helpers (research, planning, productivity, memory review, diagnostics, and an optional
  Hermes helper) that the assistant can hand multi-step jobs to, within strict limits.
- **Automation**: reminders and recurring scheduled tasks, with history, retries and an inbox.
- **Personalisation**: name, response style, tone, units, time zone, and per-integration switches.
- **PWA**: installable, offline shell, connection status, responsive layouts, optional push notifications.
- **Voice**: dictate with server-side Whisper, hear replies read by your device.
- **Admin** view: health, errors, usage and run traces (no secrets).

## Run it locally

Requires Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

cp .env.example .env          # put your real GROQ_API_KEY in .env
.venv/bin/flask --app wsgi kyvon db-upgrade
.venv/bin/flask --app wsgi kyvon create-user      # username + password
.venv/bin/python app.py                            # http://localhost:8080
```

Browser location, microphone, installation and notifications need HTTPS (or `localhost`).

Check a running server end to end:

```bash
KYVON_SMOKE_PASSWORD='...' .venv/bin/python scripts/smoke_test.py http://127.0.0.1:8080 yourusername
```

## Administration

`flask --app wsgi kyvon <command>`

| Command | Purpose |
|---|---|
| `doctor` | Check configuration, permissions and migrations |
| `db-upgrade` | Apply database migrations |
| `create-user` | Create the owner account (one only; no public sign-up) |
| `set-password` / `revoke-tokens` | Change the password / sign out every device |
| `import-memories` | Import the old prototype's JSON memories (safe to repeat) |
| `backup` / `restore` | Consistent database backups (see the deployment guide) |
| `generate-key` / `generate-vapid-keys` | Create the encryption key / Web Push keys |

## Development

```bash
.venv/bin/pytest -n auto              # 1,014 tests; no network (models and services are faked)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/bandit -c pyproject.toml -r kyvon && .venv/bin/pip-audit -r requirements.txt
```

```
kyvon/         backend package (api, services, tools, agents, automation, integrations, llm, models)
web/           the web app / PWA (plain ES modules, no build step)
ios/           native client sources (NOT compiled yet; see ios/README.md)
migrations/    Alembic migrations          deploy/   systemd units and examples
docs/          architecture, security, deployment, configuration
```

## API

All under `/api/v1`. Everything except `GET /health`, `GET /health/ready` and `POST /auth/login` needs a
device token (`Authorization: Bearer ...`) or the web app's session cookie. Errors look like
`{"error": {"code": "...", "message": "..."}}`. The routes are defined in `kyvon/api/v1/`; the tool
catalogue is at `GET /tools`.
