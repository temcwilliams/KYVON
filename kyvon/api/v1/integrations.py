"""Status of optional integrations."""

from __future__ import annotations

from flask import Blueprint, jsonify

from kyvon.api.deps import login_required, services

bp = Blueprint("integrations", __name__, url_prefix="/api/v1/integrations")


@bp.get("/hermes")
@login_required
def hermes_status():
    hermes = services().hermes
    if hermes is None:
        return jsonify({"configured": False, "reachable": False})
    # Never returns the URL or key: only whether it works.
    return jsonify(hermes.health())
