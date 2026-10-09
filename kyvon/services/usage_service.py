"""Monthly usage metering and quotas for the hosted service.

Every action that costs money (a model call, a transcription, a web search) is checked against
the person's plan *before* it runs and recorded *after*. Allowances are per calendar month (UTC).
Personal installs have no limits: the gate is only built in hosted mode.

Limits are checked, not locked: two simultaneous requests can both pass just under a limit, so the
cap can be overshot by the size of one request. That is accepted; the monthly token cap, not any
single request, is what protects the bill.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kyvon.config import Settings
from kyvon.db import utcnow
from kyvon.models import UsageEvent, User
from kyvon.services.errors import EmailNotVerified, QuotaExceeded

LIMIT_NAMES = ("messages", "tokens", "voice", "searches")


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """(first instant of this month, first instant of next month), both UTC."""
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    nxt = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC)
    return start, nxt


def plan_for(session: Session, user: User, *, grace_days: int = 3) -> str:
    """'admin' (unlimited), 'pro' or 'free'. Billing decides pro (see billing_service)."""
    if user.is_admin:
        return "admin"
    from kyvon.services import billing_service

    return billing_service.entitled_plan(session, user, grace_days=grace_days)


def limits_for(settings: Settings, plan: str) -> dict[str, int] | None:
    """The monthly allowances for a plan, or None for no limit."""
    if plan == "admin":
        return None
    prefix = "pro" if plan == "pro" else "free"
    return {name: getattr(settings, f"quota_{prefix}_{name}") for name in LIMIT_NAMES}


def totals(session: Session, user_id: int, start: datetime) -> dict[str, int]:
    rows = session.execute(
        select(
            UsageEvent.kind,
            func.count(),
            func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
        )
        .where(UsageEvent.user_id == user_id, UsageEvent.created_at >= start)
        .group_by(UsageEvent.kind)
    ).all()
    out = {"messages": 0, "tokens": 0, "voice": 0, "searches": 0}
    for kind, count, tokens in rows:
        out["tokens"] += int(tokens)
        if kind == "chat":
            out["messages"] += count
        elif kind == "voice":
            out["voice"] += count
        elif kind == "search":
            out["searches"] += count
    return out


# What each kind of action must have room for.
_NEEDS = {
    "chat": ("messages", "tokens"),
    "agent": ("tokens",),
    "search": ("searches", "tokens"),
    "voice": ("voice",),
}


class UsageGate:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        user_id: int,
        *,
        now: Callable[[], datetime] = utcnow,
    ):
        self._s = session
        self._settings = settings
        self._user_id = user_id
        self._now = now

    def _user(self) -> User:
        user = self._s.get(User, self._user_id)
        if user is None:
            raise EmailNotVerified("Unknown account.")
        return user

    def check(self, kind: str) -> None:
        """Raise EmailNotVerified or QuotaExceeded if ``kind`` of action is not allowed now."""
        user = self._user()
        plan = plan_for(self._s, user, grace_days=self._settings.billing_grace_days)
        if plan == "admin":
            return
        if not user.email_verified:
            raise EmailNotVerified("Confirm your email address first.")
        limits = limits_for(self._settings, plan) or {}
        start, resets = month_bounds(self._now())
        used = totals(self._s, user.id, start)
        for name in _NEEDS[kind]:
            if used[name] >= limits[name]:
                raise QuotaExceeded(
                    name,
                    limit=limits[name],
                    used=used[name],
                    plan=plan,
                    resets_at=resets.isoformat(),
                )

    def record(self, kind: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self._s.add(
            UsageEvent(
                user_id=self._user_id,
                kind=kind,
                tokens_in=max(0, int(tokens_in or 0)),
                tokens_out=max(0, int(tokens_out or 0)),
                created_at=self._now(),
            )
        )
        self._s.commit()


def summary(
    session: Session, settings: Settings, user: User, *, now: datetime | None = None
) -> dict:
    """The plan, allowances, usage so far and reset date, for the account screen."""
    current = now or utcnow()
    plan = plan_for(session, user, grace_days=settings.billing_grace_days)
    start, resets = month_bounds(current)
    used = totals(session, user.id, start)
    limits = limits_for(settings, plan)
    return {
        "plan": plan,
        "period_start": start.isoformat(),
        "resets_at": resets.isoformat(),
        "limits": limits,  # None means unlimited
        "used": used,
        "remaining": None
        if limits is None
        else {name: max(0, limits[name] - used[name]) for name in LIMIT_NAMES},
        "email_verified": user.email_verified,
    }


def top_users(session: Session, *, days: int = 30, limit: int = 20, now: datetime | None = None):
    """Biggest consumers, for the admin view: who is costing the most tokens."""
    from datetime import timedelta

    since = (now or utcnow()) - timedelta(days=days)
    rows = session.execute(
        select(
            UsageEvent.user_id,
            func.count(),
            func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
        )
        .where(UsageEvent.created_at >= since)
        .group_by(UsageEvent.user_id)
        .order_by(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out).desc())
        .limit(limit)
    ).all()
    return [{"user_id": u, "events": int(n), "tokens": int(t)} for u, n, t in rows]
