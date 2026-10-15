"""Sound: dialogue cleanup, take levelling, ducking, stem summing, mastering, diagnosis.

Order: level takes (gain in vv) -> render dialogue stem -> clean -> duck music -> sum -> master -> gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from cva.ff import ffmpeg
from cva.media.loudness import ebur128

SR = 48000


def _db(x: float) -> float:
    return float(20 * np.log10(x)) if x > 0 else float("-inf")


# ---------------- cleanup ----------------
def clean(src: str | Path, out: str | Path, *, hpf: float = 80, mud_hz: float = 350, mud_db: float = -3,
          presence_hz: float = 3500, presence_db: float = 2, nr: float = 8, denoise: bool = True,
          deess: bool = False, leveller: bool = True, peak_control: bool = True) -> dict:
    """Dialogue chain: rumble cut, mud cut, presence lift, gentle NR, leveller, peak comp, limiter."""
    chain = [f"highpass=f={hpf}:poles=2"]
    if mud_db:
        chain.append(f"equalizer=f={mud_hz}:t=q:w=1.0:g={mud_db}")
    if presence_db:
        chain.append(f"equalizer=f={presence_hz}:t=q:w=0.9:g={presence_db}")
    if denoise:
        chain.append(f"afftdn=nr={nr}:nf=-50:tn=1")   # kept light: AI voices go watery when pushed
    if deess:
        chain.append("deesser=i=0.3")
    if leveller:
        chain.append("acompressor=threshold=-24dB:ratio=2.5:attack=20:release=250:makeup=1")
    if peak_control:
        chain.append("acompressor=threshold=-10dB:ratio=6:attack=2:release=60:makeup=1")
        chain.append("alimiter=limit=0.891:attack=3:release=50:level=false")
    before = ebur128(src)
    ffmpeg("-i", str(src), "-af", ",".join(chain), "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(out))
    return {"out": str(out), "chain": chain, "before": before, "after": ebur128(out)}


# ---------------- levelling ----------------
def gain_to(src: str | Path, target_lufs: float, *, start: float | None = None,
            duration: float | None = None) -> dict:
    m = ebur128(src, start=start, duration=duration)
    if m["integrated_lufs"] is None or m["integrated_lufs"] == float("-inf"):
        return {"measured": m, "gain_db": 0.0, "note": "no measurable loudness (silent?)"}
    return {"measured": m, "gain_db": round(target_lufs - m["integrated_lufs"], 2)}


def level_takes(project, target_lufs: float = -16.0) -> list[dict]:
    """Set every take's gain in a vv project so its dialogue measures target_lufs."""
    res = []
    for sid, s in project.data["sources"].items():
        if not s.get("has_audio", True):
            continue
        g = gain_to(project.abspath(s["path"]), target_lufs)
        project.set_take_gain(sid, g["gain_db"])
        res.append({"source": sid, "take": s["take"], "measured_lufs": g["measured"]["integrated_lufs"],
                    "gain_db": g["gain_db"]})
    project.save()
    return res


def apply_gain(src: str | Path, out: str | Path, gain_db: float) -> str:
    x, sr = sf.read(str(src), always_2d=True)
    sf.write(str(out), x * 10 ** (gain_db / 20), sr, subtype="PCM_24")
    return str(out)


# ---------------- ducking ----------------
def duck_envelope(n: int, sr: int, regions: list[list[float]], *, depth_db: float = -8.0, pre: float = 0.15,
                  post: float = 0.10, attack: float = 0.15, release: float = 0.5) -> np.ndarray:
    env = np.ones(n)
    low = 10 ** (depth_db / 20)
    for s, e in regions:
        a, b = int((s - pre) * sr), int((e + post) * sr)
        da, dr = max(int(attack * sr), 1), max(int(release * sr), 1)
        lo, hi = max(a - da, 0), min(b + dr, n)
        if hi <= 0 or lo >= n:
            continue
        seg = np.full(hi - lo, low)
        ramp_in = np.linspace(1.0, low, da)
        ramp_out = np.linspace(low, 1.0, dr)
        i0 = a - da - lo
        seg[max(i0, 0):max(i0 + da, 0)] = ramp_in[max(-i0, 0):]
        j0 = b - lo
        if j0 < len(seg):
            k = min(dr, len(seg) - j0)
            seg[j0:j0 + k] = ramp_out[:k]
        env[lo:hi] = np.minimum(env[lo:hi], seg)
    return env


def duck(music: str | Path, regions: list[list[float]] | str | Path, out: str | Path, *,
         depth_db: float = -8.0, **kw) -> dict:
    if isinstance(regions, (str, Path)):
        data = json.loads(Path(regions).read_text())
        regions = data["regions"] if isinstance(data, dict) else data
    x, sr = sf.read(str(music), always_2d=True)
    env = duck_envelope(len(x), sr, regions, depth_db=depth_db, **kw)
    sf.write(str(out), x * env[:, None], sr, subtype="PCM_24")
    return {"out": str(out), "regions": len(regions), "depth_db": depth_db,
            "ducked_seconds": round(float(np.sum(env < 0.999)) / sr, 2)}


# ---------------- sum + master ----------------
def _load(path: str | Path, n: int | None = None) -> np.ndarray:
    x, sr = sf.read(str(path), always_2d=True)
    if sr != SR:
        raise ValueError(f"{path}: expected {SR} Hz, got {sr}")
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    if n is not None:
        x = x[:n] if len(x) >= n else np.vstack([x, np.zeros((n - len(x), 2))])
    return x


def sum_stems(stems: dict[str, tuple[str, float]], out: str | Path, *, length_from: str | None = None) -> dict:
    """stems: {name: (path, gain_db)}. Length follows `length_from` stem (default: dialogue or first)."""
    ref = length_from or ("dialogue" if "dialogue" in stems else next(iter(stems)))
    n = len(_load(stems[ref][0]))
    mix = np.zeros((n, 2))
    for name, (path, g) in stems.items():
        mix += _load(path, n) * 10 ** (g / 20)
    sf.write(str(out), mix, SR, subtype="FLOAT")
    return {"out": str(out), "peak_dbfs": round(_db(float(np.max(np.abs(mix)))), 2), "seconds": n / SR}


def master(src: str | Path, out: str | Path, *, lufs: float = -14.0, tp: float = -1.0, iterations: int = 3) -> dict:
    """Gain to the loudness target with a limiter below the true-peak ceiling. Reports limiter work."""
    m0 = ebur128(src)
    x, sr = sf.read(str(src), always_2d=True)
    peak0 = _db(float(np.max(np.abs(x))))
    g = lufs - m0["integrated_lufs"]
    tmp = Path(out).with_suffix(".tmp.wav")
    result = None
    for _ in range(iterations):
        ceiling_db = tp - 1.0                          # sample-peak ceiling, 1 dB under the true-peak limit
        limit_in = min(1.0, 10 ** ((ceiling_db - g) / 20))   # limiter acts before the gain
        chain = f"alimiter=limit={max(limit_in, 0.0625):.6f}:attack=3:release=80:level=false,volume={g:.3f}dB"
        ffmpeg("-i", str(src), "-af", chain, "-ar", str(SR), "-c:a", "pcm_s24le", str(tmp))
        m = ebur128(tmp)
        result = {"gain_db": round(g, 2), "limiter_reduction_db": round(max(0.0, peak0 + g - ceiling_db), 2), **m}
        err = lufs - m["integrated_lufs"]
        if abs(err) <= 0.3 and m["true_peak_dbtp"] <= tp:
            break
        g += err
    tmp.replace(out)
    ok = abs(result["integrated_lufs"] - lufs) <= 1.0 and result["true_peak_dbtp"] <= tp + 0.05
    if result["limiter_reduction_db"] > 5:
        result["warning"] = (f"limiter is pulling ~{result['limiter_reduction_db']} dB; add compression to the stem "
                             "that drives the peaks (see diagnose)")
    return {"out": str(out), "target_lufs": lufs, "target_tp": tp, "pass": ok, "before": m0, **result}


def diagnose(stems: dict[str, tuple[str, float]], *, top_db: float = 3.0) -> dict:
    """Which stem drives the loudest moments of the mix (and so the limiter)?"""
    ref = "dialogue" if "dialogue" in stems else next(iter(stems))
    n = len(_load(stems[ref][0]))
    loaded = {k: _load(p, n) * 10 ** (g / 20) for k, (p, g) in stems.items()}
    mix = sum(loaded.values())
    amp = np.max(np.abs(mix), axis=1)
    thr = np.max(amp) * 10 ** (-top_db / 20)
    idx = amp >= thr
    shares = {k: float(np.mean(np.max(np.abs(v[idx]), axis=1))) for k, v in loaded.items()}
    tot = sum(shares.values()) or 1.0
    return {"peak_samples": int(idx.sum()), "top_db": top_db,
            "share": {k: round(v / tot, 3) for k, v in shares.items()},
            "driver": max(shares, key=shares.get),
            "stem_peaks_dbfs": {k: round(_db(float(np.max(np.abs(v)))), 2) for k, v in loaded.items()}}
