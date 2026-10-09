"""Memory tools. Writes made by the model always need the user's confirmation."""

from __future__ import annotations

from pydantic import Field

from kyvon.services.errors import ConflictError, NotFoundError, ValidationFailure
from kyvon.services.memory_service import MemoryService, serialize_memory
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry


class SearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=200, description="What to look for.")
    limit: int = Field(default=5, ge=1, le=20)


class CreateArgs(ToolArgs):
    text: str = Field(
        min_length=3, max_length=500, description="The fact to remember, as a statement."
    )
    category: str | None = Field(
        default=None, description="general, preference, personal, project, routine or contact."
    )
    importance: int | None = Field(default=None, ge=1, le=5)


class UpdateArgs(ToolArgs):
    memory_id: int = Field(ge=1)
    text: str | None = Field(default=None, min_length=3, max_length=500)
    category: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)


class DeleteArgs(ToolArgs):
    memory_id: int = Field(ge=1)


def _service(ctx: ToolContext) -> MemoryService:
    return MemoryService(
        ctx.session,
        ctx.user_id,
        max_memories=ctx.settings.memory_max,
        retrieval_k=ctx.settings.memory_retrieval_k,
    )


def _current_text(ctx: ToolContext | None, memory_id: int) -> str:
    if ctx is None:
        return f"#{memory_id}"
    try:
        return f'"{_service(ctx).get(memory_id).content}"'
    except NotFoundError:
        return f"#{memory_id} (not found)"


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "memory_search",
        "Search the user's saved long-term memories for facts relevant to a topic.",
        SearchArgs,
        untrusted_output=True,
    )
    def memory_search(ctx: ToolContext, args: SearchArgs):
        hits = _service(ctx).retrieve(args.query, args.limit)
        return [serialize_memory(h.memory, score=h.score) for h in hits]

    @registry.tool(
        "memory_create",
        "Propose saving a durable fact about the user to long-term memory. Only use this when "
        "the user clearly wants something remembered. Never store passwords or keys. The user "
        "must approve the save.",
        CreateArgs,
        risk=RiskLevel.WRITE,
        confirm=True,
        summarize=lambda a, ctx: f'Save to memory: "{a.text}"',
    )
    def memory_create(ctx: ToolContext, args: CreateArgs):
        try:
            result = _service(ctx).add(
                args.text, category=args.category, importance=args.importance, source="assistant"
            )
        except ValidationFailure as problem:
            raise ToolError(str(problem)) from problem
        return {"id": result.memory.id, "created": result.created}

    @registry.tool(
        "memory_update",
        "Propose changing an existing memory (use memory_search to find its id first). "
        "The user must approve the change.",
        UpdateArgs,
        risk=RiskLevel.WRITE,
        confirm=True,
        summarize=lambda a, ctx: (
            f"Change memory {_current_text(ctx, a.memory_id)}"
            + (f' to: "{a.text}"' if a.text else "")
            + (f" (importance {a.importance})" if a.importance else "")
            + (f" (category {a.category})" if a.category else "")
        ),
    )
    def memory_update(ctx: ToolContext, args: UpdateArgs):
        if args.text is None and args.category is None and args.importance is None:
            raise ToolError("Nothing to change.")
        try:
            memory = _service(ctx).update(
                args.memory_id, text=args.text, category=args.category, importance=args.importance
            )
        except (NotFoundError, ValidationFailure, ConflictError) as problem:
            raise ToolError(str(problem)) from problem
        return {"id": memory.id}

    @registry.tool(
        "memory_delete",
        "Propose deleting a memory (use memory_search to find its id first). The user must approve.",
        DeleteArgs,
        risk=RiskLevel.DESTRUCTIVE,
        summarize=lambda a, ctx: f"Delete memory {_current_text(ctx, a.memory_id)}",
    )
    def memory_delete(ctx: ToolContext, args: DeleteArgs):
        try:
            _service(ctx).delete(args.memory_id)
        except NotFoundError as problem:
            raise ToolError(str(problem)) from problem
        return {"deleted": args.memory_id}
