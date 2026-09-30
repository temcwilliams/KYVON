import json

import pytest
from sqlalchemy import select

from kyvon.models import ApiToken, Memory, User
from kyvon.services import auth_service
from tests.conftest import TEST_PASSWORD, TEST_USERNAME, make_app


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


def run(runner, *args, input=None):
    return runner.invoke(args=["kyvon", *args], input=input)


def test_db_upgrade_creates_schema(settings, fake_llm):
    from kyvon import create_app

    app = create_app(settings, llm=fake_llm)  # no create_all: use real migrations
    result = app.test_cli_runner().invoke(args=["kyvon", "db-upgrade"])
    assert result.exit_code == 0, result.output
    with app.extensions["kyvon"].session_factory() as s:
        assert s.scalars(select(User)).all() == []


def test_create_user_via_stdin(runner, app):
    result = run(
        runner, "create-user", "--username", "Boss", "--password-stdin", input=TEST_PASSWORD
    )
    assert result.exit_code == 0, result.output
    assert TEST_PASSWORD not in result.output
    with app.extensions["kyvon"].session_factory() as s:
        assert s.scalar(select(User.username)) == "boss"


def test_create_user_prompts_with_confirmation(runner, app):
    result = run(
        runner, "create-user", "--username", "boss", input=f"{TEST_PASSWORD}\n{TEST_PASSWORD}\n"
    )
    assert result.exit_code == 0, result.output


def test_create_user_rejects_weak_password(runner):
    result = run(runner, "create-user", "--username", "boss", "--password-stdin", input="short")
    assert result.exit_code != 0 and "at least" in result.output


def test_second_user_refused(runner, owner):
    result = run(
        runner, "create-user", "--username", "two", "--password-stdin", input=TEST_PASSWORD
    )
    assert result.exit_code != 0 and "single-user" in result.output


def test_set_password_revokes_devices(runner, app, owner, client):
    result = run(
        runner,
        "set-password",
        "--username",
        TEST_USERNAME,
        "--password-stdin",
        input="a brand new password",
    )
    assert result.exit_code == 0, result.output
    assert client.get("/api/v1/memories").status_code == 401
    with app.extensions["kyvon"].session_factory() as s:
        assert auth_service.verify_login(s, TEST_USERNAME, "a brand new password")


def test_revoke_tokens(runner, owner, client):
    result = run(runner, "revoke-tokens")
    assert "Revoked 1 token" in result.output
    assert client.get("/api/v1/memories").status_code == 401


def test_revoke_tokens_without_owner(runner):
    assert run(runner, "revoke-tokens").exit_code != 0


def test_import_memories_command(runner, app, owner, settings):
    settings.memory_file.write_text(
        json.dumps([{"date": "2026-03-01T10:00:00", "memory": "from prototype"}])
    )
    before = settings.memory_file.read_bytes()
    result = run(runner, "import-memories")
    assert result.exit_code == 0, result.output
    assert "Imported 1 memories" in result.output
    assert settings.memory_file.read_bytes() == before
    with app.extensions["kyvon"].session_factory() as s:
        assert s.scalar(select(Memory.content)) == "from prototype"
    assert "Imported 0 memories (1 skipped)" in run(runner, "import-memories").output


def test_import_requires_owner(runner, settings):
    settings.memory_file.write_text("[]")
    assert run(runner, "import-memories").exit_code != 0


def test_import_missing_file_is_clean_error(runner, owner):
    result = run(runner, "import-memories")
    assert result.exit_code != 0 and "not found" in result.output


def test_imported_memories_reach_the_prompt(app, client, fake_llm, settings, owner):
    settings.memory_file.write_text(
        json.dumps([{"date": "2026-03-01T10:00:00", "memory": "old fact"}])
    )
    app.test_cli_runner().invoke(args=["kyvon", "import-memories"])
    client.post("/api/v1/chat", json={"message": "hi"})
    assert "- old fact" in fake_llm.calls[0]["messages"][0]["content"]
    assert ApiToken and make_app  # keep imports used
