"""Unit tests for the extracted memory service.

Mirrors the memory characterization tests for app.py, so old and new code are
held to the same behavior.
"""

import json
from datetime import datetime

import pytest

from kyvon.config import Settings
from kyvon.services.memory_service import MemoryStore, parse_memory_shortcut


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "data" / "kyvon_memory.json")


# ------------------------------------------------------------ shortcuts


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("remember my dog is Rex", "my dog is Rex"),
        ("REMEMBER x", "x"),
        ("Remember   spaced  ", "spaced"),
        ("remember that I am tall", "that I am tall"),  # known quirk
        ("don't forget that milk is low", "milk is low"),
        ("Don't Forget That milk", "milk"),
        ("keep in mind that it rains", "it rains"),
    ],
)
def test_shortcuts_recognized(message, expected):
    assert parse_memory_shortcut(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "hello",
        "remember",  # stripped message lacks the trailing space
        "please remember this",
        "web remember x",
        "don't forget that",
        "keep in mind that",
        "",
    ],
)
def test_non_shortcuts(message):
    assert parse_memory_shortcut(message) is None


# ------------------------------------------------------------ store


def test_empty_store(store):
    assert store.all() == []
    assert len(store) == 0
    assert store.prompt_text() == "No saved memories."


def test_add_persists_prototype_format(store):
    fixed = datetime(2026, 1, 2, 3, 4, 5)
    store._now = lambda: fixed
    store.add("my dog is Rex")

    raw = store.path.read_text(encoding="utf-8")
    assert json.loads(raw) == [{"date": "2026-01-02T03:04:05", "memory": "my dog is Rex"}]
    assert raw.startswith("[\n    {")  # indent=4, as before


def test_data_dir_created_on_first_write(tmp_path):
    s = MemoryStore(tmp_path / "nested" / "dir" / "m.json")
    s.add("x")
    assert (tmp_path / "nested" / "dir" / "m.json").exists()


def test_capped_at_100(store):
    for i in range(105):
        store.add(f"item {i}")
    assert len(store) == 100
    assert store.all()[0]["memory"] == "item 5"
    assert len(json.loads(store.path.read_text())) == 100


def test_prompt_text_last_20(store):
    for i in range(25):
        store.add(f"item {i}")
    lines = store.prompt_text().splitlines()
    assert len(lines) == 20
    assert lines[0] == "- item 5" and lines[-1] == "- item 24"


def test_loads_existing_prototype_file(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps([{"date": "2026-01-01T00:00:00", "memory": "old"}]))
    s = MemoryStore(path)
    assert s.all() == [{"date": "2026-01-01T00:00:00", "memory": "old"}]
    s.add("new")
    assert [m["memory"] for m in json.loads(path.read_text())] == ["old", "new"]


def test_corrupt_file_loads_empty(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{not json")
    assert MemoryStore(path).all() == []


def test_non_list_file_loads_empty(tmp_path):
    path = tmp_path / "m.json"
    path.write_text('{"a": 1}')
    assert MemoryStore(path).all() == []


def test_entry_missing_memory_key_renders_blank(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps([{"date": "x"}]))
    assert MemoryStore(path).prompt_text() == "- "


def test_unicode_round_trip(store):
    store.add("café ☕")
    assert MemoryStore(store.path).all()[0]["memory"] == "café ☕"


def test_all_returns_copy(store):
    store.add("a")
    store.all().clear()
    assert len(store) == 1


def test_reload_reads_disk_without_changing_state(store):
    store.add("a")
    store.path.write_text(json.dumps([{"date": "d", "memory": "b"}, {"date": "d", "memory": "c"}]))
    assert len(store.reload()) == 2
    assert len(store) == 1


def test_uses_configured_data_dir(tmp_path):
    settings = Settings.from_env({"GROQ_API_KEY": "k", "KYVON_DATA_DIR": str(tmp_path / "d")})
    s = MemoryStore(settings.memory_file)
    s.add("x")
    assert (tmp_path / "d" / "kyvon_memory.json").exists()


def test_file_is_interchangeable_with_legacy_app(prototype, tmp_path):
    """A file written by the new service is read by app.py, and vice versa."""
    path = tmp_path / "data" / "kyvon_memory.json"
    prototype.add_memory("from legacy")
    assert MemoryStore(path).all()[0]["memory"] == "from legacy"

    MemoryStore(path).add("from new")
    assert [m["memory"] for m in prototype.load_memory()] == ["from legacy", "from new"]
