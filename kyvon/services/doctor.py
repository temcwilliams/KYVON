"""Pre-flight configuration checks (`kyvon doctor`): catch a bad setup before it bites."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from kyvon.config import Settings
from kyvon.integrations.hermes import HermesConfigError, validate_url
from kyvon.models import User
from kyvon.utils.crypto import CryptoError, SecretBox

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    level: str
    message: str


def run_checks(
    settings: Settings, session_factory: Any, *, env_file: Path | None = None
) -> list[Check]:
    checks: list[Check] = []

    def add(level: str, message: str) -> None:
        checks.append(Check(level, message))

    production = settings.env == "production"

    # Basics
    add(
        OK if settings.groq_api_key else FAIL,
        "GROQ_API_KEY is set" if settings.groq_api_key else "GROQ_API_KEY is missing",
    )
    data_dir = settings.data_dir
    if data_dir.is_dir() and os.access(data_dir, os.W_OK):
        add(OK, f"data folder {data_dir} is writable")
    else:
        add(FAIL, f"data folder {data_dir} is missing or not writable")

    # Production hygiene
    if production:
        add(
            OK if settings.cookie_secure else WARN,
            "sign-in cookies are Secure"
            if settings.cookie_secure
            else "KYVON_ENV=production but cookies are not Secure (HTTPS needed)",
        )
        if not settings.public_url.startswith("https://"):
            add(WARN, "KYVON_PUBLIC_URL is not https:// (needed for Google sign-in and push)")
        if not settings.log_json:
            add(WARN, "production logs are not JSON (KYVON_LOG_JSON=false)")
    else:
        add(OK, f"environment is '{settings.env}' (production hardening not required)")
    if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
        add(WARN, "more than one gunicorn worker: the scheduler and rate limits are per process")

    # .env file permissions
    if env_file is not None and env_file.exists():
        mode = stat.S_IMODE(env_file.stat().st_mode)
        if mode & 0o077:
            add(WARN, f"{env_file.name} is readable by other users (chmod 600 {env_file.name})")
        else:
            add(OK, f"{env_file.name} permissions are private")

    # Database
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
            try:
                current = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:
                current = None
            from alembic.script import ScriptDirectory

            from kyvon.db import alembic_config

            head = ScriptDirectory.from_config(alembic_config(settings.db_url)).get_current_head()
            if current == head:
                add(OK, f"database is migrated ({head})")
            else:
                add(
                    FAIL,
                    f"database migration is {current or 'missing'}, expected {head}: run kyvon db-upgrade",
                )
            if current:
                owners = session.scalar(select(User.id).limit(1))
                add(
                    OK if owners else WARN,
                    "owner account exists"
                    if owners
                    else "no owner account yet: run kyvon create-user",
                )
    except Exception as error:
        add(FAIL, f"database check failed ({type(error).__name__})")

    if settings.hosted:
        _hosted_checks(settings, add)

    # Optional integrations: half-configured is a mistake worth flagging.
    google = [
        bool(settings.google_client_id),
        bool(settings.google_client_secret),
        bool(settings.encryption_key),
    ]
    if any(google) and not all(google):
        add(
            WARN,
            "Google Calendar is partly configured (needs GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and KYVON_ENCRYPTION_KEY)",
        )
    elif all(google):
        try:
            SecretBox(settings.encryption_key)
            add(OK, "Google Calendar is configured")
        except CryptoError:
            add(FAIL, "KYVON_ENCRYPTION_KEY is not a valid key (kyvon generate-key)")
    if settings.hermes_url:
        try:
            validate_url(settings.hermes_url, allow_remote=settings.hermes_allow_remote)
            add(OK, "Hermes URL is acceptable")
        except HermesConfigError as error:
            add(FAIL, str(error))
    if settings.logseq_dir:
        add(
            OK if Path(settings.logseq_dir).expanduser().is_dir() else FAIL,
            "Logseq folder found"
            if Path(settings.logseq_dir).expanduser().is_dir()
            else "KYVON_LOGSEQ_DIR is not a folder",
        )
    push = [
        bool(settings.vapid_public_key),
        bool(settings.vapid_private_key),
        bool(settings.vapid_subject),
    ]
    if any(push) and not all(push):
        add(WARN, "Web Push is partly configured (needs both VAPID keys and KYVON_VAPID_SUBJECT)")
    return checks


def _hosted_checks(settings, add) -> None:
    """Extra checks for KYVON_MODE=hosted (a public, multi-user service)."""
    add(OK, "hosted mode: many accounts, quotas and billing apply")
    production = settings.env == "production"
    if settings.db_url.startswith("sqlite"):
        add(
            WARN if production else OK,
            "database is SQLite: fine for a trial, use Postgres (DATABASE_URL) for a public service",
        )
    else:
        add(OK, "database is not SQLite")
    if settings.email_configured:
        add(OK, "outgoing email is configured")
    else:
        add(
            FAIL if production else WARN,
            "no outgoing email (KYVON_SMTP_HOST and KYVON_EMAIL_FROM): verification and reset emails cannot be sent",
        )
    if not settings.public_url.startswith("https://") and production:
        add(FAIL, "KYVON_PUBLIC_URL must be an https:// address in production")
    if settings.signup_open and not settings.email_configured and production:
        add(FAIL, "sign-up is open but email is not configured")
    if production and not settings.proxy_hops:
        add(
            WARN,
            "KYVON_PROXY_HOPS is 0: behind a proxy every visitor looks like one IP, so rate limits are shared",
        )
