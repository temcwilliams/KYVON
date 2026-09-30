"""Service-worker rendering: a cache version derived from the shipped web files."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Files needed to show the app offline. Everything is under /static/ except the page itself.
SHELL_EXTRA = ["/", "/manifest.webmanifest"]


def shell_files() -> list[str]:
    urls = list(SHELL_EXTRA)
    for path in sorted(WEB_DIR.rglob("*")):
        if not path.is_file() or path.name in ("sw.js", "index.html", "manifest.webmanifest"):
            continue
        urls.append("/static/" + path.relative_to(WEB_DIR).as_posix())
    return urls


def version() -> str:
    digest = hashlib.sha256()
    for path in sorted(WEB_DIR.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(WEB_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


@lru_cache(maxsize=1)
def render_service_worker() -> str:
    source = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
    return source.replace("__VERSION__", version()).replace("__SHELL__", json.dumps(shell_files()))
