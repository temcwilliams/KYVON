"""End to end against a real PostgreSQL server (skipped unless KYVON_TEST_POSTGRES_URL is set).

CI runs this against a Postgres service container. Locally:
    KYVON_TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost/kyvon_test pytest tests/test_postgres.py
The database named there is WIPED, so point it at a scratch database.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from tests.fakes import FakeEmail
from tests.test_hosted_accounts import PASSWORD, hosted_settings

URL = os.environ.get("KYVON_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="KYVON_TEST_POSTGRES_URL is not set")


@pytest.fixture
def pg_app(tmp_path, fake_llm, fake_environment, fake_stt):
    from kyvon import create_app
    from kyvon.db import upgrade_database

    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    upgrade_database(URL)  # the real migrations, from empty, to head
    settings = hosted_settings(tmp_path, DATABASE_URL=URL, KYVON_QUOTA_FREE_MESSAGES="3")
    app = create_app(settings, llm=fake_llm, environment=fake_environment, stt=fake_stt)
    app.extensions["kyvon"].email = FakeEmail()
    yield app
    app.extensions["kyvon"].engine.dispose()


def test_migrations_and_models_agree_on_postgres(pg_app):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from kyvon.db import Base

    with pg_app.extensions["kyvon"].engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_the_whole_hosted_journey_works_on_postgres(pg_app):
    http = pg_app.test_client()
    mail = pg_app.extensions["kyvon"].email
    assert (
        http.post(
            "/api/v1/auth/signup",
            json={"email": "pg@example.com", "password": PASSWORD, "accept_terms": True},
        ).status_code
        == 202
    )
    token = mail.token("pg@example.com", "verify")
    assert http.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    login = http.post(
        "/api/v1/auth/login", json={"username": "pg@example.com", "password": PASSWORD}
    )
    client = pg_app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {login.get_json()['token']}"

    for _ in range(3):  # the free plan allows 3 messages
        assert client.post("/api/v1/chat", json={"message": "hello"}).status_code == 200
    blocked = client.post("/api/v1/chat", json={"message": "hello"})
    assert blocked.status_code == 402  # sums come back as Decimal on Postgres: must still work

    usage = client.get("/api/v1/account/usage").get_json()
    assert usage["used"]["messages"] == 3 and usage["used"]["tokens"] > 0
    assert client.post("/api/v1/tasks", json={"title": "pg task"}).status_code == 201
    export = client.get("/api/v1/account/export").get_json()
    assert export["tasks"][0]["title"] == "pg task" and export["conversations"]

    assert client.delete("/api/v1/account", json={"password": PASSWORD}).status_code == 200
    with pg_app.extensions["kyvon"].engine.connect() as conn:
        for table in (
            "users",
            "conversations",
            "messages",
            "tasks",
            "usage_events",
            "email_tokens",
        ):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table


def test_shared_rate_limits_work_on_postgres(pg_app):
    from kyvon.utils.rate_limit import DbRateLimiter

    factory = pg_app.extensions["kyvon"].session_factory
    a, b = DbRateLimiter(factory), DbRateLimiter(factory)
    assert a.hit("k", 2)[0] and b.hit("k", 2)[0] and not a.hit("k", 2)[0]


def test_two_people_cannot_see_each_others_data_on_postgres(pg_app):
    def person(email):
        http = pg_app.test_client()
        http.post(
            "/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "accept_terms": True}
        )
        http.post(
            "/api/v1/auth/verify-email",
            json={"token": pg_app.extensions["kyvon"].email.token(email, "verify")},
        )
        token = http.post(
            "/api/v1/auth/login", json={"username": email, "password": PASSWORD}
        ).get_json()["token"]
        client = pg_app.test_client()
        client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client

    a, b = person("a@example.com"), person("b@example.com")
    task = a.post("/api/v1/tasks", json={"title": "alpha only"}).get_json()["task"]
    assert b.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert b.get("/api/v1/tasks").get_json()["tasks"] == []
