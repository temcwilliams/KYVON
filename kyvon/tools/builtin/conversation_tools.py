"""Tools that work with the user's conversations."""

from __future__ import annotations

from pydantic import Field
from sqlalchemy import select

from kyvon.models import Conversation, Message
from kyvon.services.conversation_service import ConversationService, serialize_conversation
from kyvon.services.errors import NotFoundError, ValidationFailure
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry


class ListArgs(ToolArgs):
    limit: int = Field(default=10, ge=1, le=50)
    archived: bool = False


class SearchArgs(ToolArgs):
    query: str = Field(min_length=2, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)


class ReadArgs(ToolArgs):
    conversation_id: int = Field(ge=1)
    limit: int = Field(default=20, ge=1, le=50)


class RenameArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=80)
    conversation_id: int | None = Field(
        default=None, ge=1, description="Default: this conversation."
    )


class ArchiveArgs(ToolArgs):
    conversation_id: int | None = Field(
        default=None, ge=1, description="Default: this conversation."
    )
    archived: bool = True


class DeleteArgs(ToolArgs):
    conversation_id: int = Field(ge=1)


def _service(ctx: ToolContext) -> ConversationService:
    return ConversationService(ctx.session, ctx.user_id)


def _target(ctx: ToolContext, conversation_id: int | None) -> int:
    target = conversation_id or ctx.conversation_id
    if target is None:
        raise ToolError("Say which conversation you mean.")
    return target


def _title(ctx: ToolContext | None, conversation_id: int) -> str:
    if ctx is None:
        return f"#{conversation_id}"
    try:
        return f'"{_service(ctx).get(conversation_id).title or "Untitled"}"'
    except NotFoundError:
        return f"#{conversation_id} (not found)"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def register(registry: ToolRegistry) -> None:
    @registry.tool("conversation_list", "List the user's recent conversations.", ListArgs)
    def conversation_list(ctx: ToolContext, args: ListArgs):
        service = _service(ctx)
        return [
            serialize_conversation(c, message_count=service.message_count(c.id))
            for c in service.list(archived=args.archived, limit=args.limit)
        ]

    @registry.tool(
        "conversation_search",
        "Search the user's past conversations (titles and messages) for a word or phrase.",
        SearchArgs,
        untrusted_output=True,
    )
    def conversation_search(ctx: ToolContext, args: SearchArgs):
        pattern = f"%{_escape_like(args.query)}%"
        rows = ctx.session.execute(
            select(Conversation.id, Conversation.title, Message.id, Message.role, Message.content)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == ctx.user_id,
                Message.kind == "message",
                Message.content.like(pattern, escape="\\"),
            )
            .order_by(Message.id.desc())
            .limit(args.limit)
        ).all()
        return [
            {
                "conversation_id": cid,
                "title": title,
                "message_id": mid,
                "role": role,
                "snippet": content[:300],
            }
            for cid, title, mid, role, content in rows
        ]

    @registry.tool(
        "conversation_read",
        "Read the most recent messages of one of the user's conversations.",
        ReadArgs,
        untrusted_output=True,
    )
    def conversation_read(ctx: ToolContext, args: ReadArgs):
        try:
            rows = _service(ctx).messages(args.conversation_id, limit=args.limit)
        except NotFoundError as problem:
            raise ToolError(str(problem)) from problem
        return [{"role": m.role, "content": m.content[:1000]} for m in rows]

    @registry.tool(
        "conversation_rename",
        "Rename a conversation (default: the current one).",
        RenameArgs,
        risk=RiskLevel.WRITE,
    )
    def conversation_rename(ctx: ToolContext, args: RenameArgs):
        try:
            conversation = _service(ctx).rename(_target(ctx, args.conversation_id), args.title)
        except (NotFoundError, ValidationFailure) as problem:
            raise ToolError(str(problem)) from problem
        return serialize_conversation(conversation)

    @registry.tool(
        "conversation_archive",
        "Archive (or restore) a conversation. Archiving is reversible. Default: the current one.",
        ArchiveArgs,
        risk=RiskLevel.WRITE,
    )
    def conversation_archive(ctx: ToolContext, args: ArchiveArgs):
        try:
            conversation = _service(ctx).archive(_target(ctx, args.conversation_id), args.archived)
        except NotFoundError as problem:
            raise ToolError(str(problem)) from problem
        return serialize_conversation(conversation)

    @registry.tool(
        "conversation_delete",
        "Permanently delete a conversation and its messages. The user must approve.",
        DeleteArgs,
        risk=RiskLevel.DESTRUCTIVE,
        summarize=lambda a, ctx: (
            f"Permanently delete the conversation {_title(ctx, a.conversation_id)}"
        ),
    )
    def conversation_delete(ctx: ToolContext, args: DeleteArgs):
        try:
            _service(ctx).delete(args.conversation_id)
        except NotFoundError as problem:
            raise ToolError(str(problem)) from problem
        return {"deleted": args.conversation_id}
