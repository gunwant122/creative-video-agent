"""Picture analysis: scene changes, sudden-change (glitch) candidates, review sheets, stills."""
from __future__ import annotations

import json
import math
import re
import statistics
import tempfile
from pathlib import Path

from cva.ff import ensure_dir, ffmpeg, has_filter
from cva.media.probe import probe


def _secs(tc) -> float:
    s = getattr(tc, "seconds", None)  # PySceneDetect >= 0.7 property; older versions only have get_seconds()
    return float(s) if s is not None and not callable(s) else tc.get_seconds()


def scenes(path: str | Path, *, threshold: float = 3.0) -> list[dict]:
    """Shot boundaries inside a clip (PySceneDetect adaptive detector)."""
    from scenedetect import AdaptiveDetector, detect

    out = []
    for start, end in detect(str(path), AdaptiveDetector(adaptive_threshold=threshold)):
        out.append({"start": round(_secs(start), 3), "end": round(_secs(end), 3)})
    return out


def frame_diffs(path: str | Path) -> list[tuple[float, float]]:
    """Mean luma of the frame-to-frame difference: [(time, value)]."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "diff.txt"
        # metadata=print:file= needs the path escaped for the filter parser
        esc = str(out).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        ffmpeg("-i", str(path), "-an", "-vf",
               f"tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file='{esc}'",
               "-f", "null", "-")
        text = out.read_text()
    times = [float(t) for t in re.findall(r"pts_time:(\d+(?:\.\d+)?)", text)]
    vals = [float(v) for v in re.findall(r"YAVG=(\d+(?:\.\d+)?)", text)]
    return list(zip(times, vals))


def change_spikes(path: str | Path, *, factor: float = 4.0, window: int = 12, floor: float = 2.0,
                  known_cuts: list[float] | None = None, cut_tolerance: float = 0.1) -> list[dict]:
    """Frames whose change is far above the local median. Spikes near known cuts are labelled 'cut'."""
    d = frame_diffs(path)
    vals = [v for _, v in d]
    spikes = []
    for i, (t, v) in enumerate(d):
        lo, hi = max(0, i - window), min(len(vals), i + window + 1)
        neigh = vals[lo:i] + vals[i + 1:hi]
        med = statistics.median(neigh) if neigh else 0.0
        if v > max(floor, factor * max(med, 0.25)):
            kind = "cut" if known_cuts and any(abs(t - c) <= cut_tolerance for c in known_cuts) else "suspect"
            spikes.append({"t": round(t, 3), "value": round(v, 2), "local_median": round(med, 2), "kind": kind})
    return spikes


def sheets(path: str | Path, out_dir: str | Path, *, fps: float = 3, cols: int = 8, rows: int = 4,
           cell_width: int = 240, start: float = 0.0, duration: float | None = None) -> dict:
    """Contact sheets with a time map. Returns {"sheets": [...], "map": [{sheet, cell, t}]}."""
    out_dir = ensure_dir(out_dir)
    for old in out_dir.glob("sheet_*.png"):
        old.unlink()
    vf = [f"fps={fps}", f"scale={cell_width}:-2"]
    if has_filter("drawtext"):
        # label with the absolute source time
        vf.append(f"drawtext=text='%{{pts\\:hms\\:{start}}}':x=4:y=4:fontsize={max(12, cell_width // 13)}:"
                  "fontcolor=white:box=1:boxcolor=black@0.6")
    vf.append(f"tile={cols}x{rows}")
    seek = ["-ss", str(start)] if start else []
    dur = ["-t", str(duration)] if duration else []
    ffmpeg(*seek, *dur, "-i", str(path), "-an", "-vf", ",".join(vf), str(out_dir / "sheet_%03d.png"))
    files = sorted(out_dir.glob("sheet_*.png"))
    total = duration if duration else probe(path)["duration"] - start
    n_frames = int(math.ceil(total * fps))
    per = cols * rows
    tmap = [{"sheet": files[k // per].name if k // per < len(files) else None, "cell": k % per,
             "row": (k % per) // cols, "col": (k % per) % cols, "t": round(start + k / fps, 3)}
            for k in range(n_frames)]
    meta = {"source": str(path), "fps": fps, "cols": cols, "rows": rows, "start": start,
            "labelled": has_filter("drawtext"), "sheets": [str(f) for f in files], "map": tmap}
    (out_dir / "sheets.json").write_text(json.dumps(meta, indent=1))
    return meta


def zoom_sheet(path: str | Path, t: float, out_png: str | Path, *, span: float = 1.0, fps: float = 8,
               cols: int = 4, cell_width: int = 360) -> dict:
    """One sheet covering t-span .. t+span at a higher frame rate, for confirming a suspect."""
    start = max(0.0, t - span)
    dur = 2 * span
    n = int(math.ceil(dur * fps))
    rows = int(math.ceil(n / cols))
    ffmpeg("-ss", str(start), "-t", str(dur), "-i", str(path), "-an", "-vf",
           f"fps={fps},scale={cell_width}:-2,tile={cols}x{rows}", "-frames:v", "1", str(out_png))
    return {"png": str(out_png), "cells": [{"cell": k, "t": round(start + k / fps, 3)} for k in range(n)]}


def still(path: str | Path, t: float, out: str | Path) -> str:
    ffmpeg("-ss", f"{max(t, 0):.3f}", "-i", str(path), "-frames:v", "1", "-q:v", "2", str(out))
    return str(out)


def stills_at(path: str | Path, times: list[float], out_dir: str | Path, *, fps: float,
              frames_each_side: int = 2) -> list[dict]:
    """A still just before and just after each time (e.g. every cut)."""
    out_dir = ensure_dir(out_dir)
    res = []
    for t in times:
        pre, post = t - frames_each_side / fps, t + frames_each_side / fps
        res.append({"t": t,
                    "before": still(path, pre, out_dir / f"cut_{t:08.3f}_a.jpg"),
                    "after": still(path, post, out_dir / f"cut_{t:08.3f}_b.jpg")})
    return res
