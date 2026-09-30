import importlib
import sys
from types import SimpleNamespace

import pytest


class FakeCompletions:
    """Stands in for groq.Groq().chat.completions; records every call."""

    def __init__(self):
        self.calls = []
        self.reply = "fake reply"
        self.error = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = SimpleNamespace(content=f"  {self.reply}  ")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def prototype(tmp_path, monkeypatch):
    """Import the legacy app.py in an isolated cwd with a fake Groq client."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    sys.modules.pop("app", None)
    module = importlib.import_module("app")

    completions = FakeCompletions()
    module.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    module.completions = completions
    yield module
    sys.modules.pop("app", None)


@pytest.fixture
def legacy_client(prototype):
    return prototype.app.test_client()


# ---------------------------------------------------------------- new app factory


@pytest.fixture
def settings(tmp_path):
    from kyvon.config import Settings

    return Settings.from_env({"GROQ_API_KEY": "test-key", "KYVON_DATA_DIR": str(tmp_path / "data")})


@pytest.fixture
def fake_llm():
    from tests.fakes import FakeLLM

    return FakeLLM()


TEST_USERNAME = "owner"
TEST_PASSWORD = "correct horse battery"  # test-only value


def make_app(settings, **kwargs):
    """Build an app with an empty, schema-initialised database."""
    from kyvon import create_app
    from kyvon.db import Base

    app = create_app(settings, **kwargs)
    Base.metadata.create_all(app.extensions["kyvon"].engine)
    return app


@pytest.fixture
def app(settings, fake_llm):
    return make_app(settings, llm=fake_llm)


@pytest.fixture
def owner(app):
    from kyvon.services import auth_service

    with app.extensions["kyvon"].session_factory() as session:
        return auth_service.create_owner(session, TEST_USERNAME, TEST_PASSWORD)


@pytest.fixture
def anon_client(app):
    return app.test_client()


@pytest.fixture
def client(app, owner):
    """A test client logged in with a bearer token."""
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {response.get_json()['token']}"
    return client
