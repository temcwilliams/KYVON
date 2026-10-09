"""Login, logout, device tokens, and (hosted mode) sign-up, email verification and password reset."""

from __future__ import annotations

import secrets
from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import (
    CSRF_COOKIE,
    TOKEN_COOKIE,
    enforce_ip_rate,
    get_session,
    login_required,
    parse_json,
    services,
)
from kyvon.api.errors import ApiError
from kyvon.api.schemas import (
    EmailRequest,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenRequest,
)
from kyvon.services import auth_service, email_service

bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


def _throttle_key(username: str) -> str:
    return f"{request.remote_addr}|{auth_service.normalize_username(username)}"


def user_json(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "email_verified": user.email_verified,
        "role": user.role,
    }


_user_json = user_json


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


GENERIC_SIGNUP = {"ok": True, "message": "Check your email to finish creating your account."}
GENERIC_RESET = {
    "ok": True,
    "message": "If that address has an account, we sent a link to reset the password.",
}


def _require_hosted_signup() -> None:
    if not services().settings.signup_enabled:
        raise ApiError(403, "signup_closed", "Sign-up is not open right now.")


def _send_verification(user) -> None:
    svc = services()
    token = auth_service.issue_email_token(
        get_session(),
        user,
        "verify",
        ttl=timedelta(hours=svc.settings.verify_ttl_hours),
    )
    email_service.deliver(
        svc.email, user.email, email_service.verification_message(svc.settings, token)
    )


@bp.post("/signup")
def signup():
    """Create an account. The answer is the same whether or not the address is already taken,
    so this cannot be used to discover who has an account."""
    _require_hosted_signup()
    enforce_ip_rate("signup")
    svc = services()
    body = parse_json(SignupRequest)
    if not body.accept_terms:
        raise ApiError(400, "terms_required", "You need to accept the terms to create an account.")
    try:
        email = auth_service.validate_email(body.email)
        auth_service.validate_password(body.password)
    except auth_service.AuthError as error:
        raise ApiError(400, "invalid_request", str(error)) from error

    session = get_session()
    if auth_service.find_by_email(session, email) is not None:
        auth_service.burn_hash(body.password)  # keep the timing of both outcomes alike
        email_service.deliver(
            svc.email, email, email_service.already_registered_message(svc.settings)
        )
        return jsonify(GENERIC_SIGNUP), 202
    user = auth_service.create_user(
        session, email=email, password=body.password, terms_version=svc.settings.terms_version
    )
    _send_verification(user)
    return jsonify(GENERIC_SIGNUP), 202


@bp.post("/verify-email")
def verify_email():
    enforce_ip_rate("verify")
    user = auth_service.verify_email(get_session(), parse_json(TokenRequest).token)
    if user is None:
        raise ApiError(400, "invalid_token", "That link is invalid or has expired.")
    return jsonify({"ok": True, "email_verified": True})


@bp.post("/resend-verification")
@login_required
def resend_verification():
    if g.user.email is None or g.user.email_verified:
        return jsonify({"ok": True})
    allowed, wait = services().rate_limiter.hit(f"resend:{g.user.id}", 2)
    if not allowed:
        raise ApiError(
            429, "rate_limited", "Please wait before asking again.", {"Retry-After": str(wait)}
        )
    _send_verification(g.user)
    return jsonify({"ok": True})


@bp.post("/forgot-password")
def forgot_password():
    _require_hosted()
    enforce_ip_rate("forgot")
    svc = services()
    body = parse_json(EmailRequest)
    session = get_session()
    user = auth_service.find_by_email(session, body.email)
    if user is not None and user.disabled_at is None:
        token = auth_service.issue_email_token(
            session, user, "reset", ttl=timedelta(minutes=svc.settings.reset_ttl_minutes)
        )
        email_service.deliver(
            svc.email, user.email, email_service.reset_message(svc.settings, token)
        )
    return jsonify(GENERIC_RESET), 202


def _require_hosted() -> None:
    if not services().settings.hosted:
        raise ApiError(404, "not_found", "Not found.")


@bp.post("/reset-password")
def reset_password():
    _require_hosted()
    enforce_ip_rate("reset")
    body = parse_json(ResetPasswordRequest)
    try:
        user = auth_service.reset_password(get_session(), body.token, body.password)
    except auth_service.AuthError as error:
        raise ApiError(400, "invalid_request", str(error)) from error
    if user is None:
        raise ApiError(400, "invalid_token", "That link is invalid or has expired.")
    return jsonify({"ok": True})


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
