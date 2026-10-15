"""Read the score back (the agent cannot listen): ranges, voice clashes, hit sync, escalation, dry air."""
from __future__ import annotations

from cva.vd.score import Score


def _overlaps(t0: float, t1: float, regions: list[list[float]]) -> bool:
    return any(t0 < b and t1 > a for a, b in regions)


def check(s: Score, *, sync_ms: float = 20.0) -> dict:
    issues, warnings = [], []
    speech = s.speech_regions()
    cues = {c["name"]: c for c in s.data["cues"]}

    for name, notes in s.data["notes"].items():
        part = s.data["parts"].get(name, {})
        lo, hi = part.get("range", (21, 108))
        mapped = part.get("mapped")
        for n in notes:
            if mapped and not mapped[0] <= n["p"] <= mapped[1]:
                issues.append({"type": "unmapped", "part": name, "t": n["t"], "p": n["p"],
                               "msg": f"{name}: pitch {n['p']} is outside the patch's samples {mapped[0]}-{mapped[1]} (silent)"})
            elif not lo <= n["p"] <= hi:
                issues.append({"type": "range", "part": name, "t": n["t"], "p": n["p"],
                               "msg": f"{name}: pitch {n['p']} outside comfortable range {lo}-{hi}"})
        if speech:
            for n in notes:
                under = _overlaps(n["t"], n["t"] + n["d"], speech)
                if not under:
                    continue
                if 60 <= n["p"] <= 84 and n["v"] > 70:
                    issues.append({"type": "voice_clash", "part": name, "t": n["t"], "p": n["p"],
                                   "msg": f"{name}: loud note {n['p']} (v{n['v']}) in the voice range under speech"})
                elif part.get("role") == "melody":
                    warnings.append({"type": "melody_under_speech", "part": name, "t": n["t"],
                                     "msg": f"{name}: melody note under speech at {n['t']:.2f}s"})

    for h in s.data["hits"]:
        c = cues.get(h.get("cue") or "")
        if not c:
            continue
        if h["align"] == "start":
            err = (h["t"] - c["t"]) * 1000
            if abs(err) > sync_ms:
                issues.append({"type": "hit_sync", "t": h["t"], "cue": c["name"],
                               "msg": f"impact {h['file']} starts {err:+.0f} ms from cue {c['name']}"})
        elif abs(h["t"] - c["t"]) * 1000 > sync_ms:
            issues.append({"type": "riser_sync", "t": h["t"], "cue": c["name"],
                           "msg": f"riser {h['file']} should end on cue {c['name']} ({c['t']}s), ends at {h['t']}s"})

    impacts = [h for h in s.data["hits"] if h.get("kind", "impact") == "impact"]
    if len(impacts) >= 2:
        last = impacts[-1].get("gain_db", 0.0)
        bigger = [h for h in impacts[:-1] if h.get("gain_db", 0.0) > last]
        if bigger:
            warnings.append({"type": "escalation",
                             "msg": f"{len(bigger)} earlier impact(s) louder than the final one; hold earlier hits back"})

    for c in s.data["cues"]:
        if c.get("dry"):
            t0, t1 = c["t"], c["t"] + float(c.get("dry_len", 2.0))
            sounding = [(name, n["t"]) for name, ns in s.data["notes"].items() for n in ns
                        if n["t"] < t1 and n["t"] + n["d"] > t0]
            if sounding:
                issues.append({"type": "dry_air", "cue": c["name"],
                               "msg": f"{len(sounding)} note(s) sound during the dry moment at {c['name']}"})

    hits_report = [{"file": h["file"], "t": h["t"], "cue": h.get("cue"),
                    "error_ms": round((h["t"] - cues[h["cue"]]["t"]) * 1000, 1) if h.get("cue") in cues else None}
                   for h in s.data["hits"]]
    return {"ok": not issues, "issues": issues, "warnings": warnings, "hits": hits_report,
            "speech_regions": len(speech),
            "note": "Numbers only - the agent cannot hear. Feel and balance need a human listener."}
