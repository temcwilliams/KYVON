"""Typed application settings, loaded from environment variables.

Defaults match the legacy prototype (app.py): port 8080, the same Groq models,
and a ``data/`` directory relative to the working directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_WEB_MODEL = "groq/compound"
VALID_ENVS = ("development", "testing", "production")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    model: str = DEFAULT_MODEL
    web_model: str = DEFAULT_WEB_MODEL
    env: str = "development"
    secret_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    allowed_origins: tuple[str, ...] = ()
    database_url: str = ""
    token_ttl_days: int = 30
    cookie_secure: bool = False

    # Derived paths (same file names the prototype uses).
    @property
    def memory_file(self) -> Path:
        return self.data_dir / "kyvon_memory.json"

    @property
    def error_log(self) -> Path:
        return self.data_dir / "kyvon_errors.log"

    @property
    def db_url(self) -> str:
        """SQLAlchemy URL; defaults to SQLite at <data_dir>/kyvon.db."""
        return self.database_url or f"sqlite:///{self.data_dir / 'kyvon.db'}"

    def __repr__(self) -> str:
        # Never print secrets, even by accident.
        return (
            f"Settings(env={self.env!r}, model={self.model!r}, web_model={self.web_model!r}, "
            f"host={self.host!r}, port={self.port}, data_dir={str(self.data_dir)!r}, "
            "groq_api_key='***', secret_key='***')"
        )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_dotenv_file: bool = False,
        require_api_key: bool = True,
    ) -> Settings:
        """Build settings from ``environ`` (defaults to ``os.environ``).

        ``load_dotenv_file`` reads ``.env`` first without overriding variables that are
        already set, so real environment variables (systemd, Codespaces secrets) win.
        """
        if load_dotenv_file:
            load_dotenv(find_dotenv(usecwd=True), override=False)
        env_map = os.environ if environ is None else environ

        def get(name: str, default: str = "") -> str:
            return (env_map.get(name) or default).strip()

        env = get("KYVON_ENV", "development").lower()
        if env not in VALID_ENVS:
            raise ConfigError(f"KYVON_ENV must be one of {', '.join(VALID_ENVS)} (got {env!r}).")

        api_key = get("GROQ_API_KEY")
        if require_api_key and not api_key:
            raise ConfigError(
                "GROQ_API_KEY was not found. "
                "Set it in the environment or in a .env file (see .env.example)."
            )

        try:
            port = int(get("PORT", "8080"))
        except ValueError as error:
            raise ConfigError("PORT must be an integer.") from error
        if not 1 <= port <= 65535:
            raise ConfigError("PORT must be between 1 and 65535.")

        try:
            token_ttl_days = int(get("KYVON_TOKEN_TTL_DAYS", "30"))
        except ValueError as error:
            raise ConfigError("KYVON_TOKEN_TTL_DAYS must be an integer.") from error
        if token_ttl_days < 1:
            raise ConfigError("KYVON_TOKEN_TTL_DAYS must be at least 1.")

        # Cookies default to Secure in production (HTTPS is terminated by the
        # Cloudflare Tunnel, so this is a setting rather than request.is_secure).
        secure_default = "true" if env == "production" else "false"
        cookie_secure = get("KYVON_COOKIE_SECURE", secure_default).lower() in ("1", "true", "yes")

        origins = tuple(o.strip() for o in get("ALLOWED_ORIGINS").split(",") if o.strip())

        return cls(
            groq_api_key=api_key,
            model=get("KYVON_MODEL", DEFAULT_MODEL),
            web_model=get("KYVON_WEB_MODEL", DEFAULT_WEB_MODEL),
            env=env,
            secret_key=get("SECRET_KEY"),
            host=get("KYVON_HOST", "0.0.0.0"),
            port=port,
            log_level=get("LOG_LEVEL", "INFO").upper(),
            data_dir=Path(get("KYVON_DATA_DIR", "data")),
            allowed_origins=origins,
            database_url=get("DATABASE_URL"),
            token_ttl_days=token_ttl_days,
            cookie_secure=cookie_secure,
        )
