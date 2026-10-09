"""Subscriptions: Stripe webhooks, plan entitlement, checkout, deletion, and the client's wire format."""

import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from kyvon.db import utcnow
from kyvon.integrations.stripe_billing import StripeClient, WebhookError, verify_webhook
from kyvon.models import BillingEvent, Subscription, User
from kyvon.services import billing_service
from kyvon.services.errors import IntegrationError
from tests.conftest import make_app
from tests.fakes import FakeEmail, FakeHTTP, FakeHTTPResponse, FakeStripe
from tests.test_hosted_accounts import PASSWORD, hosted_settings, login, make_verified

SECRET = "whsec_test_secret"
EMAIL = "payer@example.com"


def sign(payload: bytes, secret=SECRET, t=None):
    t = int(time.time()) if t is None else t
    digest = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={digest}"


@pytest.fixture
def shop(tmp_path, fake_llm, fake_environment, fake_stt):
    app = make_app(
        hosted_settings(
            tmp_path,
            STRIPE_SECRET_KEY="sk_test_123",
            STRIPE_WEBHOOK_SECRET=SECRET,
            STRIPE_PRICE_ID="price_123",
            KYVON_PRICE_LABEL="$9 / month",
            KYVON_QUOTA_FREE_MESSAGES="2",
        ),
        llm=fake_llm,
        environment=fake_environment,
        stt=fake_stt,
    )
    svc = app.extensions["kyvon"]
    svc.email = FakeEmail()
    svc.stripe = FakeStripe()
    return app


def event(kind, obj, *, id=None, created=None):
    return {
        "id": id or f"evt_{kind}_{time.time_ns()}",
        "type": kind,
        "created": created or int(time.time()),
        "data": {"object": obj},
    }


def post_event(app, evt, *, secret=SECRET):
    body = json.dumps(evt).encode()
    return app.test_client().post(
        "/api/v1/billing/webhook",
        data=body,
        content_type="application/json",
        headers={"Stripe-Signature": sign(body, secret)},
    )


def subscribe(app, user_id, status="active", *, period_days=30, customer=None, sub_id="sub_1"):
    """Put a user on a subscription the way Stripe's events would."""
    customer = customer or f"cus_{user_id}"
    with app.extensions["kyvon"].session_factory() as s:
        s.add(
            Subscription(
                user_id=user_id,
                stripe_customer_id=customer,
                stripe_subscription_id=sub_id,
                status=status,
                current_period_end=utcnow() + timedelta(days=period_days),
            )
        )
        s.commit()


def plan(app, user_id):
    with app.extensions["kyvon"].session_factory() as s:
        return billing_service.entitled_plan(s, s.get(User, user_id))


# ------------------------------------------------------- signature checking


def test_a_correctly_signed_webhook_is_accepted():
    body = json.dumps({"id": "evt_1", "type": "x"}).encode()
    assert verify_webhook(body, sign(body), SECRET)["id"] == "evt_1"


def test_webhooks_with_a_wrong_secret_tampered_body_or_old_timestamp_are_refused():
    body = json.dumps({"id": "evt_1", "type": "x"}).encode()
    for header, payload in (
        (sign(body, "whsec_other"), body),
        (sign(body), body + b" "),
        (sign(body, t=int(time.time()) - 3600), body),
        (sign(body, t=int(time.time()) + 3600), body),
        ("", body),
        ("garbage", body),
        ("t=abc,v1=ff", body),
    ):
        with pytest.raises(WebhookError):
            verify_webhook(payload, header, SECRET)
    with pytest.raises(WebhookError):
        verify_webhook(body, sign(body), "")  # no secret configured: never trust


def test_any_one_of_several_v1_signatures_may_match():
    body = json.dumps({"id": "evt_1", "type": "x"}).encode()
    header = sign(body) + ",v1=" + "0" * 64
    assert verify_webhook(body, header, SECRET)["id"] == "evt_1"
    with pytest.raises(WebhookError):
        verify_webhook(b"not json", sign(b"not json"), SECRET)


# ----------------------------------------------------------- the endpoint


def test_the_webhook_endpoint_rejects_bad_signatures_and_hides_when_billing_is_off(shop, app):
    bad = shop.test_client().post(
        "/api/v1/billing/webhook",
        data=b'{"id":"e","type":"t"}',
        headers={"Stripe-Signature": "t=1,v1=00"},
    )
    assert bad.status_code == 400 and bad.get_json()["error"]["code"] == "invalid_signature"
    assert (
        app.test_client().post("/api/v1/billing/webhook", data=b"{}").status_code == 404
    )  # personal mode


def test_the_webhook_has_a_body_size_limit(shop):
    big = b"x" * 600_000
    response = shop.test_client().post(
        "/api/v1/billing/webhook", data=big, headers={"Stripe-Signature": sign(big)}
    )
    assert response.status_code == 413


def test_events_are_applied_once_even_if_stripe_retries(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid, status="incomplete", sub_id=None)
    evt = event(
        "customer.subscription.updated",
        {"id": "sub_9", "customer": f"cus_{uid}", "status": "active"},
        id="evt_same",
    )
    assert post_event(shop, evt).get_json() == {"received": True, "applied": True}
    assert post_event(shop, evt).get_json() == {"received": True, "applied": False}
    with shop.extensions["kyvon"].session_factory() as s:
        assert len(s.scalars(select(BillingEvent)).all()) == 1


def test_the_full_lifecycle_moves_the_plan_up_and_down(shop):
    uid = make_verified(shop, EMAIL)
    client = login(shop.test_client(), EMAIL)
    assert client.post("/api/v1/billing/checkout").status_code == 200  # creates the customer
    assert plan(shop, uid) == "free"
    period_end = int(time.time()) + 30 * 86400
    t0 = int(time.time())

    post_event(
        shop,
        event(
            "checkout.session.completed",
            {
                "customer": f"cus_{uid}",
                "subscription": "sub_77",
                "payment_status": "paid",
                "client_reference_id": str(uid),
            },
            created=t0,
        ),
    )
    assert plan(shop, uid) == "pro"

    post_event(
        shop,
        event(
            "customer.subscription.updated",
            {
                "id": "sub_77",
                "customer": f"cus_{uid}",
                "status": "active",
                "current_period_end": period_end,
                "cancel_at_period_end": True,
            },
            created=t0 + 1,
        ),
    )
    status = client.get("/api/v1/billing").get_json()
    assert status["plan"] == "pro" and status["cancel_at_period_end"] is True
    assert status["current_period_end"] is not None and status["price_label"] == "$9 / month"

    post_event(
        shop,
        event(
            "customer.subscription.deleted",
            {"id": "sub_77", "customer": f"cus_{uid}"},
            created=t0 + 2,
        ),
    )
    assert plan(shop, uid) == "free"
    assert client.get("/api/v1/billing").get_json()["status"] == "canceled"


def test_older_events_that_arrive_late_are_ignored(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid, status="incomplete")
    now = int(time.time())
    post_event(
        shop,
        event(
            "customer.subscription.updated",
            {"id": "sub_1", "customer": f"cus_{uid}", "status": "canceled"},
            created=now,
        ),
    )
    post_event(
        shop,
        event(
            "customer.subscription.updated",
            {"id": "sub_1", "customer": f"cus_{uid}", "status": "active"},
            created=now - 100,
        ),
    )
    assert plan(shop, uid) == "free"  # the stale "active" must not resurrect it


def test_a_failed_payment_keeps_access_for_the_grace_period_then_stops(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid, status="active", period_days=-1)  # period ended yesterday
    post_event(shop, event("invoice.payment_failed", {"customer": f"cus_{uid}"}))
    assert plan(shop, uid) == "pro"  # inside the 3 day grace
    with shop.extensions["kyvon"].session_factory() as s:
        sub = s.scalar(select(Subscription))
        sub.current_period_end = utcnow() - timedelta(days=5)
        s.commit()
    assert plan(shop, uid) == "free"
    post_event(
        shop, event("invoice.paid", {"customer": f"cus_{uid}"}, created=int(time.time()) + 5)
    )
    assert plan(shop, uid) == "pro"


def test_the_newer_stripe_shape_with_the_period_on_items_is_understood(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid, status="incomplete")
    end = int(time.time()) + 86400
    post_event(
        shop,
        event(
            "customer.subscription.updated",
            {
                "id": "sub_1",
                "customer": f"cus_{uid}",
                "status": "trialing",
                "items": {"data": [{"current_period_end": end}]},
            },
        ),
    )
    with shop.extensions["kyvon"].session_factory() as s:
        assert int(s.scalar(select(Subscription)).current_period_end.timestamp()) == end
    assert plan(shop, uid) == "pro"


def test_events_for_unknown_customers_and_unknown_types_do_nothing(shop):
    uid = make_verified(shop, EMAIL)
    assert (
        post_event(
            shop,
            event("customer.subscription.updated", {"customer": "cus_nobody", "status": "active"}),
        ).status_code
        == 200
    )
    assert post_event(shop, event("charge.refunded", {"customer": f"cus_{uid}"})).status_code == 200
    assert plan(shop, uid) == "free"


def test_paying_changes_the_allowance(shop):
    uid = make_verified(shop, EMAIL)
    client = login(shop.test_client(), EMAIL)
    for _ in range(2):
        client.post("/api/v1/chat", json={"message": "hi"})
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 402
    subscribe(shop, uid)
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 200
    assert client.get("/api/v1/account/usage").get_json()["plan"] == "pro"


# ----------------------------------------------------------------- checkout


def test_checkout_needs_a_verified_email_and_one_customer_per_person(shop):
    from kyvon.services import auth_service

    with shop.extensions["kyvon"].session_factory() as s:
        auth_service.create_user(s, email="new@example.com", password=PASSWORD, verified=False)
    unverified = login(shop.test_client(), "new@example.com")
    assert unverified.post("/api/v1/billing/checkout").status_code == 409

    make_verified(shop, EMAIL)
    client = login(shop.test_client(), EMAIL)
    first = client.post("/api/v1/billing/checkout").get_json()["url"]
    second = client.post("/api/v1/billing/checkout").get_json()["url"]
    assert first == second and first.startswith("https://checkout.stripe.test/")
    stripe = shop.extensions["kyvon"].stripe
    assert stripe.customers == 1  # the second click reuses the customer
    checkout = [c for c in stripe.calls if c[0] == "checkout"][0][1]
    assert checkout["price_id"] == "price_123"
    assert checkout["success_url"].startswith("https://kyvon.example.com/#billing=")


def test_someone_already_subscribed_is_sent_to_the_portal_not_charged_twice(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid)
    client = login(shop.test_client(), EMAIL)
    again = client.post("/api/v1/billing/checkout")
    assert again.status_code == 409
    assert (
        client.post("/api/v1/billing/portal")
        .get_json()["url"]
        .startswith("https://billing.stripe.test")
    )


def test_portal_needs_an_existing_customer(shop):
    make_verified(shop, EMAIL)
    assert login(shop.test_client(), EMAIL).post("/api/v1/billing/portal").status_code == 409


def test_billing_endpoints_do_not_exist_in_personal_mode(client):
    assert client.get("/api/v1/billing").status_code == 404


def test_without_stripe_configured_checkout_says_so(tmp_path, fake_llm, fake_environment, fake_stt):
    app = make_app(
        hosted_settings(tmp_path), llm=fake_llm, environment=fake_environment, stt=fake_stt
    )
    make_verified(app, EMAIL)
    response = login(app.test_client(), EMAIL).post("/api/v1/billing/checkout")
    assert response.status_code == 409 and response.get_json()["error"]["code"] == "not_connected"


# ----------------------------------------------------------------- deletion


def test_deleting_an_account_cancels_the_subscription_first(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid)
    client = login(shop.test_client(), EMAIL)
    assert client.delete("/api/v1/account", json={"password": PASSWORD}).status_code == 200
    assert ("cancel", "sub_1") in shop.extensions["kyvon"].stripe.calls
    with shop.extensions["kyvon"].session_factory() as s:
        assert s.get(User, uid) is None and s.scalars(select(Subscription)).all() == []


def test_if_stripe_cannot_cancel_the_account_is_not_deleted(shop):
    uid = make_verified(shop, EMAIL)
    subscribe(shop, uid)
    shop.extensions["kyvon"].stripe.fail_cancel = True
    client = login(shop.test_client(), EMAIL)
    response = client.delete("/api/v1/account", json={"password": PASSWORD})
    assert response.status_code == 502 and "not deleted" in response.get_json()["error"]["message"]
    with shop.extensions["kyvon"].session_factory() as s:
        assert s.get(User, uid) is not None  # still charging means we must not delete


# ------------------------------------------------------- the Stripe client


def test_the_client_sends_stripes_documented_request_shapes():
    http = FakeHTTP()
    http.responses = [
        FakeHTTPResponse(200, {"id": "cus_1"}),
        FakeHTTPResponse(200, {"url": "https://c"}),
        FakeHTTPResponse(200, {"url": "https://p"}),
        FakeHTTPResponse(200, {}),
    ]
    stripe = StripeClient(http, "sk_test_abc")
    assert stripe.create_customer(email="a@b.co", user_id=7) == "cus_1"
    assert (
        stripe.create_checkout_session(
            customer_id="cus_1",
            price_id="price_1",
            user_id=7,
            success_url="https://s",
            cancel_url="https://c",
        )
        == "https://c"
    )
    assert stripe.create_portal_session(customer_id="cus_1", return_url="https://r") == "https://p"
    stripe.cancel_subscription("sub_1")
    customer, checkout, portal, cancel = http.calls
    assert customer["url"] == "https://api.stripe.com/v1/customers"
    assert customer["data"] == {"email": "a@b.co", "metadata[user_id]": "7"}
    assert customer["headers"]["Authorization"] == "Bearer sk_test_abc"
    assert customer["headers"]["Idempotency-Key"] == "kyvon-customer-7"
    assert checkout["data"]["mode"] == "subscription"
    assert checkout["data"]["line_items[0][price]"] == "price_1"
    assert checkout["data"]["client_reference_id"] == "7"
    assert portal["url"].endswith("/billing_portal/sessions")
    assert (cancel["method"], cancel["url"]) == (
        "DELETE",
        "https://api.stripe.com/v1/subscriptions/sub_1",
    )
    assert all(c["allow_redirects"] is False and c["timeout"] for c in http.calls)


def test_stripe_errors_become_clean_integration_errors_without_the_key():
    http = FakeHTTP()
    http.responses = [
        FakeHTTPResponse(402, {"error": {"message": "Your card was declined."}}),
        ConnectionError("boom sk_test_abc"),
    ]
    stripe = StripeClient(http, "sk_test_abc")
    with pytest.raises(IntegrationError, match="declined"):
        stripe.create_customer(email="a@b.co", user_id=1)
    with pytest.raises(IntegrationError) as caught:
        stripe.create_customer(email="a@b.co", user_id=1)
    assert "sk_test_abc" not in str(caught.value)
