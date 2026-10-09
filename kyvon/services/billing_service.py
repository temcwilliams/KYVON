"""Subscriptions and plan entitlement (filled in by the billing phase)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from kyvon.models import User


def entitled_plan(session: Session, user: User) -> str:
    """'pro' while a paid subscription is in good standing, otherwise 'free'."""
    return "free"
