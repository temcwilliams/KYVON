from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text

from kyvon.config import Settings
from kyvon.db import Base, UTCDateTime, make_engine, make_session_factory, upgrade_database
from kyvon.models import ApiToken, Memory, User


@pytest.fixture
def migrated_engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'kyvon.db'}"
    upgrade_database(url)
    return make_engine(url)


def test_default_db_url_is_sqlite_in_data_dir():
    s = Settings.from_env({"GROQ_API_KEY": "k", "KYVON_DATA_DIR": "data"})
    assert s.db_url == "sqlite:///data/kyvon.db"


def test_database_url_override():
    s = Settings.from_env({"GROQ_API_KEY": "k", "DATABASE_URL": "sqlite:///x.db"})
    assert s.db_url == "sqlite:///x.db"


def test_migration_creates_expected_tables(migrated_engine):
    tables = set(inspect(migrated_engine).get_table_names())
    assert {"users", "api_tokens", "memories", "conversations", "messages"} <= tables
    assert "alembic_version" in tables


def test_migrations_match_models(migrated_engine):
    """No drift between the ORM models and the migration history."""
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_then_upgrade(tmp_path):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    url = f"sqlite:///{tmp_path / 'k.db'}"
    upgrade_database(url)
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "base")
    assert "users" not in inspect(make_engine(url)).get_table_names()
    upgrade_database(url)
    assert "users" in inspect(make_engine(url)).get_table_names()


def test_sqlite_foreign_keys_enforced(migrated_engine):
    Session = make_session_factory(migrated_engine)
    with Session() as session:
        session.add(Memory(user_id=999, content="orphan"))
        with pytest.raises(Exception, match="FOREIGN KEY"):
            session.commit()


def test_utc_round_trip_and_awareness(migrated_engine):
    Session = make_session_factory(migrated_engine)
    ct = timezone(timedelta(hours=-6))
    with Session() as session:
        user = User(username="me", password_hash="x")
        session.add(user)
        session.flush()
        session.add(
            Memory(user_id=user.id, content="a", created_at=datetime(2026, 1, 1, 12, tzinfo=ct))
        )
        session.commit()
    with Session() as session:
        created = session.scalar(select(Memory.created_at))
        assert created == datetime(2026, 1, 1, 18, tzinfo=UTC)
        assert created.tzinfo is not None
        raw = session.execute(text("select created_at from memories")).scalar()
        assert "18:00:00" in str(raw)  # stored as UTC


def test_naive_datetime_rejected():
    with pytest.raises(ValueError, match="Naive"):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), None)


def test_defaults_are_utc_aware(migrated_engine):
    Session = make_session_factory(migrated_engine)
    with Session() as session:
        user = User(username="me", password_hash="x")
        session.add(user)
        session.commit()
        assert user.created_at.tzinfo is UTC
        assert user.settings == {}


def test_token_hash_unique(migrated_engine):
    Session = make_session_factory(migrated_engine)
    exp = datetime.now(UTC) + timedelta(days=1)
    with Session() as session:
        user = User(username="me", password_hash="x")
        session.add(user)
        session.flush()
        session.add(ApiToken(user_id=user.id, token_hash="h", expires_at=exp))
        session.commit()
        session.add(ApiToken(user_id=user.id, token_hash="h", expires_at=exp))
        with pytest.raises(Exception, match="UNIQUE"):
            session.commit()
