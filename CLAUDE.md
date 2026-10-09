# KYVON

Flask + SQLAlchemy/Alembic backend (SQLite locally, PostgreSQL when hosted), Groq for the LLM, a PWA in `web/`,
a Swift iOS app in `ios/`, a marketing site in `site/`. Python 3.12+. See `KYVON_STATUS.md` for what exists and
`docs/ARCHITECTURE.md` / `docs/SECURITY.md` for design and the security model.

## Commands (use the project venv)

```bash
.venv/bin/pytest -n auto                       # tests (CI runs this)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/bandit -q -c pyproject.toml -r kyvon # skips are reviewed in pyproject.toml
.venv/bin/flask --app wsgi kyvon db-upgrade    # apply migrations
.venv/bin/flask --app wsgi kyvon doctor        # check config, permissions, migrations
.venv/bin/python scripts/gen_config_docs.py    # regenerate docs/CONFIGURATION.md (add --check to verify)
.venv/bin/python app.py                        # dev server on :8080
```

`tests/test_postgres.py` needs a Postgres instance and is a separate CI job.

## Layout

- `kyvon/api/v1/` thin route handlers; errors in `kyvon/api/errors.py`, schemas in `schemas.py`
- `kyvon/services/` business logic (chat, billing, usage, accounts, memory...); raise errors from `services/errors.py`
- `kyvon/models/` SQLAlchemy models; `migrations/versions/` Alembic (sequential `NNNN_name.py`)
- `kyvon/tools/`, `kyvon/agents/`, `kyvon/automation/`, `kyvon/integrations/`
- `kyvon/config.py` is the single source of settings

## Rules

- Schema change means a new Alembic revision; never edit a committed migration (a hook blocks it).
- Adding or changing a setting in `config.py` means regenerating `docs/CONFIGURATION.md`; CI checks it.
- Never commit secrets or read `.env`; use `.env.example` / `.env.hosted.example`.
- Anything with an external effect or that deletes goes through the tool-approval flow.
- Memory must never store secrets (`services/memory_rules.py`).
- Keep ruff clean (line length 100); a hook formats edited Python files automatically.

## Automation in `.claude/`

`settings.json` allowlists test/lint commands and runs two hooks: `guard_edit.py` (blocks real env files and
committed migrations) and `ruff_format.py` (fix + format on edit).
