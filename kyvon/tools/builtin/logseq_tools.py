"""Logseq tools. Searching and reading are automatic; every change needs the user's approval."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from kyvon.services.errors import ConflictError, IntegrationError, NotFoundError, ValidationFailure
from kyvon.tools.base import RiskLevel, ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry

READ_LIMIT = 8000


class SearchArgs(ToolArgs):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=8, ge=1, le=30)


class ListArgs(ToolArgs):
    query: str | None = Field(default=None, max_length=100, description="Filter page names.")
    limit: int = Field(default=30, ge=1, le=100)


class PageArgs(ToolArgs):
    name: str = Field(min_length=1, max_length=120)


class WriteArgs(ToolArgs):
    name: str = Field(min_length=1, max_length=120, description="Page name, e.g. 'Projects/Alpha'.")
    content: str = Field(
        min_length=1, max_length=20000, description="Text; each line becomes a Logseq block."
    )


class AppendArgs(ToolArgs):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)


class JournalArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=20000)
    day: str | None = Field(default=None, max_length=10, description="YYYY-MM-DD. Default: today.")


def _graph(ctx: ToolContext):
    graph = ctx.services.logseq
    if graph is None:
        raise ToolError("Logseq is not configured on this server.")
    return graph


def _guard(action):
    try:
        return action()
    except (ValidationFailure, NotFoundError, ConflictError, IntegrationError) as problem:
        raise ToolError(str(problem)) from problem


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= 160 else flat[:157] + "..."


def register(registry: ToolRegistry) -> None:
    enabled = lambda services: services.logseq is not None  # noqa: E731

    @registry.tool(
        "logseq_search",
        "Search the user's Logseq notes (their second brain) for a word or phrase.",
        SearchArgs,
        enabled=enabled,
        untrusted_output=True,
    )
    def logseq_search(ctx: ToolContext, args: SearchArgs):
        hits = _guard(lambda: _graph(ctx).search(args.query, args.limit))
        return [{"page": h.page, "line": h.line, "text": h.snippet} for h in hits]

    @registry.tool(
        "logseq_list_pages",
        "List page names in the user's Logseq notes.",
        ListArgs,
        enabled=enabled,
        untrusted_output=True,
    )
    def logseq_list_pages(ctx: ToolContext, args: ListArgs):
        return _guard(lambda: _graph(ctx).list_pages(args.query, args.limit))

    @registry.tool(
        "logseq_read_page",
        "Read one page of the user's Logseq notes.",
        PageArgs,
        enabled=enabled,
        untrusted_output=True,
    )
    def logseq_read_page(ctx: ToolContext, args: PageArgs):
        page = _guard(lambda: _graph(ctx).read_page(args.name))
        text = page.content[:READ_LIMIT]
        return {
            "page": page.name,
            "content": text,
            "truncated": page.truncated or len(page.content) > READ_LIMIT,
        }

    @registry.tool(
        "logseq_create_page",
        "Propose creating a new Logseq page. The user must approve.",
        WriteArgs,
        risk=RiskLevel.EXTERNAL,
        enabled=enabled,
        summarize=lambda a, ctx: f'Create the Logseq page "{a.name}": {_preview(a.content)}',
    )
    def logseq_create_page(ctx: ToolContext, args: WriteArgs):
        return {"page": _guard(lambda: _graph(ctx).create_page(args.name, args.content))}

    @registry.tool(
        "logseq_append",
        "Propose adding text to the end of an existing Logseq page. The user must approve.",
        AppendArgs,
        risk=RiskLevel.EXTERNAL,
        enabled=enabled,
        summarize=lambda a, ctx: f'Add to the Logseq page "{a.name}": {_preview(a.text)}',
    )
    def logseq_append(ctx: ToolContext, args: AppendArgs):
        return {"page": _guard(lambda: _graph(ctx).append_to_page(args.name, args.text))}

    @registry.tool(
        "logseq_journal_append",
        "Propose adding a note to a Logseq journal day (default today). Good for saving what was "
        "discussed. The user must approve.",
        JournalArgs,
        risk=RiskLevel.EXTERNAL,
        enabled=enabled,
        summarize=lambda a, ctx: (
            f"Add to the Logseq journal ({a.day or 'today'}): {_preview(a.text)}"
        ),
    )
    def logseq_journal_append(ctx: ToolContext, args: JournalArgs):
        try:
            day = date.fromisoformat(args.day) if args.day else None
        except ValueError:
            raise ToolError("The day must look like 2026-10-03.") from None
        return {"journal": _guard(lambda: _graph(ctx).append_to_journal(args.text, day))}

    @registry.tool(
        "logseq_replace_page",
        "Propose replacing the entire content of an existing Logseq page. The old version is "
        "backed up. The user must approve.",
        WriteArgs,
        risk=RiskLevel.DESTRUCTIVE,
        enabled=enabled,
        summarize=lambda a, ctx: (
            f'Replace the whole Logseq page "{a.name}" (a backup is kept) with: {_preview(a.content)}'
        ),
    )
    def logseq_replace_page(ctx: ToolContext, args: WriteArgs):
        return {"page": _guard(lambda: _graph(ctx).replace_page(args.name, args.content))}
