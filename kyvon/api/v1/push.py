"""Push notification subscriptions (Web Push now; APNs device tokens for the iOS app)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.schemas import ApnsRegister, PushSubscribe, PushUnsubscribe
from kyvon.services import push_service

bp = Blueprint("push", __name__, url_prefix="/api/v1/push")


@bp.get("/public-key")
@login_required
def public_key():
    settings = services().settings
    if not settings.push_configured:
        return jsonify({"configured": False})
    return jsonify({"configured": True, "public_key": settings.vapid_public_key})


@bp.post("/subscribe")
@login_required
def subscribe():
    body = parse_json(PushSubscribe)
    push_service.subscribe_web(
        get_session(), g.user.id, body.endpoint, body.keys, request.headers.get("User-Agent", "")
    )
    return jsonify({"ok": True}), 201


@bp.delete("/subscribe")
@login_required
def unsubscribe():
    body = parse_json(PushUnsubscribe)
    return jsonify({"removed": push_service.unsubscribe(get_session(), g.user.id, body.endpoint)})


@bp.post("/apns")
@login_required
def register_apns():
    body = parse_json(ApnsRegister)
    push_service.register_apns(
        get_session(), g.user.id, body.device_token, request.headers.get("User-Agent", "")
    )
    return jsonify({"ok": True}), 201
