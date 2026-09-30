"""Administration commands: ``flask --app wsgi kyvon <command>``."""

from __future__ import annotations

import sys
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
