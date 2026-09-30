"""Builds a ChatService outside of any HTTP request (API routes, automations, agents)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from kyvon.services.chat_service import ChatService
from kyvon.services.conversation_service import ConversationService
from kyvon.services.environment_context import render_environment
from kyvon.services.memory_service import MemoryService
from kyvon.services.settings_service import timezone_for


def make_chat_service(services: Any, session: Session, user_id: int) -> ChatService:
    settings = services.settings
    return ChatService(
        session=session,
        settings=settings,
        llm=services.llm,
        user_id=user_id,
        conversations=ConversationService(session, user_id),
        memory=MemoryService(
            session,
            user_id,
            max_memories=settings.memory_max,
            retrieval_k=settings.memory_retrieval_k,
        ),
        environment_text=lambda: render_environment(
            services.environment_cache.get(user_id),
            timezone=timezone_for(session, user_id, services.environment_cache.get(user_id)),
        ),
        executor=services.executor,
    )
