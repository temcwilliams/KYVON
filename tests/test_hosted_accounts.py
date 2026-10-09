"""Hosted-service accounts: sign-up, email verification, password reset, export and deletion."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from kyvon.config import Settings
from kyvon.db import make_engine, upgrade_database, utcnow
from kyvon.models import Conversation, EmailToken, Memory, Message, Task, User
from kyvon.services import auth_service
from tests.conftest import TEST_ENCRYPTION_KEY, make_app
from tests.fakes import FakeEmail

PASSWORD = "a long enough password"
EMAIL = "Person@Example.com"


def hosted_settings(tmp_path, **extra):
    env = {
        "GROQ_API_KEY": "test-key",
        "KYVON_DATA_DIR": str(tmp_path / "data"),
        "KYVON_AUTO_TITLE_LLM": "false",
        "KYVON_SCHEDULER": "false",
        "KYVON_RATE_LIMIT_CHAT": "10000",
        "KYVON_RATE_LIMIT_API": "100000",
        "KYVON_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "KYVON_PUBLIC_URL": "https://kyvon.example.com",
        "KYVON_MODE": "hosted",
        "KYVON_SIGNUP_OPEN": "true",
        "KYVON_AUTH_RATE_PER_MINUTE": "1000",
    }
    env.update(extra)
    return Settings.from_env(env)


@pytest.fixture
def hosted(tmp_path, fake_llm, fake_environment, fake_stt):
    app = make_app(
        hosted_settings(tmp_path), llm=fake_llm, environment=fake_environment, stt=fake_stt
    )
    app.extensions["kyvon"].email = FakeEmail()
    return app


@pytest.fixture
def mail(hosted):
    return hosted.extensions["kyvon"].email


@pytest.fixture
def http(hosted):
    return hosted.test_client()


def signup(http, email=EMAIL, password=PASSWORD, accept=True):
    return http.post(
        "/api/v1/auth/signup", json={"email": email, "password": password, "accept_terms": accept}
    )


def login(http, who, password=PASSWORD):
    response = http.post("/api/v1/auth/login", json={"username": who, "password": password})
    assert response.status_code == 200, response.get_json()
    client = http.application.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {response.get_json()['token']}"
    return client


def make_verified(hosted, email, password=PASSWORD, role="user"):
    with hosted.extensions["kyvon"].session_factory() as s:
        return auth_service.create_user(
            s, email=email, password=password, verified=True, role=role
        ).id


# ---------------------------------------------------------------- sign-up


def test_signup_is_closed_in_personal_mode(app):
    response = app.test_client().post(
        "/api/v1/auth/signup", json={"email": "a@b.co", "password": PASSWORD, "accept_terms": True}
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "signup_closed"


def test_signup_stays_closed_in_hosted_mode_until_opened(tmp_path):
    app = make_app(hosted_settings(tmp_path, KYVON_SIGNUP_OPEN="false"))
    response = app.test_client().post(
        "/api/v1/auth/signup", json={"email": "a@b.co", "password": PASSWORD, "accept_terms": True}
    )
    assert response.get_json()["error"]["code"] == "signup_closed"


def test_signup_creates_an_unverified_account_and_emails_a_link(http, mail, hosted):
    response = signup(http)
    assert response.status_code == 202
    assert "Check your email" in response.get_json()["message"]
    with hosted.extensions["kyvon"].session_factory() as s:
        user = auth_service.find_by_email(s, EMAIL)
        assert user.email == "person@example.com"  # normalised
        assert user.email_verified_at is None
        assert user.role == "user"
        assert user.terms_accepted_at is not None and user.terms_version == "1"
        assert user.password_hash != PASSWORD
    body = mail.to("person@example.com")[0][2]
    assert "https://kyvon.example.com/#verify=" in body
    assert "?" not in body.split("#verify=")[1].split()[0]  # token only in the fragment


def test_signup_gives_the_same_answer_when_the_email_is_taken(http, mail, hosted):
    first = signup(http)
    second = signup(http)
    assert (first.status_code, first.get_json()) == (second.status_code, second.get_json())
    with hosted.extensions["kyvon"].session_factory() as s:
        assert len(list(s.scalars(select(User)))) == 1
    subjects = [m[1] for m in mail.to("person@example.com")]
    assert subjects == ["Confirm your KYVON email address", "You already have a KYVON account"]


def test_signup_requires_terms_a_valid_email_and_a_decent_password(http, mail):
    assert signup(http, accept=False).get_json()["error"]["code"] == "terms_required"
    assert signup(http, email="not-an-email").status_code == 400
    assert signup(http, email="x@y.com\nBcc: evil@example.com").status_code == 400
    assert signup(http, password="short").status_code == 400
    assert mail.sent == []


def test_signup_is_rate_limited_per_ip(tmp_path):
    app = make_app(hosted_settings(tmp_path, KYVON_AUTH_RATE_PER_MINUTE="2"))
    app.extensions["kyvon"].email = FakeEmail()
    http = app.test_client()
    codes = [signup(http, email=f"u{i}@example.com").status_code for i in range(4)]
    assert codes == [202, 202, 429, 429]


def test_a_mail_failure_does_not_break_or_reveal_anything(http, mail, hosted):
    mail.fail = True
    assert signup(http).status_code == 202  # same answer even though nothing was delivered


# ----------------------------------------------------------- verification


def test_the_emailed_link_verifies_the_address_once(http, mail, hosted):
    signup(http)
    token = mail.token("person@example.com", "verify")
    assert http.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    with hosted.extensions["kyvon"].session_factory() as s:
        assert auth_service.find_by_email(s, EMAIL).email_verified_at is not None
    again = http.post("/api/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and again.get_json()["error"]["code"] == "invalid_token"


def test_expired_and_unknown_verification_tokens_are_rejected(http, mail, hosted):
    signup(http)
    token = mail.token("person@example.com", "verify")
    with hosted.extensions["kyvon"].session_factory() as s:
        row = s.scalar(select(EmailToken))
        row.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert http.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400
    assert http.post("/api/v1/auth/verify-email", json={"token": "x" * 40}).status_code == 400


def test_a_reset_token_cannot_verify_an_address_and_vice_versa(http, mail, hosted):
    signup(http)
    verify = mail.token("person@example.com", "verify")
    http.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    reset = mail.token("person@example.com", "reset")
    assert http.post("/api/v1/auth/verify-email", json={"token": reset}).status_code == 400
    assert (
        http.post(
            "/api/v1/auth/reset-password", json={"token": verify, "password": "another long one"}
        ).status_code
        == 400
    )


def test_resending_a_verification_invalidates_the_older_link(http, mail, hosted):
    signup(http)
    old = mail.token("person@example.com", "verify")
    client = login(http, "person@example.com")
    assert client.post("/api/v1/auth/resend-verification").status_code == 200
    new = mail.token("person@example.com", "verify")
    assert new != old
    assert http.post("/api/v1/auth/verify-email", json={"token": old}).status_code == 400
    assert http.post("/api/v1/auth/verify-email", json={"token": new}).status_code == 200


# ------------------------------------------------------------------ login


def test_login_works_with_the_email_or_the_username(http, hosted):
    make_verified(hosted, "who@example.com")
    assert (
        http.post(
            "/api/v1/auth/login", json={"username": "WHO@example.com", "password": PASSWORD}
        ).status_code
        == 200
    )
    assert (
        http.post("/api/v1/auth/login", json={"username": "who", "password": PASSWORD}).status_code
        == 200
    )
    assert (
        http.post(
            "/api/v1/auth/login", json={"username": "who", "password": "wrong password"}
        ).status_code
        == 401
    )


def test_a_disabled_account_cannot_sign_in(http, hosted):
    make_verified(hosted, "gone@example.com")
    with hosted.extensions["kyvon"].session_factory() as s:
        auth_service.find_by_email(s, "gone@example.com").disabled_at = utcnow()
        s.commit()
    response = http.post(
        "/api/v1/auth/login", json={"username": "gone@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


# --------------------------------------------------------- password reset


def test_forgot_password_answers_the_same_for_known_and_unknown_addresses(http, mail, hosted):
    make_verified(hosted, "real@example.com")
    known = http.post("/api/v1/auth/forgot-password", json={"email": "real@example.com"})
    unknown = http.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert (known.status_code, known.get_json()) == (unknown.status_code, unknown.get_json())
    assert len(mail.to("real@example.com")) == 1 and mail.to("nobody@example.com") == []


def test_reset_sets_a_new_password_signs_everything_out_and_is_single_use(http, mail, hosted):
    make_verified(hosted, "real@example.com")
    old_client = login(http, "real@example.com")
    http.post("/api/v1/auth/forgot-password", json={"email": "real@example.com"})
    token = mail.token("real@example.com", "reset")
    new = "a brand new password"
    assert (
        http.post("/api/v1/auth/reset-password", json={"token": token, "password": new}).status_code
        == 200
    )
    assert old_client.get("/api/v1/auth/me").status_code == 401  # old sessions are gone
    assert (
        http.post(
            "/api/v1/auth/login", json={"username": "real@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert login(http, "real@example.com", new)
    reuse = http.post("/api/v1/auth/reset-password", json={"token": token, "password": new})
    assert reuse.status_code == 400


def test_reset_rejects_a_weak_password_without_spending_the_token(http, mail, hosted):
    make_verified(hosted, "real@example.com")
    http.post("/api/v1/auth/forgot-password", json={"email": "real@example.com"})
    token = mail.token("real@example.com", "reset")
    assert (
        http.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": "short"}
        ).status_code
        == 400
    )
    assert (
        http.post(
            "/api/v1/auth/reset-password", json={"token": token, "password": "long enough now"}
        ).status_code
        == 200
    )


def test_password_endpoints_do_not_exist_in_personal_mode(app):
    client = app.test_client()
    assert client.post("/api/v1/auth/forgot-password", json={"email": "a@b.co"}).status_code == 404


# ---------------------------------------------------------------- account


def test_change_password_needs_the_current_one_and_signs_out_other_devices(http, hosted):
    make_verified(hosted, "me@example.com")
    first = login(http, "me@example.com")
    second = login(http, "me@example.com")
    bad = first.post(
        "/api/v1/account/change-password",
        json={"current_password": "nope nope nope", "new_password": "something new long"},
    )
    assert bad.status_code == 400
    ok = first.post(
        "/api/v1/account/change-password",
        json={"current_password": PASSWORD, "new_password": "something new long"},
    )
    assert ok.status_code == 200
    assert first.get("/api/v1/auth/me").status_code == 200
    assert second.get("/api/v1/auth/me").status_code == 401


def _seed(hosted, user_id, label):
    with hosted.extensions["kyvon"].session_factory() as s:
        convo = Conversation(user_id=user_id, title=f"{label} chat")
        s.add(convo)
        s.flush()
        s.add(Message(conversation_id=convo.id, role="user", content=f"{label} secret message"))
        s.add(Memory(user_id=user_id, content=f"{label} memory", source="user"))
        s.add(Task(user_id=user_id, title=f"{label} task"))
        s.commit()


def test_export_contains_only_the_callers_data_and_no_secrets(http, hosted):
    a, b = make_verified(hosted, "a@example.com"), make_verified(hosted, "b@example.com")
    _seed(hosted, a, "alpha")
    _seed(hosted, b, "bravo")
    response = login(http, "a@example.com").get("/api/v1/account/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    text = response.get_data(as_text=True)
    assert "alpha secret message" in text and "alpha memory" in text and "alpha task" in text
    assert "bravo" not in text
    for forbidden in ("password_hash", "token_hash", "pbkdf2", "kyv_"):
        assert forbidden not in text
    data = response.get_json()
    assert data["account"]["email"] == "a@example.com"
    assert data["conversations"][0]["messages"][0]["content"] == "alpha secret message"


def test_deleting_an_account_removes_everything_it_owned_and_nothing_else(http, mail, hosted):
    a, b = make_verified(hosted, "a@example.com"), make_verified(hosted, "b@example.com")
    _seed(hosted, a, "alpha")
    _seed(hosted, b, "bravo")
    client = login(http, "a@example.com")
    wrong = client.delete("/api/v1/account", json={"password": "wrong password"})
    assert wrong.status_code == 403
    assert client.delete("/api/v1/account", json={"password": PASSWORD}).status_code == 200
    with hosted.extensions["kyvon"].session_factory() as s:
        assert s.get(User, a) is None
        assert s.scalars(select(Conversation).where(Conversation.user_id == a)).all() == []
        assert s.scalars(select(Memory).where(Memory.user_id == a)).all() == []
        assert s.scalars(select(Task).where(Task.user_id == a)).all() == []
        assert s.scalars(select(Message).where(Message.content.like("alpha%"))).all() == []
        assert s.get(User, b) is not None
        assert len(s.scalars(select(Memory).where(Memory.user_id == b)).all()) == 1
        assert len(s.scalars(select(Message).where(Message.content.like("bravo%"))).all()) == 1
    assert client.get("/api/v1/auth/me").status_code == 401  # the token went with the account
    assert any("deleted" in m[1] for m in mail.to("a@example.com"))
    http.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
    assert [m for m in mail.to("a@example.com") if "Reset" in m[1]] == []


def test_a_deleted_email_can_sign_up_again(http, mail, hosted):
    make_verified(hosted, "back@example.com")
    client = login(http, "back@example.com")
    client.delete("/api/v1/account", json={"password": PASSWORD})
    assert signup(http, email="back@example.com").status_code == 202
    assert mail.to("back@example.com")[-1][1] == "Confirm your KYVON email address"


# ------------------------------------------------------------------ admin


def test_admin_endpoints_are_for_administrators_only(http, hosted):
    make_verified(hosted, "user@example.com")
    make_verified(hosted, "boss@example.com", role="admin")
    user, boss = login(http, "user@example.com"), login(http, "boss@example.com")
    for path in ("/api/v1/admin/status", "/api/v1/admin/errors", "/api/v1/admin/usage"):
        denied = user.get(path)
        assert denied.status_code == 403, path
        assert denied.get_json()["error"]["code"] == "forbidden"
        assert boss.get(path).status_code == 200, path


def test_server_wide_tools_are_admin_only_on_a_hosted_service(hosted):
    from kyvon.tools.executor import CallOrigin

    svc = hosted.extensions["kyvon"]
    user_id = make_verified(hosted, "user@example.com")
    admin_id = make_verified(hosted, "boss@example.com", role="admin")
    for tool in ("recent_errors", "system_status"):
        with svc.session_factory() as s:
            denied = svc.executor.call(s, CallOrigin(user_id), tool, "{}")
            allowed = svc.executor.call(s, CallOrigin(admin_id), tool, "{}")
        assert denied.status == "failed", tool
        assert "administrators" in str(denied.content), tool
        assert allowed.status == "succeeded", tool


def test_server_wide_tools_stay_open_in_personal_mode(app, owner):
    from kyvon.tools.executor import CallOrigin

    svc = app.extensions["kyvon"]
    with svc.session_factory() as s:
        assert (
            svc.executor.call(s, CallOrigin(owner.id), "recent_errors", "{}").status == "succeeded"
        )


def test_hosted_mode_never_exposes_server_folders_or_private_model_endpoints(tmp_path):
    folder = tmp_path / "graph"
    folder.mkdir()
    app = make_app(
        hosted_settings(
            tmp_path, KYVON_LOGSEQ_DIR=str(folder), KYVON_HERMES_URL="http://localhost:9999/v1"
        )
    )
    svc = app.extensions["kyvon"]
    assert svc.logseq is None and svc.hermes is None
    enabled = {t.name for t in svc.registry.available(svc)}
    assert not any(n.startswith("logseq_") for n in enabled)


# -------------------------------------------------------------- migration


def test_the_accounts_migration_keeps_existing_users_and_their_data(tmp_path):
    """Regression: rebuilding `users` on SQLite once cascade-deleted every user's data."""
    from sqlalchemy import MetaData, Table, text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade_database(url, "0009")
    engine = make_engine(url)
    meta = MetaData()

    def insert(conn, name, **values):
        """Insert a row, filling any other NOT NULL column with a neutral value."""
        table = Table(name, meta, autoload_with=engine)
        row = dict(values)
        for column in table.columns:
            if column.name in ("created_at", "updated_at") and column.name not in row:
                row[column.name] = datetime(2026, 1, 1)
            if column.name in row or column.nullable or column.server_default is not None:
                continue
            kind = str(column.type).upper()
            row[column.name] = (
                datetime(2026, 1, 1)
                if "DATETIME" in kind
                else 0
                if "INT" in kind or "BOOL" in kind
                else "{}"
                if "JSON" in kind
                else ""
            )
        conn.execute(table.insert().values(**row))

    with engine.begin() as conn:
        insert(conn, "users", id=1, username="owner", password_hash="x")
        insert(conn, "conversations", id=1, user_id=1, title="t")
        insert(conn, "tasks", user_id=1, title="keep me")
    upgrade_database(url, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM conversations")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM tasks")).scalar() == 1
        row = conn.execute(text("SELECT username, role, email FROM users")).one()
    assert tuple(row) == ("owner", "admin", None)


# ------------------------------------------------------------------ email


def test_smtp_sender_refuses_header_injection(monkeypatch):
    from kyvon.services.email_service import EmailError, SmtpEmailSender

    sender = SmtpEmailSender("smtp.example.com", 587, "KYVON <no-reply@example.com>")
    with pytest.raises(EmailError):
        sender.send("a@b.com\nBcc: x@y.com", "hi", "body")
    with pytest.raises(EmailError):
        sender.send("a@b.com", "hi\nBcc: x@y.com", "body")


def test_smtp_sender_uses_starttls_and_login(monkeypatch):
    from kyvon.services import email_service

    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    email_service.SmtpEmailSender(
        "smtp.example.com", 587, "no-reply@example.com", user="u", password="p"
    ).send("a@b.com", "Hello", "Body")
    assert calls == [
        ("connect", "smtp.example.com", 587),
        ("starttls",),
        ("login", "u"),
        ("send", "a@b.com", "Hello"),
    ]


def test_no_email_transport_means_nothing_is_sent_and_nothing_breaks(tmp_path):
    from kyvon.services.email_service import deliver

    assert deliver(None, "a@b.com", ("s", "b")) is False


# -------------------------------------------------------------------- cli


def _cli(hosted, *args, input=None):
    return hosted.test_cli_runner().invoke(args=["kyvon", *args], input=input)


def test_cli_creates_admin_and_ordinary_hosted_accounts_and_allows_many(hosted):
    admin = _cli(
        hosted,
        "create-user",
        "--email",
        "root@example.com",
        "--admin",
        "--password-stdin",
        input=PASSWORD + "\n",
    )
    assert "Created administrator account 'root@example.com'" in admin.output
    other = _cli(
        hosted,
        "create-user",
        "--email",
        "two@example.com",
        "--password-stdin",
        input=PASSWORD + "\n",
    )
    assert "Created user account" in other.output  # several accounts are fine in hosted mode
    with hosted.extensions["kyvon"].session_factory() as s:
        users = {u.email: u for u in s.scalars(select(User))}
    assert users["root@example.com"].role == "admin" and users["root@example.com"].email_verified
    assert users["two@example.com"].role == "user"


def test_cli_needs_an_account_name_when_there_are_several(hosted):
    make_verified(hosted, "a@example.com")
    make_verified(hosted, "b@example.com")
    result = _cli(hosted, "revoke-tokens")
    assert result.exit_code != 0 and "--username" in result.output
    named = _cli(hosted, "revoke-tokens", "--username", "a@example.com")
    assert named.exit_code == 0


def test_doctor_flags_a_hosted_production_setup_without_email(tmp_path):
    from kyvon.services.doctor import FAIL, run_checks

    settings = hosted_settings(tmp_path, KYVON_ENV="production", KYVON_COOKIE_SECURE="true")
    app = make_app(settings)
    svc = app.extensions["kyvon"]
    results = run_checks(settings, svc.session_factory, env_file=None)
    failures = [c.message for c in results if c.level == FAIL]
    assert any("outgoing email" in message for message in failures)


# ------------------------------------------------- shared limits (hosted)


def test_hosted_mode_uses_database_backed_limits_and_personal_mode_does_not(hosted, app):
    from kyvon.utils.rate_limit import (
        DbFailureThrottle,
        DbRateLimiter,
        FailureThrottle,
        RateLimiter,
    )

    h = hosted.extensions["kyvon"]
    assert isinstance(h.auth_limiter, DbRateLimiter) and isinstance(
        h.login_throttle, DbFailureThrottle
    )
    p = app.extensions["kyvon"]
    assert isinstance(p.auth_limiter, RateLimiter) and isinstance(p.login_throttle, FailureThrottle)


def test_two_server_processes_share_one_count(hosted):
    """Separate limiter objects (as in separate worker processes) over one database."""
    from kyvon.utils.rate_limit import DbRateLimiter

    factory = hosted.extensions["kyvon"].session_factory
    worker_a, worker_b = DbRateLimiter(factory), DbRateLimiter(factory)
    assert worker_a.hit("signup:1.2.3.4", 3)[0] and worker_b.hit("signup:1.2.3.4", 3)[0]
    assert worker_a.hit("signup:1.2.3.4", 3)[0]
    allowed, wait = worker_b.hit("signup:1.2.3.4", 3)
    assert allowed is False and 1 <= wait <= 61
    assert worker_a.hit("signup:9.9.9.9", 3)[0]  # other addresses are separate


def test_the_window_expires_and_old_rows_are_pruned(hosted):
    from kyvon.models import RateHit
    from kyvon.utils.rate_limit import DbRateLimiter

    factory = hosted.extensions["kyvon"].session_factory
    clock = {"now": utcnow()}
    limiter = DbRateLimiter(factory, clock=lambda: clock["now"])
    assert limiter.hit("k", 1)[0] and not limiter.hit("k", 1)[0]
    clock["now"] += timedelta(seconds=61)
    assert limiter.hit("k", 1)[0]
    clock["now"] += timedelta(hours=3)
    with factory() as s:
        limiter._prune(s, clock["now"] - timedelta(hours=2))
        assert s.scalars(select(RateHit)).all() == []


def test_ten_wrong_passwords_from_different_addresses_lock_the_account(hosted):
    make_verified(hosted, "target@example.com")
    for i in range(10):
        client = hosted.test_client()
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "target@example.com", "password": "wrong password!"},
            environ_overrides={"REMOTE_ADDR": f"10.0.0.{i + 1}"},
        )
        assert response.status_code == 401
    locked = hosted.test_client().post(
        "/api/v1/auth/login",
        json={"username": "target@example.com", "password": PASSWORD},
        environ_overrides={"REMOTE_ADDR": "10.9.9.9"},
    )
    assert locked.status_code == 429  # even the right password waits out the lock
    other = make_verified(hosted, "bystander@example.com")
    assert other and login(hosted.test_client(), "bystander@example.com")


def test_a_successful_login_clears_the_failure_count(hosted):
    make_verified(hosted, "me@example.com")
    client = hosted.test_client()
    for _ in range(4):
        client.post(
            "/api/v1/auth/login", json={"username": "me@example.com", "password": "wrong password!"}
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "me@example.com", "password": PASSWORD}
        ).status_code
        == 200
    )
    for _ in range(4):
        client.post(
            "/api/v1/auth/login", json={"username": "me@example.com", "password": "wrong password!"}
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "me@example.com", "password": PASSWORD}
        ).status_code
        == 200
    )


# --------------------------------------------------- several workers (hosted)


def test_a_hosted_restart_only_closes_agent_runs_too_old_to_be_alive(hosted):
    from kyvon.models import AgentRun

    svc = hosted.extensions["kyvon"]
    uid = make_verified(hosted, "a@example.com")
    with svc.session_factory() as s:
        fresh = AgentRun(
            user_id=uid, agent="researcher", goal="goal goal", status="running", created_at=utcnow()
        )
        old = AgentRun(
            user_id=uid,
            agent="researcher",
            goal="goal goal",
            status="running",
            created_at=utcnow() - timedelta(hours=1),
        )
        s.add_all([fresh, old])
        s.commit()
        closed = svc.agent_service.recover_orphans(s, stale_after=timedelta(minutes=10))
        assert closed == 1
        assert s.get(AgentRun, fresh.id).status == "running"
        assert s.get(AgentRun, old.id).status == "failed"
        assert svc.agent_service.recover_orphans(s) == 1  # personal mode closes everything left


def test_the_scheduler_command_runs_until_signalled(hosted, monkeypatch):
    import threading

    started = []
    svc = hosted.extensions["kyvon"]
    monkeypatch.setattr(svc.scheduler, "start", lambda: started.append("start"))
    monkeypatch.setattr(svc.scheduler, "stop", lambda: started.append("stop"))
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: True)
    monkeypatch.setattr("signal.signal", lambda *a, **k: None)
    result = _cli(hosted, "scheduler")
    assert result.exit_code == 0 and started == ["start", "stop"]
    assert "Scheduler stopped" in result.output


def test_backup_of_a_server_database_points_to_pg_dump():
    import click

    from kyvon.cli import _sqlite_path

    with pytest.raises(click.ClickException, match="pg_dump"):
        _sqlite_path("postgresql+psycopg://u:p@db/kyvon")
