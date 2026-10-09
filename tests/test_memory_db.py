import json
from datetime import UTC, datetime, timedelta

import pytest

from kyvon.db import Base, make_engine, make_session_factory
from kyvon.models import Memory, User
from kyvon.services.memory_import import MemoryImportError, import_json_memories
from kyvon.services.memory_service import MemoryService


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'k.db'}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


@pytest.fixture
def user(session):
    u = User(username="owner", password_hash="x")
    session.add(u)
    session.commit()
    return u


@pytest.fixture
def clock():
    state = {"t": datetime(2026, 1, 1, tzinfo=UTC)}

    def now():
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return now


@pytest.fixture
def memory(session, user, clock):
    return MemoryService(session, user.id, now=clock)


def test_empty(memory):
    assert memory.all() == [] and len(memory) == 0


def test_add_and_list(memory):
    memory.add("my dog is Rex")
    (item,) = memory.all()
    assert item["memory"] == "my dog is Rex"
    assert item["date"].endswith("+00:00")
    assert len(memory) == 1


def test_capped_at_100(memory):
    for i in range(105):
        memory.add(f"item {i}")
    assert len(memory) == 100
    assert memory.all()[0]["memory"] == "item 5"


def test_overflow_is_soft_deleted(memory, session):
    for i in range(101):
        memory.add(f"item {i}")
    assert session.query(Memory).count() == 101
    assert session.query(Memory).filter(Memory.deleted_at.is_not(None)).count() == 1


def test_scoped_to_user(session, user, clock):
    other = User(username="other", password_hash="x")
    session.add(other)
    session.commit()
    MemoryService(session, user.id, now=clock).add("mine")
    theirs = MemoryService(session, other.id, now=clock)
    assert theirs.all() == [] and len(theirs) == 0


def test_same_timestamp_ordering_stable(session, user):
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    svc = MemoryService(session, user.id, now=lambda: fixed)
    for i in range(3):
        svc.add(f"memory {i}")
    assert [m["memory"] for m in svc.all()] == ["memory 0", "memory 1", "memory 2"]


# ------------------------------------------------------------------ import


def write(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_import_preserves_text_and_dates(session, user, tmp_path):
    f = tmp_path / "kyvon_memory.json"
    write(
        f,
        [
            {"date": "2026-03-01T10:00:00", "memory": "a"},
            {"date": "2026-03-02T10:00:00", "memory": "b"},
        ],
    )
    result = import_json_memories(session, user.id, f)
    assert (result.imported, result.skipped) == (2, 0)
    items = MemoryService(session, user.id).all()
    assert [m["memory"] for m in items] == ["a", "b"]
    assert items[0]["date"] == "2026-03-01T10:00:00+00:00"
    assert session.query(Memory).filter_by(source="import").count() == 2


def test_import_is_idempotent(session, user, tmp_path):
    f = tmp_path / "m.json"
    write(f, [{"date": "2026-03-01T10:00:00", "memory": "a"}])
    import_json_memories(session, user.id, f)
    again = import_json_memories(session, user.id, f)
    assert (again.imported, again.skipped) == (0, 1)
    assert len(MemoryService(session, user.id)) == 1


def test_import_without_dates_is_still_idempotent(session, user, tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps([{"memory": "no date here"}, {"memory": "nor here", "date": "junk"}]))
    assert import_json_memories(session, user.id, f).imported == 2
    again = import_json_memories(session, user.id, f)
    assert (again.imported, again.skipped) == (0, 2)
    assert session.query(Memory).filter_by(user_id=user.id).count() == 2


def test_import_refuses_entries_that_look_like_secrets(session, user, tmp_path):
    f = tmp_path / "m.json"
    secret = "my key is gsk_" + "a" * 30
    f.write_text(
        json.dumps([{"memory": "likes tea", "date": "2026-01-01T10:00:00"}, {"memory": secret}])
    )
    result = import_json_memories(session, user.id, f)
    assert (result.imported, result.skipped, result.refused_secrets) == (1, 1, 1)
    assert [m.content for m in session.query(Memory).filter_by(user_id=user.id)] == ["likes tea"]


def test_import_does_not_touch_file(session, user, tmp_path):
    f = tmp_path / "m.json"
    write(f, [{"date": "2026-03-01T10:00:00", "memory": "a"}])
    before = f.read_bytes()
    import_json_memories(session, user.id, f)
    assert f.read_bytes() == before


def test_import_skips_bad_entries(session, user, tmp_path):
    f = tmp_path / "m.json"
    write(
        f,
        ["str", {"date": "x"}, {"memory": ""}, {"memory": 5}, {"memory": "ok", "date": "garbage"}],
    )
    result = import_json_memories(session, user.id, f)
    assert (result.imported, result.skipped) == (1, 4)


def test_import_respects_cap(session, user, tmp_path):
    f = tmp_path / "m.json"
    write(f, [{"date": f"2026-01-01T00:00:{i % 60:02d}", "memory": f"m{i}"} for i in range(110)])
    import_json_memories(session, user.id, f)
    assert len(MemoryService(session, user.id)) == 100


@pytest.mark.parametrize("content", ["{not json", '{"a": 1}'])
def test_import_rejects_bad_file(session, user, tmp_path, content):
    f = tmp_path / "m.json"
    f.write_text(content)
    with pytest.raises(MemoryImportError):
        import_json_memories(session, user.id, f)


def test_import_missing_file(session, user, tmp_path):
    with pytest.raises(MemoryImportError, match="not found"):
        import_json_memories(session, user.id, tmp_path / "nope.json")
