"""Render a vd score to stems and a music bed.

Per part: SFZ patch -> sfizz_render, SF2 -> fluidsynth, otherwise a built-in preview synth (clearly
labelled; good enough to check timing, not for delivery). Then pan, reverb send, hits/risers, sum.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pretty_midi
import soundfile as sf

from cva.ff import FFMPEG, ensure_dir
from cva.vd.score import Score

SR = 48000


def write_midi(notes: list[dict], path: Path, program: int = 48, name: str = "part") -> Path:
    pm = pretty_midi.PrettyMIDI(initial_tempo=60)
    inst = pretty_midi.Instrument(program=program, name=name)
    for n in notes:
        inst.notes.append(pretty_midi.Note(velocity=int(n["v"]), pitch=int(n["p"]), start=float(n["t"]),
                                           end=float(n["t"] + n["d"])))
    pm.instruments.append(inst)
    pm.write(str(path))
    return path


def _read_any(path: Path) -> np.ndarray:
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


# ---------------- preview synth ----------------
def _voice(p: int, d: float, v: int, role: str) -> np.ndarray:
    f = 440.0 * 2 ** ((p - 69) / 12)
    rel = 0.6 if role in ("pad", "melody", "bass") else 1.5
    n = int((d + rel) * SR)
    t = np.arange(n) / SR
    amp = (v / 127) ** 1.6 * 0.25
    if role == "perc":
        env = np.exp(-t * 6)
        sig = np.random.default_rng(p).standard_normal(n) * 0.4 + np.sin(2 * np.pi * f * t)
    elif role in ("pluck", "harp"):
        env = np.exp(-t * 2.5)
        sig = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)
    else:
        att = 0.25 if role == "pad" else 0.06
        env = np.minimum(1.0, t / att) * np.where(t < d, 1.0, np.exp(-(t - d) * 6))
        sig = sum(np.sin(2 * np.pi * f * k * t) / k ** 1.5 for k in range(1, 6))
    return sig * env * amp


def preview_synth(notes: list[dict], dur: float, role: str) -> np.ndarray:
    out = np.zeros(int(dur * SR) + SR * 2)
    for n in notes:
        x = _voice(n["p"], n["d"], n["v"], role)
        i = int(n["t"] * SR)
        j = min(i + len(x), len(out))
        if j > i:
            out[i:j] += x[:j - i]
    return np.stack([out, out], 1)


# ---------------- engines ----------------
TOOLS_BIN = Path(__file__).resolve().parent.parent.parent / "tools" / "bin"


def sfizz_bin() -> str | None:
    local = TOOLS_BIN / "sfizz_render"
    return str(local) if local.exists() else shutil.which("sfizz_render")


def engine_for(patch: str | None) -> str:
    if patch and patch.lower().endswith(".sfz") and sfizz_bin():
        return "sfizz"
    if patch and patch.lower().endswith(".sf2") and shutil.which("fluidsynth"):
        return "fluidsynth"
    return "preview"


def render_part(s: Score, name: str, dur: float, tmp: Path) -> tuple[np.ndarray, str]:
    part = s.part(name)
    notes = s.data["notes"].get(name, [])
    eng = engine_for(part.get("patch"))
    if part.get("patch") and eng == "preview" and not s.abspath(part["patch"]).exists():
        eng = "preview(missing patch)"
    if eng in ("sfizz", "fluidsynth"):
        mid = write_midi(notes, tmp / f"{name}.mid", part.get("program", 48), name)
        wav = tmp / f"{name}.wav"
        patch = str(s.abspath(part["patch"]))
        if eng == "sfizz":
            cmd = [sfizz_bin(), "--sfz", patch, "--midi", str(mid), "--wav", str(wav), "-s", str(SR)]
        else:
            cmd = ["fluidsynth", "-ni", "-F", str(wav), "-r", str(SR), patch, str(mid)]
        subprocess.run(cmd, capture_output=True, check=True)
        x = _read_any(wav)
    else:
        x = preview_synth(notes, dur, part.get("role", "pad"))
    return x, eng


def pan(x: np.ndarray, p: float) -> np.ndarray:
    a = (p + 1) * np.pi / 4  # constant power, p in [-1, 1]
    mono = x.mean(axis=1)
    return np.stack([mono * np.cos(a), mono * np.sin(a)], 1) * np.sqrt(2)


def hall_ir(seconds: float = 2.4, seed: int = 7) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    decay = np.exp(-6.9 * t / seconds)  # -60 dB at `seconds`
    ir = rng.standard_normal((n, 2)) * decay[:, None]
    ir[: int(0.012 * SR)] = 0  # pre-delay
    return ir / np.sqrt(np.sum(ir ** 2, axis=0))


def convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    n = len(x) + len(ir) - 1
    nfft = 1 << (n - 1).bit_length()
    out = np.empty((n, 2))
    for ch in range(2):
        out[:, ch] = np.fft.irfft(np.fft.rfft(x[:, ch], nfft) * np.fft.rfft(ir[:, ch], nfft), nfft)[:n]
    return out


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    return x[:n] if len(x) >= n else np.vstack([x, np.zeros((n - len(x), 2))])


def render(s: Score, *, tag: str | None = None, peak_dbfs: float = -3.0, target_lufs: float = -20.0) -> dict:
    dur = float(s.data.get("duration") or max([n["t"] + n["d"] for ns in s.data["notes"].values() for n in ns] or [1]))
    n = int(dur * SR) + int(3 * SR)  # room for tails, trimmed below
    tag = tag or f"m{1 + len(s.data.get('renders', []))}"
    stems_dir = ensure_dir(s.root / "work" / "stems" / tag)
    dry, wet = np.zeros((n, 2)), np.zeros((n, 2))
    engines, stems = {}, {}
    with tempfile.TemporaryDirectory() as td:
        for name in s.data["parts"]:
            if not s.data["notes"].get(name):
                continue
            x, eng = render_part(s, name, dur, Path(td))
            part = s.part(name)
            x = _fit(pan(x, part.get("pan", 0.0)) * 10 ** (part.get("gain_db", 0.0) / 20), n)
            engines[name] = eng
            sf.write(str(stems_dir / f"{name}.wav"), x[: int(dur * SR)], SR, subtype="PCM_24")
            stems[name] = str((stems_dir / f"{name}.wav").relative_to(s.root))
            dry += x
            wet += x * part.get("reverb", 0.25)
    if np.any(wet):
        dry += _fit(convolve(wet, hall_ir()), n) * 0.5

    hits = np.zeros((n, 2))
    for h in s.data["hits"]:
        x = _read_any(s.abspath(h["file"])) * 10 ** (h.get("gain_db", 0.0) / 20)
        start = int(round(h["t"] * SR)) - (len(x) if h["align"] == "end" else 0)
        a, b = max(start, 0), min(start + len(x), n)
        if b > a:
            hits[a:b] += x[a - start:b - start]
    if s.data["hits"]:
        sf.write(str(stems_dir / "hits.wav"), hits[: int(dur * SR)], SR, subtype="PCM_24")
        stems["hits"] = str((stems_dir / "hits.wav").relative_to(s.root))

    mix = (dry + hits)[: int(dur * SR)]
    out = s.root / "work" / f"music_{tag}.wav"
    # bring the bed to a consistent loudness so mixing starts from the same place, never above the peak cap
    sf.write(str(out), mix, SR, subtype="FLOAT")
    from cva.media.loudness import ebur128
    lufs = ebur128(out)["integrated_lufs"]
    pk = float(np.max(np.abs(mix))) if len(mix) else 0.0
    g_lufs = 10 ** ((target_lufs - lufs) / 20) if lufs not in (None, float("-inf")) else 1.0
    g_peak = 10 ** (peak_dbfs / 20) / pk if pk > 0 else 1.0
    scale = min(g_lufs, g_peak)
    sf.write(str(out), mix * scale, SR, subtype="PCM_24")
    rec = {"tag": tag, "music": str(out.relative_to(s.root)), "stems": stems, "engines": engines,
           "timed_to": s.data.get("timed_to"), "gain_db": round(20 * np.log10(scale), 2), "loudness_lufs": round(lufs + 20 * np.log10(scale), 1) if lufs not in (None, float("-inf")) else None,
           "limited_by": "peak" if g_peak < g_lufs else "loudness"}
    if any(e.startswith("preview") for e in engines.values()):
        rec["warning"] = "some parts used the preview synth (no patch/engine): fine for timing checks, not for delivery"
    s.data.setdefault("renders", []).append(rec)
    s.save()
    return rec
