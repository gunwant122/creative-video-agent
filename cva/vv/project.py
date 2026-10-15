"""vv project: an editable timeline stored as JSON (work/episode.vv.json).

Picture is a single ordered track of clips. Each clip owns its audio, which can lead (J-cut) or
trail (L-cut) the picture, so split edits are first-class. Times in the file are frames at the
profile fps for picture, seconds for audio offsets. Gain lives on the source (the take), so every
piece cut from one take shares it.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from cva.media.probe import probe

PROJECT_FILE = "work/episode.vv.json"
TRANSITIONS = ("cut", "dissolve", "dip")
ALIGNS = ("auto", "center", "pre", "post")


class VVError(ValueError):
    pass


def new_project(width: int = 1080, height: int = 1920, fps: int = 24, sample_rate: int = 48000) -> dict:
    return {
        "version": 1,
        "profile": {"width": width, "height": height, "fps": fps, "sample_rate": sample_rate},
        "sources": {},
        "clips": [],
        "audio_fade_frames": 3,
        "end": {"fade_frames": 0},
        "renders": [],
        "next_clip": 1,
    }


class Project:
    def __init__(self, root: str | Path, data: dict):
        self.root = Path(root).resolve()
        self.data = data

    # ---------- persistence ----------
    @classmethod
    def load(cls, root: str | Path) -> "Project":
        root = Path(root)
        f = root / PROJECT_FILE
        if not f.exists():
            raise VVError(f"no project at {f}; run `vv init` first")
        return cls(root, json.loads(f.read_text()))

    @classmethod
    def init(cls, root: str | Path, **profile) -> "Project":
        root = Path(root)
        (root / "work").mkdir(parents=True, exist_ok=True)
        p = cls(root, new_project(**profile))
        p.save()
        return p

    def save(self) -> None:
        f = self.root / PROJECT_FILE
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(f)

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)

    # ---------- helpers ----------
    @property
    def fps(self) -> int:
        return self.data["profile"]["fps"]

    def f(self, seconds: float) -> int:
        return int(round(seconds * self.fps))

    def s(self, frames: int) -> float:
        return frames / self.fps

    def abspath(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    def clip(self, cid: str) -> dict:
        for c in self.data["clips"]:
            if c["id"] == cid:
                return c
        raise VVError(f"no clip {cid!r}; clips: {[c['id'] for c in self.data['clips']]}")

    def index(self, cid: str) -> int:
        return [c["id"] for c in self.data["clips"]].index(self.clip(cid)["id"])

    def source(self, sid: str) -> dict:
        try:
            return self.data["sources"][sid]
        except KeyError:
            raise VVError(f"no source {sid!r}; sources: {list(self.data['sources'])}") from None

    def src_frames(self, sid: str) -> int:
        return int(math.floor(self.source(sid)["duration"] * self.fps + 1e-6))

    # ---------- sources ----------
    def add_source(self, path: str, sid: str | None = None, take: str | None = None) -> dict:
        ap = self.abspath(path)
        if not ap.exists():
            raise VVError(f"file not found: {ap}")
        spec = probe(ap)
        sid = sid or Path(path).stem
        if sid in self.data["sources"]:
            raise VVError(f"source id {sid!r} already exists")
        try:
            rel = str(ap.relative_to(self.root))
        except ValueError:
            rel = str(ap)
        v = spec["video"] or {}
        self.data["sources"][sid] = {
            "path": rel, "take": take or sid, "gain_db": 0.0, "duration": spec["duration"],
            "fps": v.get("fps"), "width": v.get("width"), "height": v.get("height"),
            "has_audio": spec["audio"] is not None,
        }
        return self.data["sources"][sid]

    def set_take_gain(self, sid_or_take: str, gain_db: float) -> list[str]:
        """Set gain for a take; every source of that take (and so every piece cut from it) shares it."""
        take = self.data["sources"][sid_or_take]["take"] if sid_or_take in self.data["sources"] else sid_or_take
        hit = [k for k, s in self.data["sources"].items() if s["take"] == take]
        if not hit:
            raise VVError(f"no source or take {sid_or_take!r}")
        for k in hit:
            self.data["sources"][k]["gain_db"] = round(float(gain_db), 2)
        return hit

    # ---------- clips ----------
    def _new_id(self) -> str:
        n = self.data["next_clip"]
        self.data["next_clip"] = n + 1
        return f"c{n}"

    def add_clip(self, sid: str, in_s: float | None = None, out_s: float | None = None,
                 at: int | None = None) -> dict:
        self.source(sid)
        last = self.src_frames(sid)
        fin = self.f(in_s) if in_s is not None else 0
        fout = self.f(out_s) if out_s is not None else last
        self._check_range(sid, fin, fout)
        c = {"id": self._new_id(), "src": sid, "in": fin, "out": fout,
             "audio": {"lead": 0.0, "tail": 0.0, "gain_db": 0.0, "mute": False},
             "punch": [], "transition_in": {"type": "cut", "frames": 0, "align": "auto"}, "note": ""}
        if at is None:
            self.data["clips"].append(c)
        else:
            self.data["clips"].insert(at, c)
        return c

    def _check_range(self, sid: str, fin: int, fout: int) -> None:
        last = self.src_frames(sid)
        if not (0 <= fin < fout <= last):
            raise VVError(f"range {fin}-{fout} frames outside source {sid} (0-{last}) or empty")

    def trim(self, cid: str, in_s: float | None = None, out_s: float | None = None,
             head: float | None = None, tail: float | None = None) -> dict:
        c = self.clip(cid)
        fin, fout = c["in"], c["out"]
        if in_s is not None:
            fin = self.f(in_s)
        if out_s is not None:
            fout = self.f(out_s)
        if head is not None:
            fin += self.f(head)
        if tail is not None:
            fout -= self.f(tail)
        self._check_range(c["src"], fin, fout)
        c["in"], c["out"] = fin, fout
        return c

    def split(self, cid: str, at_src_s: float) -> tuple[dict, dict]:
        """Split a clip at a source time. Both halves keep the take's gain."""
        c = self.clip(cid)
        k = self.f(at_src_s)
        if not c["in"] < k < c["out"]:
            raise VVError(f"split point {at_src_s}s is outside clip {cid} ({self.s(c['in'])}-{self.s(c['out'])}s)")
        second = copy.deepcopy(c)
        second["id"] = self._new_id()
        second["in"] = k
        second["transition_in"] = {"type": "cut", "frames": 0, "align": "auto"}
        second["audio"]["lead"] = 0.0
        second["punch"] = [dict(kf) for kf in c["punch"]]
        c["out"] = k
        c["audio"]["tail"] = 0.0
        self.data["clips"].insert(self.index(cid) + 1, second)
        return c, second

    def cut_out(self, cid: str, from_s: float, to_s: float) -> tuple[dict, dict]:
        """Remove a span (source time) from inside a clip, e.g. a pause or a glitch."""
        c = self.clip(cid)
        a, b = self.f(from_s), self.f(to_s)
        if not c["in"] < a < b < c["out"]:
            raise VVError("span must lie strictly inside the clip")
        first, second = self.split(cid, from_s)
        second["in"] = b
        return first, second

    def cover(self, cid: str, from_s: float, to_s: float, src: str, src_in: float) -> tuple[dict, dict, dict]:
        """Picture-only cut: replace a span of a clip's picture with a cutaway of the same length while
        the clip's own audio keeps running over it (an L-cut), so no words are lost and sync is kept."""
        first, second = self.cut_out(cid, from_s, to_s)
        span = second["in"] - first["out"]          # frames removed from the picture
        fin = self.f(src_in)
        self._check_range(src, fin, fin + span)
        cut = self.add_clip(src, self.s(fin), self.s(fin + span), at=self.index(first["id"]) + 1)
        cut["in"], cut["out"] = fin, fin + span      # exact frame length
        cut["audio"]["mute"] = True
        cut["note"] = f"cutaway covering {cid} {from_s:.3f}-{to_s:.3f}s"
        first["audio"]["tail"] = round(self.s(span), 6)
        return first, cut, second

    def remove(self, cid: str) -> None:
        self.data["clips"].pop(self.index(cid))

    def move(self, cid: str, to: int) -> None:
        c = self.data["clips"].pop(self.index(cid))
        self.data["clips"].insert(to, c)

    def set_audio(self, cid: str, lead: float | None = None, tail: float | None = None,
                  gain_db: float | None = None, mute: bool | None = None) -> dict:
        a = self.clip(cid)["audio"]
        for k, v in (("lead", lead), ("tail", tail), ("gain_db", gain_db), ("mute", mute)):
            if v is not None:
                a[k] = v
        return a

    def set_punch(self, cid: str, scale: float, x: float = 0.5, y: float = 0.5, t: float | None = None) -> list:
        """Add a punch-in keyframe (t seconds from the clip's start); without t, a static punch."""
        if not 1.0 <= scale <= 2.0:
            raise VVError("scale must be between 1.0 and 2.0")
        c = self.clip(cid)
        kf = {"t": 0.0 if t is None else float(t), "scale": float(scale), "x": float(x), "y": float(y)}
        if t is None:
            c["punch"] = [kf]
        else:
            c["punch"] = sorted([k for k in c["punch"] if abs(k["t"] - kf["t"]) > 1e-6] + [kf], key=lambda k: k["t"])
        return c["punch"]

    # ---------- overlays (titles, captions, logos) ----------
    def add_overlay(self, file: str, start: float, end: float, *, x: str = "(W-w)/2", y: str = "(H-h)/2",
                    fade: float = 0.1, tag: str | None = None) -> dict:
        """A transparent PNG or video composited over the edit between start and end (timeline seconds)."""
        if not self.abspath(file).exists():
            raise VVError(f"overlay file not found: {file}")
        if end <= start:
            raise VVError("overlay end must be after start")
        ovs = self.data.setdefault("overlays", [])
        n = self.data.get("next_overlay", 1)
        self.data["next_overlay"] = n + 1
        ov = {"id": f"o{n}", "file": file, "start": round(float(start), 4), "end": round(float(end), 4),
              "x": str(x), "y": str(y), "fade": float(fade), "tag": tag}
        ovs.append(ov)
        ovs.sort(key=lambda o: o["start"])
        return ov

    def remove_overlay(self, oid: str) -> None:
        before = len(self.data.get("overlays", []))
        self.data["overlays"] = [o for o in self.data.get("overlays", []) if o["id"] != oid]
        if len(self.data["overlays"]) == before:
            raise VVError(f"no overlay {oid!r}")

    def clear_overlays(self, tag: str | None = None) -> int:
        ovs = self.data.get("overlays", [])
        keep = [o for o in ovs if tag is not None and o.get("tag") != tag]
        self.data["overlays"] = keep
        return len(ovs) - len(keep)

    def set_transition(self, cid: str, kind: str, frames: int = 0, align: str = "auto") -> dict:
        if kind not in TRANSITIONS:
            raise VVError(f"transition must be one of {TRANSITIONS}")
        if align not in ALIGNS:
            raise VVError(f"align must be one of {ALIGNS}")
        if self.index(cid) == 0 and kind == "dissolve":
            raise VVError("the first clip has nothing to dissolve from")
        t = {"type": kind, "frames": int(frames) if kind != "cut" else 0, "align": align}
        self.clip(cid)["transition_in"] = t
        return t
