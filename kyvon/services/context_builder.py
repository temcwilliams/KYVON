"""Builds the message list sent to the model for one turn.

Three kinds of context are kept apart on purpose:

* conversation context - the recent messages of this conversation (bounded)
* long-term memory     - retrieved memories, not the whole store
* temporary context    - time / location / weather, rebuilt every turn and never stored

History is limited by a token budget and a message count. What does not fit is
represented by a running summary of the conversation, when one exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kyvon.llm.prompts import build_system_prompt
from kyvon.models import Conversation, Message

CHARS_PER_TOKEN = 4
TRUNCATION_NOTE = "\n[message truncated to fit the context limit]"


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (about four characters per token)."""
    return math.ceil(len(text or "") / CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ContextLimits:
    max_tokens: int = 6000
    max_messages: int = 40
    reserve_tokens: int = 1500  # room left for the model's reply


@dataclass
class BuiltContext:
    messages: list[dict]
    included_message_ids: list[int] = field(default_factory=list)
    dropped_count: int = 0
    estimated_tokens: int = 0
    summary_used: bool = False


def _history_role(message: Message) -> dict | None:
    if message.kind == "event":
        return {"role": "system", "content": f"Note: {message.content}"}
    if message.kind != "message" or message.status != "complete":
        return None
    if message.role not in ("user", "assistant"):
        return None
    if not message.content.strip():
        return None
    return {"role": message.role, "content": message.content}


class ContextBuilder:
    def __init__(self, session: Session, limits: ContextLimits):
        self._s = session
        self._limits = limits

    def build(
        self,
        conversation: Conversation,
        *,
        profile: str = "",
        memory: str = "",
        environment: str = "",
    ) -> BuiltContext:
        """Assemble system prompt + recent history. The newest message is always kept."""
        rows = list(
            self._s.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.kind.in_(("message", "event")),
                )
                .order_by(Message.id.desc())
                .limit(self._limits.max_messages * 3)  # over-fetch: some rows are filtered out
            )
        )
        usable = [(m, h) for m in rows if (h := _history_role(m)) is not None]
        total_usable = len(usable)

        # Decide whether the summary can be included: it is only meaningful when older
        # messages have been cut off.
        prompt_no_summary = build_system_prompt(
            profile=profile, memory=memory, environment=environment
        )
        budget = (
            self._limits.max_tokens
            - self._limits.reserve_tokens
            - estimate_tokens(prompt_no_summary)
        )
        budget = max(budget, 200)

        kept: list[tuple[Message, dict]] = []
        used = 0
        for message, entry in usable:  # newest first
            cost = estimate_tokens(entry["content"]) + 4
            if len(kept) >= self._limits.max_messages:
                break
            if not kept:
                # The newest message is always sent, truncated if it alone is too large.
                if cost > budget:
                    keep_chars = max(budget - 4, 1) * CHARS_PER_TOKEN
                    entry = {**entry, "content": entry["content"][:keep_chars] + TRUNCATION_NOTE}
                    cost = budget
            elif used + cost > budget:
                break
            kept.append((message, entry))
            used += cost
        kept.reverse()

        # History must not start with an assistant turn.
        while kept and kept[0][1]["role"] == "assistant":
            kept.pop(0)

        dropped = max(0, total_usable - len(kept))
        older_exists = dropped > 0 or (
            self._s.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.kind == "message",
                    Message.id < (kept[0][0].id if kept else 0),
                )
                .limit(1)
            )
            is not None
        )
        summary = conversation.summary if older_exists and conversation.summary else ""

        system = build_system_prompt(
            profile=profile, memory=memory, summary=summary or "", environment=environment
        )
        messages = [{"role": "system", "content": system}] + [e for _, e in kept]
        return BuiltContext(
            messages=messages,
            included_message_ids=[m.id for m, _ in kept],
            dropped_count=dropped,
            estimated_tokens=sum(estimate_tokens(m["content"]) for m in messages),
            summary_used=bool(summary),
        )
