"""Logseq (a folder of Markdown files) as KYVON's second brain.

KYVON's database stays the operational source of truth; this is a knowledge integration.
``KnowledgeBase`` is the abstraction (so the storage could change later: an API, a sync
service...); ``FileLogseqGraph`` implements it on a Logseq graph folder.

File-system boundaries, enforced here and nowhere else in KYVON:

* only ``<graph>/pages/*.md`` and ``<graph>/journals/*.md`` are ever read or written
* page names are validated (no path separators except Logseq's ``/`` namespaces, no ``..``,
  no control characters, bounded length) and mapped to file names by a fixed rule
* symbolic links are never followed, and every resolved path must stay inside the graph
* sizes are bounded, writes are atomic, and there is no delete operation at all
* overwriting a page first copies the old version to ``<graph>/.kyvon-backups/``
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from kyvon.services.errors import ConflictError, IntegrationError, NotFoundError, ValidationFailure

MAX_NAME = 120
MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 20_000
MAX_PAGE_BYTES = 200_000
MAX_SEARCH_FILES = 3000
SNIPPET = 200
BACKUP_DIR = ".kyvon-backups"
_BAD_NAME = re.compile(r"[\x00-\x1f\x7f\\:*?\"<>|#%^\[\]{}]")


@dataclass(frozen=True)
class Hit:
    page: str
    line: int
    snippet: str
    score: float


@dataclass(frozen=True)
class Page:
    name: str
    content: str
    truncated: bool
    modified: str


class KnowledgeBase(Protocol):
    def search(self, query: str, limit: int = 10) -> list[Hit]: ...
    def list_pages(self, query: str | None = None, limit: int = 50) -> list[str]: ...
    def read_page(self, name: str) -> Page: ...
    def create_page(self, name: str, content: str) -> str: ...
    def append_to_page(self, name: str, text: str) -> str: ...
    def append_to_journal(self, text: str, day: date | None = None) -> str: ...
    def replace_page(self, name: str, content: str) -> str: ...


def clean_page_name(name: str) -> str:
    """Validate a page name. Logseq namespaces (``Projects/Alpha``) are allowed."""
    value = unicodedata.normalize("NFC", (name or "").strip())
    if not value or len(value) > MAX_NAME:
        raise ValidationFailure(f"A page name must be 1-{MAX_NAME} characters.")
    if _BAD_NAME.search(value) or value.startswith((".", "/")) or value.endswith("/"):
        raise ValidationFailure("That page name contains characters that are not allowed.")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p != p.strip() or p.startswith(".") for p in parts):
        raise ValidationFailure("That page name is not allowed.")
    return value


def to_blocks(text: str) -> str:
    """Logseq is an outliner: make sure each line is a ``- `` block."""
    lines = []
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        if not raw.strip():
            continue
        stripped = raw.lstrip()
        indent = raw[: len(raw) - len(stripped)]
        lines.append(raw if stripped.startswith("- ") else f"{indent}- {stripped}")
    if not lines:
        raise ValidationFailure("There is nothing to write.")
    return "\n".join(lines)


class FileLogseqGraph:
    def __init__(self, root: str | Path):
        self._root = Path(root).expanduser().resolve()
        if not self._root.is_dir():
            raise IntegrationError("The Logseq folder does not exist.")
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------ path safety

    def _dir(self, name: str, *, create: bool = False) -> Path:
        directory = self._root / name
        if directory.is_symlink():
            raise IntegrationError(f"'{name}' must be a real folder, not a link.")
        if create:
            directory.mkdir(exist_ok=True)
        return directory

    def _safe(self, path: Path) -> Path:
        """The path itself must be a regular file inside the graph and not reached via links."""
        if path.is_symlink():
            raise ValidationFailure("Links are not followed.")
        resolved = path.resolve()
        if self._root != resolved and self._root not in resolved.parents:
            raise ValidationFailure("That path is outside the notes folder.")
        return path

    def _page_file(self, name: str) -> tuple[str, Path]:
        clean = clean_page_name(name)
        directory = self._dir("pages")
        filename = clean.replace("/", "___") + ".md"
        # Logseq is case-insensitive about page names; match an existing file that way.
        if directory.is_dir():
            wanted = filename.casefold()
            for existing in directory.iterdir():
                if existing.name.casefold() == wanted:
                    return clean, self._safe(existing)
        return clean, directory / filename

    @staticmethod
    def _page_name(path: Path) -> str:
        return path.stem.replace("___", "/")

    def _journal_file(self, day: date) -> Path:
        return self._dir("journals") / f"{day.strftime('%Y_%m_%d')}.md"

    def _files(self) -> list[Path]:
        found: list[Path] = []
        for folder in ("pages", "journals"):
            directory = self._root / folder
            if not directory.is_dir() or directory.is_symlink():
                continue
            for path in sorted(directory.iterdir()):
                if path.suffix == ".md" and path.is_file() and not path.is_symlink():
                    found.append(path)
                    if len(found) >= MAX_SEARCH_FILES:
                        return found
        return found

    # ------------------------------------------------------------ reading

    @staticmethod
    def _read(path: Path) -> tuple[str, bool]:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            data = handle.read(MAX_READ_BYTES)
        return data.decode("utf-8", errors="replace"), size > MAX_READ_BYTES

    def list_pages(self, query: str | None = None, limit: int = 50) -> list[str]:
        needle = (query or "").casefold()
        names = [self._page_name(p) for p in self._files() if p.parent.name == "pages"]
        if needle:
            names = [n for n in names if needle in n.casefold()]
        return sorted(names, key=str.casefold)[: max(1, min(limit, 200))]

    def read_page(self, name: str) -> Page:
        clean, path = self._page_file(name)
        if not path.is_file():
            raise NotFoundError(f"There is no page called '{clean}'.")
        content, truncated = self._read(self._safe(path))
        return Page(
            self._page_name(path),
            content,
            truncated,
            datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
        )

    def search(self, query: str, limit: int = 10) -> list[Hit]:
        terms = [t for t in re.findall(r"\w+", (query or "").casefold()) if len(t) > 1]
        if not terms:
            raise ValidationFailure("Search for at least one word.")
        hits: list[Hit] = []
        for path in self._files():
            try:
                content, _ = self._read(path)
            except OSError:
                continue
            title = self._page_name(path).casefold()
            title_bonus = sum(2 for t in terms if t in title)
            for number, line in enumerate(content.splitlines(), start=1):
                lowered = line.casefold()
                matched = sum(1 for t in terms if t in lowered)
                if matched == 0 and not (title_bonus and number == 1):
                    continue
                score = matched / len(terms) + title_bonus
                hits.append(Hit(self._page_name(path), number, line.strip()[:SNIPPET], score))
        hits.sort(key=lambda h: (-h.score, h.page.casefold(), h.line))
        return hits[: max(1, min(limit, 50))]

    # ------------------------------------------------------------ writing

    def _write(self, path: Path, content: str) -> None:
        data = content.encode("utf-8")
        if len(data) > MAX_PAGE_BYTES:
            raise ValidationFailure("That page would become too large.")
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".kyvon-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temp, path)  # atomic: readers never see a half-written page
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    @staticmethod
    def _check_size(text: str) -> None:
        if len(text.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValidationFailure(f"Write at most {MAX_WRITE_BYTES // 1000} KB at a time.")

    def create_page(self, name: str, content: str) -> str:
        self._check_size(content)
        clean, path = self._page_file(name)
        blocks = to_blocks(content)
        with self._lock:
            self._dir("pages", create=True)
            if path.exists():
                raise ConflictError(f"A page called '{clean}' already exists.")
            self._write(self._safe(path), blocks + "\n")
        return self._page_name(path)

    def append_to_page(self, name: str, text: str) -> str:
        self._check_size(text)
        clean, path = self._page_file(name)
        blocks = to_blocks(text)
        with self._lock:
            if not path.is_file():
                raise NotFoundError(f"There is no page called '{clean}'. Create it first.")
            existing, truncated = self._read(self._safe(path))
            if truncated:
                raise ValidationFailure("That page is too large to append to safely.")
            separator = "" if existing.endswith("\n") or not existing else "\n"
            self._write(path, existing + separator + blocks + "\n")
        return self._page_name(path)

    def append_to_journal(self, text: str, day: date | None = None) -> str:
        self._check_size(text)
        blocks = to_blocks(text)
        target = self._journal_file(day or date.today())
        with self._lock:
            self._dir("journals", create=True)
            existing = ""
            if target.exists():
                existing, truncated = self._read(self._safe(target))
                if truncated:
                    raise ValidationFailure("That journal is too large to append to safely.")
            separator = "" if existing.endswith("\n") or not existing else "\n"
            self._write(target, existing + separator + blocks + "\n")
        return target.stem.replace("_", "-")

    def replace_page(self, name: str, content: str) -> str:
        self._check_size(content)
        clean, path = self._page_file(name)
        blocks = to_blocks(content)
        with self._lock:
            if not path.is_file():
                raise NotFoundError(f"There is no page called '{clean}'.")
            old, truncated = self._read(self._safe(path))
            if truncated:
                raise ValidationFailure("That page is too large to replace safely.")
            backups = self._root / BACKUP_DIR
            if backups.is_symlink():
                raise IntegrationError("The backup folder must be a real folder.")
            backups.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            (backups / f"{path.stem}.{stamp}.md").write_text(old, encoding="utf-8")
            self._write(path, blocks + "\n")
        return self._page_name(path)


def build_graph(directory: str) -> FileLogseqGraph | None:
    """The configured graph, or None (Logseq is optional; a bad path disables it)."""
    if not directory:
        return None
    try:
        return FileLogseqGraph(directory)
    except IntegrationError:
        return None
