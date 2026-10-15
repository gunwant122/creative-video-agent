"""Style profile of a reference episode: pacing, transitions, loudness, how much is talk vs silence.

Numbers the agent can match (cut rate, shot lengths, dips, LUFS); taste it cannot measure stays with the user.
"""
from __future__ import annotations

import re
import statistics

from cva.ff import ffmpeg_analyse
from cva.media.loudness import ebur128, silences
from cva.media.probe import probe
from cva.media.visual import scenes


def _black_spans(path: str) -> list[dict]:
    err = ffmpeg_analyse("-i", path, "-an", "-vf", "blackdetect=d=0.08:pix_th=0.10", "-f", "null", "-")
    return [{"start": float(s), "end": float(e)}
            for s, e in re.findall(r"black_start:(\d+(?:\.\d+)?) black_end:(\d+(?:\.\d+)?)", err)]


def style_profile(path: str) -> dict:
    path = str(path)
    spec = probe(path)
    dur = spec["duration"] or 0.0
    shots = scenes(path)
    lengths = [s["end"] - s["start"] for s in shots] or [dur]
    black = _black_spans(path)
    sil = silences(path, noise_db=-40, min_dur=0.5) if spec["audio"] else []
    silent = sum(((s["end"] if s["end"] is not None else dur) - s["start"]) for s in sil)
    loud = ebur128(path) if spec["audio"] else {}
    v = spec["video"] or {}
    prof = {
        "file": path,
        "duration_s": round(dur, 2),
        "format": f'{v.get("width")}x{v.get("height")} @ {v.get("fps")} fps',
        "shots": len(shots),
        "cuts_per_minute": round(max(len(shots) - 1, 0) / dur * 60, 1) if dur else None,
        "shot_length_s": {"median": round(statistics.median(lengths), 2), "mean": round(statistics.mean(lengths), 2),
                          "shortest": round(min(lengths), 2), "longest": round(max(lengths), 2)},
        "dips_to_black": len([b for b in black if 0.1 < b["start"] < dur - 0.5]),
        "opens_from_black": any(b["start"] < 0.1 for b in black),
        "ends_on_black": any(b["end"] > dur - 0.2 for b in black),
        "loudness": loud,
        "silent_fraction": round(silent / dur, 3) if dur else None,
    }
    prof["summary"] = (
        f'{prof["cuts_per_minute"]} cuts/min, median shot {prof["shot_length_s"]["median"]} s, '
        f'{prof["dips_to_black"]} dips to black, {loud.get("integrated_lufs")} LUFS / {loud.get("true_peak_dbtp")} dBTP, '
        f'{int((prof["silent_fraction"] or 0) * 100)}% near-silent.')
    prof["note"] = ("Measured pacing and loudness only. Music style, performance and colour need the user's "
                    "description (e.g. 'Bridgerton strings') in brief.md.")
    return prof
