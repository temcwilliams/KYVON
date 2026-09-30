"""Single-owner authentication: password hashing and per-device bearer tokens.

Tokens are random 256-bit values. Only their SHA-256 is stored, so a database
leak does not reveal usable tokens.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from kyvon.db import utcnow
from kyvon.models import ApiToken, User

MIN_PASSWORD_LENGTH = 10
TOKEN_PREFIX = "kyv_"
LAST_USED_GRANULARITY = timedelta(minutes=1)
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{1,64}$")

# Verified against when the username is unknown, so login timing does not
# reveal whether an account exists.
_DUMMY_HASH = generate_password_hash("kyvon-dummy-password")


class AuthError(Exception):
    """A user-facing authentication/administration error."""


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ users


def create_owner(session: Session, username: str, password: str) -> User:
    """Create the one owner account. There is no public registration."""
    username = normalize_username(username)
    if not _USERNAME_RE.match(username):
        raise AuthError("Username must be 1-64 characters: letters, digits, '.', '_' or '-'.")
    validate_password(password)
    if session.scalar(select(User.id).limit(1)) is not None:
        raise AuthError("An owner account already exists. KYVON is single-user.")
    user = User(username=username, password_hash=generate_password_hash(password))
    session.add(user)
    session.commit()
    return user


def set_password(session: Session, username: str, password: str) -> User:
    validate_password(password)
    user = session.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        raise AuthError("No such user.")
    user.password_hash = generate_password_hash(password)
    session.commit()
    return user


def verify_login(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        check_password_hash(_DUMMY_HASH, password or "")
        return None
    return user if check_password_hash(user.password_hash, password or "") else None


# ------------------------------------------------------------------ tokens


def issue_token(
    session: Session,
    user: User,
    *,
    name: str,
    ttl_days: int,
    now: Callable[[], datetime] = utcnow,
) -> tuple[str, ApiToken]:
    """Create a device token. The raw value is returned once and never stored."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    current = now()
    token = ApiToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        name=(name or "")[:100],
        created_at=current,
        expires_at=current + timedelta(days=ttl_days),
    )
    session.add(token)
    session.commit()
    return raw, token


def resolve_token(
    session: Session, raw: str, *, now: Callable[[], datetime] = utcnow
) -> ApiToken | None:
    """Return the live token row for ``raw`` (with ``.user``), or None."""
    if not raw:
        return None
    token = session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None:
        return None
    current = now()
    if token.expires_at <= current:
        return None
    if token.last_used_at is None or current - token.last_used_at > LAST_USED_GRANULARITY:
        token.last_used_at = current
        session.commit()
    return token


def list_tokens(session: Session, user_id: int) -> list[ApiToken]:
    return list(
        session.scalars(
            select(ApiToken)
            .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        )
    )


def revoke_token(
    session: Session, user_id: int, token_id: int, *, now: Callable[[], datetime] = utcnow
) -> bool:
    token = session.get(ApiToken, token_id)
    if token is None or token.user_id != user_id or token.revoked_at is not None:
        return False
    token.revoked_at = now()
    session.commit()
    return True


def revoke_all_tokens(
    session: Session, user_id: int, *, now: Callable[[], datetime] = utcnow
) -> int:
    count = 0
    for token in list_tokens(session, user_id):
        token.revoked_at = now()
        count += 1
    session.commit()
    return count
