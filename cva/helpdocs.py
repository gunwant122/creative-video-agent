"""`help` pages for vv / vd. Craft topics are the skills' reference files, so there is one source."""
from __future__ import annotations

import os
from pathlib import Path


def skills_root() -> Path:
    env = os.environ.get("CVA_SKILLS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "skills"


def render_help(builtin: dict[str, str], craft: dict[str, str], topic: str | None) -> str:
    if not topic:
        lines = ["Topics:"]
        lines += [f"  {k:22s} (commands)" for k in builtin]
        lines += [f"  {k:22s} (craft guide)" for k in craft]
        return "\n".join(lines)
    if topic in builtin:
        return builtin[topic].strip()
    if topic in craft:
        f = skills_root() / craft[topic]
        return f.read_text() if f.exists() else f"(guide file missing: {f})"
    return f"unknown topic {topic!r}\n\n" + render_help(builtin, craft, None)
