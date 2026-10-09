"""Rolling conversation summary, so long chats stay coherent inside the context limit."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from kyvon.llm.base import LLMClient
from kyvon.models import Conversation, Message

MAX_TRANSCRIPT_CHARS = 12_000
MAX_SUMMARY_CHARS = 3_000

SUMMARY_PROMPT = (
    "You maintain a running summary of a conversation between a user and their assistant KYVON. "
    "Update the summary with the new transcript. Keep facts, decisions, preferences, names, "
    "numbers and open questions. Drop small talk. Write plain prose or short bullet points, "
    "at most 250 words. Output only the updated summary."
)


class Summarizer:
    def __init__(self, session: Session, llm: LLMClient, model: str):
        self._s = session
        self._llm = llm
        self._model = model

    def maybe_update(
        self, conversation: Conversation, first_included_id: int | None, *, trigger: int
    ) -> bool:
        """Fold messages that fell out of the context window into the summary.

        Returns True when the summary changed. Failures are the caller's to ignore: a
        missing summary only costs some continuity.
        """
        if first_included_id is None:
            return False
        after = conversation.summary_upto_message_id or 0
        older = list(
            self._s.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.kind == "message",
                    Message.status == "complete",
                    Message.id > after,
                    Message.id < first_included_id,
                )
                .order_by(Message.id)
            )
        )
        if not older:
            return False
        total = self._s.scalar(
            select(Message.id)
            .where(Message.conversation_id == conversation.id, Message.kind == "message")
            .order_by(Message.id.desc())
            .offset(trigger - 1)
            .limit(1)
        )
        if total is None:  # fewer than ``trigger`` messages overall
            return False

        lines = [f"{m.role.upper()}: {m.content}" for m in older]
        transcript = "\n".join(lines)[-MAX_TRANSCRIPT_CHARS:]
        prompt = (
            f"Current summary:\n{conversation.summary or '(none yet)'}\n\n"
            f"New transcript:\n{transcript}"
        )
        text = self._llm.complete(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": prompt},
            ],
            model=self._model,
            temperature=0.2,
            max_tokens=500,
        )
        text = text.strip()
        if not text:
            return False
        conversation.summary = text[:MAX_SUMMARY_CHARS]
        conversation.summary_upto_message_id = older[-1].id
        self._s.commit()
        return True
