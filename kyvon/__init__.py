"""KYVON assistant backend package."""

from __future__ import annotations

from dataclasses import dataclass

from flask import Flask

from kyvon.api.errors import register_error_handlers
from kyvon.config import Settings
from kyvon.llm.base import LLMClient
from kyvon.llm.groq_client import GroqClient
from kyvon.services.environment_service import EnvironmentService
from kyvon.services.memory_service import MemoryStore
from kyvon.utils.error_log import ErrorLog


@dataclass
class Services:
    settings: Settings
    llm: LLMClient
    environment: EnvironmentService
    error_log: ErrorLog
    memory_store: MemoryStore


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    environment: EnvironmentService | None = None,
) -> Flask:
    """Application factory. ``llm`` / ``environment`` can be replaced in tests."""
    settings = settings or Settings.from_env(load_dotenv_file=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    error_log = ErrorLog(settings.error_log)
    app.extensions["kyvon"] = Services(
        settings=settings,
        llm=llm or GroqClient(settings.groq_api_key),
        environment=environment or EnvironmentService(error_log),
        error_log=error_log,
        memory_store=MemoryStore(settings.memory_file),
    )

    register_error_handlers(app)

    from kyvon.api.v1.routes import bp as v1

    app.register_blueprint(v1)
    return app
