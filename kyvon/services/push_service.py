"""Push subscriptions and delivery. Delivery is best effort: the inbox is the record."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kyvon.db import utcnow
from kyvon.integrations.webpush import WebPushError, WebPushSender, is_allowed_endpoint
from kyvon.models import PushSubscription
from kyvon.services.errors import ValidationFailure

log = logging.getLogger("kyvon.push")
MAX_PER_USER = 10


def subscribe_web(
    session: Session, user_id: int, endpoint: str, keys: dict, user_agent: str = ""
) -> PushSubscription:
    if not is_allowed_endpoint(endpoint):
        raise ValidationFailure("That push endpoint is not from a supported push service.")
    if not isinstance(keys, dict) or not keys.get("p256dh") or not keys.get("auth"):
        raise ValidationFailure("The subscription is missing its encryption keys.")
    existing = session.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if existing is not None and existing.user_id != user_id:
        session.delete(existing)  # the browser was re-used by another account: re-home it
        session.flush()
        existing = None
    if existing is None:
        count = len(
            session.scalars(
                select(PushSubscription.id).where(PushSubscription.user_id == user_id)
            ).all()
        )
        if count >= MAX_PER_USER:
            raise ValidationFailure("Too many devices are subscribed. Remove one first.")
        existing = PushSubscription(user_id=user_id, kind="webpush", endpoint=endpoint)
        session.add(existing)
    existing.keys = {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])}
    existing.user_agent = user_agent[:200]
    session.commit()
    return existing


def register_apns(
    session: Session, user_id: int, device_token: str, user_agent: str = ""
) -> PushSubscription:
    """Store an iOS device token. Sending needs Apple credentials and is not implemented yet."""
    token = (device_token or "").strip()
    if not token or len(token) > 300 or not all(c.isalnum() for c in token):
        raise ValidationFailure("That does not look like an APNs device token.")
    existing = session.scalar(select(PushSubscription).where(PushSubscription.endpoint == token))
    if existing is None:
        existing = PushSubscription(user_id=user_id, kind="apns", endpoint=token)
        session.add(existing)
    existing.user_id = user_id
    existing.user_agent = user_agent[:200]
    session.commit()
    return existing


def unsubscribe(session: Session, user_id: int, endpoint: str) -> bool:
    result = session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )
    session.commit()
    return result.rowcount > 0


class PushService:
    """Delivers a notification to every Web Push subscription of a user."""

    def __init__(self, sender: WebPushSender):
        self._sender = sender

    def send(
        self, session: Session, user_id: int, title: str, body: str, note_id: int | None = None
    ) -> int:
        delivered = 0
        subs = session.scalars(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id, PushSubscription.kind == "webpush"
            )
        ).all()
        for sub in subs:
            try:
                self._sender.send(
                    sub.endpoint,
                    sub.keys or {},
                    {
                        "title": title,
                        "body": body[:240],
                        "url": "/",
                        "tag": f"kyvon-{note_id or 0}",
                    },
                )
                sub.last_success_at = utcnow()
                delivered += 1
            except WebPushError as error:
                if error.gone:
                    session.delete(sub)  # the user removed the app or revoked permission
                else:
                    log.warning("push failed: %s", error)
            except Exception:
                log.exception("push delivery error")
        session.commit()
        return delivered


def build_push(settings: Any, http: Any) -> PushService | None:
    if not settings.push_configured:
        return None
    return PushService(
        WebPushSender(
            http,
            public_key=settings.vapid_public_key,
            private_key=settings.vapid_private_key,
            subject=settings.vapid_subject,
        )
    )
