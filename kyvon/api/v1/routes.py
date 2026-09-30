"""Version 1 API routes."""

from __future__ import annotations

import traceback

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import ChatRequest, EnvironmentRequest
from kyvon.services.chat_service import ChatInputError, ChatService
from kyvon.services.memory_service import MemoryService
from kyvon.services.status_service import overall_ok, run_diagnostics

bp = Blueprint("v1", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.get("/status")
@login_required
def status():
    svc = services()
    deep = request.args.get("deep", "").lower() in ("1", "true", "yes")
    results = run_diagnostics(
        memory_count=lambda: len(MemoryService(get_session(), g.user.id)),
        llm=svc.llm,
        model=svc.settings.model,
        deep=deep,
    )
    return jsonify({"online": overall_ok(results), "diagnostics": results})


@bp.get("/memories")
@login_required
def list_memories():
    return jsonify({"memories": MemoryService(get_session(), g.user.id).all()})


@bp.post("/environment")
@login_required
def environment():
    svc = services()
    body = parse_json(EnvironmentRequest)
    try:
        return jsonify(svc.environment.get_environment(body.latitude, body.longitude))
    except Exception as error:
        svc.error_log.log("Environment Error", str(error), traceback.format_exc())
        raise ApiError(500, "environment_unavailable", str(error)) from error


@bp.post("/chat")
@login_required
def chat():
    svc = services()
    body = parse_json(ChatRequest)
    service = ChatService(
        svc.llm,
        MemoryService(get_session(), g.user.id),
        model=svc.settings.model,
        web_model=svc.settings.web_model,
    )
    try:
        return jsonify(service.reply(body.message, body.environment))
    except ChatInputError as error:
        raise ApiError(400, "invalid_request", str(error)) from error
    except Exception as error:
        svc.error_log.log("Chat Error", str(error), traceback.format_exc())
        raise ApiError(500, "chat_failed", str(error)) from error
