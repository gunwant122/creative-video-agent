"""Paid generation (ElevenLabs, fal), cost-gated.

Every paid call: build a request summary + estimate -> check the project budget -> interrupt() for the
user's approval -> call -> save to assets/generated/ with metadata -> append to the ledger.
Keys come from the environment (ELEVENLABS_API_KEY, FAL_KEY); nothing is spent without a yes.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from langchain_core.tools import tool
from langgraph.types import interrupt

from cva.ff import ensure_dir, ffmpeg

GEN_DIR = "assets/generated"


class GenError(RuntimeError):
    pass


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")[:60] or "out"


_LEDGER_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class Ledger:
    """Spend log. Parallel tool calls write to it at once, so every read-modify-write holds a per-file lock
    and the file is replaced atomically (never seen half-written)."""

    def __init__(self, root: Path):
        self.root = root
        self.dir = ensure_dir(root / GEN_DIR)
        self.file = self.dir / "ledger.json"
        with _LOCKS_GUARD:
            self.lock = _LEDGER_LOCKS.setdefault(str(self.file.resolve()), threading.Lock())

    def _read(self) -> list[dict]:
        if not self.file.exists():
            return []
        try:
            return json.loads(self.file.read_text() or "[]")
        except json.JSONDecodeError:  # a file corrupted by an older version: keep it, start fresh
            self.file.replace(self.file.with_suffix(f".corrupt-{int(time.time())}.json"))
            return []

    def entries(self) -> list[dict]:
        with self.lock:
            return self._read()

    def spent_usd(self) -> float:
        return round(sum(e.get("estimate_usd") or 0 for e in self.entries() if e.get("status") == "done"), 4)

    def budget_usd(self) -> float | None:
        f = self.root / "work" / "budget.json"
        return json.loads(f.read_text()).get("limit_usd") if f.exists() else None

    def add(self, entry: dict) -> None:
        with self.lock:
            e = self._read()
            e.append({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry})
            tmp = self.file.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(e, indent=1, ensure_ascii=False))
            tmp.replace(self.file)


def approve(ledger: Ledger, service: str, operation: str, details: dict, estimate: dict) -> dict:
    """Budget check, then ask the user. Returns the user's decision dict."""
    budget, spent = ledger.budget_usd(), ledger.spent_usd()
    usd = estimate.get("usd")
    if budget is not None and usd is not None and spent + usd > budget:
        return {"approved": False, "reason": f"over budget: spent ${spent:.2f} of ${budget:.2f}, request ~${usd:.2f}"}
    decision = interrupt({"type": "cost_approval", "service": service, "operation": operation,
                          "details": details, "estimate": estimate,
                          "budget": {"limit_usd": budget, "spent_usd": spent}})
    if isinstance(decision, bool):
        decision = {"approved": decision}
    return decision if isinstance(decision, dict) else {"approved": False, "reason": "no decision"}


def _to_wav(src: Path, dst: Path) -> Path:
    ffmpeg("-i", str(src), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(dst))
    return dst


def _write_stream(chunks, path: Path) -> Path:
    with path.open("wb") as fh:
        if isinstance(chunks, (bytes, bytearray)):
            fh.write(chunks)
        else:
            for c in chunks:
                if c:
                    fh.write(c)
    return path


# ---------------- pricing ----------------
def fal_price(endpoint: str) -> dict:
    """Unit price from fal's platform API, when reachable. Never guessed."""
    key = os.environ.get("FAL_KEY")
    if not key:
        return {"usd": None, "note": "FAL_KEY not set"}
    try:
        req = urllib.request.Request(f"https://api.fal.ai/v1/models/pricing?endpoint_id={endpoint}",
                                     headers={"Authorization": f"Key {key}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        p = (data.get("prices") or [{}])[0]
        return {"unit_price": p.get("unit_price"), "unit": p.get("unit"), "currency": p.get("currency"),
                "usd": p.get("unit_price") if p.get("currency", "USD") == "USD" else None,
                "note": "per unit; total depends on the unit (e.g. per second of video)"}
    except Exception as e:  # pricing is advisory; approval still happens
        return {"usd": None, "note": f"price lookup failed ({type(e).__name__}); check fal.ai pricing"}


def _el_client():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise GenError("ELEVENLABS_API_KEY is not set")
    from elevenlabs.client import ElevenLabs
    return ElevenLabs(api_key=key)


def _lite_client():
    from openai import OpenAI

    from cva.models import _openai_base, litellm_settings
    base, key = litellm_settings()
    return OpenAI(base_url=_openai_base(base), api_key=key, timeout=600, max_retries=2)


def make_gen_tools(project_root: str | Path, *, el_client_factory=None, fal_module=None,
                   lite_client_factory=None) -> dict:
    root = Path(project_root).resolve()
    ledger = Ledger(root)
    el = el_client_factory or _el_client

    def inside(p: str) -> Path:
        f = (root / p).resolve()
        if root not in f.parents:
            raise GenError(f"path outside the project: {p}")
        if not f.exists():
            raise GenError(f"missing file: {p}")
        return f

    lite = lite_client_factory or _lite_client
    actual_cost: dict = {}

    def run_gated(service, operation, details, estimate, fn):
        d = approve(ledger, service, operation, details, estimate)
        if not d.get("approved"):
            ledger.add({"service": service, "operation": operation, "details": details, "status": "declined",
                        "reason": d.get("reason") or d.get("note")})
            return json.dumps({"ok": False, "declined": True, "reason": d.get("reason") or d.get("note") or "user declined"})
        try:
            files = fn()
        except Exception as e:
            ledger.add({"service": service, "operation": operation, "details": details, "status": "error",
                        "error": str(e)})
            return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})
        rel = [str(Path(f).relative_to(root)) for f in files]
        cost = actual_cost.pop("usd", None)
        ledger.add({"service": service, "operation": operation, "details": details, "status": "done",
                    "estimate_usd": cost if cost is not None else estimate.get("usd"),
                    "cost_source": "proxy-reported" if cost is not None else "estimate", "files": rel})
        for f in files:
            Path(str(f) + ".json").write_text(json.dumps({"service": service, "operation": operation,
                                                          "details": details, "estimate": estimate}, indent=1))
        return json.dumps({"ok": True, "files": rel})

    gen = ledger.dir

    @tool
    def el_sound_effect(text: str, out_name: str, duration_s: float | None = None) -> str:
        """ElevenLabs sound effect (impact, riser, whoosh, foley, ambience, room tone). Paid - asks the user.
        Describe the sound concretely: "deep cinematic boom with long sub tail, no music"."""
        details = {"text": text, "duration_s": duration_s}
        def call():
            raw = gen / f"{_slug(out_name)}.mp3"
            _write_stream(el().text_to_sound_effects.convert(text=text, duration_seconds=duration_s), raw)
            return [_to_wav(raw, gen / f"{_slug(out_name)}.wav")]
        return run_gated("elevenlabs", "sound_effect", details,
                         {"usd": None, "note": "billed in ElevenLabs credits per generation; see your plan"}, call)

    @tool
    def el_voice_isolate(src: str, out_name: str) -> str:
        """ElevenLabs Voice Isolator: strip noise/music from a dialogue file before the ffmpeg cleanup chain.
        Paid - asks the user. Use on clips whose noise floor or artefacts defeat the normal chain."""
        f = inside(src)
        from cva.media.probe import probe
        secs = probe(f)["duration"]
        def call():
            raw = gen / f"{_slug(out_name)}.mp3"
            with f.open("rb") as fh:
                _write_stream(el().audio_isolation.convert(audio=fh), raw)
            return [_to_wav(raw, gen / f"{_slug(out_name)}.wav")]
        return run_gated("elevenlabs", "voice_isolation", {"src": src, "seconds": round(secs, 1)},
                         {"usd": None, "note": "billed per minute of audio in ElevenLabs credits"}, call)

    @tool
    def el_tts(text: str, voice_id: str, out_name: str, model_id: str = "eleven_multilingual_v2",
               language_code: str | None = None) -> str:
        """ElevenLabs text-to-speech for narration, pickup lines or dubs. Paid - asks the user."""
        details = {"chars": len(text), "voice_id": voice_id, "model_id": model_id, "text": text[:200]}
        def call():
            raw = gen / f"{_slug(out_name)}.mp3"
            kw = {"voice_id": voice_id, "text": text, "model_id": model_id}
            if language_code:
                kw["language_code"] = language_code
            _write_stream(el().text_to_speech.convert(**kw), raw)
            return [_to_wav(raw, gen / f"{_slug(out_name)}.wav")]
        return run_gated("elevenlabs", "tts", details,
                         {"usd": None, "note": f"{len(text)} characters of ElevenLabs credits"}, call)

    @tool
    def el_music(prompt: str, seconds: float, out_name: str, instrumental: bool = True) -> str:
        """ElevenLabs music generation - a quick bed when the user does not want a composed vd score.
        Paid - asks the user. The composed score stays the default."""
        details = {"prompt": prompt, "seconds": seconds, "instrumental": instrumental}
        def call():
            raw = gen / f"{_slug(out_name)}.mp3"
            _write_stream(el().music.compose(prompt=prompt, music_length_ms=int(seconds * 1000),
                                             force_instrumental=instrumental), raw)
            return [_to_wav(raw, gen / f"{_slug(out_name)}.wav")]
        return run_gated("elevenlabs", "music", details, {"usd": None, "note": "billed in ElevenLabs credits"}, call)

    @tool
    def transcribe_paid(sources: list[str], language_code: str | None = None) -> str:
        """Word-timed transcripts with ElevenLabs Scribe v2 for SEVERAL clips under ONE approval (strong for Hindi
        and Indian languages). Use when local transcription is unavailable or weak. Pass every source at once,
        e.g. ["src/v1.mp4", "src/v2.mp4", ...]. Runs via fal (FAL_KEY) or ElevenLabs directly (ELEVENLABS_API_KEY).
        Writes analysis/<file stem>.words.json for each, the same format as the local transcriber."""
        from concurrent.futures import ThreadPoolExecutor

        from cva.media.probe import probe
        files = [inside(p) for p in sources]
        minutes = round(sum(probe(f)["duration"] for f in files) / 60, 2)
        use_fal = bool(os.environ.get("FAL_KEY")) or fal_module is not None
        if not use_fal and not os.environ.get("ELEVENLABS_API_KEY") and el_client_factory is None:
            return json.dumps({"ok": False, "error": "no paid transcription key: add FAL_KEY (fal Scribe v2) or "
                                                     "ELEVENLABS_API_KEY to .env"})
        endpoint = "fal-ai/elevenlabs/speech-to-text/scribe-v2"
        est = {"usd": None, "note": f"{minutes} min of audio"}
        if use_fal:
            price = fal_price(endpoint)
            if price.get("usd") is not None and "min" in str(price.get("unit", "")).lower():
                est = {"usd": round(price["usd"] * minutes, 4), "note": f"{minutes} min x ${price['usd']}/{price['unit']}"}
            elif price.get("usd") is not None:
                est = {"usd": None, "note": f"{minutes} min; fal price ${price['usd']} per {price.get('unit')}"}

        def one(f: Path) -> Path:
            with tempfile.TemporaryDirectory() as td:
                audio = Path(td) / "a.m4a"
                ffmpeg("-i", str(f), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "64k", str(audio))
                if use_fal:
                    fal = fal_module
                    if fal is None:
                        import fal_client as fal
                    args = {"audio_url": fal.upload_file(audio), "diarize": False, "tag_audio_events": False}
                    if language_code:
                        args["language_code"] = language_code
                    res = fal.subscribe(endpoint, arguments=args)
                    raw_words = res.get("words") or []
                    if isinstance(raw_words, dict):
                        raw_words = [raw_words]
                    words = [{"word": str(w.get("text", "")).strip(), "start": float(w["start"]), "end": float(w["end"])}
                             for w in raw_words if w.get("type", "word") == "word" and w.get("start") is not None]
                    text, lang, backend = res.get("text", ""), res.get("language_code"), "fal-scribe-v2"
                else:
                    kw = {"model_id": "scribe_v1", "timestamps_granularity": "word"}
                    if language_code:
                        kw["language_code"] = language_code
                    with audio.open("rb") as fh:
                        res = el().speech_to_text.convert(file=fh, **kw)
                    words = [{"word": w.text.strip(), "start": float(w.start), "end": float(w.end)}
                             for w in (res.words or []) if getattr(w, "type", "word") == "word"]
                    text, lang, backend = res.text, getattr(res, "language_code", None), "elevenlabs-scribe"
            out = ensure_dir(root / "analysis") / f"{f.stem}.words.json"
            out.write_text(json.dumps({"text": text, "language": lang, "words": words,
                                       "source": str(f.relative_to(root)), "backend": backend},
                                      indent=1, ensure_ascii=False))
            return out

        def call():
            with ThreadPoolExecutor(max_workers=4) as ex:
                return list(ex.map(one, files))
        return run_gated("fal" if use_fal else "elevenlabs", "transcribe (Scribe v2)",
                         {"files": len(files), "minutes": minutes, "language": language_code,
                          "sources": [str(Path(p)) for p in sources]}, est, call)

    @tool
    def fal_pricing(endpoint: str) -> str:
        """Look up a fal model's unit price (free, no approval needed)."""
        return json.dumps(fal_price(endpoint))

    @tool
    def fal_run(endpoint: str, arguments: dict, out_name: str, units_estimate: float = 1.0) -> str:
        """Run a fal model (image-to-video to regenerate a glitched shot, upscalers, image gen/edit).
        Paid - asks the user with the price. In `arguments`, give local files as "file:<project path>";
        they are uploaded. Media URLs in the result are downloaded to assets/generated/.
        units_estimate: how many billing units you expect (e.g. seconds of video) for the cost estimate."""
        fal = fal_module
        if fal is None:
            if not os.environ.get("FAL_KEY"):
                return json.dumps({"ok": False, "error": "FAL_KEY is not set"})
            import fal_client as fal
        price = fal_price(endpoint)
        est = dict(price)
        if price.get("usd") is not None:
            est["usd"] = round(price["usd"] * units_estimate, 4)
            est["units"] = units_estimate
        uploads = {k: v[5:] for k, v in arguments.items() if isinstance(v, str) and v.startswith("file:")}
        for p in uploads.values():
            inside(p)
        details = {"endpoint": endpoint, "arguments": arguments}

        def call():
            args = dict(arguments)
            for k, p in uploads.items():
                args[k] = fal.upload_file(root / p)
            result = fal.subscribe(endpoint, arguments=args)
            urls = re.findall(r"https://[^\s\"']+\.(?:mp4|mov|webm|png|jpe?g|webp|wav|mp3)", json.dumps(result))
            files = []
            for i, u in enumerate(dict.fromkeys(urls)):
                ext = u.rsplit(".", 1)[-1]
                dst = gen / f"{_slug(out_name)}_{i}.{ext}"
                urllib.request.urlretrieve(u, dst)
                files.append(dst)
            (gen / f"{_slug(out_name)}.result.json").write_text(json.dumps(result, indent=1))
            return files or [gen / f"{_slug(out_name)}.result.json"]
        return run_gated("fal", endpoint, details, est, call)

    def _save_images(resp, stem: str) -> list[Path]:
        import base64 as b64
        files = []
        for i, d in enumerate(resp.data or []):
            dst = gen / f"{stem}_{i}.png"
            if getattr(d, "b64_json", None):
                dst.write_bytes(b64.b64decode(d.b64_json))
            elif getattr(d, "url", None):
                urllib.request.urlretrieve(d.url, dst)
            else:
                continue
            files.append(dst)
        if not files:
            raise GenError("the image model returned no images")
        return files

    def _record_cost(raw) -> None:
        try:
            c = raw.headers.get("x-litellm-response-cost")
            if c:
                actual_cost["usd"] = round(float(c), 6)
        except Exception:
            pass

    @tool
    def image_generate(prompt: str, out_name: str, size: str = "1024x1792", model: str | None = None,
                       n: int = 1) -> str:
        """Generate images through the LiteLLM proxy (title-card backgrounds, thumbnails, a clean still to
        regenerate a shot from). Paid - asks the user. size e.g. 1024x1792 (portrait) or 1792x1024.
        model defaults to CVA_IMAGE_MODEL."""
        model = model or os.environ.get("CVA_IMAGE_MODEL")
        if not model:
            return json.dumps({"ok": False, "error": "no image model: set CVA_IMAGE_MODEL in .env or pass model"})
        details = {"model": model, "prompt": prompt, "size": size, "n": n}
        def call():
            raw = lite().images.with_raw_response.generate(model=model, prompt=prompt, size=size, n=n)
            _record_cost(raw)
            return _save_images(raw.parse(), _slug(out_name))
        return run_gated("litellm", f"image_generate:{model}", details,
                         {"usd": None, "note": "billed by your LiteLLM proxy; the actual cost is recorded after"}, call)

    @tool
    def image_edit(src: str, prompt: str, out_name: str, model: str | None = None, size: str | None = None) -> str:
        """Edit an image through the LiteLLM proxy (fix a still before regenerating a shot, remove an artefact,
        extend a frame). src is a project path (png/jpg). Paid - asks the user."""
        model = model or os.environ.get("CVA_IMAGE_MODEL")
        if not model:
            return json.dumps({"ok": False, "error": "no image model: set CVA_IMAGE_MODEL in .env or pass model"})
        f = inside(src)
        details = {"model": model, "src": src, "prompt": prompt}
        def call():
            kw = {"model": model, "prompt": prompt}
            if size:
                kw["size"] = size
            with f.open("rb") as fh:
                raw = lite().images.with_raw_response.edit(image=fh, **kw)
            _record_cost(raw)
            return _save_images(raw.parse(), _slug(out_name))
        return run_gated("litellm", f"image_edit:{model}", details,
                         {"usd": None, "note": "billed by your LiteLLM proxy; the actual cost is recorded after"}, call)

    @tool
    def generation_spend() -> str:
        """Spend so far, the budget, and the ledger of paid generations (free, no approval)."""
        return json.dumps({"spent_usd": ledger.spent_usd(), "budget_usd": ledger.budget_usd(),
                           "entries": ledger.entries()[-20:]}, ensure_ascii=False)

    return {"el_sound_effect": el_sound_effect, "el_voice_isolate": el_voice_isolate, "el_tts": el_tts,
            "el_music": el_music, "transcribe_paid": transcribe_paid, "fal_pricing": fal_pricing, "fal_run": fal_run,
            "image_generate": image_generate, "image_edit": image_edit,
            "generation_spend": generation_spend}
