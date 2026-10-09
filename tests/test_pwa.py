"""PWA: manifest, service worker, icons, push (RFC 8291 vector, VAPID, subscriptions)."""

import base64
import json
import re
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import select

from kyvon.integrations.webpush import (
    WebPushError,
    WebPushSender,
    b64d,
    b64e,
    encrypt_payload,
    generate_vapid_keys,
    is_allowed_endpoint,
    vapid_authorization,
)
from kyvon.models import Notification, PushSubscription, User
from kyvon.pwa import shell_files, version
from kyvon.services import auth_service
from kyvon.services.push_service import PushService
from tests.conftest import make_app
from tests.fakes import FakeHTTPResponse

WEB = Path(__file__).resolve().parent.parent / "web"
GOOD = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {"p256dh": generate_vapid_keys()[0], "auth": b64e(b"0123456789abcdef")}


# ------------------------------------------------------------ manifest and icons


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifest_is_valid_and_installable(anon_client):
    response = anon_client.get("/manifest.webmanifest")
    assert response.status_code == 200 and response.mimetype == "application/manifest+json"
    manifest = response.get_json()
    assert manifest["name"] == "KYVON" and manifest["display"] == "standalone"
    assert manifest["start_url"].startswith("/") and manifest["scope"] == "/"
    assert manifest["background_color"] == manifest["theme_color"] == "#050505"
    sizes = {(i["sizes"], i["purpose"]) for i in manifest["icons"]}
    assert (
        ("192x192", "any") in sizes
        and ("512x512", "any") in sizes
        and ("512x512", "maskable") in sizes
    )


def test_manifest_icons_exist_with_the_declared_size(anon_client):
    for icon in anon_client.get("/manifest.webmanifest").get_json()["icons"]:
        path = WEB / icon["src"].removeprefix("/static/")
        width, height = map(int, icon["sizes"].split("x"))
        assert png_size(path) == (width, height), icon["src"]


def test_apple_and_favicon_icons():
    assert png_size(WEB / "icons" / "apple-touch-icon.png") == (180, 180)
    assert png_size(WEB / "icons" / "favicon-32.png") == (32, 32)


def test_page_links_manifest_and_icons(anon_client):
    html = anon_client.get("/").get_data(as_text=True)
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html and "apple-mobile-web-app-capable" in html
    assert "viewport-fit=cover" in html and 'id="offlineBanner"' in html
    for asset in re.findall(r'(?:href|src)="(/static/[^"]+)"', html):
        assert anon_client.get(asset).status_code == 200, asset


# ------------------------------------------------------------ service worker


def test_service_worker_is_served_from_the_root(anon_client):
    response = anon_client.get("/sw.js")
    assert response.status_code == 200 and response.mimetype == "text/javascript"
    assert (
        response.headers["Service-Worker-Allowed"] == "/"
        and response.headers["Cache-Control"] == "no-cache"
    )
    text = response.get_data(as_text=True)
    assert "__VERSION__" not in text and "__SHELL__" not in text
    assert f'const VERSION = "{version()}"' in text


def test_shell_precache_list_points_at_real_files(anon_client):
    text = anon_client.get("/sw.js").get_data(as_text=True)
    shell = json.loads(re.search(r"const SHELL = (\[.*?\]);", text, re.S).group(1))
    assert shell == shell_files() and "/" in shell and "/static/js/main.js" in shell
    for url in shell:
        assert anon_client.get(url).status_code == 200, url
    assert "/sw.js" not in shell and not any(u.startswith("/api/") for u in shell)


def test_service_worker_never_caches_the_api():
    source = (WEB / "sw.js").read_text()
    assert 'url.pathname.startsWith("/api/")) return' in source
    assert "cache.put" in source and source.count("cache.put") == 1  # only the /static/ branch
    assert "notificationclick" in source and "showNotification" in source


def test_version_changes_when_files_change(tmp_path, monkeypatch):
    import kyvon.pwa as pwa

    (tmp_path / "a.txt").write_text("one")
    monkeypatch.setattr(pwa, "WEB_DIR", tmp_path)
    first = pwa.version()
    (tmp_path / "a.txt").write_text("two")
    assert pwa.version() != first


def test_csp_allows_the_worker_and_manifest(anon_client):
    csp = anon_client.get("/").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp  # worker-src and manifest-src fall back to it


# ------------------------------------------------------------ Web Push crypto


def test_payload_header_matches_the_rfc_8291_example_inputs():
    """With the RFC 8291 example salt and sender key, the record header is the RFC's:
    salt, record size 4096, and the sender's uncompressed public key. (The ciphertext itself
    is covered by the round-trip test below; it was not compared with the RFC's ciphertext
    and delivery to real push services has not been tested.)"""
    as_private = ec.derive_private_key(
        int.from_bytes(b64d("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1()
    )
    body = encrypt_payload(
        b"When I grew up, I was the smallest kid in the class.",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHGzo-0JyJv-o1-yw",
        salt=b64d("DGv6ra1nlYgDCS1FRnbzlw"),
        server_private=as_private,
    )
    header = "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
    assert b64e(body[:86]) == header
    assert len(body) == 86 + len(b"When I grew up, I was the smallest kid in the class.") + 1 + 16


def test_encrypted_payload_round_trips_with_the_receivers_key():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    ua = ec.generate_private_key(ec.SECP256R1())
    ua_pub = ua.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = b"secretsecret1234"
    body = encrypt_payload(b'{"title":"hi"}', b64e(ua_pub), b64e(auth))
    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_pub, ciphertext = body[21 : 21 + idlen], body[21 + idlen :]
    assert rs == 4096 and idlen == 65
    shared = ua.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub)
    )
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ua_pub + as_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    assert AESGCM(cek).decrypt(nonce, ciphertext, None) == b'{"title":"hi"}\x02'


def test_payload_size_limit():
    with pytest.raises(ValueError, match="4 KB"):
        encrypt_payload(b"x" * 5000, KEYS["p256dh"], KEYS["auth"])


def test_vapid_jwt_is_valid_and_verifiable():
    public, private = generate_vapid_keys()
    header = vapid_authorization(GOOD, "mailto:me@example.com", public, private, now=1_000_000)
    assert header.startswith("vapid t=") and header.endswith(f", k={public}")
    jwt = header.split("t=")[1].split(",")[0]
    head, claims, signature = jwt.split(".")
    assert json.loads(b64d(head)) == {"typ": "JWT", "alg": "ES256"}
    parsed = json.loads(b64d(claims))
    assert parsed == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1_000_000 + 43200,
        "sub": "mailto:me@example.com",
    }
    raw = b64d(signature)
    assert len(raw) == 64
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64d(public))
    key.verify(
        encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        f"{head}.{claims}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )


def test_generated_vapid_keys_are_well_formed():
    public, private = generate_vapid_keys()
    assert len(b64d(public)) == 65 and b64d(public)[0] == 4 and len(b64d(private)) == 32


# ------------------------------------------------------------ endpoint allow-list (SSRF)


@pytest.mark.parametrize(
    "endpoint",
    [
        GOOD,
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://web.push.apple.com/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=1",
    ],
)
def test_real_push_services_are_allowed(endpoint):
    assert is_allowed_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/x",
        "https://evil.example.com/x",
        "https://fcm.googleapis.com.evil.com/x",
        "https://evilfcm.googleapis.com.attacker.io/",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com:8443/x",
        "file:///etc/passwd",
        "",
        "notaurl",
    ],
)
def test_other_addresses_are_refused(endpoint):
    assert not is_allowed_endpoint(endpoint)


# ------------------------------------------------------------ sender and service


class FakePushHTTP:
    def __init__(self, status=201):
        self.status = status
        self.requests = []

    def request(self, method, url, data=None, headers=None, timeout=None, **kwargs):
        self.requests.append({"method": method, "url": url, "data": data, "headers": headers})
        return FakeHTTPResponse(self.status, {})


def sender(http):
    public, private = generate_vapid_keys()
    return WebPushSender(
        http, public_key=public, private_key=private, subject="mailto:me@example.com"
    )


def test_sender_posts_an_encrypted_message_with_vapid():
    http = FakePushHTTP()
    sender(http).send(GOOD, KEYS, {"title": "Hi", "body": "There"})
    (request,) = http.requests
    assert request["url"] == GOOD and request["headers"]["Content-Encoding"] == "aes128gcm"
    assert request["headers"]["Authorization"].startswith("vapid t=") and request["headers"]["TTL"]
    assert b"Hi" not in request["data"] and len(request["data"]) > 100  # encrypted


def test_sender_refuses_bad_endpoints_without_sending():
    http = FakePushHTTP()
    with pytest.raises(WebPushError):
        sender(http).send("https://internal.example/x", KEYS, {})
    assert http.requests == []


@pytest.mark.parametrize(("status", "gone"), [(404, True), (410, True), (500, False), (429, False)])
def test_push_errors(status, gone):
    with pytest.raises(WebPushError) as info:
        sender(FakePushHTTP(status)).send(GOOD, KEYS, {})
    assert info.value.gone is gone


@pytest.fixture
def session(app):
    with app.extensions["kyvon"].session_factory() as s:
        yield s


def test_service_delivers_and_prunes_dead_subscriptions(session, owner):
    session.add_all(
        [
            PushSubscription(user_id=owner.id, kind="webpush", endpoint=GOOD, keys=KEYS),
            PushSubscription(user_id=owner.id, kind="webpush", endpoint=GOOD + "-dead", keys=KEYS),
            PushSubscription(user_id=owner.id, kind="apns", endpoint="abcdef", keys=None),
        ]
    )
    session.commit()

    class Selective(FakePushHTTP):
        def request(self, method, url, **kw):
            super().request(method, url, **kw)
            return FakeHTTPResponse(410 if url.endswith("dead") else 201, {})

    http = Selective()
    assert PushService(sender(http)).send(session, owner.id, "T", "B", 1) == 1
    assert {s.endpoint for s in session.scalars(select(PushSubscription))} == {GOOD, "abcdef"}
    assert len(http.requests) == 2  # the APNs token is not sent to a web push service


def test_reminders_are_pushed_when_configured(app, settings, fake_llm, fake_environment):
    from kyvon.automation.runner import AutomationRunner
    from kyvon.services.automation_service import AutomationService

    public, private = generate_vapid_keys()
    configured = replace(
        settings,
        vapid_public_key=public,
        vapid_private_key=private,
        vapid_subject="mailto:me@example.com",
    )
    push_app = make_app(configured, llm=fake_llm, environment=fake_environment)
    svc = push_app.extensions["kyvon"]
    http = FakePushHTTP()
    svc.push._sender._http = http
    with svc.session_factory() as s:
        user = auth_service.create_owner(s, "owner", "correct horse battery")
        s.add(PushSubscription(user_id=user.id, kind="webpush", endpoint=GOOD, keys=KEYS))
        s.commit()
        a = AutomationService(s, user.id, timezone="UTC").create(
            "Vitamins", "reminder", {"type": "daily", "time": "08:00"}, text="Take vitamins"
        )
        AutomationRunner(svc).execute(s, a.id, triggered_by="manual")
        assert s.scalar(select(Notification.title)) == "Vitamins"
    assert len(http.requests) == 1


def test_a_failing_push_never_breaks_the_reminder(app, settings, fake_llm, fake_environment):
    from kyvon.automation.runner import AutomationRunner
    from kyvon.services.automation_service import AutomationService

    public, private = generate_vapid_keys()
    push_app = make_app(
        replace(
            settings,
            vapid_public_key=public,
            vapid_private_key=private,
            vapid_subject="mailto:x@example.com",
        ),
        llm=fake_llm,
        environment=fake_environment,
    )
    svc = push_app.extensions["kyvon"]

    class Boom:
        def request(self, *a, **k):
            raise ConnectionError("push service down")

    svc.push._sender._http = Boom()
    with svc.session_factory() as s:
        user = auth_service.create_owner(s, "owner", "correct horse battery")
        s.add(PushSubscription(user_id=user.id, kind="webpush", endpoint=GOOD, keys=KEYS))
        s.commit()
        a = AutomationService(s, user.id, timezone="UTC").create(
            "R", "reminder", {"type": "daily", "time": "08:00"}, text="x"
        )
        assert AutomationRunner(svc).execute(s, a.id, triggered_by="manual").status == "succeeded"


# ------------------------------------------------------------ API


def test_public_key_endpoint(client, app, settings, fake_llm, fake_environment):
    assert client.get("/api/v1/push/public-key").get_json() == {"configured": False}
    public, private = generate_vapid_keys()
    other = make_app(
        replace(
            settings,
            vapid_public_key=public,
            vapid_private_key=private,
            vapid_subject="mailto:x@example.com",
        ),
        llm=fake_llm,
        environment=fake_environment,
    )
    c = other.test_client()
    c.environ_base["HTTP_AUTHORIZATION"] = client.environ_base["HTTP_AUTHORIZATION"]
    data = c.get("/api/v1/push/public-key").get_json()
    assert data == {"configured": True, "public_key": public}
    assert private not in json.dumps(data)


def test_subscribe_unsubscribe(client, session):
    assert (
        client.post("/api/v1/push/subscribe", json={"endpoint": GOOD, "keys": KEYS}).status_code
        == 201
    )
    assert (
        client.post("/api/v1/push/subscribe", json={"endpoint": GOOD, "keys": KEYS}).status_code
        == 201
    )
    assert session.query(PushSubscription).count() == 1
    assert client.delete("/api/v1/push/subscribe", json={"endpoint": GOOD}).get_json() == {
        "removed": True
    }
    assert client.delete("/api/v1/push/subscribe", json={"endpoint": GOOD}).get_json() == {
        "removed": False
    }


@pytest.mark.parametrize(
    "body",
    [
        {"endpoint": "https://evil.example.com/push", "keys": KEYS},
        {"endpoint": GOOD, "keys": {"p256dh": "x"}},
        {"endpoint": GOOD, "keys": {}},
        {"endpoint": GOOD},
        {},
    ],
)
def test_subscribe_validation(client, body):
    assert client.post("/api/v1/push/subscribe", json=body).status_code == 400


def test_subscription_limit(client):
    for i in range(10):
        assert (
            client.post(
                "/api/v1/push/subscribe", json={"endpoint": f"{GOOD}{i}", "keys": KEYS}
            ).status_code
            == 201
        )
    assert (
        client.post(
            "/api/v1/push/subscribe", json={"endpoint": GOOD + "x", "keys": KEYS}
        ).status_code
        == 400
    )


def test_apns_registration(client, session):
    assert client.post("/api/v1/push/apns", json={"device_token": "ab12" * 16}).status_code == 201
    assert session.query(PushSubscription).filter_by(kind="apns").count() == 1
    for bad in ("", "has space", "x" * 301, "no-dashes-allowed"):
        assert client.post("/api/v1/push/apns", json={"device_token": bad}).status_code == 400


def test_another_user_cannot_remove_my_subscription(app, client, anon_client, session):
    client.post("/api/v1/push/subscribe", json={"endpoint": GOOD, "keys": KEYS})
    other = User(username="stranger", password_hash="x")
    session.add(other)
    session.commit()
    raw, _ = auth_service.issue_token(session, other, name="t", ttl_days=1)
    h = {"Authorization": f"Bearer {raw}"}
    assert anon_client.delete(
        "/api/v1/push/subscribe", json={"endpoint": GOOD}, headers=h
    ).get_json() == {"removed": False}
    assert session.query(PushSubscription).count() == 1


def test_push_api_requires_auth(anon_client, owner):
    for method, path in [
        ("get", "/api/v1/push/public-key"),
        ("post", "/api/v1/push/subscribe"),
        ("delete", "/api/v1/push/subscribe"),
        ("post", "/api/v1/push/apns"),
    ]:
        assert getattr(anon_client, method)(path, json={}).status_code == 401


def test_cli_prints_vapid_keys(app):
    result = app.test_cli_runner().invoke(args=["kyvon", "generate-vapid-keys"])
    assert (
        result.exit_code == 0
        and "KYVON_VAPID_PUBLIC_KEY=" in result.output
        and "KYVON_VAPID_PRIVATE_KEY=" in result.output
    )
    assert (
        base64.urlsafe_b64decode(
            result.output.split("KYVON_VAPID_PUBLIC_KEY=")[1].split()[0] + "=="
        )[0]
        == 4
    )
