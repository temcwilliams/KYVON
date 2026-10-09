#!/usr/bin/env python3
"""PostToolUse: run ruff fix + format on edited Python files, using the project venv."""

import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
data = json.load(sys.stdin)
path = data.get("tool_input", {}).get("file_path", "")
ruff = root / ".venv" / "bin" / "ruff"

if path.endswith(".py") and ruff.exists() and Path(path).exists():
    subprocess.run([str(ruff), "check", "--fix", "-q", path], cwd=root)
    subprocess.run([str(ruff), "format", "-q", path], cwd=root)
