"""KYVON assistant backend package."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from flask import Flask, request, send_from_directory
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from kyvon.agents.runner import AgentRunner
from kyvon.agents.service import AgentService
from kyvon.api.deps import close_session
from kyvon.api.errors import register_error_handlers
from kyvon.automation.runner import AutomationRunner
from kyvon.automation.scheduler import Scheduler
from kyvon.config import Settings
from kyvon.db import make_engine, make_session_factory
from kyvon.integrations.hermes import build_hermes
from kyvon.integrations.logseq import build_graph
from kyvon.llm.base import LLMClient
from kyvon.llm.groq_client import GroqClient
from kyvon.services.environment_context import EnvironmentCache
from kyvon.services.environment_service import EnvironmentService
from kyvon.tools import build_registry
from kyvon.tools.executor import ToolExecutor
from kyvon.tools.registry import ToolRegistry
from kyvon.utils.error_log import ErrorLog
from kyvon.utils.rate_limit import FailureThrottle

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# The web client uses only same-origin scripts, styles and requests.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
)


@dataclass
class Services:
    settings: Settings
    llm: LLMClient
    environment: EnvironmentService
    error_log: ErrorLog
    engine: Engine
    session_factory: sessionmaker[Session]
    login_throttle: FailureThrottle
    environment_cache: EnvironmentCache
    registry: ToolRegistry
    executor: ToolExecutor | None = None
    http: Any = None  # requests.Session-like; replaced by a fake in tests
    agent_runner: Any = None
    hermes: Any = None  # HermesBackend | None (optional)
    logseq: Any = None  # KnowledgeBase | None (optional)
    automation_runner: Any = None
    scheduler: Any = None
    push: Any = None  # web/native push sender (Phase 11), optional
    agent_service: Any = None


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    environment: EnvironmentService | None = None,
) -> Flask:
    """Application factory. ``llm`` / ``environment`` can be replaced in tests."""
    settings = settings or Settings.from_env(load_dotenv_file=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
    app.logger.setLevel(settings.log_level)
    error_log = ErrorLog(settings.error_log)
    engine = make_engine(settings.db_url)
    container = Services(
        settings=settings,
        llm=llm or GroqClient(settings.groq_api_key, timeout=settings.llm_timeout_seconds),
        environment=environment or EnvironmentService(error_log),
        error_log=error_log,
        engine=engine,
        session_factory=make_session_factory(engine),
        login_throttle=FailureThrottle(),
        environment_cache=EnvironmentCache(),
        registry=build_registry(),
        http=requests.Session(),
    )
    container.hermes = build_hermes(settings, container.http)
    container.logseq = build_graph(settings.logseq_dir)
    container.executor = ToolExecutor(container.registry, container)
    container.agent_runner = AgentRunner(container)
    container.automation_runner = AutomationRunner(container)
    container.scheduler = Scheduler(container, tick_seconds=settings.scheduler_tick_seconds)
    container.agent_service = AgentService(container)
    with container.session_factory() as startup_session:
        try:
            container.agent_service.recover_orphans(startup_session)
        except Exception:  # the database may not be migrated yet (e.g. running db-upgrade)
            startup_session.rollback()
    app.extensions["kyvon"] = container
    if settings.scheduler_enabled and settings.env != "testing":
        container.scheduler.start()
        atexit.register(container.scheduler.stop)

    register_error_handlers(app)
    app.teardown_appcontext(close_session)

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    from kyvon.api.v1.agents import bp as agents_bp
    from kyvon.api.v1.auth import bp as auth_bp
    from kyvon.api.v1.automations import bp as automations_bp
    from kyvon.api.v1.calendar import bp as calendar_bp
    from kyvon.api.v1.chat import bp as chat_bp
    from kyvon.api.v1.conversations import bp as conversations_bp
    from kyvon.api.v1.integrations import bp as integrations_bp
    from kyvon.api.v1.logseq import bp as logseq_bp
    from kyvon.api.v1.memories import bp as memories_bp
    from kyvon.api.v1.routes import bp as v1_bp
    from kyvon.api.v1.tasks import bp as tasks_bp
    from kyvon.api.v1.tools import bp as tools_bp
    from kyvon.cli import cli

    app.register_blueprint(v1_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(memories_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(logseq_bp)
    app.register_blueprint(automations_bp)
    app.cli.add_command(cli)
    return app
