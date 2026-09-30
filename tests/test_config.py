from pathlib import Path

import pytest

from kyvon.config import ConfigError, Settings


def test_defaults_match_prototype():
    s = Settings.from_env({"GROQ_API_KEY": "k"})
    assert s.model == "openai/gpt-oss-120b"
    assert s.web_model == "groq/compound"
    assert s.port == 8080
    assert s.host == "0.0.0.0"
    assert s.data_dir == Path("data")
    assert s.memory_file == Path("data/kyvon_memory.json")
    assert s.error_log == Path("data/kyvon_errors.log")
    assert s.env == "development"


def test_missing_api_key_raises():
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        Settings.from_env({})


def test_blank_api_key_raises():
    with pytest.raises(ConfigError):
        Settings.from_env({"GROQ_API_KEY": "   "})


def test_api_key_optional_when_not_required():
    assert Settings.from_env({}, require_api_key=False).groq_api_key == ""


def test_overrides():
    s = Settings.from_env(
        {
            "GROQ_API_KEY": "k",
            "KYVON_MODEL": "m1",
            "KYVON_WEB_MODEL": "m2",
            "PORT": "9000",
            "KYVON_DATA_DIR": "/var/kyvon",
            "KYVON_ENV": "Production",
            "ALLOWED_ORIGINS": "https://a.example, https://b.example",
        }
    )
    assert (s.model, s.web_model, s.port) == ("m1", "m2", 9000)
    assert s.data_dir == Path("/var/kyvon")
    assert s.env == "production"
    assert s.allowed_origins == ("https://a.example", "https://b.example")


@pytest.mark.parametrize("port", ["abc", "0", "70000"])
def test_bad_port(port):
    with pytest.raises(ConfigError, match="PORT"):
        Settings.from_env({"GROQ_API_KEY": "k", "PORT": port})


def test_bad_env_name():
    with pytest.raises(ConfigError, match="KYVON_ENV"):
        Settings.from_env({"GROQ_API_KEY": "k", "KYVON_ENV": "staging"})


def test_repr_hides_secrets():
    s = Settings.from_env({"GROQ_API_KEY": "super-secret", "SECRET_KEY": "also-secret"})
    assert "super-secret" not in repr(s)
    assert "also-secret" not in repr(s)


def test_dotenv_loaded_but_real_env_wins(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GROQ_API_KEY=from-file\nKYVON_MODEL=file-model\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("KYVON_MODEL", "env-model")
    s = Settings.from_env(load_dotenv_file=True)
    assert s.groq_api_key == "from-file"
    assert s.model == "env-model"
