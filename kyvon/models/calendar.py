from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kyvon.db import Base, UTCDateTime, utcnow


class CalendarAccount(Base):
    """A connected calendar provider. Tokens are stored encrypted (Fernet)."""

    __tablename__ = "calendar_accounts"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_calendar_user_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16), default="google")
    account_email: Mapped[str] = mapped_column(String(255), default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text, default=None)
    access_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    scopes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class OAuthState(Base):
    """A pending OAuth authorization: single use, short lived, bound to one user."""

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    verifier_enc: Mapped[str] = mapped_column(Text)  # PKCE code verifier
    provider: Mapped[str] = mapped_column(String(16), default="google")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
