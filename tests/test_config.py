from pathlib import Path

import pytest

from kyvon.config import ConfigError, Settings


def test_defaults():
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
        }
    )
    assert (s.model, s.web_model, s.port) == ("m1", "m2", 9000)
    assert s.data_dir == Path("/var/kyvon")
    assert s.env == "production"


@pytest.mark.parametrize("port", ["abc", "0", "70000"])
def test_bad_port(port):
    with pytest.raises(ConfigError, match="PORT"):
        Settings.from_env({"GROQ_API_KEY": "k", "PORT": port})


def test_bad_env_name():
    with pytest.raises(ConfigError, match="KYVON_ENV"):
        Settings.from_env({"GROQ_API_KEY": "k", "KYVON_ENV": "staging"})


def test_repr_hides_secrets():
    s = Settings.from_env({"GROQ_API_KEY": "super-secret"})
    assert "super-secret" not in repr(s)


def test_dotenv_loaded_but_real_env_wins(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GROQ_API_KEY=from-file\nKYVON_MODEL=file-model\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("KYVON_MODEL", "env-model")
    s = Settings.from_env(load_dotenv_file=True)
    assert s.groq_api_key == "from-file"
    assert s.model == "env-model"


def test_bad_log_level():
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Settings.from_env({"GROQ_API_KEY": "k", "LOG_LEVEL": "loud"})


def test_log_level_case_insensitive():
    assert Settings.from_env({"GROQ_API_KEY": "k", "LOG_LEVEL": "debug"}).log_level == "DEBUG"


def test_cookie_secure_defaults_by_environment():
    dev = Settings.from_env({"GROQ_API_KEY": "k"})
    prod = Settings.from_env({"GROQ_API_KEY": "k", "KYVON_ENV": "production"})
    override = Settings.from_env(
        {"GROQ_API_KEY": "k", "KYVON_ENV": "production", "KYVON_COOKIE_SECURE": "false"}
    )
    assert (dev.cookie_secure, prod.cookie_secure, override.cookie_secure) == (False, True, False)


@pytest.mark.parametrize("value", ["x", "0"])
def test_bad_token_ttl(value):
    with pytest.raises(ConfigError, match="TTL"):
        Settings.from_env({"GROQ_API_KEY": "k", "KYVON_TOKEN_TTL_DAYS": value})
