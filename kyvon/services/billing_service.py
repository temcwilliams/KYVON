"""Subscriptions: who is on the paid plan, kept in step with Stripe by signed webhooks.

Stripe is the source of truth. We store the last state it told us about, apply events at most once
(by event id), ignore events older than what we already hold (Stripe does not guarantee order), and
treat anything unexpected as "free": the safe direction for cost.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kyvon.config import Settings
from kyvon.db import utcnow
from kyvon.models import BillingEvent, Subscription, User
from kyvon.services.errors import ConflictError, IntegrationError, NotConnectedError

log = logging.getLogger("kyvon.billing")

PAID_STATES = ("active", "trialing")


def subscription_for(session: Session, user_id: int) -> Subscription | None:
    return session.scalar(select(Subscription).where(Subscription.user_id == user_id))


def entitled_plan(
    session: Session,
    user: User,
    *,
    now: Callable[[], datetime] = utcnow,
    grace_days: int = 3,
) -> str:
    """'pro' while a paid subscription is in good standing, otherwise 'free'.

    A payment that failed (``past_due``) keeps the paid plan for a short grace period after the
    period ended so a card hiccup does not cut someone off mid-conversation.
    """
    sub = subscription_for(session, user.id)
    if sub is None:
        return "free"
    if sub.status in PAID_STATES:
        return "pro"
    if sub.status == "past_due" and sub.current_period_end is not None:
        if now() < sub.current_period_end + timedelta(days=grace_days):
            return "pro"
    return "free"


def _from_unix(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC) if value else None
    except (TypeError, ValueError, OverflowError):
        return None


def _period_end(obj: dict) -> datetime | None:
    """Stripe moved the period end onto subscription items in newer API versions: accept both."""
    if obj.get("current_period_end"):
        return _from_unix(obj["current_period_end"])
    items = (obj.get("items") or {}).get("data") or []
    for item in items:
        if item.get("current_period_end"):
            return _from_unix(item["current_period_end"])
    return None


class BillingService:
    def __init__(self, session: Session, settings: Settings, stripe: Any):
        self._s = session
        self._settings = settings
        self._stripe = stripe

    # ----------------------------------------------------------- customer pages

    def _client(self):
        if self._stripe is None:
            raise NotConnectedError("Billing is not available on this server.")
        return self._stripe

    def _customer_id(self, user: User) -> str:
        sub = subscription_for(self._s, user.id)
        if sub is not None:
            return sub.stripe_customer_id
        customer_id = self._client().create_customer(email=user.email or "", user_id=user.id)
        self._s.add(Subscription(user_id=user.id, stripe_customer_id=customer_id, status="none"))
        try:
            self._s.commit()
        except IntegrityError:  # a double click created it first
            self._s.rollback()
            existing = subscription_for(self._s, user.id)
            if existing is not None:
                return existing.stripe_customer_id
            raise
        return customer_id

    def checkout_url(self, user: User) -> str:
        if not user.email_verified:
            raise ConflictError("Confirm your email address before subscribing.")
        if entitled_plan(self._s, user, grace_days=self._settings.billing_grace_days) == "pro":
            raise ConflictError(
                "You already have the paid plan. Manage it from the billing portal."
            )
        base = self._settings.public_url.rstrip("/")
        return self._client().create_checkout_session(
            customer_id=self._customer_id(user),
            price_id=self._settings.stripe_price_id,
            user_id=user.id,
            success_url=f"{base}/#billing=success",
            cancel_url=f"{base}/#billing=cancelled",
        )

    def portal_url(self, user: User) -> str:
        sub = subscription_for(self._s, user.id)
        if sub is None:
            raise ConflictError("There is no subscription to manage yet.")
        return self._client().create_portal_session(
            customer_id=sub.stripe_customer_id,
            return_url=self._settings.public_url.rstrip("/") + "/",
        )

    def status(self, user: User) -> dict:
        sub = subscription_for(self._s, user.id)
        plan = entitled_plan(self._s, user, grace_days=self._settings.billing_grace_days)
        return {
            "configured": self._stripe is not None,
            "plan": plan,
            "status": sub.status if sub else "none",
            "current_period_end": sub.current_period_end.isoformat()
            if sub and sub.current_period_end
            else None,
            "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
            "price_label": self._settings.price_label,
        }

    # -------------------------------------------------------------------- hooks

    def cancel_before_deletion(self, user: User) -> None:
        """Stop charging before an account is deleted. If Stripe cannot confirm, deletion is refused:
        deleting the data while the card is still being billed would be the worst outcome."""
        sub = subscription_for(self._s, user.id)
        if sub is None or not sub.stripe_subscription_id or sub.status in ("canceled", "none"):
            return
        try:
            self._client().cancel_subscription(sub.stripe_subscription_id)
        except (IntegrationError, NotConnectedError) as error:
            raise IntegrationError(
                "We could not cancel your subscription just now, so your account was not deleted. "
                "Please try again in a few minutes."
            ) from error

    # ------------------------------------------------------------------ webhooks

    def apply_event(self, event: dict, *, now: Callable[[], datetime] = utcnow) -> bool:
        """Apply one verified Stripe event. Returns False if it was already processed."""
        self._s.add(
            BillingEvent(stripe_event_id=event["id"], type=event["type"], processed_at=now())
        )
        try:
            self._s.flush()
        except IntegrityError:
            self._s.rollback()
            return False  # a replay or a retry: nothing to do

        obj = (event.get("data") or {}).get("object") or {}
        handler = {
            "checkout.session.completed": self._checkout_completed,
            "customer.subscription.created": self._subscription_changed,
            "customer.subscription.updated": self._subscription_changed,
            "customer.subscription.deleted": self._subscription_deleted,
            "invoice.payment_failed": self._payment_failed,
            "invoice.paid": self._payment_succeeded,
        }.get(event["type"])
        if handler is not None:
            handler(obj, int(event.get("created") or 0), now())
        self._s.commit()
        return True

    def _find(self, obj: dict) -> Subscription | None:
        customer = obj.get("customer")
        if isinstance(customer, str):
            sub = self._s.scalar(
                select(Subscription).where(Subscription.stripe_customer_id == customer)
            )
            if sub is not None:
                return sub
        meta = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
        if meta and str(meta).isdigit() and self._s.get(User, int(meta)) is not None:
            return subscription_for(self._s, int(meta))
        return None

    def _stale(self, sub: Subscription, created: int) -> bool:
        return bool(created) and created < sub.last_event_at

    def _touch(self, sub: Subscription, created: int, current: datetime) -> None:
        sub.last_event_at = max(sub.last_event_at, created)
        sub.updated_at = current

    def _checkout_completed(self, obj: dict, created: int, current: datetime) -> None:
        sub = self._find(obj)
        if sub is None:
            log.warning("checkout completed for an unknown customer")
            return
        if self._stale(sub, created):
            return
        if obj.get("subscription"):
            sub.stripe_subscription_id = obj["subscription"]
        if obj.get("payment_status") in ("paid", "no_payment_required"):
            sub.status = "active"
        self._touch(sub, created, current)

    def _subscription_changed(self, obj: dict, created: int, current: datetime) -> None:
        sub = self._find(obj)
        if sub is None:
            log.warning("subscription event for an unknown customer")
            return
        if self._stale(sub, created):
            return
        sub.stripe_subscription_id = obj.get("id") or sub.stripe_subscription_id
        sub.status = str(obj.get("status") or sub.status)[:24]
        sub.current_period_end = _period_end(obj) or sub.current_period_end
        sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
        self._touch(sub, created, current)

    def _subscription_deleted(self, obj: dict, created: int, current: datetime) -> None:
        sub = self._find(obj)
        if sub is None or self._stale(sub, created):
            return
        sub.status = "canceled"
        sub.cancel_at_period_end = False
        self._touch(sub, created, current)

    def _payment_failed(self, obj: dict, created: int, current: datetime) -> None:
        sub = self._find(obj)
        if sub is None or self._stale(sub, created):
            return
        sub.status = "past_due"
        self._touch(sub, created, current)

    def _payment_succeeded(self, obj: dict, created: int, current: datetime) -> None:
        sub = self._find(obj)
        if sub is None or self._stale(sub, created):
            return
        if sub.status in ("past_due", "incomplete", "unpaid"):
            sub.status = "active"
        self._touch(sub, created, current)
