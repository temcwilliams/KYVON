"""Read-only access to the Logseq notes for the web client (writes go through approved tools)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from kyvon.api.deps import login_required, services
from kyvon.api.errors import ApiError

bp = Blueprint("logseq", __name__, url_prefix="/api/v1/logseq")


def _graph():
    graph = services().logseq
    if graph is None:
        raise ApiError(409, "not_connected", "Logseq is not configured on this server.")
    return graph


@bp.get("/status")
@login_required
def status():
    graph = services().logseq
    return jsonify({"configured": graph is not None})


@bp.get("/search")
@login_required
def search():
    try:
        limit = int(request.args.get("limit") or 10)
    except ValueError:
        raise ApiError(400, "invalid_request", "limit must be an integer.") from None
    hits = _graph().search(request.args.get("q", ""), limit)
    return jsonify({"hits": [{"page": h.page, "line": h.line, "text": h.snippet} for h in hits]})


@bp.get("/pages")
@login_required
def pages():
    return jsonify({"pages": _graph().list_pages(request.args.get("q") or None)})


@bp.get("/page")
@login_required
def page():
    result = _graph().read_page(request.args.get("name", ""))
    return jsonify(
        {
            "page": {
                "name": result.name,
                "content": result.content,
                "truncated": result.truncated,
                "modified": result.modified,
            }
        }
    )
