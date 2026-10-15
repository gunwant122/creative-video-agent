"""Media specs."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from cva.ff import ffprobe_json


def _fps(rate: str | None) -> float | None:
    if not rate or rate == "0/0":
        return None
    return float(Fraction(rate))


def probe(path: str | Path) -> dict:
    """Return a compact spec dict: duration, video {w,h,fps,...}, audio {rate,channels,...}."""
    raw = ffprobe_json(path)
    out: dict = {"path": str(path), "duration": float(raw.get("format", {}).get("duration", 0) or 0),
                 "video": None, "audio": None}
    for s in raw.get("streams", []):
        if s.get("codec_type") == "video" and out["video"] is None and s.get("disposition", {}).get("attached_pic") != 1:
            fps = _fps(s.get("avg_frame_rate")) or _fps(s.get("r_frame_rate"))
            out["video"] = {
                "codec": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "fps": round(fps, 3) if fps else None,
                "fps_rational": s.get("avg_frame_rate") or s.get("r_frame_rate"),
                "pix_fmt": s.get("pix_fmt"),
                "frames": int(s["nb_frames"]) if s.get("nb_frames", "").isdigit() else None,
            }
        elif s.get("codec_type") == "audio" and out["audio"] is None:
            out["audio"] = {
                "codec": s.get("codec_name"),
                "sample_rate": int(s.get("sample_rate", 0) or 0),
                "channels": s.get("channels"),
            }
    return out
