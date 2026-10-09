"""Version 1 API routes."""

from __future__ import annotations

import traceback

from flask import Blueprint, g, jsonify, request
from sqlalchemy import text

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import EnvironmentRequest
from kyvon.services.memory_service import MemoryService
from kyvon.services.status_service import overall_ok, run_diagnostics

bp = Blueprint("v1", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.get("/health/ready")
def ready():
    """Readiness for load balancers and monitors: can we reach the database? No details."""
    try:
        with services().session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return jsonify({"status": "unavailable"}), 503
    return jsonify({"status": "ready"})


@bp.get("/config")
def public_config():
    """What the sign-in page needs to know before anyone is signed in. Nothing secret."""
    settings = services().settings
    return jsonify(
        {
            "mode": settings.mode,
            "signup_open": settings.signup_enabled,
            "billing": settings.billing_configured,
            "price_label": settings.price_label if settings.billing_configured else "",
            "terms_version": settings.terms_version,
            "privacy_url": settings.privacy_url,
            "terms_url": settings.terms_url,
        }
    )


@bp.get("/status")
@login_required
def status():
    svc = services()
    deep = request.args.get("deep", "").lower() in ("1", "true", "yes")
    if deep and svc.settings.hosted and not g.user.is_admin:
        deep = False  # a deep check makes a paid model call; not for ordinary hosted accounts
    results = run_diagnostics(
        memory_count=lambda: len(MemoryService(get_session(), g.user.id)),
        llm=svc.llm,
        model=svc.settings.model,
        deep=deep,
    )
    return jsonify({"online": overall_ok(results), "diagnostics": results})


@bp.post("/environment")
@login_required
def environment():
    svc = services()
    body = parse_json(EnvironmentRequest)
    try:
        result = svc.environment.get_environment(body.latitude, body.longitude)
        svc.environment_cache.put(g.user.id, result)
        return jsonify(result)
    except Exception as error:
        svc.error_log.log("Environment Error", str(error), traceback.format_exc())
        raise ApiError(500, "environment_unavailable", str(error)) from error
