"""Long-term memory: view, search, add, edit, delete."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from kyvon.api.deps import build_memory_service, login_required, parse_json
from kyvon.api.errors import ApiError
from kyvon.api.schemas import MemoryCreate, MemoryUpdate
from kyvon.services.memory_rules import CATEGORIES
from kyvon.services.memory_service import serialize_memory

bp = Blueprint("memories", __name__, url_prefix="/api/v1/memories")


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except ValueError:
        raise ApiError(400, "invalid_request", f"{name} must be an integer.") from None


@bp.get("")
@login_required
def list_memories():
    service = build_memory_service()
    query = request.args.get("q", "").strip()
    if query:
        hits = service.search(query, _int_arg("limit", 20))
        return jsonify(
            {
                "memories": [serialize_memory(h.memory, score=h.score) for h in hits],
                "total": len(hits),
            }
        )
    rows, total = service.list(
        category=request.args.get("category") or None,
        limit=_int_arg("limit", 100),
        offset=_int_arg("offset", 0),
    )
    return jsonify({"memories": [serialize_memory(m) for m in rows], "total": total})


@bp.get("/categories")
@login_required
def categories():
    return jsonify({"categories": list(CATEGORIES)})


@bp.post("")
@login_required
def create_memory():
    body = parse_json(MemoryCreate)
    result = build_memory_service().add(
        body.text, category=body.category, importance=body.importance, source="user"
    )
    return jsonify({"memory": serialize_memory(result.memory), "duplicate": not result.created}), (
        201 if result.created else 200
    )


@bp.get("/<int:memory_id>")
@login_required
def get_memory(memory_id: int):
    return jsonify({"memory": serialize_memory(build_memory_service().get(memory_id))})


@bp.patch("/<int:memory_id>")
@login_required
def update_memory(memory_id: int):
    body = parse_json(MemoryUpdate)
    memory = build_memory_service().update(
        memory_id, text=body.text, category=body.category, importance=body.importance
    )
    return jsonify({"memory": serialize_memory(memory)})


@bp.delete("/<int:memory_id>")
@login_required
def delete_memory(memory_id: int):
    build_memory_service().delete(memory_id)
    return jsonify({"ok": True})
