"""Chat endpoints: a plain JSON turn and a streaming (Server-Sent Events) turn."""

from __future__ import annotations

import json
import traceback

from flask import Blueprint, Response, g, jsonify, stream_with_context

from kyvon.api.deps import (
    build_chat_service,
    get_session,
    login_required,
    parse_json,
    services,
)
from kyvon.api.errors import ApiError
from kyvon.api.schemas import ChatRequest
from kyvon.services.chat_service import ChatFailed, ChatInputError
from kyvon.services.conversation_service import ConversationService

bp = Blueprint("chat", __name__, url_prefix="/api/v1")


def _sse(event: dict) -> str:
    payload = {k: v for k, v in event.items() if k != "type"}
    return f"event: {event['type']}\ndata: {json.dumps(payload)}\n\n"


@bp.post("/chat")
@login_required
def chat():
    body = parse_json(ChatRequest)
    service = build_chat_service()
    try:
        result = service.reply(body.message, body.conversation_id)
    except ChatFailed as error:
        services().error_log.log("Chat Error", str(error), traceback.format_exc())
        raise ApiError(500, "chat_failed", str(error)) from error
    payload = {
        "conversation": result.conversation,
        "conversation_id": result.conversation["id"],
        "user_message": result.user_message,
        "message": result.message,
        "response": result.message["content"],
    }
    payload.update(result.flags)
    return jsonify(payload)


@bp.post("/chat/stream")
@login_required
def chat_stream():
    body = parse_json(ChatRequest)
    svc = services()
    user_id = g.user.id

    # Validate up front so these are ordinary JSON errors rather than a broken stream.
    if not body.message.strip():
        raise ChatInputError("Empty message.")
    if body.conversation_id is not None:
        ConversationService(get_session(), user_id).get(body.conversation_id)

    def generate():
        # The generator runs after the view returns (in a fresh app context), so it owns
        # its database session instead of using the request's.
        with svc.session_factory() as session:
            turn = build_chat_service(session, user_id).turn(body.message, body.conversation_id)
            try:
                for event in turn:
                    if event["type"] == "error":
                        svc.error_log.log("Chat Error", event["message"], "")
                    yield _sse(event)
            finally:
                # Closing the generator (client disconnect) lets the turn save partial text.
                turn.close()

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response
