"""Resolve a vv project into concrete timeline positions (the cut list).

Every clip keeps its cut point fixed: clip i starts at T_i = sum of earlier clip lengths. A dissolve
into clip i borrows handle frames from outside the trimmed ranges:
  center - half from after A's out, half from before B's in
  pre    - all from before B's in (the dissolve finishes on the cut)
  post   - all from after A's out (the dissolve starts on the cut)
`auto` picks center, then pre, then post, whichever the handles allow, and refuses otherwise.
"""
from __future__ import annotations

import json
from pathlib import Path

from cva.media.transcribe import speech_regions
from cva.vv.project import Project, VVError


def _resolve_dissolve(p: Project, a: dict, b: dict, d: int, align: str) -> tuple[int, int, str]:
    post_avail = p.src_frames(a["src"]) - a["out"]
    pre_avail = b["in"]
    options = {
        "center": (d - d // 2, d // 2),   # (post from A, pre from B)
        "pre": (0, d),
        "post": (d, 0),
    }
    order = ["center", "pre", "post"] if align == "auto" else [align]
    for name in order:
        post, pre = options[name]
        if post <= post_avail and pre <= pre_avail:
            return post, pre, name
    raise VVError(
        f"dissolve of {d} frames into {b['id']} does not fit: {a['id']} has {post_avail} spare frames after its out, "
        f"{b['id']} has {pre_avail} before its in. Shorten the dissolve, trim the clips to free handles, "
        f"or use a dip/cut.")


def layout(p: Project) -> dict:
    clips = p.data["clips"]
    if not clips:
        raise VVError("timeline is empty")
    fps = p.fps
    fade = p.data.get("audio_fade_frames", 3)
    items = []
    t = 0
    for i, c in enumerate(clips):
        L = c["out"] - c["in"]
        tr = c["transition_in"]
        item = {"id": c["id"], "src": c["src"], "index": i, "T": t, "L": L, "in": c["in"], "out": c["out"],
                "pre": 0, "post": 0, "tin": {"type": "cut", "frames": 0}, "tout": {"type": "cut", "frames": 0},
                "dip_in": 0, "dip_out": 0}
        if i > 0 and tr["type"] == "dissolve" and tr["frames"] > 0:
            prev = items[-1]
            post, pre, name = _resolve_dissolve(p, clips[i - 1], c, tr["frames"], tr.get("align", "auto"))
            prev["post"] = post
            item["pre"] = pre
            item["tin"] = {"type": "dissolve", "frames": tr["frames"], "align": name}
            prev["tout"] = {"type": "dissolve", "frames": tr["frames"], "align": name}
        elif i > 0 and tr["type"] == "dip" and tr["frames"] > 0:
            d = tr["frames"]
            items[-1]["dip_out"] = d // 2
            item["dip_in"] = d - d // 2
            item["tin"] = {"type": "dip", "frames": d}
            items[-1]["tout"] = {"type": "dip", "frames": d}
        items.append(item)
        t += L

    # transitions on one clip must not overlap each other
    # frames of each transition that fall inside the clip's own trimmed range
    for it in items:
        in_span = it["tin"]["frames"] - it["pre"] if it["tin"]["type"] == "dissolve" else it["dip_in"]
        out_span = it["tout"]["frames"] - it["post"] if it["tout"]["type"] == "dissolve" else it["dip_out"]
        if in_span + out_span > it["L"]:
            raise VVError(f"clip {it['id']} ({it['L']} frames) is too short for its transitions "
                          f"({in_span} + {out_span} frames)")

    end_fade = int(p.data.get("end", {}).get("fade_frames", 0) or 0)
    total = t

    # audio placement (seconds)
    audio = []
    for c, it in zip(clips, items):
        a = c["audio"]
        src = p.source(c["src"])
        if a.get("mute") or not src.get("has_audio", True):
            continue
        pre_s, post_s = it["pre"] / fps, it["post"] / fps
        lead = max(a.get("lead", 0.0), pre_s) if it["tin"]["type"] == "dissolve" else a.get("lead", 0.0)
        tail = max(a.get("tail", 0.0), post_s) if it["tout"]["type"] == "dissolve" else a.get("tail", 0.0)
        s0 = it["in"] / fps - lead
        s1 = it["out"] / fps + tail
        tl0 = it["T"] / fps - lead
        if s0 < 0:          # not enough source before: start later on the timeline
            tl0 -= s0
            s0 = 0.0
        s1 = min(s1, src["duration"])
        if s1 <= s0:
            continue
        fin = it["tin"]["frames"] / fps if it["tin"]["type"] == "dissolve" else (
            it["dip_in"] / fps if it["tin"]["type"] == "dip" else fade / fps)
        fout = it["tout"]["frames"] / fps if it["tout"]["type"] == "dissolve" else (
            it["dip_out"] / fps if it["tout"]["type"] == "dip" else fade / fps)
        if it is items[-1] and end_fade:
            fout = max(fout, end_fade / fps)
        audio.append({"clip": c["id"], "src": c["src"], "src_start": round(s0, 6), "src_end": round(s1, 6),
                      "tl_start": round(tl0, 6), "fade_in": max(fin, fade / fps), "fade_out": max(fout, fade / fps),
                      "gain_db": float(src.get("gain_db", 0.0)) + float(a.get("gain_db", 0.0))})

    return {"fps": fps, "total_frames": total, "duration": total / fps, "items": items, "audio": audio,
            "end_fade_frames": end_fade}


def cut_list(p: Project, lay: dict | None = None) -> dict:
    lay = lay or layout(p)
    fps = lay["fps"]
    cuts = []
    for it in lay["items"]:
        cuts.append({
            "clip": it["id"], "src": it["src"],
            "start": round(it["T"] / fps, 3), "end": round((it["T"] + it["L"]) / fps, 3),
            "src_in": round(it["in"] / fps, 3), "src_out": round(it["out"] / fps, 3),
            "transition_in": it["tin"],
        })
    dips = []
    for it in lay["items"]:
        if it["tin"]["type"] == "dip":
            c = it["T"] / fps
            dips.append([round(c - it["dip_in"] / fps, 3), round(c + it["dip_in"] / fps, 3)])
    if lay["end_fade_frames"]:
        dips.append([round(lay["duration"] - lay["end_fade_frames"] / fps, 3), round(lay["duration"], 3)])
    return {"duration": round(lay["duration"], 3), "fps": fps, "clips": cuts,
            "cut_times": [c["start"] for c in cuts[1:]], "black_spans": dips}


def timeline_speech(p: Project, lay: dict | None = None, words_dir: str = "analysis",
                    merge_gap: float = 0.8) -> dict:
    """Map each source's word-timed transcript onto the timeline through the audio placements."""
    lay = lay or layout(p)
    words, missing = [], []
    for a in lay["audio"]:
        f = p.root / words_dir / f"{a['src']}.words.json"
        if not f.exists():
            missing.append(a["src"])
            continue
        for w in json.loads(f.read_text())["words"]:
            if w["start"] >= a["src_start"] and w["end"] <= a["src_end"]:
                off = a["tl_start"] - a["src_start"]
                words.append({"word": w["word"], "start": w["start"] + off, "end": w["end"] + off, "clip": a["clip"]})
    words.sort(key=lambda w: w["start"])
    return {"words": words, "regions": speech_regions(words, merge_gap=merge_gap),
            "missing_transcripts": sorted(set(missing))}


def write_json(path: str | Path, obj) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    return str(path)
