"""Web research (through Groq's built-in search model)."""

from __future__ import annotations

from pydantic import Field

from kyvon.llm.prompts import WEB_SYSTEM_PROMPT
from kyvon.services.errors import EmailNotVerified, QuotaExceeded
from kyvon.services.usage_service import UsageGate
from kyvon.tools.base import ToolArgs, ToolContext, ToolError
from kyvon.tools.registry import ToolRegistry

MAX_TOKENS = 1500


class WebSearchArgs(ToolArgs):
    query: str = Field(
        min_length=2, max_length=500, description="The question or topic to research."
    )


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        "web_search",
        "Research a question on the web and return an answer. Use for current events, facts "
        "that may have changed, or anything you are unsure about.",
        WebSearchArgs,
        timeout=90,
        retries=1,
        untrusted_output=True,
    )
    def web_search(ctx: ToolContext, args: WebSearchArgs):
        services = ctx.services
        gate = (
            UsageGate(ctx.session, services.settings, ctx.user_id)
            if services.settings.hosted
            else None
        )
        if gate is not None:
            try:
                gate.check("search")
            except (QuotaExceeded, EmailNotVerified) as error:
                raise ToolError(str(error)) from error
        answer = services.llm.complete(
            [
                {"role": "system", "content": WEB_SYSTEM_PROMPT},
                {"role": "user", "content": args.query},
            ],
            model=services.settings.web_model,
            max_tokens=MAX_TOKENS,
        )
        if gate is not None:
            gate.record("search", len(args.query) // 4, len(answer) // 4)
        if not answer.strip():
            raise ToolError("The search returned no answer.")
        return {"query": args.query, "answer": answer}
