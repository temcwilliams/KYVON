"""The signed-in person's own account: profile, password, data export and deletion."""

from __future__ import annotations

import json

from flask import Blueprint, Response, g, jsonify

from kyvon.api.deps import get_session, login_required, parse_json, services
from kyvon.api.errors import ApiError
from kyvon.api.schemas import ChangePasswordRequest, DeleteAccountRequest
from kyvon.api.v1.auth import _clear_auth_cookies, user_json
from kyvon.services import account_service, auth_service, email_service, usage_service

bp = Blueprint("account", __name__, url_prefix="/api/v1/account")


@bp.get("")
@login_required
def profile():
    settings = services().settings
    payload = {
        "user": user_json(g.user),
        "created_at": g.user.created_at.isoformat(),
        "hosted": settings.hosted,
    }
    if settings.hosted:
        payload["usage"] = usage_service.summary(get_session(), settings, g.user)
    return jsonify(payload)


@bp.get("/usage")
@login_required
def usage():
    """This month's allowance and what has been used (hosted mode)."""
    settings = services().settings
    if not settings.hosted:
        raise ApiError(404, "not_found", "Not found.")
    return jsonify(usage_service.summary(get_session(), settings, g.user))


@bp.post("/change-password")
@login_required
def change_password():
    body = parse_json(ChangePasswordRequest)
    try:
        auth_service.change_password(
            get_session(), g.user, body.current_password, body.new_password
        )
    except auth_service.AuthError as error:
        raise ApiError(400, "invalid_request", str(error)) from error
    # Sign out every other device; keep this one.
    for token in auth_service.list_tokens(get_session(), g.user.id):
        if token.id != g.token.id:
            auth_service.revoke_token(get_session(), g.user.id, token.id)
    return jsonify({"ok": True})


@bp.get("/export")
@login_required
def export():
    data = account_service.export_user_data(get_session(), g.user)
    response = Response(json.dumps(data, indent=2), mimetype="application/json")
    response.headers["Content-Disposition"] = 'attachment; filename="kyvon-data.json"'
    return response


@bp.delete("")
@login_required
def delete():
    """Permanently delete the account. Needs the password again, so a stolen session cannot do it."""
    svc = services()
    body = parse_json(DeleteAccountRequest)
    session = get_session()
    user = auth_service.verify_login(session, g.user.username, body.password)
    if user is None or user.id != g.user.id:
        raise ApiError(403, "invalid_credentials", "That password is not right.")
    email = user.email
    for hook in svc.account_deletion_hooks:  # e.g. cancel a paid subscription first
        hook(session, user)
    account_service.delete_account(session, user)
    if email:
        email_service.deliver(svc.email, email, email_service.account_deleted_message())
    response = jsonify({"ok": True})
    _clear_auth_cookies(response)
    return response
