"""Access to application services, the DB session and authentication."""

from __future__ import annotations

import hmac
from functools import wraps

from flask import current_app, g, request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kyvon.api.errors import ApiError
from kyvon.services import auth_service

TOKEN_COOKIE = "kyvon_token"
CSRF_COOKIE = "kyvon_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def services():
    return current_app.extensions["kyvon"]


def get_session() -> Session:
    """One SQLAlchemy session per request, closed at teardown."""
    if "db_session" not in g:
        g.db_session = services().session_factory()
    return g.db_session


def close_session(_exception=None) -> None:
    session = g.pop("db_session", None)
    if session is not None:
        session.close()


def parse_json[T: BaseModel](model: type[T]) -> T:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
    return model.model_validate(data)


def _bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def login_required(view):
    """Require a valid device token (Authorization: Bearer, or the web cookie).

    Requests authenticated by cookie must also pass a CSRF check on unsafe
    methods (double-submit token). Bearer requests are not CSRF-prone.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        raw = _bearer_token()
        via = "bearer"
        if raw is None:
            raw = request.cookies.get(TOKEN_COOKIE)
            via = "cookie"

        token = auth_service.resolve_token(get_session(), raw) if raw else None
        if token is None:
            raise ApiError(401, "unauthorized", "Authentication required.")

        if via == "cookie" and request.method not in SAFE_METHODS:
            expected = request.cookies.get(CSRF_COOKIE, "")
            supplied = request.headers.get(CSRF_HEADER, "")
            if not expected or not hmac.compare_digest(expected, supplied):
                raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token.")

        g.token = token
        g.user = token.user
        g.auth_via = via
        return view(*args, **kwargs)

    return wrapper
