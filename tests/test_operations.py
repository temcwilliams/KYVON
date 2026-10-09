"""Operations: backup/restore, doctor, graceful shutdown and the generated config docs."""

import os
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text

from kyvon import create_app
from kyvon.services import auth_service
from kyvon.services.doctor import FAIL, OK, WARN, run_checks
from tests.conftest import TEST_ENCRYPTION_KEY, TEST_PASSWORD, TEST_USERNAME

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def migrated(settings, fake_llm, fake_environment):
    """An app whose database was created by the real migrations (like production)."""
    app = create_app(settings, llm=fake_llm, environment=fake_environment)
    assert app.test_cli_runner().invoke(args=["kyvon", "db-upgrade"]).exit_code == 0
    with app.extensions["kyvon"].session_factory() as s:
        auth_service.create_owner(s, TEST_USERNAME, TEST_PASSWORD)
    return app


def cli(app, *args, **kw):
    return app.test_cli_runner().invoke(args=["kyvon", *args], **kw)


def db_rows(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT username FROM users").fetchall()


def factory(app):
    return app.extensions["kyvon"].session_factory


# ------------------------------------------------------------ backup


def test_backup_creates_a_verified_private_copy(migrated, settings):
    result = cli(migrated, "backup")
    assert result.exit_code == 0 and "Backup written" in result.output
    (backup,) = list((settings.data_dir / "backups").glob("kyvon-*.db"))
    assert db_rows(backup) == [(TEST_USERNAME,)]
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE((settings.data_dir / "backups").stat().st_mode) == 0o700


def test_backup_works_while_the_database_is_in_use(migrated):
    with factory(migrated)() as s:  # an open connection, as in production
        s.execute(text("SELECT 1"))
        assert cli(migrated, "backup").exit_code == 0


def test_backup_retention(migrated, settings):
    folder = settings.data_dir / "backups"
    folder.mkdir()
    for i in range(5):
        (folder / f"kyvon-2020010{i}-000000.db").write_text("old")
    assert cli(migrated, "backup", "--keep", "3").exit_code == 0
    names = sorted(p.name for p in folder.glob("kyvon-*.db"))
    assert len(names) == 3 and "kyvon-20200100-000000.db" not in names


def test_backup_only_touches_its_own_files(migrated, settings):
    folder = settings.data_dir / "backups"
    folder.mkdir()
    (folder / "notes.txt").write_text("keep me")
    cli(migrated, "backup", "--keep", "1")
    assert (folder / "notes.txt").exists()


def test_backup_to_another_folder(migrated, tmp_path):
    dest = tmp_path / "elsewhere"
    assert cli(migrated, "backup", "--dest", str(dest)).exit_code == 0
    assert len(list(dest.glob("kyvon-*.db"))) == 1


def test_backup_refuses_non_sqlite_databases():
    import click

    from kyvon.cli import _sqlite_path

    for url in ("postgresql://u:p@localhost/db", "sqlite://", "sqlite:///:memory:"):
        with pytest.raises(click.ClickException, match="SQLite"):
            _sqlite_path(url)
    assert _sqlite_path("sqlite:///data/kyvon.db") == Path("data/kyvon.db")


# ------------------------------------------------------------ restore


def make_backup(app, settings):
    cli(app, "backup")
    (backup,) = list((settings.data_dir / "backups").glob("kyvon-*.db"))
    return backup


def test_restore_round_trip(migrated, settings):
    backup = make_backup(migrated, settings)
    with factory(migrated)() as s:
        s.execute(text("DELETE FROM users"))
        s.commit()
    migrated.extensions["kyvon"].engine.dispose()
    assert db_rows(settings.data_dir / "kyvon.db") == []
    result = cli(migrated, "restore", str(backup), "--yes")
    assert result.exit_code == 0, result.output
    assert db_rows(settings.data_dir / "kyvon.db") == [(TEST_USERNAME,)]
    assert (
        len(list(settings.data_dir.glob("kyvon.db.pre-restore-*"))) == 1
    )  # the replaced db is kept


def test_restore_needs_confirmation(migrated, settings):
    backup = make_backup(migrated, settings)
    result = cli(migrated, "restore", str(backup))
    assert result.exit_code != 0 and "--yes" in result.output


def test_restore_rejects_bad_files(migrated, tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("this is not a database")
    assert "healthy SQLite" in cli(migrated, "restore", str(junk), "--yes").output
    foreign = tmp_path / "foreign.db"
    with closing(sqlite3.connect(foreign)) as db:
        db.execute("CREATE TABLE something (id integer)")
        db.commit()
    assert "not a KYVON database" in cli(migrated, "restore", str(foreign), "--yes").output


def test_restore_refuses_while_the_database_is_in_use(migrated, settings):
    backup = make_backup(migrated, settings)
    holder = sqlite3.connect(settings.data_dir / "kyvon.db", timeout=1, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        result = cli(migrated, "restore", str(backup), "--yes")
        assert result.exit_code != 0 and "in use" in result.output
    finally:
        holder.close()


# ------------------------------------------------------------ doctor


def test_doctor_passes_a_healthy_setup(migrated, settings):
    checks = run_checks(settings, factory(migrated))
    assert all(c.level != FAIL for c in checks)
    assert any("database is migrated" in c.message and c.level == OK for c in checks)
    assert cli(migrated, "doctor").exit_code == 0


def test_doctor_fails_on_an_unmigrated_database(settings, fake_llm, fake_environment):
    app = create_app(settings, llm=fake_llm, environment=fake_environment)  # never migrated
    result = cli(app, "doctor")
    assert result.exit_code != 0 and "FAIL" in result.output and "db-upgrade" in result.output


def test_doctor_flags_production_problems(migrated, settings):
    prod = replace(
        settings,
        env="production",
        cookie_secure=False,
        public_url="http://kyvon.example.com",
        log_json=False,
    )
    found = {c.message: c.level for c in run_checks(prod, factory(migrated))}
    assert found["KYVON_ENV=production but cookies are not Secure (HTTPS needed)"] == WARN
    assert found["KYVON_PUBLIC_URL is not https:// (needed for Google sign-in and push)"] == WARN
    assert found["production logs are not JSON (KYVON_LOG_JSON=false)"] == WARN


def test_doctor_checks_the_env_file_permissions(migrated, settings, tmp_path):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=x\n")
    env.chmod(0o644)
    assert any(
        c.level == WARN and "readable by other users" in c.message
        for c in run_checks(settings, factory(migrated), env_file=env)
    )
    env.chmod(0o600)
    assert any(
        c.level == OK and "permissions are private" in c.message
        for c in run_checks(settings, factory(migrated), env_file=env)
    )


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"google_client_id": ""}, "partly configured"),
        ({"encryption_key": "not-a-key"}, "not a valid key"),
        ({"hermes_url": "https://api.example.com/v1"}, "private network"),
        ({"logseq_dir": "/definitely/not/here"}, "not a folder"),
        ({"vapid_public_key": "abc"}, "Web Push is partly configured"),
        ({"groq_api_key": ""}, "GROQ_API_KEY is missing"),
    ],
)
def test_doctor_spots_misconfiguration(migrated, settings, change, expected):
    checks = run_checks(replace(settings, **change), factory(migrated))
    assert any(expected in c.message and c.level in (WARN, FAIL) for c in checks), [
        c.message for c in checks
    ]


def test_doctor_warns_about_a_missing_owner(settings, fake_llm, fake_environment):
    app = create_app(settings, llm=fake_llm, environment=fake_environment)
    cli(app, "db-upgrade")
    assert any(
        c.level == WARN and "no owner account" in c.message
        for c in run_checks(settings, factory(app))
    )


def test_doctor_warns_about_multiple_workers(migrated, settings, monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    assert any(
        c.level == WARN and "more than one gunicorn worker" in c.message
        for c in run_checks(settings, factory(migrated))
    )


def test_doctor_output_never_prints_secrets(migrated):
    result = cli(migrated, "doctor")
    for secret in ("test-key", TEST_ENCRYPTION_KEY, "test-client-secret"):
        assert secret not in result.output


# ------------------------------------------------------------ shutdown and startup


def test_shutdown_stops_background_work(app):
    svc = app.extensions["kyvon"]
    svc.scheduler.start()
    assert svc.scheduler.running
    svc.shutdown()
    assert not svc.scheduler.running


def test_shutdown_is_safe_to_call_twice(app):
    app.extensions["kyvon"].shutdown()
    app.extensions["kyvon"].shutdown()


def test_startup_logs_a_feature_summary_without_secrets(settings, fake_llm, fake_environment):
    import io
    import logging

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("kyvon")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        create_app(settings, llm=fake_llm, environment=fake_environment)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    output = stream.getvalue()
    assert "KYVON starting: env=development" in output and "calendar=True" in output
    assert "test-key" not in output and "test-client-secret" not in output


def test_a_real_gunicorn_process_starts_serves_and_stops_gracefully(tmp_path):
    """Boot the production server process, hit it, stop it with SIGTERM."""
    import json

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = {
        **os.environ,
        "GROQ_API_KEY": "test-key",
        "KYVON_DATA_DIR": str(tmp_path / "data"),
        "PORT": str(port),
        "KYVON_HOST": "127.0.0.1",
        "KYVON_SCHEDULER": "false",
        "PYTHONPATH": str(ROOT),
    }
    upgrade = [sys.executable, "-m", "flask", "--app", "wsgi", "kyvon", "db-upgrade"]
    assert subprocess.run(upgrade, cwd=ROOT, env=env, capture_output=True).returncode == 0
    server = [sys.executable, "-m", "gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
    proc = subprocess.Popen(
        server, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        body = None
        for _ in range(150):
            try:
                body = json.load(
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/v1/health/ready", timeout=1
                    )
                )
                break
            except Exception:
                time.sleep(0.1)
        assert body == {"status": "ready"}
        with pytest.raises(urllib.error.HTTPError) as info:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/memories", timeout=2)
        assert info.value.code == 401
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 0  # a clean exit, not a kill
    finally:
        if proc.poll() is None:
            proc.kill()


# ------------------------------------------------------------ generated documentation


def test_configuration_reference_is_up_to_date():
    result = subprocess.run([sys.executable, "scripts/gen_config_docs.py", "--check"], cwd=ROOT)
    assert result.returncode == 0, "run: python scripts/gen_config_docs.py"


def all_setting_names():
    from kyvon import config

    return (
        [e for e, *_ in config._INTS.values()]
        + [e for e, _ in config._FLAGS.values()]
        + [e for e, _ in config._STRINGS.values()]
    )


def test_every_setting_is_documented():
    doc = (ROOT / "docs" / "CONFIGURATION.md").read_text()
    assert [n for n in all_setting_names() if f"`{n}`" not in doc] == []


def test_env_example_only_names_real_settings_and_has_no_values():
    real = set(all_setting_names()) | {
        "GROQ_API_KEY",
        "KYVON_ENV",
        "LOG_LEVEL",
        "KYVON_DATA_DIR",
        "DATABASE_URL",
        "KYVON_COOKIE_SECURE",
        "KYVON_LOG_JSON",
    }
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.lstrip("# ").strip()
        name, _, value = line.partition("=")
        if _ and name.isupper() and " " not in name:
            assert name in real, f"{name} is in .env.example but is not a setting"
            assert not value.startswith(("gsk_", "sk-", "AIza")), name


def test_systemd_units_are_consistent_with_the_app():
    unit = (ROOT / "deploy" / "kyvon.service").read_text()
    assert "kyvon doctor" in unit and "kyvon db-upgrade" in unit and "wsgi:app" in unit
    assert (
        "KillSignal=SIGTERM" in unit
        and "NoNewPrivileges=true" in unit
        and "EnvironmentFile=" in unit
    )
    assert unit.index("doctor") < unit.index("db-upgrade") < unit.index("gunicorn")
    assert "kyvon backup" in (ROOT / "deploy" / "kyvon-backup.service").read_text()
    assert "OnCalendar" in (ROOT / "deploy" / "kyvon-backup.timer").read_text()
    assert (
        "http://localhost:8080" in (ROOT / "deploy" / "cloudflared-config.example.yml").read_text()
    )
