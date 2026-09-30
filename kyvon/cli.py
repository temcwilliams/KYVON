"""Administration commands: ``flask --app wsgi kyvon <command>``."""

from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import click
from flask import current_app
from flask.cli import AppGroup
from sqlalchemy import select

from kyvon.db import upgrade_database
from kyvon.integrations.webpush import generate_vapid_keys
from kyvon.models import User
from kyvon.services import auth_service
from kyvon.services.memory_import import MemoryImportError, import_json_memories
from kyvon.utils.crypto import generate_key

cli = AppGroup("kyvon", help="KYVON administration.")


def _svc():
    return current_app.extensions["kyvon"]


def _read_password(from_stdin: bool, *, confirm: bool = True) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    return click.prompt("Password", hide_input=True, confirmation_prompt=confirm)


@cli.command("db-upgrade")
def db_upgrade():
    """Apply database migrations."""
    upgrade_database(_svc().settings.db_url)
    click.echo("Database is up to date.")


@cli.command("create-user")
@click.option("--username", prompt=True)
@click.option("--password-stdin", is_flag=True, help="Read the password from stdin (no prompt).")
def create_user(username: str, password_stdin: bool):
    """Create the owner account (only one is allowed)."""
    password = _read_password(password_stdin)
    with _svc().session_factory() as session:
        try:
            user = auth_service.create_owner(session, username, password)
        except auth_service.AuthError as error:
            raise click.ClickException(str(error)) from error
    click.echo(f"Created owner account '{user.username}'.")


@cli.command("set-password")
@click.option("--username", prompt=True)
@click.option("--password-stdin", is_flag=True)
def set_password(username: str, password_stdin: bool):
    """Change the owner's password and sign out all devices."""
    password = _read_password(password_stdin)
    with _svc().session_factory() as session:
        try:
            user = auth_service.set_password(session, username, password)
        except auth_service.AuthError as error:
            raise click.ClickException(str(error)) from error
        revoked = auth_service.revoke_all_tokens(session, user.id)
    click.echo(f"Password updated; {revoked} device token(s) revoked.")


@cli.command("revoke-tokens")
def revoke_tokens():
    """Sign out every device."""
    with _svc().session_factory() as session:
        user = session.scalar(select(User).limit(1))
        if user is None:
            raise click.ClickException("No owner account exists.")
        count = auth_service.revoke_all_tokens(session, user.id)
    click.echo(f"Revoked {count} token(s).")


@cli.command("import-memories")
@click.option(
    "--file",
    "file_",
    type=click.Path(path_type=Path),
    help="JSON memory file (default: <data dir>/kyvon_memory.json).",
)
def import_memories(file_: Path | None):
    """Import the prototype's JSON memories. Safe to re-run; the file is not modified."""
    path = file_ or _svc().settings.memory_file
    with _svc().session_factory() as session:
        user = session.scalar(select(User).limit(1))
        if user is None:
            raise click.ClickException("Create the owner account first (kyvon create-user).")
        try:
            result = import_json_memories(session, user.id, path)
        except MemoryImportError as error:
            raise click.ClickException(str(error)) from error
    click.echo(f"Imported {result.imported} memories ({result.skipped} skipped) from {path}.")
    if result.refused_secrets:
        click.echo(f"{result.refused_secrets} entries looked like secrets and were not imported.")
    click.echo("The JSON file was left untouched as a backup.")


@cli.command("generate-key")
def generate_key_command():
    """Print a new KYVON_ENCRYPTION_KEY (used to encrypt stored OAuth tokens)."""
    click.echo(generate_key())


@cli.command("generate-vapid-keys")
def generate_vapid_keys_command():
    """Print a VAPID key pair for Web Push (set the two values in your environment)."""
    public, private = generate_vapid_keys()
    click.echo(f"KYVON_VAPID_PUBLIC_KEY={public}")
    click.echo(f"KYVON_VAPID_PRIVATE_KEY={private}")
    click.echo("KYVON_VAPID_SUBJECT=mailto:you@example.com")


# ---------------------------------------------------------------------------- backup / restore


def _sqlite_path(url: str) -> Path:
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if (
        parsed.get_backend_name() != "sqlite"
        or not parsed.database
        or parsed.database == ":memory:"
    ):
        raise click.ClickException("Backups are only implemented for a file-based SQLite database.")
    return Path(parsed.database)


def _integrity_ok(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            return db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.Error:
        return False


@cli.command("backup")
@click.option(
    "--dest", type=click.Path(path_type=Path), help="Backup folder (default: <data dir>/backups)."
)
@click.option("--keep", default=14, show_default=True, help="How many backups to keep.")
def backup(dest: Path | None, keep: int):
    """Make a consistent online copy of the database and prune old copies."""
    source = _sqlite_path(_svc().settings.db_url)
    folder = dest or (_svc().settings.data_dir / "backups")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    target = folder / f"kyvon-{datetime.now():%Y%m%d-%H%M%S}.db"

    # SQLite's backup API copies a consistent snapshot even while KYVON is running.
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    if not _integrity_ok(target):
        target.unlink(missing_ok=True)
        raise click.ClickException("The backup failed its integrity check and was removed.")
    os.chmod(target, 0o600)

    existing = sorted(folder.glob("kyvon-*.db"))
    for old in existing[: max(len(existing) - max(keep, 1), 0)]:
        old.unlink()
    click.echo(
        f"Backup written: {target} ({target.stat().st_size} bytes). Keeping {min(len(existing), keep)}."
    )


@cli.command("restore")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True, help="Confirm that you want to replace the current database.")
def restore(file: Path, yes: bool):
    """Replace the database with a backup. Stop the service first."""
    target = _sqlite_path(_svc().settings.db_url)
    if not yes:
        raise click.ClickException(
            "This replaces the current database. Stop KYVON, then add --yes."
        )
    if not _integrity_ok(file):
        raise click.ClickException("That file is not a healthy SQLite database.")
    with closing(sqlite3.connect(f"file:{file}?mode=ro", uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'alembic_version'").fetchone():
            raise click.ClickException("That file is not a KYVON database (no migration table).")
    if target.exists():
        try:  # refuse while something else holds the database open
            with closing(sqlite3.connect(target, timeout=1)) as live:
                live.execute("BEGIN EXCLUSIVE")
                live.rollback()
        except sqlite3.OperationalError as error:
            raise click.ClickException(
                "The database is in use. Stop the KYVON service first."
            ) from error
        safety = target.with_name(f"{target.name}.pre-restore-{datetime.now():%Y%m%d-%H%M%S}")
        with closing(sqlite3.connect(target)) as src, closing(sqlite3.connect(safety)) as dst:
            src.backup(dst)
        click.echo(f"Current database saved as {safety}")
    staged = target.with_name(target.name + ".restoring")
    with (
        closing(sqlite3.connect(f"file:{file}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(staged)) as dst,
    ):
        src.backup(dst)
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    os.replace(staged, target)
    os.chmod(target, 0o600)
    click.echo("Restored. Run `kyvon db-upgrade` (if the backup is older) and start the service.")


@cli.command("doctor")
@click.option("--quiet", is_flag=True, help="Only print warnings and problems.")
def doctor(quiet: bool):
    """Check the configuration. Exits with an error if something must be fixed."""
    from kyvon.services.doctor import FAIL, OK, WARN, run_checks

    checks = run_checks(_svc().settings, _svc().session_factory, env_file=Path(".env"))
    marks = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}
    for check in checks:
        if quiet and check.level == OK:
            continue
        click.echo(f"[{marks[check.level]}] {check.message}")
    failed = [c for c in checks if c.level == FAIL]
    if failed:
        raise click.ClickException(f"{len(failed)} problem(s) must be fixed before starting.")
    if not quiet:
        click.echo("Configuration looks good.")
