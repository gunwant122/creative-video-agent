"""Environment loading shared by every entry point (server, cva, vv, vd, chat)."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_env(path: str | Path | None = None) -> None:
    """KEY=value lines from the given file, else the repo's .env and ./.env. Real env vars win."""
    files = [Path(path)] if path else [REPO / ".env", Path.cwd() / ".env"]
    for f in files:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and k and not k.startswith("#") and v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
