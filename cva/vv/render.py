"""Compile a vv project to media.

1. Each clip is pre-rendered to a conformed segment (trim incl. dissolve handles, scale/crop to the
   profile, punch-in, dip/end fades). Small graphs, run in parallel.
2. Segments are joined in one pass: `xfade` for dissolves, `concat` for cuts and dips.
3. The dialogue stem is built sample-accurately in numpy from the audio placements.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from cva.ff import FFMPEG, ensure_dir, ffmpeg
from cva.vv.layout import cut_list, layout, timeline_speech, write_json
from cva.vv.project import Project


# ---------------- picture ----------------
def _lerp_expr(kfs: list[dict], key: str, tvar: str) -> str:
    """Piecewise-linear ffmpeg expression over keyframes (t in seconds)."""
    if len(kfs) == 1:
        return f"{kfs[0][key]:.6f}"
    expr = f"{kfs[-1][key]:.6f}"
    for a, b in reversed(list(zip(kfs, kfs[1:]))):
        span = max(b["t"] - a["t"], 1e-6)
        seg = f"({a[key]:.6f}+({b[key]:.6f}-{a[key]:.6f})*({tvar}-{a['t']:.6f})/{span:.6f})"
        expr = f"if(lt({tvar},{b['t']:.6f}),{seg},{expr})"
    return f"if(lt({tvar},{kfs[0]['t']:.6f}),{kfs[0][key]:.6f},{expr})"


def _punch_filter(punch: list[dict], W: int, H: int, F: int, pre_frames: int) -> str | None:
    if not punch or all(abs(k["scale"] - 1.0) < 1e-6 for k in punch):
        return None
    static = len(punch) == 1 or all(
        abs(k["scale"] - punch[0]["scale"]) < 1e-6 and abs(k["x"] - punch[0]["x"]) < 1e-6
        and abs(k["y"] - punch[0]["y"]) < 1e-6 for k in punch)
    if static:
        k = punch[0]
        w, h = int(round(W / k["scale"] / 2) * 2), int(round(H / k["scale"] / 2) * 2)
        x = int(min(max(k["x"] * W - w / 2, 0), W - w))
        y = int(min(max(k["y"] * H - h / 2, 0), H - h))
        return f"crop={w}:{h}:{x}:{y},scale={W}:{H}:flags=lanczos,setsar=1"
    # animated: zoompan, time measured from the clip's in point
    tvar = f"(on/{F}-{pre_frames / F:.6f})"
    z = _lerp_expr(punch, "scale", tvar)
    cx = _lerp_expr(punch, "x", tvar)
    cy = _lerp_expr(punch, "y", tvar)
    return (f"zoompan=z='{z}':x='max(0,min(iw-iw/zoom,({cx})*iw-iw/zoom/2))':"
            f"y='max(0,min(ih-ih/zoom,({cy})*ih-ih/zoom/2))':d=1:s={W}x{H}:fps={F},setsar=1")


def _segment_cmd(p: Project, it: dict, clip: dict, out: Path, *, proxy: bool, end_fade: int, is_last: bool) -> list:
    prof = p.data["profile"]
    F = prof["fps"]
    W, H = prof["width"], prof["height"]
    a_f = it["in"] - it["pre"]
    n = it["pre"] + it["L"] + it["post"]
    seek_f = max(0, a_f - F)
    k = a_f - seek_f
    vf = [f"fps={F}", f"trim=start_frame={k}:end_frame={k + n}", "setpts=PTS-STARTPTS",
          f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}", "setsar=1"]
    pf = _punch_filter(clip.get("punch") or [], W, H, F, it["pre"])
    if pf:
        vf.append(pf)
    if it["dip_in"]:
        vf.append(f"fade=t=in:st=0:d={it['dip_in'] / F:.6f}")
    out_fade = it["dip_out"] or (end_fade if is_last else 0)
    if out_fade:
        vf.append(f"fade=t=out:st={(n - out_fade) / F:.6f}:d={out_fade / F:.6f}")
    if proxy:
        vf.append(f"scale={W // 2 // 2 * 2}:{H // 2 // 2 * 2}")
    vf.append("format=yuv420p")
    src = p.abspath(p.source(it["src"])["path"])
    enc = (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26"] if proxy
           else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12"])
    return ["-ss", f"{seek_f / F:.6f}", "-i", str(src), "-an", "-vf", ",".join(vf), *enc, "-g", str(F), str(out)]


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _assemble_cmd(lay: dict, segs: list[Path], out: Path, *, proxy: bool, overlays: list[dict] | None = None,
                  root: Path | None = None) -> list:
    F = lay["fps"]
    items = lay["items"]
    args = []
    for s in segs:
        args += ["-i", str(s)]
    parts = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[s{i}]" for i in range(len(segs))]
    acc = "[s0]"
    for i in range(1, len(items)):
        it = items[i]
        nxt = f"[x{i}]"
        if it["tin"]["type"] == "dissolve":
            off = (it["T"] - it["pre"]) / F
            parts.append(f"{acc}[s{i}]xfade=transition=fade:duration={it['tin']['frames'] / F:.6f}:offset={off:.6f}{nxt}")
        else:
            parts.append(f"{acc}[s{i}]concat=n=2:v=1:a=0{nxt}")
        acc = nxt
    total = lay["duration"]
    n = len(segs)
    for k, o in enumerate(overlays or []):
        start, end = max(0.0, o["start"]), min(o["end"], total)
        if end <= start:
            continue
        dur = end - start
        f = (root / o["file"]) if root else Path(o["file"])
        if f.suffix.lower() in IMAGE_EXT:
            args += ["-loop", "1", "-framerate", str(F), "-t", f"{dur:.4f}", "-i", str(f)]
            chain = [f"[{n}:v]format=rgba"]
        else:
            args += ["-i", str(f)]
            chain = [f"[{n}:v]trim=duration={dur:.4f},format=rgba"]
        if proxy:
            chain.append("scale=iw/2:ih/2")
        fd = min(o.get("fade", 0.1), dur / 2)
        if fd > 0:
            chain += [f"fade=t=in:st=0:d={fd:.4f}:alpha=1", f"fade=t=out:st={dur - fd:.4f}:d={fd:.4f}:alpha=1"]
        chain.append(f"setpts=PTS-STARTPTS+{start:.4f}/TB")
        parts.append(",".join(chain) + f"[ov{k}]")
        nxt = f"[o{k}]"
        parts.append(f"{acc}[ov{k}]overlay=x='{o['x']}':y='{o['y']}':eof_action=pass:"
                     f"enable='between(t,{start:.4f},{end:.4f})'{nxt}")
        acc = nxt
        n += 1
    parts.append(f"{acc}fps={F},format=yuv420p[vout]")
    enc = (["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26"] if proxy
           else ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high"])
    return [*args, "-filter_complex", ";".join(parts), "-map", "[vout]", "-frames:v", str(lay["total_frames"]),
            *enc, "-movflags", "+faststart", str(out)]


# ---------------- audio ----------------
def _read_audio(path: Path, start: float, end: float, sr: int) -> np.ndarray:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.6f}", "-t",
                           f"{end - start:.6f}", "-i", str(path), "-vn", "-ac", "2", "-ar", str(sr),
                           "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.float32).reshape(-1, 2).copy()


def _fade(n: int, kind: str) -> np.ndarray:
    x = np.linspace(0.0, 1.0, n, endpoint=False) + 0.5 / max(n, 1)
    curve = np.sin(x * np.pi / 2) ** 2  # raised-cosine; equal-gain crossfade sums to 1
    return curve if kind == "in" else curve[::-1]


def build_dialogue(p: Project, lay: dict, out: Path) -> dict:
    sr = p.data["profile"]["sample_rate"]
    total = int(round(lay["duration"] * sr))
    buf = np.zeros((total, 2), dtype=np.float64)
    placed = []
    for a in lay["audio"]:
        src = p.abspath(p.source(a["src"])["path"])
        x = _read_audio(src, a["src_start"], a["src_end"], sr).astype(np.float64)
        x *= 10 ** (a["gain_db"] / 20)
        fi, fo = int(a["fade_in"] * sr), int(a["fade_out"] * sr)
        if 0 < fi <= len(x):
            x[:fi] *= _fade(fi, "in")[:, None]
        if 0 < fo <= len(x):
            x[-fo:] *= _fade(fo, "out")[:, None]
        start = int(round(a["tl_start"] * sr))
        s0, s1 = max(start, 0), min(start + len(x), total)
        if s1 > s0:
            buf[s0:s1] += x[s0 - start:s1 - start]
        placed.append({"clip": a["clip"], "tl_start": a["tl_start"], "len": len(x) / sr, "gain_db": a["gain_db"]})
    sf.write(str(out), buf.astype(np.float32), sr, subtype="PCM_24")
    peak = float(np.max(np.abs(buf))) if total else 0.0
    return {"path": str(out), "peak_dbfs": round(20 * np.log10(peak), 2) if peak > 0 else None, "items": placed}


# ---------------- render ----------------
def next_version(p: Project) -> int:
    return 1 + max([r["v"] for r in p.data.get("renders", [])] or [0])


def render(p: Project, *, proxy: bool = False, jobs: int | None = None, keep_segments: bool = False) -> dict:
    lay = layout(p)
    v = next_version(p)
    work = ensure_dir(p.root / "work")
    segdir = ensure_dir(work / f"segments_v{v}")
    clips = {c["id"]: c for c in p.data["clips"]}
    end_fade = lay["end_fade_frames"]
    segs = [segdir / f"{i:03d}_{it['id']}.mp4" for i, it in enumerate(lay["items"])]
    cmds = [_segment_cmd(p, it, clips[it["id"]], segs[i], proxy=proxy, end_fade=end_fade,
                         is_last=i == len(lay["items"]) - 1) for i, it in enumerate(lay["items"])]
    with ThreadPoolExecutor(max_workers=jobs or min(4, os.cpu_count() or 2)) as ex:
        list(ex.map(lambda c: ffmpeg(*c), cmds))

    tag = f"v{v}" + ("_proxy" if proxy else "")
    picture = work / f"picture_{tag}.mp4"
    ffmpeg(*_assemble_cmd(lay, segs, picture, proxy=proxy, overlays=p.data.get("overlays"), root=p.root))
    dialogue = build_dialogue(p, lay, work / f"dialogue_{tag}.wav")

    renders = ensure_dir(p.root / "renders")
    rough = renders / f"{tag}_rough.mp4"
    ffmpeg("-i", str(picture), "-i", dialogue["path"], "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(rough))

    hist = ensure_dir(work / "history")
    snap = hist / f"episode_v{v}.vv.json"
    snap.write_text(json.dumps(p.data, indent=1))
    cl = cut_list(p, lay)
    cl_path = write_json(work / f"cutlist_v{v}.json", cl)
    speech = timeline_speech(p, lay)
    sp_path = write_json(work / f"speech_regions_v{v}.json", speech)
    if not keep_segments:
        shutil.rmtree(segdir, ignore_errors=True)

    rec = {"v": v, "proxy": proxy, "picture": str(picture.relative_to(p.root)),
           "dialogue": str(Path(dialogue["path"]).relative_to(p.root)), "rough": str(rough.relative_to(p.root)),
           "cut_list": str(Path(cl_path).relative_to(p.root)), "speech": str(Path(sp_path).relative_to(p.root)),
           "snapshot": str(snap.relative_to(p.root)), "duration": cl["duration"]}
    p.data.setdefault("renders", []).append(rec)
    p.save()
    return {**rec, "dialogue_peak_dbfs": dialogue["peak_dbfs"], "cut_times": cl["cut_times"],
            "black_spans": cl["black_spans"], "missing_transcripts": speech["missing_transcripts"]}


def deliver(p: Project, audio: str, *, version: int | None = None, target: str = "social") -> dict:
    """Mux the picture of a render with a mastered mix into renders/vN.mp4 and run the check gate."""
    from cva.qc import gate

    recs = [r for r in p.data.get("renders", []) if not r["proxy"]]
    if not recs:
        raise ValueError("no full-quality render yet; run `vv render` (without --proxy) first")
    rec = next((r for r in recs if r["v"] == version), None) if version else recs[-1]
    if rec is None:
        raise ValueError(f"no full render v{version}")
    out = p.root / "renders" / f"v{rec['v']}.mp4"
    ffmpeg("-i", str(p.abspath(rec["picture"])), "-i", str(p.abspath(audio)), "-map", "0:v", "-map", "1:a",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", "-shortest",
           "-movflags", "+faststart", str(out))
    cl = json.loads(p.abspath(rec["cut_list"]).read_text())
    report = gate(out, target=target, expected_duration=cl["duration"], expected_fps=p.fps,
                  allowed_black=cl["black_spans"],
                  size=(p.data["profile"]["width"], p.data["profile"]["height"]))
    rec["delivered"] = {"file": str(out.relative_to(p.root)), "audio": audio, "pass": report["pass"]}
    p.save()
    write_json(p.root / "renders" / f"v{rec['v']}_qc.json", report)
    return {"file": str(out), **report}
