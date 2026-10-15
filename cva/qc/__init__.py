"""The check gate: every render must pass before it is reported as done."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cva.ff import ffmpeg_analyse
from cva.media.loudness import ebur128, silences
from cva.media.probe import probe

TARGETS = {
    "social": {"lufs": -14.0, "tp": -1.0, "w": 1080, "h": 1920},
    "youtube": {"lufs": -14.0, "tp": -1.0, "w": 1920, "h": 1080},
    "voice": {"lufs": -16.0, "tp": -1.0, "w": None, "h": None},
    "broadcast": {"lufs": -23.0, "tp": -1.0, "w": 1920, "h": 1080},
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    data: dict = field(default_factory=dict)


def _black_freeze(path: str) -> dict:
    err = ffmpeg_analyse("-i", path, "-an", "-vf",
                         "blackdetect=d=0.1:pix_th=0.10,freezedetect=n=0.003:d=0.5", "-f", "null", "-")
    black = [{"start": float(s), "end": float(e)}
             for s, e in re.findall(r"black_start:(\d+(?:\.\d+)?) black_end:(\d+(?:\.\d+)?)", err)]
    fs = [float(x) for x in re.findall(r"freeze_start: (\d+(?:\.\d+)?)", err)]
    fe = [float(x) for x in re.findall(r"freeze_end: (\d+(?:\.\d+)?)", err)]
    freeze = [{"start": s, "end": fe[i] if i < len(fe) else None} for i, s in enumerate(fs)]
    return {"black": black, "freeze": freeze}


def _covered(span: dict, allowed: list[list[float]], tol: float = 0.25) -> bool:
    end = span["end"] if span["end"] is not None else span["start"]
    return any(span["start"] >= a - tol and end <= b + tol for a, b in allowed)


def gate(path: str | Path, *, target: str = "social", expected_duration: float | None = None,
         expected_fps: float | None = None, allowed_black: list[list[float]] | None = None,
         allowed_silence: list[list[float]] | None = None, lufs_tol: float = 1.0,
         max_duration: float | None = None, size: tuple[int, int] | None = None) -> dict:
    """Run every check. Returns {"pass": bool, "checks": [...], "summary": str}."""
    path = str(path)
    t = dict(TARGETS[target])
    if size:
        t["w"], t["h"] = size
    checks: list[Check] = []
    spec = probe(path)
    v, a = spec["video"], spec["audio"]

    if v:
        ok = (t["w"] is None or (v["width"], v["height"]) == (t["w"], t["h"])) and v["pix_fmt"] == "yuv420p"
        if expected_fps:
            ok = ok and abs((v["fps"] or 0) - expected_fps) < 0.01
        checks.append(Check("specs", ok, f'{v["width"]}x{v["height"]} {v["fps"]}fps {v["pix_fmt"]} {v["codec"]}', v))
    if not a:
        checks.append(Check("audio", False, "no audio stream"))
    else:
        checks.append(Check("audio_format", a["sample_rate"] == 48000 and a["channels"] == 2,
                            f'{a["codec"]} {a["sample_rate"]} Hz {a["channels"]} ch', a))
        lo = ebur128(path)
        i_ok = lo["integrated_lufs"] is not None and abs(lo["integrated_lufs"] - t["lufs"]) <= lufs_tol
        tp_ok = lo["true_peak_dbtp"] is not None and lo["true_peak_dbtp"] <= t["tp"] + 0.05
        checks.append(Check("loudness", i_ok, f'{lo["integrated_lufs"]} LUFS (target {t["lufs"]}±{lufs_tol})', lo))
        checks.append(Check("true_peak", tp_ok, f'{lo["true_peak_dbtp"]} dBTP (max {t["tp"]})', lo))
        sil = silences(path, noise_db=-50, min_dur=0.7)
        bad = [s for s in sil if not _covered(s, allowed_silence or [])]
        checks.append(Check("silence_holes", not bad, f"{len(bad)} unexpected silent stretch(es)", {"spans": bad}))

    dur = spec["duration"]
    if expected_duration is not None:
        fps = (v or {}).get("fps") or 25
        checks.append(Check("length", abs(dur - expected_duration) <= 1.5 / fps,
                            f"{dur:.3f}s (expected {expected_duration:.3f}s)"))
    if max_duration is not None:
        checks.append(Check("max_length", dur <= max_duration, f"{dur:.2f}s (max {max_duration}s)"))

    if v:
        bf = _black_freeze(path)
        bad_black = [b for b in bf["black"] if not _covered(b, allowed_black or [])]
        checks.append(Check("black_frames", not bad_black, f"{len(bad_black)} unexpected black span(s)",
                            {"unexpected": bad_black, "all": bf["black"]}))
        checks.append(Check("frozen_frames", not bf["freeze"], f'{len(bf["freeze"])} frozen span(s) >= 0.5s',
                            {"spans": bf["freeze"]}))

    passed = all(c.ok for c in checks)
    lines = [f'{"PASS" if c.ok else "FAIL"}  {c.name}: {c.detail}' for c in checks]
    return {"pass": passed, "file": path, "target": target, "checks": [asdict(c) for c in checks],
            "summary": "\n".join(lines),
            "cannot_check": "Music balance, emotional feel and voice tone need a human listener."}
