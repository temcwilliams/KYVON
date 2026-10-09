from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from kyvon.db import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"
    # A unique *index* (not a table constraint): the migration can add it without rebuilding the
    # table, and rebuilding `users` on SQLite would cascade-delete every user's data.
    __table_args__ = (Index("ix_users_email", "email", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    # Hosted-service accounts. Personal mode leaves email empty and the owner is an admin.
    email: Mapped[str | None] = mapped_column(String(254), default=None)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | admin
    disabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    terms_version: Mapped[str | None] = mapped_column(String(16), default=None)

    tokens: Mapped[list[ApiToken]] = relationship(back_populates="user")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class ApiToken(Base):
    """A per-device login. Only the SHA-256 of the token is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    user: Mapped[User] = relationship(back_populates="tokens")


class EmailToken(Base):
    """A single-use link token (email verification or password reset). Only its hash is stored."""

    __tablename__ = "email_tokens"
    __table_args__ = (Index("ix_email_tokens_user_purpose", "user_id", "purpose"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16))  # verify | reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
