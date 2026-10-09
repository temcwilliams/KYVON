"""Database plumbing: declarative base, UTC datetime type, engine and sessions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Stores datetimes as UTC and always returns timezone-aware UTC values.

    SQLite has no timezone support, so values are stored naive-UTC and the
    timezone is re-attached on the way out. Naive inputs are rejected so a
    local-time value can never be stored by accident.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime given; use timezone-aware UTC datetimes.")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url)
    else:
        # A server database (Postgres): a bounded pool, and a liveness check before each use so a
        # restarted database or an idle-closed connection does not surface as a user-visible error.
        engine = create_engine(
            url, pool_size=10, max_overflow=20, pool_recycle=1800, pool_pre_ping=True
        )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if engine.url.database not in (None, "", ":memory:"):
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def alembic_config(url: str):
    from pathlib import Path

    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade_database(url: str, revision: str = "head") -> None:
    """Apply Alembic migrations to ``url``."""
    from alembic import command

    command.upgrade(alembic_config(url), revision)
