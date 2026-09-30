"""Long-term memory: rules, retrieval, service, chat integration and API."""

from datetime import UTC, datetime, timedelta

import pytest

from kyvon.db import Base, make_engine, make_session_factory
from kyvon.models import Memory, User
from kyvon.services.errors import ConflictError, NotFoundError, ValidationFailure
from kyvon.services.memory_retrieval import LexicalRetriever, tokens
from kyvon.services.memory_rules import (
    looks_like_secret,
    parse_memory_shortcut,
    parse_recall_request,
    validate_category,
    validate_importance,
    validate_memory_text,
)
from kyvon.services.memory_service import MemoryService


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'k.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def users(session):
    a, b = User(username="a", password_hash="x"), User(username="b", password_hash="x")
    session.add_all([a, b])
    session.commit()
    return a, b


@pytest.fixture
def clock():
    state = {"t": datetime(2026, 1, 1, tzinfo=UTC)}

    def now():
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return now


@pytest.fixture
def memory(session, users, clock):
    return MemoryService(session, users[0].id, now=clock)


# ------------------------------------------------------------ shortcuts and recall parsing


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("remember my dog is Rex", "my dog is Rex"),
        ("remember that I am tall", "I am tall"),
        ("Remember That I like tea", "I like tea"),
        ("don't forget that milk", "milk"),
        ("keep in mind that it rains", "it rains"),
        ("remember", None),
        ("do you remember me?", None),
    ],
)
def test_shortcuts(message, expected):
    assert parse_memory_shortcut(message) == expected


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("What do you remember?", None),
        ("what do you remember about my dog?", "my dog"),
        ("what do you know about me", None),
        ("what do you know about Alice?", "Alice"),
        ("Show me what you remember", None),
        ("list my memories", None),
    ],
)
def test_recall_requests(message, topic):
    assert parse_recall_request(message) == (True, topic)


@pytest.mark.parametrize("message", ["hello", "what do you think about tea", "remember my dog"])
def test_not_recall_requests(message):
    assert parse_recall_request(message)[0] is False


# ------------------------------------------------------------ validation and pollution guards


@pytest.mark.parametrize(
    "text",
    [
        "my password is hunter2hunter2",
        "the api key is abc123",
        "gsk_" + "a" * 30,
        "sk-" + "b" * 30,
        "AKIA" + "A" * 16,
        "Bearer " + "x" * 30,
        "-----BEGIN RSA PRIVATE KEY-----",
        "token: " + "z" * 10,
        "0123456789abcdef" * 3,
    ],
)
def test_secrets_are_never_stored(text):
    assert looks_like_secret(text)
    with pytest.raises(ValidationFailure, match="secret"):
        validate_memory_text(text)


@pytest.mark.parametrize(
    "text", ["I like green tea", "my dog Rex is 4 years old", "Dentist is Dr. Lee"]
)
def test_normal_memories_pass(text):
    assert validate_memory_text(f"  {text}  ") == text


def test_length_limits():
    with pytest.raises(ValidationFailure, match="short"):
        validate_memory_text("hi")
    with pytest.raises(ValidationFailure, match="500"):
        validate_memory_text("x " * 300)


def test_category_and_importance_validation():
    assert (
        validate_category(None) == "general" and validate_category(" Preference ") == "preference"
    )
    assert validate_importance(None) == 3
    for bad in (0, 6, "3", True):
        with pytest.raises(ValidationFailure):
            validate_importance(bad)
    with pytest.raises(ValidationFailure):
        validate_category("secrets")


def test_shortcut_that_looks_like_a_secret_is_explained_in_chat(client, fake_llm):
    body = client.post(
        "/api/v1/chat", json={"message": "remember my password is hunter2hunter2"}
    ).get_json()
    assert body["memory_saved"] is False and "secret" in body["response"]
    assert client.get("/api/v1/memories").get_json()["memories"] == []
    assert fake_llm.calls == []


# ------------------------------------------------------------ service


def test_add_get_update_delete(memory):
    saved = memory.add("I like green tea", category="preference", importance=4)
    assert saved.created and saved.memory.category == "preference" and saved.memory.importance == 4
    updated = memory.update(saved.memory.id, text="I love green tea", importance=5)
    assert updated.content == "I love green tea" and updated.importance == 5
    memory.delete(saved.memory.id)
    assert len(memory) == 0
    with pytest.raises(NotFoundError):
        memory.get(saved.memory.id)


def test_delete_is_soft(memory, session):
    saved = memory.add("something to forget")
    memory.delete(saved.memory.id)
    row = session.get(Memory, saved.memory.id)
    assert row is not None and row.deleted_at is not None


def test_duplicates_are_not_created(memory):
    first = memory.add("I like green tea")
    again = memory.add("  i LIKE   green tea ")
    assert not again.created and again.memory.id == first.memory.id and len(memory) == 1


def test_deleted_text_can_be_saved_again(memory):
    first = memory.add("I like green tea")
    memory.delete(first.memory.id)
    assert memory.add("I like green tea").created


def test_update_cannot_create_duplicate(memory):
    memory.add("fact one here")
    other = memory.add("fact two here")
    with pytest.raises(ConflictError):
        memory.update(other.memory.id, text="Fact one here")


def test_update_hash_changes_so_dedupe_follows_new_text(memory):
    saved = memory.add("old text here")
    memory.update(saved.memory.id, text="new text here")
    assert memory.add("old text here").created
    assert not memory.add("new text here").created


def test_timestamps(memory, clock):
    saved = memory.add("timestamps matter")
    created = saved.memory.created_at
    memory.update(saved.memory.id, importance=2)
    assert saved.memory.updated_at > created and saved.memory.last_used_at is None


def test_isolation_between_users(session, users, clock):
    a = MemoryService(session, users[0].id, now=clock)
    b = MemoryService(session, users[1].id, now=clock)
    saved = a.add("only for user a")
    assert b.all() == [] and len(b) == 0 and b.search("user") == []
    assert b.recall_text(None) == "I don't have any saved memories yet."
    for action in (b.get, b.delete):
        with pytest.raises(NotFoundError):
            action(saved.memory.id)
    with pytest.raises(NotFoundError):
        b.update(saved.memory.id, text="hijacked memory")
    assert b.add("only for user a").created  # the same text is fine for another user


def test_list_filters_and_pages(memory):
    memory.add("tea preference here", category="preference")
    memory.add("project alpha notes", category="project")
    memory.add("another preference item", category="preference")
    rows, total = memory.list(category="preference")
    assert total == 2 and [m.content for m in rows] == [
        "another preference item",
        "tea preference here",
    ]
    page, total = memory.list(limit=1, offset=1)
    assert total == 3 and len(page) == 1


def test_cap_retires_least_important_oldest_first(session, users, clock):
    svc = MemoryService(session, users[0].id, now=clock, max_memories=3)
    svc.add("keeper important", importance=5)
    svc.add("old minor", importance=1)
    svc.add("newer minor", importance=1)
    svc.add("newest normal")
    assert sorted(m["memory"] for m in svc.all()) == [
        "keeper important",
        "newer minor",
        "newest normal",
    ]


# ------------------------------------------------------------ retrieval


def add_all(memory, *texts, **kw):
    return [memory.add(t, **kw).memory for t in texts]


def ranked(memory, query, k=8):
    return [h.memory.content for h in memory.search(query, k)]


def test_tokenizer_drops_stopwords_and_stems():
    assert tokens("What is my dog's name?") == tokens("dog nam")
    assert tokens("makes") == tokens("making") == tokens("make")
    assert tokens("walks") == tokens("walked") == tokens("walking") == tokens("walk")
    assert tokens("running") == tokens("runs") == tokens("run")
    assert tokens("the of and") == []


def test_relevant_memories_rank_first(memory):
    add_all(
        memory,
        "my dog is named Rex",
        "I work at a bakery on Main Street",
        "my sister Anna lives in Denver",
        "I prefer dark roast coffee",
    )
    assert ranked(memory, "what's my dog called?")[0] == "my dog is named Rex"
    assert ranked(memory, "where does my sister live")[0] == "my sister Anna lives in Denver"
    assert ranked(memory, "which coffee do I like")[0] == "I prefer dark roast coffee"


def test_irrelevant_queries_return_nothing(memory):
    add_all(memory, "my dog is named Rex", "I work at a bakery")
    assert ranked(memory, "explain quantum entanglement") == []
    assert ranked(memory, "") == [] and ranked(memory, "the of and") == []


def test_stemming_matches_word_forms(memory):
    add_all(memory, "I enjoy running in the morning")
    assert ranked(memory, "do I go run often?") == ["I enjoy running in the morning"]


def test_importance_breaks_ties(memory):
    minor, major = add_all(memory, "coffee at cafe one", "coffee at cafe two")
    memory.update(major.id, importance=4)
    assert ranked(memory, "coffee cafe")[0] == "coffee at cafe two"


def test_core_memories_always_included_but_capped(memory):
    add_all(memory, *[f"core fact number {i} here" for i in range(5)], importance=5)
    add_all(memory, "the dog is Rex")
    hits = ranked(memory, "tell me about the dog")
    assert "the dog is Rex" in hits
    assert sum(1 for h in hits if h.startswith("core fact")) == 3


def test_k_limits_results(memory):
    add_all(memory, *[f"tea variety {i}" for i in range(20)])
    assert len(ranked(memory, "tea variety", k=5)) == 5


def test_retrieve_marks_memories_used_and_search_does_not(memory):
    saved = memory.add("my dog is named Rex").memory
    memory.search("dog")
    assert saved.last_used_at is None and saved.use_count == 0
    memory.retrieve("dog")
    assert saved.last_used_at is not None and saved.use_count == 1


def test_retrieve_text_only_contains_relevant_memories(memory):
    add_all(memory, "my dog is named Rex", "I work at a bakery")
    text = memory.retrieve_text("dog")
    assert text == "- my dog is named Rex"


def test_retrieval_does_not_dump_every_memory(memory):
    add_all(memory, *[f"unrelated fact {chr(97 + i)}{i}" for i in range(25)], "the dog is Rex")
    assert memory.retrieve_text("what is the dog called") == "- the dog is Rex"


def test_retriever_is_replaceable(session, users, clock):
    class Fixed:
        def rank(self, query, memories, k, *, now):
            from kyvon.services.memory_retrieval import Scored

            return [Scored(m, 1.0) for m in memories[:1]]

    svc = MemoryService(session, users[0].id, now=clock, retriever=Fixed())
    svc.add("first memory here")
    svc.add("second memory here")
    assert [h.memory.content for h in svc.search("anything")] == ["first memory here"]
    assert isinstance(LexicalRetriever(), LexicalRetriever)


def test_recall_text(memory):
    assert memory.recall_text(None) == "I don't have any saved memories yet."
    add_all(memory, "my dog is named Rex", "I like tea")
    assert memory.recall_text(None).splitlines()[1:] == ["• I like tea", "• my dog is named Rex"]
    assert memory.recall_text("dog") == "Here is what I remember about dog:\n• my dog is named Rex"
    assert memory.recall_text("spaceships") == "I don't have anything saved about spaceships."


# ------------------------------------------------------------ chat integration


def chat(client, message, cid=None):
    body = {"message": message, **({"conversation_id": cid} if cid else {})}
    return client.post("/api/v1/chat", json=body).get_json()


def test_chat_recall_answers_from_memory_without_the_model(client, fake_llm):
    chat(client, "remember my dog is Rex")
    body = chat(client, "What do you remember about my dog?")
    assert body["recall"] is True and "my dog is Rex" in body["response"]
    assert fake_llm.calls == []


def test_chat_duplicate_remember_is_reported(client):
    chat(client, "remember my dog is Rex")
    assert chat(client, "remember my dog is Rex")["response"] == "I already have that saved."


def test_followup_uses_previous_message_for_retrieval(client, fake_llm):
    chat(client, "remember my sister Anna lives in Denver")
    cid = chat(client, "Tell me about my sister")["conversation_id"]
    chat(client, "and where does she live?", cid)
    assert "Anna lives in Denver" in fake_llm.calls[-1]["messages"][0]["content"]


def test_conversation_text_is_not_turned_into_memories(client, session_factory=None):
    chat(client, "I had pasta for lunch and my favorite color is green")
    assert client.get("/api/v1/memories").get_json()["memories"] == []


# ------------------------------------------------------------ API


def test_api_crud(client):
    created = client.post(
        "/api/v1/memories",
        json={"text": "I like green tea", "category": "preference", "importance": 4},
    )
    assert created.status_code == 201
    memory = created.get_json()["memory"]
    assert memory["category"] == "preference" and memory["importance"] == 4
    assert memory["source"] == "user"

    url = f"/api/v1/memories/{memory['id']}"
    assert client.get(url).get_json()["memory"]["memory"] == "I like green tea"
    patched = client.patch(url, json={"text": "I love green tea", "importance": 5})
    assert patched.get_json()["memory"]["importance"] == 5
    listed = client.get("/api/v1/memories").get_json()
    assert listed["total"] == 1 and listed["memories"][0]["memory"] == "I love green tea"
    assert client.delete(url).status_code == 200
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/memories").get_json()["memories"] == []


def test_api_duplicate_create_returns_existing(client):
    first = client.post("/api/v1/memories", json={"text": "I like tea"}).get_json()
    second = client.post("/api/v1/memories", json={"text": "i like TEA"})
    assert second.status_code == 200 and second.get_json()["duplicate"] is True
    assert second.get_json()["memory"]["id"] == first["memory"]["id"]


@pytest.mark.parametrize(
    "body",
    [
        {"text": "my password is hunter2hunter2"},
        {"text": "hi"},
        {"text": "fine text here", "importance": 9},
        {"text": "fine text here", "category": "nope"},
        {},
    ],
)
def test_api_validation(client, body):
    assert client.post("/api/v1/memories", json=body).status_code == 400


def test_api_search_and_category_filter(client):
    client.post("/api/v1/memories", json={"text": "my dog is named Rex"})
    client.post(
        "/api/v1/memories", json={"text": "meeting notes for project", "category": "project"}
    )
    hits = client.get("/api/v1/memories?q=dog").get_json()["memories"]
    assert [h["memory"] for h in hits] == ["my dog is named Rex"] and "score" in hits[0]
    only = client.get("/api/v1/memories?category=project").get_json()
    assert only["total"] == 1
    assert client.get("/api/v1/memories/categories").get_json()["categories"][0] == "general"
    assert client.get("/api/v1/memories?category=bogus").status_code == 400


def test_api_edit_conflict_is_409(client):
    client.post("/api/v1/memories", json={"text": "fact number one"})
    other = client.post("/api/v1/memories", json={"text": "fact number two"}).get_json()["memory"]
    response = client.patch(f"/api/v1/memories/{other['id']}", json={"text": "fact number one"})
    assert response.status_code == 409


def test_api_memory_isolation(app, client, anon_client):
    from kyvon.services import auth_service

    mine = client.post("/api/v1/memories", json={"text": "private fact here"}).get_json()["memory"]
    with app.extensions["kyvon"].session_factory() as s:
        stranger = User(username="stranger", password_hash="x")
        s.add(stranger)
        s.commit()
        raw, _ = auth_service.issue_token(s, stranger, name="t", ttl_days=1)
    h = {"Authorization": f"Bearer {raw}"}
    url = f"/api/v1/memories/{mine['id']}"
    assert anon_client.get(url, headers=h).status_code == 404
    assert anon_client.patch(url, json={"text": "hijacked text"}, headers=h).status_code == 404
    assert anon_client.delete(url, headers=h).status_code == 404
    assert anon_client.get("/api/v1/memories", headers=h).get_json()["memories"] == []
    assert anon_client.get("/api/v1/memories?q=private", headers=h).get_json()["memories"] == []
    assert client.get(url).status_code == 200


def test_memory_migration_backfills_hash(tmp_path):
    from sqlalchemy import text

    from kyvon.db import upgrade_database

    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade_database(url, "0002")
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, password_hash, created_at, settings) VALUES (1,'u','x','2026-01-01 00:00:00','{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO memories (user_id, content, source, created_at, updated_at) VALUES (1,'  Old   Fact ','import','2026-01-01 00:00:00','2026-01-01 00:00:00')"
            )
        )
    upgrade_database(url, "head")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT importance, use_count, content_hash FROM memories")).one()
    from kyvon.services.memory_rules import content_hash

    assert row[0] == 3 and row[1] == 0 and row[2] == content_hash("old fact")
