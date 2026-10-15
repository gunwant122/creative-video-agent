"""vd score: an editable score in picture time (work/score.vd.json).

Tempo is fixed at 60 bpm so one beat is one second: every note's `t` and `d` are seconds on the edit's
timeline. Cues come from the vv cut list. Hits/risers are audio files placed by time. After a re-cut,
`retime` maps every note, hit, cue and section from the old cut list to the new one via source time.
"""
from __future__ import annotations

import copy
import json
import re
from bisect import bisect_right
from pathlib import Path

import pretty_midi

SCORE_FILE = "work/score.vd.json"

# comfortable ranges (MIDI, sounding) - see skills/make-music/references/orchestra-ranges.md
RANGES = {
    "violin": (55, 93), "viola": (48, 81), "cello": (36, 76), "bass": (28, 50), "contrabass": (28, 50),
    "harp": (36, 96), "horn": (41, 77), "trumpet": (60, 84), "trombone": (45, 65), "tuba": (29, 60),
    "timpani": (38, 57), "bells": (60, 77), "tubular": (60, 77), "glockenspiel": (79, 108),
    "piano": (21, 108), "choir": (40, 81), "flute": (60, 96), "oboe": (58, 89), "clarinet": (50, 89),
    "bassoon": (34, 72),
}


class VDError(ValueError):
    pass


def note_number(p) -> int:
    if isinstance(p, int):
        return p
    if isinstance(p, str) and p.strip().lstrip("-").isdigit():
        return int(p)
    try:
        return pretty_midi.note_name_to_number(str(p).strip())
    except Exception:
        raise VDError(f"bad pitch {p!r}; use MIDI numbers or names like D4, F#3, Bb2") from None


def sfz_key_range(path: str | Path) -> tuple[int, int] | None:
    """Lowest and highest key an SFZ maps (lokey/hikey/key, numbers or note names)."""
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return None
    keys = []
    for k, v in re.findall(r"\b(lokey|hikey|key|pitch_keycenter)=([A-Za-z#]*-?\d+)", text):
        if k == "pitch_keycenter":
            continue
        try:
            keys.append(int(v) if v.lstrip("-").isdigit() else pretty_midi.note_name_to_number(v[0].upper() + v[1:]))
        except Exception:
            pass
    return (min(keys), max(keys)) if keys else None


def default_range(name: str) -> tuple[int, int] | None:
    n = name.lower()
    for key, r in RANGES.items():
        if key in n:
            return r
    return None


def new_score() -> dict:
    return {"version": 1, "tempo": 60, "sample_rate": 48000, "timed_to": None, "speech": None,
            "cues": [], "sections": [], "parts": {}, "notes": {}, "hits": [], "renders": []}


class Score:
    def __init__(self, root: str | Path, data: dict):
        self.root = Path(root).resolve()
        self.data = data

    @classmethod
    def load(cls, root) -> "Score":
        f = Path(root) / SCORE_FILE
        if not f.exists():
            raise VDError(f"no score at {f}; run `vd init`")
        return cls(root, json.loads(f.read_text()))

    @classmethod
    def init(cls, root) -> "Score":
        s = cls(root, new_score())
        s.save()
        return s

    def save(self) -> None:
        f = self.root / SCORE_FILE
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(f)

    def abspath(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    # ---------- cues ----------
    def import_cues(self, cutlist: str, speech: str | None = None) -> list[dict]:
        cl = json.loads(self.abspath(cutlist).read_text())
        keep = {c["name"]: c for c in self.data["cues"] if c.get("manual")}
        cues = [{"name": "start", "t": 0.0, "kind": "start"}]
        for c in cl["clips"][1:]:
            cues.append({"name": f"cut:{c['clip']}", "t": c["start"], "kind": c["transition_in"]["type"]})
        cues.append({"name": "end", "t": cl["duration"], "kind": "end"})
        self.data["cues"] = sorted(cues + list(keep.values()), key=lambda c: c["t"])
        self.data["timed_to"] = cutlist
        if speech:
            self.data["speech"] = speech
        self.data["duration"] = cl["duration"]
        return self.data["cues"]

    def add_cue(self, name: str, t: float, beat: str = "", **extra) -> dict:
        self.data["cues"] = [c for c in self.data["cues"] if c["name"] != name]
        c = {"name": name, "t": float(t), "kind": extra.pop("kind", "beat"), "beat": beat, "manual": True, **extra}
        self.data["cues"].append(c)
        self.data["cues"].sort(key=lambda c: c["t"])
        return c

    def cue(self, name: str) -> dict:
        for c in self.data["cues"]:
            if c["name"] == name:
                return c
        raise VDError(f"no cue {name!r}")

    def speech_regions(self) -> list[list[float]]:
        if not self.data.get("speech"):
            return []
        d = json.loads(self.abspath(self.data["speech"]).read_text())
        return d["regions"] if isinstance(d, dict) else d

    # ---------- parts / notes ----------
    def add_part(self, name: str, patch: str | None = None, *, role: str = "pad", pan: float = 0.0,
                 gain_db: float = 0.0, reverb: float = 0.25, program: int = 48,
                 rng: tuple[int, int] | None = None) -> dict:
        part = {"patch": patch, "role": role, "pan": pan, "gain_db": gain_db, "reverb": reverb,
                "program": program, "range": list(rng or default_range(name) or (21, 108))}
        if patch:
            mapped = sfz_key_range(self.abspath(patch)) if patch.lower().endswith(".sfz") else None
            if patch.lower().endswith(".sfz") and not self.abspath(patch).exists():
                raise VDError(f"patch not found: {patch} (fetch it with scripts/fetch_instruments.py)")
            if mapped:
                part["mapped"] = list(mapped)
        self.data["parts"][name] = part
        self.data["notes"].setdefault(name, [])
        return part

    def part(self, name: str) -> dict:
        if name not in self.data["parts"]:
            raise VDError(f"no part {name!r}; parts: {list(self.data['parts'])}")
        return self.data["parts"][name]

    def add_notes(self, part: str, notes: list[dict], *, section: str | None = None, offset: float = 0.0) -> int:
        self.part(part)
        out = self.data["notes"].setdefault(part, [])
        for n in notes:
            out.append({"p": note_number(n["p"]), "t": round(float(n["t"]) + offset, 4),
                        "d": round(float(n["d"]), 4), "v": int(n.get("v", 64)),
                        **({"sec": n.get("sec", section)} if (n.get("sec") or section) else {})})
        out.sort(key=lambda n: (n["t"], n["p"]))
        return len(notes)

    def clear_notes(self, part: str, section: str | None = None, t0: float | None = None,
                    t1: float | None = None) -> int:
        notes = self.data["notes"].get(part, [])
        keep = [n for n in notes if not ((section is None or n.get("sec") == section)
                                          and (t0 is None or n["t"] >= t0) and (t1 is None or n["t"] < t1))]
        self.data["notes"][part] = keep
        return len(notes) - len(keep)

    def add_hit(self, file: str, t: float, *, align: str = "start", gain_db: float = 0.0, cue: str | None = None,
                kind: str = "impact") -> dict:
        if align not in ("start", "end"):
            raise VDError("align must be start (impacts) or end (risers)")
        h = {"file": file, "t": float(t), "align": align, "gain_db": gain_db, "cue": cue, "kind": kind}
        self.data["hits"].append(h)
        self.data["hits"].sort(key=lambda h: h["t"])
        return h

    def add_section(self, name: str, start: float, end: float, **info) -> dict:
        self.data["sections"] = [s for s in self.data["sections"] if s["name"] != name]
        s = {"name": name, "start": float(start), "end": float(end), **info}
        self.data["sections"].append(s)
        self.data["sections"].sort(key=lambda s: s["start"])
        return s

    # ---------- generators ----------
    def gen_ostinato(self, part: str, pattern: list, t0: float, t1: float, step: float, v: int = 70,
                     accent: int = 0, section: str | None = None, legato: float = 0.9) -> int:
        notes, t, i = [], t0, 0
        while t < t1 - 1e-6:
            notes.append({"p": pattern[i % len(pattern)], "t": t, "d": step * legato,
                          "v": min(127, v + (accent if i % len(pattern) == 0 else 0))})
            t += step
            i += 1
        return self.add_notes(part, notes, section=section)

    def gen_chords(self, part: str, chords: list[tuple[float, float, list]], v: int = 55,
                   section: str | None = None) -> int:
        notes = [{"p": p, "t": t, "d": d, "v": v} for t, d, ps in chords for p in ps]
        return self.add_notes(part, notes, section=section)

    def gen_crescendo(self, part: str, t0: float, t1: float, v0: int, v1: int) -> int:
        n = 0
        for note in self.data["notes"].get(part, []):
            if t0 <= note["t"] < t1:
                note["v"] = int(round(v0 + (v1 - v0) * (note["t"] - t0) / max(t1 - t0, 1e-6)))
                n += 1
        return n

    # ---------- retime ----------
    def retime(self, old_cutlist: str, new_cutlist: str) -> dict:
        tm = TimeMap(json.loads(self.abspath(old_cutlist).read_text()), json.loads(self.abspath(new_cutlist).read_text()))
        moved = 0
        for part, notes in self.data["notes"].items():
            for n in notes:
                t0, t1 = tm(n["t"]), tm(n["t"] + n["d"])
                n["t"], n["d"] = round(t0, 4), round(max(t1 - t0, 0.05), 4)
                moved += 1
        for h in self.data["hits"]:
            h["t"] = round(tm(h["t"]), 4)
        for s in self.data["sections"]:
            s["start"], s["end"] = round(tm(s["start"]), 4), round(tm(s["end"]), 4)
        manual = [c for c in self.data["cues"] if c.get("manual")]
        for c in manual:
            c["t"] = round(tm(c["t"]), 4)
        self.import_cues(new_cutlist)
        # hits tied to cut cues snap exactly onto the new cut
        cues = {c["name"]: c["t"] for c in self.data["cues"]}
        snapped = 0
        for h in self.data["hits"]:
            if h.get("cue") in cues and h["align"] == "start":
                h["t"] = cues[h["cue"]]
                snapped += 1
        return {"notes": moved, "hits": len(self.data["hits"]), "hits_snapped_to_cues": snapped,
                "old_duration": tm.old_dur, "new_duration": tm.new_dur, "anchors": len(tm.anchors)}

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)


class TimeMap:
    """Old timeline time -> new timeline time, through source time where possible."""

    def __init__(self, old: dict, new: dict):
        self.old, self.new = old["clips"], new["clips"]
        self.old_dur, self.new_dur = old["duration"], new["duration"]
        self.new_by_id = {c["clip"]: c for c in self.new}
        anchors = {(0.0, 0.0), (self.old_dur, self.new_dur)}
        for c in self.old:
            for t in (c["start"], c["end"]):
                m = self._direct(t)
                if m is None:
                    m = self._boundary(t)
                if m is not None:
                    anchors.add((round(t, 6), round(m, 6)))
        a = sorted(anchors)
        # keep it monotonic
        mono = [a[0]]
        for x, y in a[1:]:
            if x > mono[-1][0] and y >= mono[-1][1]:
                mono.append((x, y))
        self.anchors = mono

    def _direct(self, t: float) -> float | None:
        for i, c in enumerate(self.old):
            last = i == len(self.old) - 1
            if c["start"] - 1e-9 <= t < c["end"] or (last and abs(t - c["end"]) < 1e-9):
                s = c["src_in"] + (t - c["start"])
                best = None
                for n in self.new:
                    if n["src"] == c["src"] and n["src_in"] - 1e-6 <= s <= n["src_out"] + 1e-6:
                        nt = n["start"] + (s - n["src_in"])
                        if best is None or abs(nt - t) < abs(best - t):
                            best = nt
                return best
        return None

    def _boundary(self, t: float) -> float | None:
        """A cut point whose source frame was trimmed away maps onto the same clip's new cut point."""
        for c in self.old:
            n = self.new_by_id.get(c["clip"])
            if n is None:
                continue
            if abs(t - c["start"]) < 1e-6:
                return n["start"]
            if abs(t - c["end"]) < 1e-6:
                return n["end"]
        return None

    def __call__(self, t: float) -> float:
        d = self._direct(t)
        if d is None:
            d = self._boundary(t)
        if d is not None:
            return d
        xs = [a[0] for a in self.anchors]
        i = bisect_right(xs, t)
        if i <= 0:
            return self.anchors[0][1] + (t - xs[0])
        if i >= len(xs):
            return self.anchors[-1][1] + (t - xs[-1])
        (x0, y0), (x1, y1) = self.anchors[i - 1], self.anchors[i]
        return y0 + (y1 - y0) * (t - x0) / (x1 - x0)
