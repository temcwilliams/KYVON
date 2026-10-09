"""Login, logout and device-token management."""

from __future__ import annotations

import secrets

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import (
    CSRF_COOKIE,
    TOKEN_COOKIE,
    get_session,
    login_required,
    parse_json,
    services,
)
from kyvon.api.errors import ApiError
from kyvon.api.schemas import LoginRequest
from kyvon.services import auth_service

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


def _throttle_key(username: str) -> str:
    return f"{request.remote_addr}|{auth_service.normalize_username(username)}"


def _user_json(user) -> dict:
    return {"id": user.id, "username": user.username}


def _set_auth_cookies(response, raw_token: str, max_age: int) -> None:
    secure = services().settings.cookie_secure
    response.set_cookie(
        TOKEN_COOKIE, raw_token, max_age=max_age, httponly=True, secure=secure, samesite="Strict"
    )
    # Readable by the page's JavaScript on purpose: it is echoed back in a header.
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(24),
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="Strict",
    )


def _clear_auth_cookies(response) -> None:
    response.delete_cookie(TOKEN_COOKIE)
    response.delete_cookie(CSRF_COOKIE)


@bp.post("/login")
def login():
    svc = services()
    body = parse_json(LoginRequest)
    key = _throttle_key(body.username)

    if svc.login_throttle.blocked(key):
        raise ApiError(429, "too_many_attempts", "Too many failed attempts. Try again later.")

    session = get_session()
    user = auth_service.verify_login(session, body.username, body.password)
    if user is None:
        svc.login_throttle.record_failure(key)
        raise ApiError(401, "invalid_credentials", "Invalid username or password.")
    svc.login_throttle.reset(key)

    ttl_days = svc.settings.token_ttl_days
    raw, token = auth_service.issue_token(
        session,
        user,
        name=body.device_name or ("Web browser" if body.cookie else "API client"),
        ttl_days=ttl_days,
    )

    payload = {"user": _user_json(user), "expires_at": token.expires_at.isoformat()}
    if not body.cookie:
        payload["token"] = raw
    response = jsonify(payload)
    if body.cookie:
        _set_auth_cookies(response, raw, ttl_days * 86400)
    return response


@bp.post("/logout")
@login_required
def logout():
    auth_service.revoke_token(get_session(), g.user.id, g.token.id)
    response = jsonify({"ok": True})
    _clear_auth_cookies(response)
    return response


@bp.get("/me")
@login_required
def me():
    return jsonify({"user": _user_json(g.user)})


@bp.get("/tokens")
@login_required
def tokens():
    rows = auth_service.list_tokens(get_session(), g.user.id)
    return jsonify(
        {
            "tokens": [
                {
                    "id": t.id,
                    "name": t.name,
                    "created_at": t.created_at.isoformat(),
                    "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                    "expires_at": t.expires_at.isoformat(),
                    "current": t.id == g.token.id,
                }
                for t in rows
            ]
        }
    )


@bp.delete("/tokens/<int:token_id>")
@login_required
def revoke(token_id: int):
    if not auth_service.revoke_token(get_session(), g.user.id, token_id):
        raise ApiError(404, "not_found", "No such token.")
    return jsonify({"ok": True})
