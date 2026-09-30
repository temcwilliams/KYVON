"""KYVON assistant backend package."""

from __future__ import annotations

import atexit
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, g, request, send_from_directory
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
from kyvon.integrations.speech import GroqWhisper
from kyvon.llm.base import LLMClient
from kyvon.llm.groq_client import GroqClient
from kyvon.logging_setup import configure_logging, request_id_var, user_id_var
from kyvon.pwa import render_service_worker
from kyvon.services.environment_context import EnvironmentCache
from kyvon.services.environment_service import EnvironmentService
from kyvon.services.observability import record_error
from kyvon.services.push_service import build_push
from kyvon.tools import build_registry
from kyvon.tools.executor import ToolExecutor
from kyvon.tools.registry import ToolRegistry
from kyvon.utils.error_log import ErrorLog
from kyvon.utils.rate_limit import FailureThrottle

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
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
    stt: Any = None  # SpeechToText | None
    agent_service: Any = None


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    environment: EnvironmentService | None = None,
    stt: Any = None,
) -> Flask:
    """Application factory. ``llm`` / ``environment`` can be replaced in tests."""
    settings = settings or Settings.from_env(load_dotenv_file=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level, json_format=settings.log_json)

    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
    app.logger.setLevel(settings.log_level)
    # Uploads (voice) may exceed the JSON limit; JSON bodies are checked separately.
    app.config["MAX_CONTENT_LENGTH"] = (
        max(settings.max_request_bytes, settings.max_audio_bytes) + 65536
    )
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
    container.push = build_push(settings, container.http)
    container.stt = stt or (
        GroqWhisper(settings.groq_api_key, settings.stt_model) if settings.groq_api_key else None
    )
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

    def persist_error(kind: str, message: str, details: str) -> None:
        with container.session_factory() as session:
            record_error(
                session,
                kind,
                message,
                details,
                request_id=request_id_var.get(),
                user_id=user_id_var.get(),
            )

    error_log.sink = persist_error  # errors are also kept in the database for the admin view

    register_error_handlers(app)
    app.teardown_appcontext(close_session)

    @app.before_request
    def _start_request():
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:16]
        g.request_id = rid
        g.started = time.perf_counter()
        request_id_var.set(rid)
        user_id_var.set(None)

    @app.teardown_request
    def _end_request(_exception=None):
        request_id_var.set(None)
        user_id_var.set(None)

    access_log = logging.getLogger("kyvon.access")

    @app.after_request
    def _security_headers(response):
        rid = getattr(g, "request_id", None)
        if rid:
            response.headers["X-Request-ID"] = rid
            if not request.path.startswith("/static/") and request.path != "/api/v1/health":
                # Method, path, status and timing only: never bodies, queries or headers.
                access_log.info(
                    "%s %s -> %s",
                    request.method,
                    request.path,
                    response.status_code,
                    extra={
                        "status": response.status_code,
                        "duration_ms": round((time.perf_counter() - g.started) * 1000, 1),
                    },
                )
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

    @app.get("/manifest.webmanifest")
    def manifest():
        response = send_from_directory(
            WEB_DIR, "manifest.webmanifest", mimetype="application/manifest+json"
        )
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/sw.js")
    def service_worker():
        """Served from the root so its scope covers the whole app; never cached by the browser."""
        response = Response(render_service_worker(), mimetype="text/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    from kyvon.api.v1.admin import bp as admin_bp
    from kyvon.api.v1.agents import bp as agents_bp
    from kyvon.api.v1.auth import bp as auth_bp
    from kyvon.api.v1.automations import bp as automations_bp
    from kyvon.api.v1.calendar import bp as calendar_bp
    from kyvon.api.v1.chat import bp as chat_bp
    from kyvon.api.v1.conversations import bp as conversations_bp
    from kyvon.api.v1.integrations import bp as integrations_bp
    from kyvon.api.v1.logseq import bp as logseq_bp
    from kyvon.api.v1.memories import bp as memories_bp
    from kyvon.api.v1.push import bp as push_bp
    from kyvon.api.v1.routes import bp as v1_bp
    from kyvon.api.v1.settings import bp as settings_bp
    from kyvon.api.v1.tasks import bp as tasks_bp
    from kyvon.api.v1.tools import bp as tools_bp
    from kyvon.api.v1.voice import bp as voice_bp
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
    app.register_blueprint(settings_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(voice_bp)
    app.register_blueprint(admin_bp)
    app.cli.add_command(cli)
    return app
