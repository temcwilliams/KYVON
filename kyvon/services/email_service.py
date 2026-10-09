"""Outgoing email for the hosted service (verification, password reset, notices).

Links carry their token in the URL *fragment* (``/#verify=...``): browsers never send the fragment
to a server, so it stays out of access logs and Referer headers. Tokens are never logged.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from kyvon.config import Settings

log = logging.getLogger("kyvon.email")
SMTP_TIMEOUT_SECONDS = 15


class EmailError(RuntimeError):
    """The message could not be sent."""


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


def _build(sender: str, to: str, subject: str, body: str) -> EmailMessage:
    for value in (sender, to, subject):
        if "\n" in value or "\r" in value:
            raise EmailError("Header values may not contain line breaks.")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


class SmtpEmailSender:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        *,
        user: str = "",
        password: str = "",
        starttls: bool = True,
    ):
        self._host, self._port, self._sender = host, port, sender
        self._user, self._password, self._starttls = user, password, starttls

    def send(self, to: str, subject: str, body: str) -> None:
        message = _build(self._sender, to, subject, body)
        try:
            context = ssl.create_default_context()
            if self._port == 465:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS, context=context
                )
            else:
                client = smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS)
            with client:
                if self._port != 465 and self._starttls:
                    client.starttls(context=context)
                if self._user:
                    client.login(self._user, self._password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise EmailError(f"Email could not be sent ({type(error).__name__}).") from error


class ConsoleEmailSender:
    """Development only: prints the message so you can click the link. Never use in production."""

    def send(self, to: str, subject: str, body: str) -> None:
        print(f"\n--- email to {to}: {subject}\n{body}\n---")  # noqa: T201


def build_email_sender(settings: Settings) -> EmailSender | None:
    if settings.email_configured:
        return SmtpEmailSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.email_from,
            user=settings.smtp_user,
            password=settings.smtp_password,
            starttls=settings.smtp_starttls,
        )
    if settings.hosted and settings.env == "development":
        return ConsoleEmailSender()
    return None


# ------------------------------------------------------------------ messages


def _link(settings: Settings, kind: str, token: str) -> str:
    return f"{settings.public_url.rstrip('/')}/#{kind}={token}"


def verification_message(settings: Settings, token: str) -> tuple[str, str]:
    return (
        "Confirm your KYVON email address",
        "Welcome to KYVON.\n\nConfirm your email address to start using your account:\n"
        f"{_link(settings, 'verify', token)}\n\n"
        f"This link works once and expires in {settings.verify_ttl_hours} hours. "
        "If you did not create a KYVON account, you can ignore this email.\n",
    )


def reset_message(settings: Settings, token: str) -> tuple[str, str]:
    return (
        "Reset your KYVON password",
        "Someone asked to reset the password for this KYVON account. Choose a new one here:\n"
        f"{_link(settings, 'reset', token)}\n\n"
        f"This link works once and expires in {settings.reset_ttl_minutes} minutes. "
        "If you did not ask for this, ignore this email: your password has not changed.\n",
    )


def already_registered_message(settings: Settings) -> tuple[str, str]:
    return (
        "You already have a KYVON account",
        "Someone tried to create a KYVON account with this email address, but one already exists.\n"
        "If it was you, sign in, or reset your password from the sign-in page. "
        "If it was not you, no action is needed.\n",
    )


def account_deleted_message() -> tuple[str, str]:
    return (
        "Your KYVON account was deleted",
        "Your KYVON account and its data have been deleted, as you asked. "
        "If you did not do this, contact support right away.\n",
    )


def deliver(sender: EmailSender | None, to: str, message: tuple[str, str]) -> bool:
    """Send, never raising: a mail failure must not break sign-up or reveal whether an address exists."""
    if sender is None:
        log.warning("email not sent: no email transport configured")
        return False
    try:
        sender.send(to, message[0], message[1])
        return True
    except EmailError:
        log.exception("email delivery failed")
        return False
