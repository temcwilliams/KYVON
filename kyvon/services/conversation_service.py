"""Conversations and messages, always scoped to one user."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.models import Conversation, Message
from kyvon.services.errors import NotFoundError, ValidationFailure

MAX_TITLE = 80
DEFAULT_TITLE = "New conversation"


def title_from_text(text: str) -> str:
    """A first-guess title: the opening words of the first message."""
    flat = " ".join((text or "").split())
    if not flat:
        return DEFAULT_TITLE
    return flat if len(flat) <= 60 else flat[:57].rstrip() + "..."


def clean_title(raw: str) -> str:
    title = " ".join((raw or "").replace("\n", " ").split()).strip(" \"'`*#")
    return title[:MAX_TITLE]


def serialize_conversation(c: Conversation, *, message_count: int | None = None) -> dict:
    data = {
        "id": c.id,
        "title": c.title or DEFAULT_TITLE,
        "title_source": c.title_source,
        "archived": c.archived,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }
    if message_count is not None:
        data["message_count"] = message_count
    return data


def serialize_message(m: Message) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "role": m.role,
        "kind": m.kind,
        "content": m.content,
        "status": m.status,
        "model": m.model,
        "tokens_in": m.tokens_in,
        "tokens_out": m.tokens_out,
        "tool_name": m.tool_name,
        "created_at": m.created_at.isoformat(),
    }


class ConversationService:
    def __init__(self, session: Session, user_id: int, *, now: Callable[[], datetime] = utcnow):
        self._s = session
        self._user_id = user_id
        self._now = now

    # ------------------------------------------------------------ conversations

    def create(self, title: str | None = None) -> Conversation:
        conversation = Conversation(
            user_id=self._user_id,
            title=clean_title(title) if title else "",
            title_source="user" if title else "auto",
            created_at=self._now(),
            updated_at=self._now(),
        )
        self._s.add(conversation)
        self._s.commit()
        return conversation

    def get(self, conversation_id: int) -> Conversation:
        conversation = self._s.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == self._user_id
            )
        )
        if conversation is None:
            raise NotFoundError("Conversation not found.")
        return conversation

    def list(
        self, *, archived: bool = False, limit: int = 50, before_id: int | None = None
    ) -> list[Conversation]:
        query = select(Conversation).where(
            Conversation.user_id == self._user_id, Conversation.archived == archived
        )
        if before_id is not None:
            anchor = self._s.get(Conversation, before_id)
            if anchor is not None and anchor.user_id == self._user_id:
                query = query.where(
                    (Conversation.updated_at < anchor.updated_at)
                    | (
                        (Conversation.updated_at == anchor.updated_at)
                        & (Conversation.id < before_id)
                    )
                )
        query = query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(
            max(1, min(limit, 200))
        )
        return list(self._s.scalars(query))

    def message_count(self, conversation_id: int) -> int:
        return self._s.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id, Message.kind == "message")
        )

    def rename(self, conversation_id: int, title: str) -> Conversation:
        title = clean_title(title)
        if not title:
            raise ValidationFailure("Title cannot be empty.")
        conversation = self.get(conversation_id)
        conversation.title = title
        conversation.title_source = "user"
        self._s.commit()
        return conversation

    def set_auto_title(self, conversation: Conversation, title: str) -> None:
        """Set a generated title unless the user has named the conversation."""
        title = clean_title(title)
        if title and conversation.title_source == "auto":
            conversation.title = title
            self._s.commit()

    def archive(self, conversation_id: int, archived: bool = True) -> Conversation:
        conversation = self.get(conversation_id)
        conversation.archived = archived
        self._s.commit()
        return conversation

    def delete(self, conversation_id: int) -> None:
        conversation = self.get(conversation_id)
        self._s.execute(delete(Message).where(Message.conversation_id == conversation.id))
        self._s.delete(conversation)
        self._s.commit()

    # ------------------------------------------------------------ messages

    def add_message(
        self,
        conversation: Conversation,
        role: str,
        content: str,
        *,
        kind: str = "message",
        status: str = "complete",
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        tool_calls: list | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            kind=kind,
            status=status,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            created_at=self._now(),
        )
        self._s.add(message)
        conversation.updated_at = self._now()
        self._s.commit()
        return message

    def finish_message(
        self,
        message: Message,
        *,
        content: str,
        status: str = "complete",
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> Message:
        message.content = content
        message.status = status
        if model:
            message.model = model
        message.tokens_in = tokens_in
        message.tokens_out = tokens_out
        conversation = self._s.get(Conversation, message.conversation_id)
        if conversation is not None:
            conversation.updated_at = self._now()
        self._s.commit()
        return message

    def messages(
        self,
        conversation_id: int,
        *,
        kinds: Iterable[str] = ("message", "event"),
        before_id: int | None = None,
        after_id: int | None = None,
        limit: int = 100,
    ) -> list[Message]:
        """Messages in chronological order. ``before_id`` pages backwards (newest page first)."""
        self.get(conversation_id)  # ownership check
        limit = max(1, min(limit, 500))
        query = select(Message).where(
            Message.conversation_id == conversation_id, Message.kind.in_(list(kinds))
        )
        if after_id is not None:
            query = query.where(Message.id > after_id).order_by(Message.id).limit(limit)
            return list(self._s.scalars(query))
        if before_id is not None:
            query = query.where(Message.id < before_id)
        rows = list(self._s.scalars(query.order_by(Message.id.desc()).limit(limit)))
        rows.reverse()
        return rows
