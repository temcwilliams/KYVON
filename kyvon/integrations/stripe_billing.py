"""Stripe, over its documented REST API (no SDK, so the surface we depend on is small and testable).

Used for: creating a customer, a Checkout session (to subscribe), a Customer Portal session (to
manage or cancel), cancelling a subscription when an account is deleted, and verifying the
signature on webhooks. Nothing here is ever called with card details: those go straight from the
person's browser to Stripe's hosted pages.

NOT verified against live Stripe: it follows Stripe's published request and signature formats and is
tested with fakes. Use Stripe's test mode first.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

from kyvon.services.errors import IntegrationError

API = "https://api.stripe.com/v1"
TIMEOUT = 15
WEBHOOK_TOLERANCE_SECONDS = 300


class WebhookError(ValueError):
    """The webhook was not signed correctly, or is too old."""


def verify_webhook(
    payload: bytes,
    header: str,
    secret: str,
    *,
    tolerance: int = WEBHOOK_TOLERANCE_SECONDS,
    now: Callable[[], float] = time.time,
) -> dict:
    """Check ``Stripe-Signature`` over the raw body and return the parsed event.

    The header looks like ``t=1492774577,v1=<hex>[,v1=<hex>...]``; the signature is HMAC-SHA256 of
    ``"<t>.<raw body>"`` with the endpoint's signing secret. Old timestamps are refused so a captured
    webhook cannot be replayed later.
    """
    if not secret:
        raise WebhookError("Webhook secret is not configured.")
    timestamp = ""
    signatures: list[str] = []
    for part in (header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp.isdigit() or not signatures:
        raise WebhookError("Malformed signature header.")
    if abs(now() - int(timestamp)) > tolerance:
        raise WebhookError("Signature timestamp is outside the allowed window.")
    expected = hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"." + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise WebhookError("Signature does not match.")
    try:
        event = json.loads(payload)
    except ValueError as error:
        raise WebhookError("Body is not JSON.") from error
    if not isinstance(event, dict) or "id" not in event or "type" not in event:
        raise WebhookError("Body is not a Stripe event.")
    return event


class StripeClient:
    def __init__(self, http: Any, secret_key: str):
        self._http = http
        self._key = secret_key

    def _call(self, method: str, path: str, data: dict | None = None, *, idem: str | None = None):
        headers = {"Authorization": f"Bearer {self._key}"}
        if idem:
            headers["Idempotency-Key"] = idem
        try:
            response = self._http.request(
                method,
                f"{API}{path}",
                headers=headers,
                data=data,
                timeout=TIMEOUT,
                allow_redirects=False,
            )
        except Exception as error:  # network trouble: never echo details that could hold a key
            raise IntegrationError(
                f"Stripe could not be reached ({type(error).__name__})."
            ) from error
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
            raise IntegrationError(f"Stripe refused the request: {message or response.status_code}")
        return body

    def create_customer(self, *, email: str, user_id: int) -> str:
        body = self._call(
            "POST",
            "/customers",
            {"email": email, "metadata[user_id]": str(user_id)},
            idem=f"kyvon-customer-{user_id}",
        )
        return body["id"]

    def create_checkout_session(
        self, *, customer_id: str, price_id: str, user_id: int, success_url: str, cancel_url: str
    ) -> str:
        body = self._call(
            "POST",
            "/checkout/sessions",
            {
                "mode": "subscription",
                "customer": customer_id,
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "client_reference_id": str(user_id),
                "subscription_data[metadata][user_id]": str(user_id),
                "success_url": success_url,
                "cancel_url": cancel_url,
                "allow_promotion_codes": "true",
            },
        )
        return body["url"]

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        body = self._call(
            "POST", "/billing_portal/sessions", {"customer": customer_id, "return_url": return_url}
        )
        return body["url"]

    def cancel_subscription(self, subscription_id: str) -> None:
        self._call("DELETE", f"/subscriptions/{subscription_id}")


def build_stripe(settings, http) -> StripeClient | None:
    if not settings.billing_configured:
        return None
    return StripeClient(http, settings.stripe_secret_key)
