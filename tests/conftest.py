import pytest

# ---------------------------------------------------------------- new app factory


@pytest.fixture
def settings(tmp_path):
    from kyvon.config import Settings

    return Settings.from_env({"GROQ_API_KEY": "test-key", "KYVON_DATA_DIR": str(tmp_path / "data")})


@pytest.fixture
def fake_llm():
    from tests.fakes import FakeLLM

    return FakeLLM()


TEST_USERNAME = "owner"
TEST_PASSWORD = "correct horse battery"  # test-only value


def make_app(settings, **kwargs):
    """Build an app with an empty, schema-initialised database."""
    from kyvon import create_app
    from kyvon.db import Base

    app = create_app(settings, **kwargs)
    Base.metadata.create_all(app.extensions["kyvon"].engine)
    return app


@pytest.fixture
def app(settings, fake_llm):
    return make_app(settings, llm=fake_llm)


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
