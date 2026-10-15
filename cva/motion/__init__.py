"""Captions and title cards as transparent PNG overlays on the vv timeline (no Remotion needed).

Captions come from the timeline speech words of a render (work/speech_regions_vN.json), so they are
already in edit time. After a re-cut, regenerate them from the new render.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from cva.ff import ensure_dir

DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def draw_cards(cards: list[dict]) -> list[dict]:
    env = dict(os.environ)
    extra = [p for p in ("/opt/homebrew/lib", "/usr/local/lib") if Path(p).exists()]
    env["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(extra + [env.get("DYLD_FALLBACK_LIBRARY_PATH", "")]).strip(":")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(cards, fh)
    try:
        proc = subprocess.run([sys.executable, "-m", "cva.motion._draw", fh.name], capture_output=True, text=True, env=env)
    finally:
        os.unlink(fh.name)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip().splitlines()[-1] if proc.stderr else "card drawing failed")
    return json.loads(proc.stdout)


def chunk_captions(words: list[dict], *, max_chars: int = 32, max_lines: int = 2, max_dur: float = 3.5,
                   min_dur: float = 0.8, gap_break: float = 0.6, hold: float = 0.3) -> list[dict]:
    """Group timeline words into caption cards: break on pauses, sentence ends, length and duration."""
    cards, cur = [], []
    limit = max_chars * max_lines

    def flush():
        if cur:
            text = " ".join(w["word"] for w in cur).strip()
            cards.append({"text": text, "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur.clear()

    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            length = len(" ".join(x["word"] for x in cur)) + 1 + len(w["word"])
            if (gap > gap_break or length > limit or w["end"] - cur[0]["start"] > max_dur
                    or re.search(r"[.!?।]$", cur[-1]["word"])):
                flush()
        cur.append(w)
    flush()
    for i, c in enumerate(cards):  # hold a little after speech, never into the next card
        nxt = cards[i + 1]["start"] if i + 1 < len(cards) else c["end"] + hold
        c["end"] = round(min(max(c["end"] + hold, c["start"] + min_dur), nxt - 0.04), 3)
        c["start"] = round(c["start"], 3)
    return cards


def add_captions(p, *, version: int | None = None, size: int | None = None, y: str = "H*0.66-h/2",
                 max_chars: int = 32, style: dict | None = None) -> dict:
    """Make caption cards from a render's timeline words and put them on the overlay track (tag captions)."""
    recs = [r for r in p.data.get("renders", []) if version in (None, r["v"])]
    if not recs:
        raise ValueError("render a version first (captions follow the edit)")
    rec = recs[-1]
    words = json.loads(p.abspath(rec["speech"]).read_text())["words"]
    if not words:
        raise ValueError("no timeline words: transcribe the sources first (cva media transcribe ... --id <source>)")
    W = p.data["profile"]["width"]
    size = size or max(28, W // 17)
    cards = chunk_captions(words, max_chars=max_chars)
    out_dir = ensure_dir(p.root / "work" / "overlays" / f"captions_v{rec['v']}")
    for f in out_dir.glob("*.png"):
        f.unlink()
    specs = [{"text": c["text"], "out": str(out_dir / f"cap_{i:03d}.png"), "size": size, "max_chars": max_chars,
              **(style or {})} for i, c in enumerate(cards)]
    drawn = draw_cards(specs)
    p.clear_overlays(tag="captions")
    for c, d in zip(cards, drawn):
        p.add_overlay(str(Path(d["out"]).relative_to(p.root)), c["start"], c["end"], y=y, fade=0.08, tag="captions")
    shaping = {d["shaping"] for d in drawn}
    note = None
    if any(DEVANAGARI.search(c["text"]) for c in cards) and "basic" in shaping:
        note = "Devanagari text drawn without complex shaping - install libraqm (brew install libraqm)"
    return {"cards": len(cards), "version": rec["v"], "dir": str(out_dir.relative_to(p.root)),
            "preview": [c["text"] for c in cards[:5]], "shaping": sorted(shaping), "warning": note}


def add_title(p, text: str, start: float, end: float, *, size: int | None = None, y: str = "(H-h)/2",
              box: bool = False, tag: str = "titles") -> dict:
    W = p.data["profile"]["width"]
    out_dir = ensure_dir(p.root / "work" / "overlays" / tag)
    out = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', text)[:40] or 'title'}_{int(start * 1000)}.png"
    spec = {"text": text, "out": str(out), "size": size or max(40, W // 11), "max_chars": 22, "max_lines": 3}
    if box:
        spec["box"] = [0, 0, 0, 150]
    d = draw_cards([spec])[0]
    ov = p.add_overlay(str(out.relative_to(p.root)), start, end, y=y, fade=0.25, tag=tag)
    return {**ov, "w": d["w"], "h": d["h"], "font": d["font"]}
