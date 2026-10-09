"""Authentication: password hashing, per-device bearer tokens, and hosted-service accounts.

Tokens are random 256-bit values. Only their SHA-256 is stored, so a database
leak does not reveal usable tokens. The same goes for email verification and
password reset links.

Personal installs have one owner (``create_owner``); a hosted service creates many accounts
with ``signup`` (email + password, verified by a link).
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
from kyvon.models import ApiToken, EmailToken, User

MIN_PASSWORD_LENGTH = 10
TOKEN_PREFIX = "kyv_"
LAST_USED_GRANULARITY = timedelta(minutes=1)
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{1,64}$")
_EMAIL_RE = re.compile(r"^[^@\s<>\"',;:()\\]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
MAX_PASSWORD_LENGTH = 1024

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
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AuthError("That password is too long.")


def burn_hash(password: str) -> None:
    """Spend the time a real password hash costs, so 'already registered' is not detectable by timing."""
    generate_password_hash(password or "")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    """The cleaned address, or AuthError. Rejects anything that could inject mail headers."""
    cleaned = normalize_email(email)
    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise AuthError("Enter a valid email address.")
    return cleaned


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
    user = User(username=username, password_hash=generate_password_hash(password), role="admin")
    session.add(user)
    session.commit()
    return user


def _free_username(session: Session, email: str) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower())[:40] or "user"
    candidate = base
    while session.scalar(select(User.id).where(User.username == candidate)) is not None:
        candidate = f"{base}{secrets.randbelow(100000)}"
    return candidate


def create_user(
    session: Session,
    *,
    email: str,
    password: str,
    role: str = "user",
    verified: bool = False,
    terms_version: str | None = None,
    now: Callable[[], datetime] = utcnow,
) -> User:
    """Create a hosted-service account. Raises AuthError if the email is invalid or taken."""
    email = validate_email(email)
    validate_password(password)
    if role not in ("user", "admin"):
        raise AuthError("Unknown role.")
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise AuthError("That email is already registered.")
    current = now()
    user = User(
        username=_free_username(session, email),
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
        email_verified_at=current if verified else None,
        terms_accepted_at=current if terms_version else None,
        terms_version=terms_version,
    )
    session.add(user)
    session.commit()
    return user


def find_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == normalize_email(email)))


def find_user(session: Session, ident: str | None) -> User | None:
    """The user named by a username or email; with no name, the only user (personal mode)."""
    if ident:
        key = normalize_username(ident)
        return session.scalar(select(User).where(User.username == key)) or find_by_email(
            session, key
        )
    users = list(session.scalars(select(User).limit(2)))
    return users[0] if len(users) == 1 else None


# ------------------------------------------------------------- email tokens


def issue_email_token(
    session: Session,
    user: User,
    purpose: str,
    *,
    ttl: timedelta,
    now: Callable[[], datetime] = utcnow,
) -> str:
    """A new single-use token for ``purpose`` (verify | reset). Older unused ones stop working."""
    current = now()
    for old in session.scalars(
        select(EmailToken).where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
    ):
        old.used_at = current
    raw = secrets.token_urlsafe(32)
    session.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            created_at=current,
            expires_at=current + ttl,
        )
    )
    session.commit()
    return raw


def consume_email_token(
    session: Session, raw: str, purpose: str, *, now: Callable[[], datetime] = utcnow
) -> User | None:
    """Use a token once. Returns its user, or None if it is unknown, expired, used or wrong kind."""
    if not raw:
        return None
    row = session.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(raw)))
    current = now()
    if (
        row is None
        or row.purpose != purpose
        or row.used_at is not None
        or row.expires_at <= current
    ):
        return None
    row.used_at = current
    user = session.get(User, row.user_id)
    session.commit()
    return user


def verify_email(
    session: Session, raw: str, *, now: Callable[[], datetime] = utcnow
) -> User | None:
    user = consume_email_token(session, raw, "verify", now=now)
    if user is not None and user.email_verified_at is None:
        user.email_verified_at = now()
        session.commit()
    return user


def reset_password(
    session: Session, raw: str, new_password: str, *, now: Callable[[], datetime] = utcnow
) -> User | None:
    """Set a new password from a reset link and sign every device out."""
    validate_password(new_password)
    user = consume_email_token(session, raw, "reset", now=now)
    if user is None:
        return None
    user.password_hash = generate_password_hash(new_password)
    # Proof of control of the mailbox also proves the address.
    if user.email_verified_at is None:
        user.email_verified_at = now()
    session.commit()
    revoke_all_tokens(session, user.id, now=now)
    return user


def change_password(session: Session, user: User, current: str, new: str) -> None:
    if not check_password_hash(user.password_hash, current or ""):
        raise AuthError("Your current password is not right.")
    validate_password(new)
    user.password_hash = generate_password_hash(new)
    session.commit()


def set_password(session: Session, username: str, password: str) -> User:
    validate_password(password)
    ident = normalize_username(username)
    user = session.scalar(select(User).where(User.username == ident))
    if user is None and "@" in ident:
        user = find_by_email(session, ident)
    if user is None:
        raise AuthError("No such user.")
    user.password_hash = generate_password_hash(password)
    session.commit()
    return user


def verify_login(session: Session, username: str, password: str) -> User | None:
    """Sign in with a username or, for hosted accounts, an email address."""
    ident = (username or "").strip().lower()
    user = session.scalar(select(User).where(User.username == ident))
    if user is None and "@" in ident:
        user = session.scalar(select(User).where(User.email == ident))
    if user is None:
        check_password_hash(_DUMMY_HASH, password or "")
        return None
    if not check_password_hash(user.password_hash, password or ""):
        return None
    return None if user.disabled_at is not None else user


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
