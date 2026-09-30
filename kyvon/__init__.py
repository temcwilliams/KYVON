"""KYVON assistant backend package."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from flask import Flask, request, send_from_directory
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from kyvon.api.deps import close_session
from kyvon.api.errors import register_error_handlers
from kyvon.config import Settings
from kyvon.db import make_engine, make_session_factory
from kyvon.llm.base import LLMClient
from kyvon.llm.groq_client import GroqClient
from kyvon.services.environment_service import EnvironmentService
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
    app.extensions["kyvon"] = Services(
        settings=settings,
        llm=llm or GroqClient(settings.groq_api_key),
        environment=environment or EnvironmentService(error_log),
        error_log=error_log,
        engine=engine,
        session_factory=make_session_factory(engine),
        login_throttle=FailureThrottle(),
    )

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

    from kyvon.api.v1.auth import bp as auth_bp
    from kyvon.api.v1.routes import bp as v1_bp
    from kyvon.cli import cli

    app.register_blueprint(v1_bp)
    app.register_blueprint(auth_bp)
    app.cli.add_command(cli)
    return app
