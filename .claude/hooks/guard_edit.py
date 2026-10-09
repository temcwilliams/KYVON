#!/usr/bin/env python3
"""PreToolUse: block edits to real env files and to migrations already committed to git."""

import json
import subprocess
import sys
from pathlib import Path


def block(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)  # exit 2 makes Claude Code block the tool call


data = json.load(sys.stdin)
path = Path(data.get("tool_input", {}).get("file_path", ""))
name = path.name

if name.startswith(".env") and not name.endswith(".example"):
    block("Blocked: real env files hold secrets. Edit .env*.example instead, or ask the user.")

if "migrations/versions" in path.as_posix() and path.suffix == ".py":
    tracked = (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=path.parent,
            capture_output=True,
        ).returncode
        == 0
    )
    if tracked:
        block(
            "Blocked: this migration is already committed. Add a new Alembic revision "
            "instead of editing history."
        )
