"""Sanity checks for deployment files (the Docker build itself runs in CI)."""

import runpy
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gunicorn_defaults_keep_port_8080(monkeypatch):
    for name in ("PORT", "KYVON_HOST", "WEB_CONCURRENCY", "GUNICORN_THREADS"):
        monkeypatch.delenv(name, raising=False)
    config = runpy.run_path(str(ROOT / "gunicorn.conf.py"))
    assert config["bind"] == "0.0.0.0:8080"
    assert config["workers"] == 1


def test_gunicorn_port_override(monkeypatch):
    monkeypatch.setenv("PORT", "9090")
    assert runpy.run_path(str(ROOT / "gunicorn.conf.py"))["bind"].endswith(":9090")


def test_entrypoint_is_executable_and_migrates_first():
    entry = ROOT / "docker-entrypoint.sh"
    assert entry.stat().st_mode & stat.S_IXUSR
    text = entry.read_text()
    assert text.index("db-upgrade") < text.index("gunicorn")


def test_wsgi_exposes_app(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("KYVON_DATA_DIR", str(tmp_path))
    namespace = runpy.run_path(str(ROOT / "wsgi.py"))
    assert namespace["app"].name == "kyvon"


def test_env_example_has_placeholders_only():
    text = (ROOT / ".env.example").read_text()
    assert "your-groq-api-key-here" in text
    assert "gsk_" not in text


def test_hosted_env_template_has_placeholders_only():
    text = (ROOT / ".env.hosted.example").read_text()
    for forbidden in ("gsk_", "sk_live", "sk_test_", "whsec_"):
        assert forbidden not in text
    assert "your-groq-api-key-here" in text and "KYVON_SIGNUP_OPEN=false" in text
    assert "STRIPE_SECRET_KEY=\n" in text  # empty, never a real key


def test_compose_runs_one_scheduler_and_migrates_once():
    text = (ROOT / "deploy" / "docker-compose.hosted.yml").read_text()
    assert text.count('kyvon", "scheduler"') == 1
    assert 'KYVON_SCHEDULER: "false"' in text  # web workers do not run it
    assert "service_completed_successfully" in text  # web waits for the migration
