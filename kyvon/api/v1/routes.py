"""Version 1 API routes."""

from __future__ import annotations

import traceback

from flask import Blueprint, jsonify, request

from kyvon.api.deps import parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import ChatRequest, EnvironmentRequest
from kyvon.services.chat_service import ChatInputError, ChatService
from kyvon.services.status_service import overall_ok, run_diagnostics

bp = Blueprint("v1", __name__, url_prefix="/api/v1")


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.get("/status")
def status():
    svc = services()
    deep = request.args.get("deep", "").lower() in ("1", "true", "yes")
    results = run_diagnostics(
        memory_count=lambda: len(svc.memory_store),
        llm=svc.llm,
        model=svc.settings.model,
        deep=deep,
    )
    return jsonify({"online": overall_ok(results), "diagnostics": results})


@bp.get("/memories")
def list_memories():
    return jsonify({"memories": services().memory_store.all()})


@bp.post("/environment")
def environment():
    svc = services()
    body = parse_json(EnvironmentRequest)
    try:
        return jsonify(svc.environment.get_environment(body.latitude, body.longitude))
    except Exception as error:
        svc.error_log.log("Environment Error", str(error), traceback.format_exc())
        raise ApiError(500, "environment_unavailable", str(error)) from error


@bp.post("/chat")
def chat():
    svc = services()
    body = parse_json(ChatRequest)
    service = ChatService(
        svc.llm,
        svc.memory_store,
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
