"""Typed application settings, loaded from environment variables.

Defaults match the original prototype where it had a setting: port 8080, the same
Groq models, and a ``data/`` directory relative to the working directory.
Tuning values are declared in the tables below so adding one is a one-line change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_WEB_MODEL = "groq/compound"
DEFAULT_STT_MODEL = "whisper-large-v3-turbo"
VALID_ENVS = ("development", "testing", "production")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# field name -> (environment variable, default, minimum, maximum)
_INTS: dict[str, tuple[str, int, int, int]] = {
    "port": ("PORT", 8080, 1, 65535),
    "token_ttl_days": ("KYVON_TOKEN_TTL_DAYS", 30, 1, 3650),
    "context_max_tokens": ("KYVON_CONTEXT_MAX_TOKENS", 6000, 500, 200_000),
    "context_max_messages": ("KYVON_CONTEXT_MAX_MESSAGES", 40, 2, 500),
    "context_reserve_tokens": ("KYVON_CONTEXT_RESERVE_TOKENS", 1500, 100, 32_000),
    "summary_trigger_messages": ("KYVON_SUMMARY_TRIGGER_MESSAGES", 30, 6, 1000),
    "memory_max": ("KYVON_MEMORY_MAX", 2000, 10, 100_000),
    "memory_retrieval_k": ("KYVON_MEMORY_RETRIEVAL_K", 8, 1, 50),
    "tool_timeout_seconds": ("KYVON_TOOL_TIMEOUT_SECONDS", 30, 1, 600),
    "tool_max_iterations": ("KYVON_TOOL_MAX_ITERATIONS", 5, 1, 20),
    "confirmation_ttl_minutes": ("KYVON_CONFIRMATION_TTL_MINUTES", 60, 1, 10_080),
    "llm_timeout_seconds": ("KYVON_LLM_TIMEOUT_SECONDS", 60, 5, 600),
    "max_request_bytes": ("KYVON_MAX_REQUEST_BYTES", 1_000_000, 1024, 50_000_000),
    "hermes_timeout_seconds": ("KYVON_HERMES_TIMEOUT_SECONDS", 90, 5, 600),
    "scheduler_tick_seconds": ("KYVON_SCHEDULER_TICK_SECONDS", 30, 1, 3600),
    "automation_max_per_user": ("KYVON_AUTOMATION_MAX_PER_USER", 50, 1, 1000),
    "agent_max_depth": ("KYVON_AGENT_MAX_DEPTH", 1, 1, 3),
    "agent_timeout_cap_seconds": ("KYVON_AGENT_TIMEOUT_CAP_SECONDS", 150, 10, 900),
    "agent_max_tool_calls": ("KYVON_AGENT_MAX_TOOL_CALLS", 12, 1, 50),
    "agent_max_concurrent": ("KYVON_AGENT_MAX_CONCURRENT", 2, 1, 10),
    "rate_limit_chat_per_minute": ("KYVON_RATE_LIMIT_CHAT", 30, 1, 10_000),
    "rate_limit_api_per_minute": ("KYVON_RATE_LIMIT_API", 300, 1, 100_000),
}

_FLAGS: dict[str, tuple[str, bool]] = {
    "auto_title_llm": ("KYVON_AUTO_TITLE_LLM", True),
    "scheduler_enabled": ("KYVON_SCHEDULER", True),
    "hermes_allow_remote": ("KYVON_HERMES_ALLOW_REMOTE", False),
}

_STRINGS: dict[str, tuple[str, str]] = {
    "model": ("KYVON_MODEL", DEFAULT_MODEL),
    "web_model": ("KYVON_WEB_MODEL", DEFAULT_WEB_MODEL),
    "host": ("KYVON_HOST", "0.0.0.0"),
    "public_url": ("KYVON_PUBLIC_URL", "http://localhost:8080"),
    "encryption_key": ("KYVON_ENCRYPTION_KEY", ""),
    "google_client_id": ("GOOGLE_CLIENT_ID", ""),
    "google_client_secret": ("GOOGLE_CLIENT_SECRET", ""),
    "hermes_url": ("KYVON_HERMES_URL", ""),
    "hermes_api_key": ("KYVON_HERMES_API_KEY", ""),
    "hermes_model": ("KYVON_HERMES_MODEL", "hermes"),
    "logseq_dir": ("KYVON_LOGSEQ_DIR", ""),
    "vapid_public_key": ("KYVON_VAPID_PUBLIC_KEY", ""),
    "vapid_private_key": ("KYVON_VAPID_PRIVATE_KEY", ""),
    "vapid_subject": ("KYVON_VAPID_SUBJECT", ""),
}

_TRUE = ("1", "true", "yes", "on")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    model: str = DEFAULT_MODEL
    web_model: str = DEFAULT_WEB_MODEL
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    database_url: str = ""
    token_ttl_days: int = 30
    cookie_secure: bool = False

    # Conversation context (Phase 2)
    context_max_tokens: int = 6000
    context_max_messages: int = 40
    context_reserve_tokens: int = 1500
    summary_trigger_messages: int = 30
    auto_title_llm: bool = True

    # Memory (Phase 3)
    memory_max: int = 2000
    memory_retrieval_k: int = 8

    # Tools (Phase 4)
    tool_timeout_seconds: int = 30
    tool_max_iterations: int = 5
    confirmation_ttl_minutes: int = 60

    # Integrations (secrets are never printed; see __repr__)
    public_url: str = "http://localhost:8080"  # how the browser reaches KYVON (OAuth redirects)
    encryption_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""

    # Hermes (Phase 7, optional): an OpenAI-compatible endpoint used as an agent backend
    hermes_url: str = ""
    hermes_api_key: str = ""
    hermes_model: str = "hermes"
    hermes_allow_remote: bool = False
    hermes_timeout_seconds: int = 90

    # Web Push (optional): VAPID keys from `flask --app wsgi kyvon generate-vapid-keys`
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""  # mailto: or https: contact, required by push services

    # Logseq (Phase 8, optional): path of a Logseq graph folder
    logseq_dir: str = ""

    # Automation (Phase 9)
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 30
    automation_max_per_user: int = 50

    # Agents (Phase 6)
    agent_max_depth: int = (
        1  # how deep agents may call agents (1: only the main assistant delegates)
    )
    agent_timeout_cap_seconds: int = 150
    agent_max_tool_calls: int = 12
    agent_max_concurrent: int = 2

    # Requests and abuse limits
    llm_timeout_seconds: int = 60
    max_request_bytes: int = 1_000_000
    rate_limit_chat_per_minute: int = 30
    rate_limit_api_per_minute: int = 300

    # Derived paths (same file names the prototype used).
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

    @property
    def push_configured(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key and self.vapid_subject)

    @property
    def calendar_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.encryption_key)

    def __repr__(self) -> str:
        # Never print secrets, even by accident.
        return (
            f"Settings(env={self.env!r}, model={self.model!r}, web_model={self.web_model!r}, "
            f"host={self.host!r}, port={self.port}, data_dir={str(self.data_dir)!r}, "
            "groq_api_key='***')"
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

        log_level = get("LOG_LEVEL", "INFO").upper()
        if log_level not in VALID_LOG_LEVELS:
            raise ConfigError(f"LOG_LEVEL must be one of {', '.join(VALID_LOG_LEVELS)}.")

        api_key = get("GROQ_API_KEY")
        if require_api_key and not api_key:
            raise ConfigError(
                "GROQ_API_KEY was not found. "
                "Set it in the environment or in a .env file (see .env.example)."
            )

        values: dict = {}
        for field, (name, default, low, high) in _INTS.items():
            raw = get(name, str(default))
            try:
                number = int(raw)
            except ValueError as error:
                raise ConfigError(f"{name} must be an integer.") from error
            if not low <= number <= high:
                raise ConfigError(f"{name} must be between {low} and {high}.")
            values[field] = number

        for field, (name, default) in _FLAGS.items():
            values[field] = get(name, "true" if default else "false").lower() in _TRUE

        for field, (name, default) in _STRINGS.items():
            values[field] = get(name, default)

        # Cookies default to Secure in production (HTTPS is terminated by the
        # Cloudflare Tunnel, so this is a setting rather than request.is_secure).
        secure_default = "true" if env == "production" else "false"
        cookie_secure = get("KYVON_COOKIE_SECURE", secure_default).lower() in _TRUE

        return cls(
            groq_api_key=api_key,
            env=env,
            log_level=log_level,
            data_dir=Path(get("KYVON_DATA_DIR", "data")),
            database_url=get("DATABASE_URL"),
            cookie_secure=cookie_secure,
            **values,
        )
