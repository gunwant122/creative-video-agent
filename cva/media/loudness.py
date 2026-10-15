"""Loudness (EBU R128), true peak, noise floor and silence."""
from __future__ import annotations

import re
from pathlib import Path

from cva.ff import ffmpeg_analyse

_NUM = r"(-?inf|-?\d+(?:\.\d+)?)"


def _f(s: str) -> float:
    return float("-inf") if "inf" in s else float(s)


def ebur128(path: str | Path, *, start: float | None = None, duration: float | None = None) -> dict:
    """Integrated loudness (LUFS), loudness range (LU) and true peak (dBTP)."""
    seek = (["-ss", str(start)] if start is not None else []) + (["-t", str(duration)] if duration else [])
    err = ffmpeg_analyse(*seek, "-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-")
    summary = err[err.rfind("Summary:"):]
    i = re.search(r"I:\s+" + _NUM + r" LUFS", summary)
    lra = re.search(r"LRA:\s+" + _NUM + r" LU", summary)
    tp = re.search(r"True peak:\s+Peak:\s+" + _NUM + r" dBFS", summary)
    return {
        "integrated_lufs": _f(i.group(1)) if i else None,
        "lra_lu": _f(lra.group(1)) if lra else None,
        "true_peak_dbtp": _f(tp.group(1)) if tp else None,
    }


def levels(path: str | Path) -> dict:
    """Overall peak, RMS and noise-floor estimate in dBFS (ffmpeg astats)."""
    err = ffmpeg_analyse("-i", str(path), "-map", "0:a:0", "-af",
                         "astats=measure_overall=Peak_level+RMS_level+Noise_floor:measure_perchannel=none",
                         "-f", "null", "-")
    def grab(label: str):
        m = re.findall(label + r" dB:\s+" + _NUM, err)
        return _f(m[-1]) if m else None
    return {"peak_dbfs": grab("Peak level"), "rms_dbfs": grab("RMS level"), "noise_floor_dbfs": grab("Noise floor")}


def silences(path: str | Path, *, noise_db: float = -45, min_dur: float = 0.4) -> list[dict]:
    """Silent stretches: [{start, end}] in seconds."""
    err = ffmpeg_analyse("-i", str(path), "-map", "0:a:0", "-af",
                         f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-")
    starts = [float(x) for x in re.findall(r"silence_start: (-?\d+(?:\.\d+)?)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?\d+(?:\.\d+)?)", err)]
    out = []
    for i, s in enumerate(starts):
        out.append({"start": max(s, 0.0), "end": ends[i] if i < len(ends) else None})
    return out
