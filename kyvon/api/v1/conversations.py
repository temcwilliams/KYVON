"""Conversation management."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import get_session, login_required, parse_json
from kyvon.api.schemas import ConversationCreate, ConversationUpdate
from kyvon.services.conversation_service import (
    ConversationService,
    serialize_conversation,
    serialize_message,
)

bp = Blueprint("conversations", __name__, url_prefix="/api/v1/conversations")


def _service() -> ConversationService:
    return ConversationService(get_session(), g.user.id)


def _int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        from kyvon.api.errors import ApiError

        raise ApiError(400, "invalid_request", f"{name} must be an integer.") from None


@bp.get("")
@login_required
def list_conversations():
    archived = request.args.get("archived", "").lower() in ("1", "true", "yes")
    service = _service()
    rows = service.list(
        archived=archived, limit=_int_arg("limit", 50), before_id=_int_arg("before_id")
    )
    return jsonify(
        {
            "conversations": [
                serialize_conversation(c, message_count=service.message_count(c.id)) for c in rows
            ]
        }
    )


@bp.post("")
@login_required
def create_conversation():
    body = parse_json(ConversationCreate)
    return jsonify({"conversation": serialize_conversation(_service().create(body.title))}), 201


@bp.get("/<int:conversation_id>")
@login_required
def get_conversation(conversation_id: int):
    service = _service()
    conversation = service.get(conversation_id)
    return jsonify(
        {
            "conversation": serialize_conversation(
                conversation, message_count=service.message_count(conversation.id)
            )
        }
    )


@bp.patch("/<int:conversation_id>")
@login_required
def update_conversation(conversation_id: int):
    body = parse_json(ConversationUpdate)
    service = _service()
    conversation = service.get(conversation_id)
    if body.title is not None:
        conversation = service.rename(conversation_id, body.title)
    if body.archived is not None:
        conversation = service.archive(conversation_id, body.archived)
    return jsonify({"conversation": serialize_conversation(conversation)})


@bp.delete("/<int:conversation_id>")
@login_required
def delete_conversation(conversation_id: int):
    _service().delete(conversation_id)
    return jsonify({"ok": True})


@bp.get("/<int:conversation_id>/messages")
@login_required
def list_messages(conversation_id: int):
    include_tools = request.args.get("include_tools", "").lower() in ("1", "true", "yes")
    kinds = (
        ("message", "event", "tool_call", "tool_result") if include_tools else ("message", "event")
    )
    rows = _service().messages(
        conversation_id,
        kinds=kinds,
        before_id=_int_arg("before_id"),
        after_id=_int_arg("after_id"),
        limit=_int_arg("limit", 100),
    )
    return jsonify({"messages": [serialize_message(m) for m in rows]})
