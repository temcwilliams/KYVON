"""One conversational turn: persistence, routing, context, model call, streaming.

``ChatService.turn`` is a generator of events, so the plain JSON endpoint and the
streaming (SSE) endpoint share exactly one implementation. Whatever happens (model
error, client disconnect), the assistant message row ends up saved with an honest status.

Routing order is unchanged from the prototype: memory shortcut -> ``web`` research ->
normal model reply.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from kyvon.config import Settings
from kyvon.llm.base import LLMClient, LLMResponse
from kyvon.llm.prompts import WEB_SYSTEM_PROMPT
from kyvon.models import Conversation, Message
from kyvon.services.context_builder import ContextBuilder, ContextLimits
from kyvon.services.conversation_service import (
    ConversationService,
    serialize_conversation,
    serialize_message,
    title_from_text,
)
from kyvon.services.errors import ValidationFailure
from kyvon.services.memory_service import (
    MemoryService,
    parse_memory_shortcut,
    parse_recall_request,
)
from kyvon.services.summarizer import Summarizer
from kyvon.tools.executor import CallOrigin, ToolExecutor, serialize_tool_run

log = logging.getLogger("kyvon.chat")

MEMORY_SAVED_TEXT = "Understood. I have saved that to my memory."
MEMORY_DUPLICATE_TEXT = "I already have that saved."
WEB_PROMPT_TEXT = "What would you like me to research?"
WEB_PREFIX = "web "
CHAT_TEMPERATURE = 0.7
MAX_TOKENS = 1500
MAX_CALLS_PER_ROUND = 5

TITLE_PROMPT = (
    "Write a short title (at most 6 words, no quotes, no trailing punctuation) for a "
    "conversation that starts with the exchange below. Output only the title."
)


class ChatInputError(ValidationFailure):
    """The message is missing or blank."""


class ChatFailed(RuntimeError):
    """The turn failed; the persisted assistant message carries the error."""

    def __init__(self, message: str, *, conversation_id: int, message_id: int | None):
        super().__init__(message)
        self.conversation_id = conversation_id
        self.message_id = message_id


@dataclass
class TurnResult:
    conversation: dict
    user_message: dict
    message: dict
    flags: dict


class ChatService:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        llm: LLMClient,
        user_id: int,
        conversations: ConversationService,
        memory: MemoryService,
        environment_text: Callable[[], str],
        profile_text: Callable[[], str] = lambda: "",
        executor: ToolExecutor | None = None,
        tool_names: set[str] | None = None,
    ):
        self._s = session
        self._settings = settings
        self._llm = llm
        self._user_id = user_id
        self._conversations = conversations
        self._memory = memory
        self._environment_text = environment_text
        self._profile_text = profile_text
        self._executor = executor
        self._tool_names = tool_names  # None: every enabled tool
        self._limits = ContextLimits(
            max_tokens=settings.context_max_tokens,
            max_messages=settings.context_max_messages,
            reserve_tokens=settings.context_reserve_tokens,
        )

    # ------------------------------------------------------------------ public

    def turn(self, message: str, conversation_id: int | None = None) -> Iterator[dict]:
        text = (message or "").strip()
        if not text:
            raise ChatInputError("Empty message.")

        conversation = (
            self._conversations.get(conversation_id)
            if conversation_id is not None
            else self._conversations.create()
        )
        first_exchange = self._conversations.message_count(conversation.id) == 0
        user_row = self._conversations.add_message(conversation, "user", text)
        if first_exchange and not conversation.title:
            conversation.title = title_from_text(text)
            self._s.commit()

        yield {
            "type": "start",
            "conversation": serialize_conversation(conversation),
            "user_message": serialize_message(user_row),
        }

        shortcut = parse_memory_shortcut(text)
        if shortcut is not None:
            yield from self._remember(conversation, user_row, shortcut)
            return

        is_recall, topic = parse_recall_request(text)
        if is_recall:
            yield from self._finish_fixed(
                conversation, user_row, self._memory.recall_text(topic), {"recall": True}
            )
            return

        if text.lower().startswith(WEB_PREFIX):
            query = text[len(WEB_PREFIX) :].strip()
            if not query:
                yield from self._finish_fixed(conversation, user_row, WEB_PROMPT_TEXT, {})
                return
            yield from self._web(conversation, user_row, query)
            return

        yield from self._converse(conversation, user_row, first_exchange)

    def reply(self, message: str, conversation_id: int | None = None) -> TurnResult:
        """Run a turn to completion (used by the non-streaming endpoint)."""
        conversation = user_message = result = None
        # Exhaust the generator (rather than returning at "done") so that the
        # post-turn housekeeping - summary, title - runs too.
        for event in self.turn(message, conversation_id):
            if event["type"] == "start":
                conversation, user_message = event["conversation"], event["user_message"]
            elif event["type"] == "error":
                raise ChatFailed(
                    event["message"],
                    conversation_id=conversation["id"],
                    message_id=event.get("message_id"),
                )
            elif event["type"] == "done":
                result = TurnResult(
                    conversation=event.get("conversation", conversation),
                    user_message=user_message,
                    message=event["message"],
                    flags=event.get("flags", {}),
                )
        if result is None:  # pragma: no cover
            raise RuntimeError("Turn ended without a result.")
        return result

    # ------------------------------------------------------------------ paths

    def _finish_fixed(
        self, conversation: Conversation, user_row: Message, text: str, flags: dict
    ) -> Iterator[dict]:
        row = self._conversations.add_message(conversation, "assistant", text)
        yield {"type": "delta", "text": text}
        yield self._done(conversation, row, flags)

    def _remember(self, conversation: Conversation, user_row: Message, text: str) -> Iterator[dict]:
        try:
            result = self._memory.add(text)
        except ValidationFailure as problem:
            # Not an error: explain why nothing was saved (too short, looks like a secret...).
            yield from self._finish_fixed(
                conversation, user_row, str(problem), {"memory_saved": False}
            )
            return
        reply = MEMORY_SAVED_TEXT if result.created else MEMORY_DUPLICATE_TEXT
        yield from self._finish_fixed(
            conversation, user_row, reply, {"memory_saved": result.created}
        )

    def _retrieval_query(self, user_row: Message) -> str:
        """What to match memories against: this message plus the previous user message,
        so a follow-up like "and tomorrow?" still finds the right memories."""
        previous = self._s.scalar(
            select(Message.content)
            .where(
                Message.conversation_id == user_row.conversation_id,
                Message.role == "user",
                Message.kind == "message",
                Message.id < user_row.id,
            )
            .order_by(Message.id.desc())
            .limit(1)
        )
        return f"{previous[:300]} {user_row.content}" if previous else user_row.content

    def _web(self, conversation: Conversation, user_row: Message, query: str) -> Iterator[dict]:
        row = self._conversations.add_message(
            conversation, "assistant", "", status="partial", model=self._settings.web_model
        )
        try:
            answer = self._run_web_search(conversation, query)
        except Exception as error:
            yield from self._fail(conversation, row, error)
            return
        self._conversations.finish_message(row, content=answer, model=self._settings.web_model)
        yield {"type": "delta", "text": answer}
        yield self._done(conversation, row, {"web": True})

    def _run_web_search(self, conversation: Conversation, query: str) -> str:
        """The ``web `` shortcut runs the same audited tool the model would use."""
        if self._executor is None:
            return self._llm.complete(
                [
                    {"role": "system", "content": WEB_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                model=self._settings.web_model,
                max_tokens=MAX_TOKENS,
            )
        outcome = self._executor.call(
            self._s,
            CallOrigin(self._user_id, conversation.id, origin="chat"),
            "web_search",
            {"query": query},
        )
        if outcome.status != "succeeded":
            raise RuntimeError(outcome.content.get("error", "The web search failed."))
        return outcome.content["data"]["answer"]

    def _tool_specs(self) -> list[dict]:
        if self._executor is None:
            return []
        return self._executor.specs(self._tool_names)

    def _converse(
        self, conversation: Conversation, user_row: Message, first_exchange: bool
    ) -> Iterator[dict]:
        row = self._conversations.add_message(
            conversation, "assistant", "", status="partial", model=self._settings.model
        )
        built = ContextBuilder(self._s, self._limits).build(
            conversation,
            profile=self._profile_text(),
            memory=self._memory.retrieve_text(self._retrieval_query(user_row)),
            reference=self._tool_digest(conversation),
            environment=self._environment_text(),
        )
        # The empty placeholder row is not part of the history sent to the model.
        messages = list(built.messages)
        specs = self._tool_specs()
        origin = CallOrigin(self._user_id, conversation.id, origin="chat")
        max_rounds = self._settings.tool_max_iterations

        pieces: list[str] = []  # all assistant text, across tool rounds
        tokens_in = tokens_out = 0
        saw_usage = False
        last_model = self._settings.model
        pending_runs: list[int] = []

        try:
            for round_no in range(max_rounds + 1):
                # On the last round tools are withheld, forcing a final written answer.
                offer_tools = specs if round_no < max_rounds else None
                response: LLMResponse | None = None
                round_text: list[str] = []
                if pieces:
                    pieces.append("\n\n")
                    yield {"type": "delta", "text": "\n\n"}
                for event in self._llm.stream_chat(
                    messages,
                    model=self._settings.model,
                    tools=offer_tools,
                    temperature=CHAT_TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                ):
                    if event.type == "text":
                        round_text.append(event.text)
                        pieces.append(event.text)
                        yield {"type": "delta", "text": event.text}
                    elif event.type == "done":
                        response = event.response
                if response is not None:
                    last_model = response.model or last_model
                    if response.usage:
                        saw_usage = True
                        tokens_in += response.usage.prompt_tokens or 0
                        tokens_out += response.usage.completion_tokens or 0

                if response is None or not response.tool_calls or self._executor is None:
                    break

                yield from self._run_tools(conversation, origin, response, messages, pending_runs)
        except GeneratorExit:
            # The client went away mid-stream: keep what was generated, flagged as partial.
            self._conversations.finish_message(
                row, content="".join(pieces).strip(), status="partial", model=last_model
            )
            raise
        except Exception as error:
            yield from self._fail(conversation, row, error, keep_partial="".join(pieces).strip())
            return

        content = "".join(pieces).strip()
        self._conversations.finish_message(
            row,
            content=content,
            model=last_model,
            tokens_in=tokens_in if saw_usage else None,
            tokens_out=tokens_out if saw_usage else None,
        )
        flags: dict = {}
        if pending_runs:
            flags["pending_confirmations"] = self._pending_payload(pending_runs)
        yield self._done(conversation, row, flags)
        self._after_turn(conversation, user_row, row, built.included_message_ids, first_exchange)

    def _run_tools(
        self,
        conversation: Conversation,
        origin: CallOrigin,
        response: LLMResponse,
        messages: list[dict],
        pending_runs: list[int],
    ) -> Iterator[dict]:
        """Execute the tool calls the model asked for and feed the results back."""
        calls = response.tool_calls
        messages.append(
            {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in calls
                ],
            }
        )
        self._conversations.add_message(
            conversation,
            "assistant",
            response.content or "",
            kind="tool_call",
            tool_calls=[
                {"id": c.id, "name": c.name, "arguments": c.arguments[:2000]} for c in calls
            ],
        )
        for index, call in enumerate(calls):
            if index >= MAX_CALLS_PER_ROUND:
                text = json.dumps(
                    {"ok": False, "error": "Too many tool calls at once; call skipped."}
                )
                outcome = None
            else:
                yield {"type": "tool", "name": call.name, "status": "running"}
                try:
                    outcome = self._executor.call(
                        self._s, origin, call.name, call.arguments, call_id=call.id
                    )
                    text = outcome.for_model()
                except Exception:  # the executor itself should not raise; be safe
                    log.exception("tool executor failed")
                    text = json.dumps({"ok": False, "error": "The tool could not be run."})
                    outcome = None
                    self._s.rollback()
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
            self._conversations.add_message(
                conversation,
                "tool",
                text[:4000],
                kind="tool_result",
                tool_call_id=call.id,
                tool_name=call.name,
            )
            yield {
                "type": "tool",
                "name": call.name,
                "status": outcome.status if outcome else "failed",
                "tool_run_id": outcome.run_id if outcome else None,
                "summary": outcome.summary if outcome else "",
            }
            if outcome is not None and outcome.pending and outcome.run_id not in pending_runs:
                pending_runs.append(outcome.run_id)
            if outcome is not None and outcome.status == "succeeded":
                # A delegated agent may have queued actions for the user's approval.
                data = outcome.content.get("data")
                for queued in (data.get("pending_run_ids") or []) if isinstance(data, dict) else []:
                    if queued not in pending_runs:
                        pending_runs.append(queued)

    def _tool_digest(self, conversation: Conversation) -> str:
        """Ids and titles from the last few tool results, so "delete that event" works in a
        later turn. Only a few short structural fields are kept, never whole results."""
        rows = self._s.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.kind == "tool_result")
            .order_by(Message.id.desc())
            .limit(3)
        ).all()
        lines: list[str] = []
        for row in reversed(rows):
            try:
                payload = json.loads(row.content)
            except ValueError:
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            for item in items[:10]:
                if not isinstance(item, dict) or "id" not in item:
                    continue
                fields = [
                    " ".join(str(item[k]).split())[:80]
                    for k in ("title", "name", "start", "due", "status")
                    if item.get(k)
                ]
                lines.append(
                    f"- {row.tool_name}: id={str(item['id'])[:64]} | " + " | ".join(fields)
                )
        return "\n".join(lines[-15:])

    def _pending_payload(self, run_ids: list[int]) -> list[dict]:
        from kyvon.models import ToolRun

        runs = self._s.scalars(select(ToolRun).where(ToolRun.id.in_(run_ids))).all()
        return [serialize_tool_run(r) for r in runs]

    # ------------------------------------------------------------------ helpers

    def _done(self, conversation: Conversation, row: Message, flags: dict) -> dict:
        self._s.refresh(conversation)
        return {
            "type": "done",
            "conversation": serialize_conversation(conversation),
            "message": serialize_message(row),
            "flags": flags,
        }

    def _fail(
        self, conversation: Conversation, row: Message, error: Exception, keep_partial: str = ""
    ) -> Iterator[dict]:
        log.warning("chat turn failed: %s", error)
        message = str(error) or error.__class__.__name__
        # The row keeps any partial text; the error text is what the client is told.
        self._conversations.finish_message(
            row, content=keep_partial or message, status="error", model=row.model
        )
        yield {"type": "error", "message": message, "message_id": row.id}

    def _after_turn(
        self,
        conversation: Conversation,
        user_row: Message,
        assistant_row: Message,
        included_ids: list[int],
        first_exchange: bool,
    ) -> None:
        """Best-effort housekeeping; a failure here must never break the reply."""
        try:
            if first_exchange and self._settings.auto_title_llm:
                self._generate_title(conversation, user_row, assistant_row)
            first_included = min(included_ids) if included_ids else None
            Summarizer(self._s, self._llm, self._settings.model).maybe_update(
                conversation, first_included, trigger=self._settings.summary_trigger_messages
            )
        except Exception:
            log.exception("post-turn housekeeping failed")
            self._s.rollback()

    def _generate_title(
        self, conversation: Conversation, user_row: Message, assistant_row: Message
    ) -> None:
        title = self._llm.complete(
            [
                {"role": "system", "content": TITLE_PROMPT},
                {
                    "role": "user",
                    "content": f"User: {user_row.content[:500]}\nAssistant: "
                    f"{assistant_row.content[:500]}",
                },
            ],
            model=self._settings.model,
            temperature=0.3,
            max_tokens=24,
        )
        self._conversations.set_auto_title(conversation, title)
