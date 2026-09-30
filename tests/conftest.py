import pytest

# ---------------------------------------------------------------- new app factory


@pytest.fixture
def settings(tmp_path):
    from kyvon.config import Settings

    return Settings.from_env(
        {
            "GROQ_API_KEY": "test-key",
            "KYVON_DATA_DIR": str(tmp_path / "data"),
            "KYVON_AUTO_TITLE_LLM": "false",
            "KYVON_SCHEDULER": "false",
            "KYVON_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "GOOGLE_CLIENT_ID": "test-client-id",
            "GOOGLE_CLIENT_SECRET": "test-client-secret",
            "KYVON_PUBLIC_URL": "https://kyvon.example.com",
        }
    )


@pytest.fixture
def fake_llm():
    from tests.fakes import FakeLLM

    return FakeLLM()


TEST_ENCRYPTION_KEY = "Ip9tPuY8_kM4PfVv3n1bL0HqUu0RzE7c0mV2xX3kQYc="  # test-only Fernet key
TEST_USERNAME = "owner"
TEST_PASSWORD = "correct horse battery"  # test-only value


def make_app(settings, **kwargs):
    """Build an app with an empty, schema-initialised database."""
    from kyvon import create_app
    from kyvon.db import Base

    app = create_app(settings, **kwargs)
    Base.metadata.create_all(app.extensions["kyvon"].engine)
    return app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never reach the internet: every real HTTP call is an error."""

    def blocked(self, method, url, *args, **kwargs):
        raise RuntimeError(f"Network access attempted in a test: {method} {url}")

    monkeypatch.setattr("requests.sessions.Session.request", blocked)


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """scrypt is deliberately slow; use a cheap hash so the suite stays fast.

    Verification still goes through werkzeug's check_password_hash, which reads the
    method from the stored hash, so the login logic under test is unchanged.
    """
    from werkzeug.security import generate_password_hash

    monkeypatch.setattr(
        "kyvon.services.auth_service.generate_password_hash",
        lambda password: generate_password_hash(password, method="pbkdf2:sha256:1000"),
    )


LOCATION = {"city": "Testville", "state": "TX", "country": "USA", "display": "Testville, TX, USA"}
WEATHER = {
    "temperature": 70.5,
    "feels_like": 71.0,
    "humidity": 40,
    "precipitation": 0.0,
    "wind": 5.0,
    "condition": "Clear sky",
    "time": "2026-01-01T12:00",
    "timezone": "America/Chicago",
}


@pytest.fixture
def fake_environment(settings):
    from kyvon.services.environment_service import EnvironmentService
    from kyvon.utils.error_log import ErrorLog

    return EnvironmentService(
        ErrorLog(settings.error_log),
        geocoder=lambda lat, lon: dict(LOCATION),
        weather_source=lambda lat, lon: dict(WEATHER),
    )


@pytest.fixture
def app(settings, fake_llm, fake_environment):
    return make_app(settings, llm=fake_llm, environment=fake_environment)


@pytest.fixture
def owner(app):
    from kyvon.services import auth_service

    with app.extensions["kyvon"].session_factory() as session:
        return auth_service.create_owner(session, TEST_USERNAME, TEST_PASSWORD)


@pytest.fixture
def anon_client(app):
    return app.test_client()


@pytest.fixture
def client(app, owner):
    """A test client logged in with a bearer token."""
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {response.get_json()['token']}"
    return client
