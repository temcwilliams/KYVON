"""Chat orchestration: memory shortcuts, web search, or a normal model reply.

Routing order and response shapes match the prototype's /api/chat route.
"""

from __future__ import annotations

from typing import Protocol

from kyvon.llm.base import LLMClient
from kyvon.llm.prompts import DEFAULT_ENVIRONMENT, WEB_SYSTEM_PROMPT, build_system_prompt
from kyvon.services.memory_service import parse_memory_shortcut

MEMORY_SAVED_TEXT = "Understood. I have saved that to my memory."
WEB_PROMPT_TEXT = "What would you like me to research?"
WEB_PREFIX = "web "

CHAT_TEMPERATURE = 0.7
MAX_TOKENS = 1500


class MemoryPort(Protocol):
    def add(self, text: str) -> None: ...

    def prompt_text(self) -> str: ...


class ChatInputError(ValueError):
    """The message is missing or blank."""


class ChatService:
    def __init__(self, llm: LLMClient, memory: MemoryPort, *, model: str, web_model: str):
        self._llm = llm
        self._memory = memory
        self._model = model
        self._web_model = web_model

    def reply(self, message: str, environment: str | None = None) -> dict:
        message = message.strip()
        if not message:
            raise ChatInputError("Empty message.")

        # 1. Memory shortcuts (no model call).
        memory_text = parse_memory_shortcut(message)
        if memory_text is not None:
            self._memory.add(memory_text)
            return {"response": MEMORY_SAVED_TEXT, "memory_saved": True}

        # 2. Web research.
        if message.lower().startswith(WEB_PREFIX):
            query = message[len(WEB_PREFIX) :].strip()
            if not query:
                return {"response": WEB_PROMPT_TEXT}
            return {"response": self._web_search(query), "web": True}

        # 3. Normal conversation.
        return {"response": self._ask(message, environment)}

    def _ask(self, message: str, environment: str | None) -> str:
        prompt = build_system_prompt(
            self._memory.prompt_text(),
            environment if environment is not None else DEFAULT_ENVIRONMENT,
        )
        return self._llm.complete(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            model=self._model,
            temperature=CHAT_TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )

    def _web_search(self, query: str) -> str:
        return self._llm.complete(
            [
                {"role": "system", "content": WEB_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            model=self._web_model,
            max_tokens=MAX_TOKENS,
        )
