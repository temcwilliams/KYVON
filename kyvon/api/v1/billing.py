"""Subscription billing (hosted mode): status, checkout, customer portal, and Stripe's webhook."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from kyvon.api.deps import enforce_ip_rate, get_session, login_required, services
from kyvon.api.errors import ApiError
from kyvon.integrations.stripe_billing import WebhookError, verify_webhook
from kyvon.services.billing_service import BillingService

bp = Blueprint("billing", __name__, url_prefix="/api/v1/billing")

MAX_WEBHOOK_BYTES = 512_000


def _service() -> BillingService:
    svc = services()
    if not svc.settings.hosted:
        raise ApiError(404, "not_found", "Not found.")
    return BillingService(get_session(), svc.settings, svc.stripe)


@bp.get("")
@login_required
def status():
    return jsonify(_service().status(g.user))


@bp.post("/checkout")
@login_required
def checkout():
    """A Stripe-hosted page where the person subscribes. Card details never touch KYVON."""
    return jsonify({"url": _service().checkout_url(g.user)})


@bp.post("/portal")
@login_required
def portal():
    """Stripe's page to update the card, see invoices, or cancel."""
    return jsonify({"url": _service().portal_url(g.user)})


@bp.post("/webhook")
def webhook():
    """Stripe calls this. It is public by necessity, so the signature is the only thing trusted."""
    svc = services()
    if not svc.settings.billing_configured:
        raise ApiError(404, "not_found", "Not found.")
    enforce_ip_rate("webhook", 600)
    if (request.content_length or 0) > MAX_WEBHOOK_BYTES:
        raise ApiError(413, "too_large", "That request is too large.")
    try:
        event = verify_webhook(
            request.get_data(),
            request.headers.get("Stripe-Signature", ""),
            svc.settings.stripe_webhook_secret,
        )
    except WebhookError as error:
        raise ApiError(400, "invalid_signature", "The signature could not be verified.") from error
    applied = BillingService(get_session(), svc.settings, svc.stripe).apply_event(event)
    return jsonify({"received": True, "applied": applied})
