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
def client(prototype):
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


@pytest.fixture
def app(settings, fake_llm):
    from kyvon import create_app

    return create_app(settings, llm=fake_llm)
