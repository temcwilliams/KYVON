"""Memory shortcut parsing (behavior preserved from the prototype)."""

import pytest

from kyvon.services.memory_service import parse_memory_shortcut

# ------------------------------------------------------------ shortcuts


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("remember my dog is Rex", "my dog is Rex"),
        ("REMEMBER x", "x"),
        ("Remember   spaced  ", "spaced"),
        ("remember that I am tall", "I am tall"),  # the prototype kept "that"
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
