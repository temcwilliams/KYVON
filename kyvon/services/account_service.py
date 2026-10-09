"""Account-level operations for the hosted service: data export and account deletion.

Export returns everything KYVON stores about a person in a portable JSON document (GDPR/CCPA
access and portability). Deletion removes the account and all of its data; every table that
holds user data cascades from ``users``, and ``error_records`` keep only an anonymised row.
Secrets (password and token hashes, OAuth tokens, push endpoints) are never exported.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import (
    AgentRun,
    Automation,
    AutomationRun,
    Conversation,
    Memory,
    Message,
    Notification,
    Task,
    ToolRun,
    User,
)

EXPORT_VERSION = 1


def _row(obj: Any, *, skip: tuple[str, ...] = ()) -> dict:
    out = {}
    for column in obj.__table__.columns:
        if column.name in skip:
            continue
        value = getattr(obj, column.name)
        out[column.name] = value.isoformat() if isinstance(value, (datetime, date)) else value
    return out


def export_user_data(session: Session, user: User) -> dict:
    """Everything stored for ``user`` that is theirs to take with them."""

    def rows(model, *where):
        return [_row(r) for r in session.scalars(select(model).where(*where).order_by(model.id))]

    conversations = []
    for convo in session.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.id)
    ):
        item = _row(convo)
        item["messages"] = [
            _row(m)
            for m in session.scalars(
                select(Message).where(Message.conversation_id == convo.id).order_by(Message.id)
            )
        ]
        conversations.append(item)

    return {
        "export_version": EXPORT_VERSION,
        "exported_at": utcnow().isoformat(),
        "account": {
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            "email_verified": user.email_verified,
            "terms_accepted_at": user.terms_accepted_at.isoformat()
            if user.terms_accepted_at
            else None,
            "terms_version": user.terms_version,
            "settings": user.settings or {},
        },
        "conversations": conversations,
        "memories": rows(Memory, Memory.user_id == user.id),
        "tasks": rows(Task, Task.user_id == user.id),
        "automations": rows(Automation, Automation.user_id == user.id),
        "automation_runs": rows(AutomationRun, AutomationRun.user_id == user.id),
        "notifications": rows(Notification, Notification.user_id == user.id),
        "tool_runs": rows(ToolRun, ToolRun.user_id == user.id),
        "agent_runs": rows(AgentRun, AgentRun.user_id == user.id),
    }


def delete_account(session: Session, user: User) -> None:
    """Permanently delete the account and everything it owns."""
    # A direct DELETE lets the database cascade to every child table (the ORM would first try to
    # null out the device tokens, which are not nullable).
    session.execute(delete(User).where(User.id == user.id))
    session.commit()
    session.expunge_all()
