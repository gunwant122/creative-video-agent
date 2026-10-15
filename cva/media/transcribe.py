"""Word-timed transcription and speech regions.

Backends, in order of preference: mlx-whisper (Apple Silicon), whisperx, ElevenLabs Scribe
(see cva.gen). All are normalised to {"text", "language", "words": [{"word","start","end"}]}.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cva.ff import ffmpeg


def _extract_16k(path: str | Path, dst: Path) -> Path:
    ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst))
    return dst


def _mlx(wav: Path, model: str, language: str | None) -> dict:
    import mlx_whisper  # type: ignore

    res = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model, word_timestamps=True, language=language)
    words = [{"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
             for seg in res.get("segments", []) for w in seg.get("words", [])]
    return {"text": res.get("text", "").strip(), "language": res.get("language"), "words": words}


def _whisperx(wav: Path, model: str, language: str | None) -> dict:
    import whisperx  # type: ignore

    audio = whisperx.load_audio(str(wav))
    m = whisperx.load_model(model, "cpu", compute_type="int8", language=language)
    res = m.transcribe(audio)
    align_model, meta = whisperx.load_align_model(language_code=res["language"], device="cpu")
    res2 = whisperx.align(res["segments"], align_model, meta, audio, "cpu")
    words = [{"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
             for seg in res2["segments"] for w in seg.get("words", []) if "start" in w]
    return {"text": " ".join(s["text"].strip() for s in res["segments"]), "language": res["language"], "words": words}


def available_backends() -> list[str]:
    out = []
    for name, mod in (("mlx", "mlx_whisper"), ("whisperx", "whisperx")):
        try:
            __import__(mod)
            out.append(name)
        except Exception:
            pass
    return out


def transcribe(path: str | Path, out_json: str | Path | None = None, *, backend: str | None = None,
               language: str | None = None, model: str | None = None) -> dict:
    backends = available_backends()
    backend = backend or (backends[0] if backends else None)
    if backend is None:
        raise RuntimeError("No local transcription backend installed. Use the generator's `transcribe_paid` tool "
                           "with every source in one call (Scribe v2 via fal / ElevenLabs), or pip install whisperx.")
    with tempfile.TemporaryDirectory() as td:
        wav = _extract_16k(path, Path(td) / "a.wav")
        if backend == "mlx":
            res = _mlx(wav, model or "mlx-community/whisper-large-v3-turbo", language)
        elif backend == "whisperx":
            res = _whisperx(wav, model or "large-v3", language)
        else:
            raise ValueError(f"unknown backend {backend}")
    res["source"] = str(path)
    res["backend"] = backend
    if out_json:
        Path(out_json).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def speech_regions(words: list[dict], *, merge_gap: float = 0.8, offset: float = 0.0) -> list[list[float]]:
    """Merge word timings into [start, end] regions; gaps shorter than merge_gap are bridged."""
    regions: list[list[float]] = []
    for w in sorted(words, key=lambda w: w["start"]):
        s, e = w["start"] + offset, w["end"] + offset
        if regions and s - regions[-1][1] < merge_gap:
            regions[-1][1] = max(regions[-1][1], e)
        else:
            regions.append([s, e])
    return [[round(s, 3), round(e, 3)] for s, e in regions]
