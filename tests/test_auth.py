from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from kyvon.models import ApiToken, User
from kyvon.services import auth_service
from kyvon.utils.rate_limit import FailureThrottle
from tests.conftest import TEST_PASSWORD, TEST_USERNAME

LOGIN = "/api/v1/auth/login"


def login(client, password=TEST_PASSWORD, username=TEST_USERNAME, **extra):
    return client.post(LOGIN, json={"username": username, "password": password, **extra})


@pytest.fixture
def session(app):
    with app.extensions["kyvon"].session_factory() as s:
        yield s


# ------------------------------------------------------------ protection

PROTECTED = [
    ("get", "/api/v1/status"),
    ("get", "/api/v1/memories"),
    ("post", "/api/v1/chat"),
    ("post", "/api/v1/environment"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/auth/tokens"),
    ("delete", "/api/v1/auth/tokens/1"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_routes_require_authentication(anon_client, owner, method, path):
    response = getattr(anon_client, method)(path, json={})
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_health_and_login_are_public(anon_client):
    assert anon_client.get("/api/v1/health").status_code == 200
    assert login(anon_client).status_code == 401  # reachable (bad creds), not 404/405


def test_garbage_token_rejected(anon_client, owner):
    response = anon_client.get("/api/v1/memories", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_non_bearer_scheme_rejected(anon_client, owner):
    response = anon_client.get("/api/v1/memories", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


def test_no_registration_endpoint(anon_client):
    assert anon_client.post("/api/v1/auth/register", json={}).status_code == 404


def test_responses_are_not_cached(client):
    assert client.get("/api/v1/memories").headers["Cache-Control"] == "no-store"


# ------------------------------------------------------------ login


def test_login_returns_token_and_it_works(anon_client, owner):
    response = login(anon_client, device_name="iPad")
    body = response.get_json()
    assert response.status_code == 200
    assert body["user"] == {"id": owner.id, "username": TEST_USERNAME}
    assert body["token"].startswith("kyv_")
    assert "Set-Cookie" not in response.headers

    me = anon_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.get_json()["user"]["username"] == TEST_USERNAME


def test_username_is_case_insensitive(anon_client, owner):
    assert login(anon_client, username="  OWNER ").status_code == 200


@pytest.mark.parametrize(
    ("username", "password"), [(TEST_USERNAME, "wrong password"), ("nobody", TEST_PASSWORD)]
)
def test_bad_credentials_share_one_message(anon_client, owner, username, password):
    response = login(anon_client, password=password, username=username)
    assert response.status_code == 401
    assert response.get_json()["error"]["message"] == "Invalid username or password."


def test_login_validation(anon_client, owner):
    assert anon_client.post(LOGIN, json={"username": "x"}).status_code == 400
    assert anon_client.post(LOGIN, data="nope").status_code == 400


def test_raw_token_never_stored(anon_client, owner, session):
    raw = login(anon_client).get_json()["token"]
    stored = session.scalars(select(ApiToken)).all()
    assert len(stored) == 1
    assert stored[0].token_hash == auth_service.hash_token(raw)
    assert raw not in stored[0].token_hash
    assert stored[0].expires_at > datetime.now(UTC) + timedelta(days=29)


def test_password_is_hashed(owner, session):
    hashed = session.scalar(select(User.password_hash))
    assert TEST_PASSWORD not in hashed and hashed.startswith(("scrypt:", "pbkdf2:"))


def test_login_never_echoes_password_or_hash(anon_client, owner):
    text = login(anon_client).get_data(as_text=True)
    assert TEST_PASSWORD not in text and "scrypt" not in text


def test_lockout_after_repeated_failures(app, anon_client, owner):
    app.extensions["kyvon"].login_throttle = FailureThrottle(max_failures=3)
    for _ in range(3):
        assert login(anon_client, password="bad password").status_code == 401
    assert login(anon_client, password="bad password").status_code == 429
    assert login(anon_client).status_code == 429  # even the right password is blocked


def test_success_resets_failure_count(app, anon_client, owner):
    app.extensions["kyvon"].login_throttle = FailureThrottle(max_failures=3)
    for _ in range(2):
        login(anon_client, password="bad password")
    assert login(anon_client).status_code == 200
    for _ in range(2):
        login(anon_client, password="bad password")
    assert login(anon_client, password="bad password").status_code == 401  # not yet locked


# ------------------------------------------------------------ cookie flow


def cookie_login(client):
    response = login(client, cookie=True)
    assert response.status_code == 200
    return response


def test_cookie_login_sets_httponly_token_and_hides_it_from_body(anon_client, owner):
    response = cookie_login(anon_client)
    assert "token" not in response.get_json()
    cookies = response.headers.getlist("Set-Cookie")
    token_cookie = next(c for c in cookies if c.startswith("kyvon_token="))
    csrf_cookie = next(c for c in cookies if c.startswith("kyvon_csrf="))
    assert "HttpOnly" in token_cookie and "SameSite=Strict" in token_cookie
    assert "HttpOnly" not in csrf_cookie


def test_cookie_secure_flag_follows_settings(settings, fake_llm, owner):
    from dataclasses import replace

    from tests.conftest import make_app

    secure_app = make_app(replace(settings, cookie_secure=True), llm=fake_llm)
    response = login(secure_app.test_client(), cookie=True)
    assert all("Secure" in c for c in response.headers.getlist("Set-Cookie"))


def test_cookie_get_works_without_csrf(anon_client, owner):
    cookie_login(anon_client)
    assert anon_client.get("/api/v1/memories").status_code == 200


def test_cookie_post_requires_csrf_header(anon_client, owner):
    cookie_login(anon_client)
    assert anon_client.post("/api/v1/chat", json={"message": "hi"}).status_code == 403
    bad = anon_client.post("/api/v1/chat", json={"message": "hi"}, headers={"X-CSRF-Token": "x"})
    assert bad.status_code == 403


def test_cookie_post_with_csrf_header_works(anon_client, owner):
    cookie_login(anon_client)
    csrf = anon_client.get_cookie("kyvon_csrf").value
    response = anon_client.post(
        "/api/v1/chat", json={"message": "hi"}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200


def test_bearer_post_needs_no_csrf(client):
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 200


# ------------------------------------------------------------ logout / revocation


def test_logout_revokes_token(client):
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/memories").status_code == 401


def test_cookie_logout_clears_cookies(anon_client, owner):
    cookie_login(anon_client)
    csrf = anon_client.get_cookie("kyvon_csrf").value
    response = anon_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert anon_client.get("/api/v1/memories").status_code == 401


def test_list_and_revoke_other_device(anon_client, client, owner):
    other = login(anon_client, device_name="iPhone").get_json()["token"]
    tokens = client.get("/api/v1/auth/tokens").get_json()["tokens"]
    assert {t["name"] for t in tokens} == {"API client", "iPhone"}
    assert sum(t["current"] for t in tokens) == 1
    assert other not in str(tokens)

    phone = next(t for t in tokens if t["name"] == "iPhone")
    assert client.delete(f"/api/v1/auth/tokens/{phone['id']}").status_code == 200
    revoked = anon_client.get("/api/v1/memories", headers={"Authorization": f"Bearer {other}"})
    assert revoked.status_code == 401
    assert client.delete(f"/api/v1/auth/tokens/{phone['id']}").status_code == 404


def test_expired_token_rejected(app, owner, session):
    raw, _ = auth_service.issue_token(session, owner, name="t", ttl_days=1)
    later = datetime.now(UTC) + timedelta(days=2)
    assert auth_service.resolve_token(session, raw, now=lambda: later) is None


def test_last_used_updated_and_throttled(session, owner):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    raw, _ = auth_service.issue_token(session, owner, name="t", ttl_days=30, now=lambda: t0)
    token = auth_service.resolve_token(session, raw, now=lambda: t0)
    assert token.last_used_at == t0
    auth_service.resolve_token(session, raw, now=lambda: t0 + timedelta(seconds=10))
    assert token.last_used_at == t0
    auth_service.resolve_token(session, raw, now=lambda: t0 + timedelta(minutes=5))
    assert token.last_used_at == t0 + timedelta(minutes=5)


def test_revoke_cannot_touch_other_users_token(session, owner):
    other = User(username="other", password_hash="x")
    session.add(other)
    session.commit()
    _, token = auth_service.issue_token(session, other, name="t", ttl_days=1)
    assert auth_service.revoke_token(session, owner.id, token.id) is False


# ------------------------------------------------------------ service rules


def test_only_one_owner_allowed(session, owner):
    with pytest.raises(auth_service.AuthError, match="single-user"):
        auth_service.create_owner(session, "second", "another long password")


@pytest.mark.parametrize("password", ["short", ""])
def test_weak_password_rejected(session, password):
    with pytest.raises(auth_service.AuthError, match="at least"):
        auth_service.create_owner(session, "me", password)


@pytest.mark.parametrize("name", ["", "has space", "x" * 65, "UPPER!"])
def test_bad_username_rejected(session, name):
    with pytest.raises(auth_service.AuthError):
        auth_service.create_owner(session, name, "long enough password")


def test_set_password_changes_login(session, owner):
    auth_service.set_password(session, TEST_USERNAME, "a brand new password")
    assert auth_service.verify_login(session, TEST_USERNAME, TEST_PASSWORD) is None
    assert auth_service.verify_login(session, TEST_USERNAME, "a brand new password") is not None


# ------------------------------------------------------------ data isolation


def test_memories_are_scoped_to_the_logged_in_user(app, client, session):
    client.post("/api/v1/chat", json={"message": "remember mine"})
    stranger = User(username="stranger", password_hash="x")
    session.add(stranger)
    session.commit()
    raw, _ = auth_service.issue_token(session, stranger, name="t", ttl_days=1)
    theirs = app.test_client().get("/api/v1/memories", headers={"Authorization": f"Bearer {raw}"})
    assert theirs.get_json() == {"memories": []}
    assert [m["memory"] for m in client.get("/api/v1/memories").get_json()["memories"]] == ["mine"]


def test_throttle_window_expires():
    now = {"t": 0.0}
    throttle = FailureThrottle(max_failures=2, window_seconds=10, clock=lambda: now["t"])
    throttle.record_failure("k")
    throttle.record_failure("k")
    assert throttle.blocked("k")
    now["t"] = 11
    assert not throttle.blocked("k")
