"""Frontend sanity checks (no browser needed): references resolve, ids exist, no unsafe patterns."""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
JS_FILES = sorted((WEB / "js").glob("*.js"))
INDEX = (WEB / "index.html").read_text()


def test_there_are_js_modules():
    assert {p.name for p in JS_FILES} >= {"main.js", "api.js", "chat.js", "auth.js", "ui.js"}


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_relative_imports_resolve(path):
    for target in re.findall(r'(?:from|import)\s+"(\./[^"]+)"', path.read_text()):
        assert (path.parent / target).exists(), f"{path.name} imports missing {target}"


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_imported_names_are_exported(path):
    for names, target in re.findall(
        r'import\s*\{([^}]+)\}\s*from\s*"(\./[^"]+)"', path.read_text()
    ):
        source = (path.parent / target).read_text()
        for name in (n.strip().split(" as ")[0] for n in names.split(",") if n.strip()):
            exported = re.search(
                rf"export\s+(?:async\s+)?(?:function|const|let|class)\s+{name}\b", source
            ) or re.search(rf"export\s*\{{[^}}]*\b{name}\b", source)
            assert exported, f"{path.name}: {name} is not exported by {target}"


def test_static_element_ids_used_by_scripts_exist_in_html():
    used = set()
    for path in JS_FILES:
        used |= set(re.findall(r'getElementById\("([^"]+)"\)', path.read_text()))
    ids = set(re.findall(r'id="([^"]+)"', INDEX))
    assert used - ids == set(), f"ids used by scripts but missing from index.html: {used - ids}"


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_no_unsafe_dom_patterns(path):
    text = path.read_text()
    assert ".innerHTML" not in text and "insertAdjacentHTML" not in text
    assert "eval(" not in text and "document.write" not in text


def test_html_is_accessible_enough():
    assert 'lang="en"' in INDEX and 'name="viewport"' in INDEX
    for control in ("sendButton", "micButton", "messageInput"):
        assert re.search(rf'id="{control}"[^>]*aria-label=', INDEX, re.S), control
    assert 'aria-live="polite"' in INDEX and 'role="log"' in INDEX


def test_no_leftover_prototype_branding():
    for path in [WEB / "index.html", WEB / "css" / "style.css", *JS_FILES]:
        assert "jarvis" not in path.read_text().lower(), path.name
