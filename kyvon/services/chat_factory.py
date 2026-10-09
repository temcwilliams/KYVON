"""Builds a ChatService outside of any HTTP request (API routes, automations, agents)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from kyvon.services.chat_service import ChatService
from kyvon.services.conversation_service import ConversationService
from kyvon.services.environment_context import render_environment
from kyvon.services.memory_service import MemoryService
from kyvon.services.settings_service import (
    allowed_tool_names,
    get_settings,
    render_profile,
    timezone_for,
)
from kyvon.services.usage_service import UsageGate


def connected_services(services: Any, session: Session, user_id: int, prefs) -> list[str]:
    """Names of integrations that are set up and switched on, for the profile block."""
    from sqlalchemy import select

    from kyvon.models import CalendarAccount

    found = []
    if prefs.calendar_enabled and services.settings.calendar_configured:
        has_account = session.scalar(
            select(CalendarAccount.id).where(CalendarAccount.user_id == user_id)
        )
        found.append("Google Calendar" if has_account else "Google Calendar (not connected yet)")
    if prefs.logseq_enabled and services.logseq is not None:
        found.append("Logseq notes")
    if prefs.hermes_enabled and services.hermes is not None:
        found.append("Hermes agent")
    return found


def make_chat_service(services: Any, session: Session, user_id: int) -> ChatService:
    settings = services.settings
    prefs = get_settings(session, user_id)
    tool_names = allowed_tool_names(services.registry.names(), prefs)
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
            units=prefs.units,
        ),
        profile_text=lambda: render_profile(
            prefs, connected=connected_services(services, session, user_id, prefs)
        ),
        executor=services.executor,
        tool_names=tool_names,
        usage=UsageGate(session, settings, user_id) if settings.hosted else None,
    )
