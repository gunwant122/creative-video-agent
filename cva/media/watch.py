"""Watch and listen with a video-native model (Gemini through the LiteLLM proxy).

Video models sample about 1 frame per second, so short AI glitches slip through at normal speed.
`glitches` mode sends a silent copy slowed down `slow` times (default 6x, i.e. ~6 real frames per second
sampled) and maps the reported times back. `listen` and `review` modes send normal-speed video with sound.
Every timestamp is approximate (+-0.3 s): confirm visual findings with zoom sheets before acting.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import tempfile
from pathlib import Path

from cva.ff import ffmpeg
from cva.media.probe import probe

PROMPTS = {
    "glitches": (
        "This is AI-generated drama footage, slowed down {slow}x and silent. Find every visual fault: morphing "
        "faces or hands, objects appearing/disappearing, sudden texture or lighting jumps, warped text, merging "
        "limbs, flashes, hidden cuts. Do NOT report normal camera moves, parallax, people entering frame, or "
        "consistent costume/set design. Timestamps are seconds of THIS video."),
    "listen": (
        "Listen to this episode section as a re-recording mixer and watch the picture for context. Report "
        "problems with timestamps: dialogue hard to understand, music too loud or too quiet under speech, music "
        "melody fighting the voice, abrupt audio cuts, clicks, level jumps between shots, noise, sync problems, "
        "and moments where the music mood does not fit the scene. Also note what works."),
    "review": (
        "Review this edited drama section as a picture editor watching at full speed. Report with timestamps: "
        "pacing that drags or rushes, cuts that feel jumpy, transitions that feel wrong, continuity errors, "
        "visible glitches, and the emotional beats that land or miss."),
}

SCHEMA = ('Answer ONLY with JSON: {"events": [{"t": <start seconds>, "end": <end seconds>, "kind": "<short label>", '
          '"what": "<one sentence>", "severity": "high|low"}], "notes": "<one or two sentences overall>"}. '
          'Use an empty list if nothing is wrong.')


def _client():
    from openai import OpenAI

    from cva.models import _openai_base, litellm_settings
    base, key = litellm_settings()
    return OpenAI(base_url=_openai_base(base), api_key=key, timeout=600, max_retries=2)


def _encode(src: str, dst: Path, start: float, dur: float, mode: str, slow: int, fps: float) -> None:
    seek = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", src]
    if mode == "glitches":
        # keep every source frame: slowed by `slow`, the output frame rate is fps/slow
        ffmpeg(*seek, "-an", "-vf", f"scale=-2:480,setpts={slow}*PTS", "-r", f"{fps / slow:.4f}",
               "-c:v", "libx264", "-crf", "30", "-preset", "veryfast", str(dst))
    else:
        ffmpeg(*seek, "-vf", "scale=-2:480", "-r", "8", "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
               "-c:a", "aac", "-b:a", "96k", "-ac", "2", str(dst))


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"events": [], "notes": text.strip()[:500], "parse_error": True}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"events": [], "notes": text.strip()[:500], "parse_error": True}


def watch(path: str | Path, *, mode: str = "glitches", start: float = 0.0, duration: float | None = None,
          question: str | None = None, model: str | None = None, slow: int = 6, chunk: float = 20.0,
          client=None, ledger=None) -> dict:
    if mode not in PROMPTS:
        raise ValueError(f"mode must be one of {list(PROMPTS)}")
    spec = probe(path)
    fps = (spec["video"] or {}).get("fps") or 24
    total = spec["duration"]
    end = min(total, start + duration) if duration else total
    model = model or (os.environ.get("CVA_WATCH_MODEL", "google/gemini-3.5-flash") if mode == "glitches"
                      else os.environ.get("CVA_LISTEN_MODEL", "google/gemini-3.1-pro-preview"))
    chunk = chunk if mode == "glitches" else max(chunk, 60.0)   # listening needs context; slowed video doesn't
    c = client or _client()
    events, notes, cost = [], [], 0.0
    n = max(1, math.ceil((end - start) / chunk - 1e-9))
    with tempfile.TemporaryDirectory() as td:
        for i in range(n):
            a = start + i * chunk
            d = min(chunk, end - a)
            if d <= 0.05:
                break
            f = Path(td) / f"c{i}.mp4"
            _encode(str(path), f, a, d, mode, slow, fps)
            data = base64.b64encode(f.read_bytes()).decode()
            prompt = PROMPTS[mode].format(slow=slow) + (f"\nAlso answer: {question}" if question else "") + "\n" + SCHEMA
            raw = c.chat.completions.with_raw_response.create(model=model, messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "file", "file": {"file_data": f"data:video/mp4;base64,{data}"}}]}])
            resp = raw.parse()
            try:
                cost += float(raw.headers.get("x-litellm-response-cost") or 0)
            except (TypeError, ValueError):
                pass
            res = _parse(resp.choices[0].message.content or "")
            k = slow if mode == "glitches" else 1
            for e in res.get("events", []):
                try:
                    t = a + float(e.get("t", 0)) / k
                    te = a + float(e.get("end", e.get("t", 0))) / k
                except (TypeError, ValueError):
                    continue
                events.append({**e, "t": round(t, 2), "end": round(max(te, t), 2), "chunk": i})
            if res.get("notes"):
                notes.append(f"[{a:.0f}-{a + d:.0f}s] {res['notes']}")
    events.sort(key=lambda e: e["t"])
    out = {"file": str(path), "mode": mode, "model": model, "range": [round(start, 2), round(end, 2)],
           "slowed": slow if mode == "glitches" else 1, "events": events, "notes": notes,
           "cost_usd": round(cost, 5),
           "caveat": "Model timestamps are approximate (+-0.3 s). Confirm visual events with `cva media zoom` "
                     "before cutting; treat listening notes as a second opinion, the user's ears decide."}
    if ledger is not None and cost:
        ledger.add({"service": "litellm", "operation": f"watch:{mode}:{model}", "details": {"file": str(path)},
                    "status": "done", "estimate_usd": round(cost, 5), "cost_source": "proxy-reported"})
    return out


def contour(path: str | Path, *, every: float = 3.0) -> list[dict]:
    """Short-term loudness (LUFS, 3 s window) sampled every `every` seconds - a level map of a stem or mix."""
    from cva.ff import ffmpeg_analyse
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "r128.txt"
        esc = str(log).replace(":", r"\:")
        ffmpeg_analyse("-i", str(path), "-map", "0:a:0", "-af",
                       f"ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.S:file='{esc}'", "-f", "null", "-")
        text = log.read_text()
    pts = [float(x) for x in re.findall(r"pts_time:(\d+(?:\.\d+)?)", text)]
    vals = [float(x) for x in re.findall(r"lavfi\.r128\.S=(-?\d+(?:\.\d+)?|-?inf)", text.replace("-inf", "-120"))]
    out, nxt = [], 0.0
    for t, v in zip(pts, vals):
        if t + 1e-6 >= nxt:
            out.append({"t": round(t, 1), "lufs_s": round(v, 1) if v > -70 else None})
            nxt += every
    return out
