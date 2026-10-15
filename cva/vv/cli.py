"""vv: headless video editor. Every command prints a JSON result (or text for `help`)."""
from __future__ import annotations

import argparse
import json
import sys

from cva.helpdocs import render_help
from cva.vv.layout import cut_list, layout, timeline_speech
from cva.vv.project import Project, VVError

HELP = {
    "jobs": """
Common jobs -> commands (times in seconds; --in/--out are SOURCE times)

Assemble        vv source add src/v1.mp4 ; vv clip add v1 --in 0.3 --out 12.5
Trim heads/tails vv clip trim c3 --head 0.25 --tail 0.4
Remove a pause  vv clip cut-out c3 --from 6.10 --to 6.85        (also hides a short glitch)
Split           vv clip split c3 --at 7.2
Reorder/remove  vv clip move c5 --to 2 ; vv clip rm c5
L-cut           vv clip audio c3 --tail 0.6 ; vv clip audio c4 --lead -0.6
J-cut           vv clip audio c4 --lead 0.5 ; vv clip audio c3 --tail -0.5
Picture-only cut (hide a morph, keep the line):
                 vv clip cover c3 --from 14.2 --to 14.9 --with v2 --src-in 3.0
                 -> the bad frames are replaced by a same-length cutaway (muted) and c3's audio runs over it.
Punch-in        vv punch set c4 --scale 1.2 --x 0.6 --y 0.4           (static)
Push-in         vv punch key c4 --t 0 --scale 1.0 ; vv punch key c4 --t 2 --scale 1.15
Dissolve        vv transition set c4 --type dissolve --frames 8 [--align auto|center|pre|post]
Morph cut       vv transition set c4 --type dissolve --frames 4
Dip to black    vv transition set c6 --type dip --frames 16
Fade out end    vv end --fade-frames 24
Title card      vv overlay title "Episode 4: The Crest" --start 0.5 --end 3.5 [--box] [--y "H*0.2"]
Captions        vv overlay captions [--version N]   (cards from the render's timeline words; re-run after a re-cut)
Any overlay     vv overlay add work/logo.png --start 0 --end 5 --x "W-w-40" --y 40 ; vv overlay list / rm / clear --tag
Take gain       vv source gain v2 --db 13.7          (shared by every piece of that take)
Inspect         vv show ; vv cut-list ; vv speech
Render          vv render --proxy (fast review) ; vv render (full) -> work/picture_vN.mp4 + dialogue stem
Deliver         vv deliver --audio work/master_vN.wav [--target social]   -> renders/vN.mp4 + QC gate
""",
    "project": """
The project file is work/episode.vv.json. Never edit renders; edit the project and re-render.
Every render is versioned (vN) and snapshots the project to work/history/episode_vN.vv.json,
writes work/cutlist_vN.json (cut times, black spans) and work/speech_regions_vN.json
(words mapped to the timeline, from analysis/<source>.words.json). The score retimes from cut lists.
""",
}

CRAFT = {
    "edit-craft": "edit-video/references/edit-craft.md",
    "speech-edits": "edit-video/references/speech-edits.md",
    "glitch-review": "edit-video/references/glitch-review.md",
    "captions": "edit-video/references/caption-craft.md",
    "delivery": "edit-video/references/delivery-specs.md",
}


def _out(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False, default=str))


def _summary(p: Project) -> dict:
    try:
        cl = cut_list(p)
    except VVError as e:
        cl = {"error": str(e)}
    return {"profile": p.data["profile"], "sources": p.data["sources"], "clips": p.data["clips"],
            "overlays": p.data.get("overlays", []),
            "end": p.data.get("end"), "cut_list": cl, "renders": p.data.get("renders", [])}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vv", description="Headless video editor (JSON timeline -> ffmpeg).")
    ap.add_argument("-C", "--project", default=".", help="project folder (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--width", type=int, default=1080)
    s.add_argument("--height", type=int, default=1920)
    s.add_argument("--fps", type=int, default=24)

    s = sub.add_parser("source")
    ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("path"); x.add_argument("--id"); x.add_argument("--take")
    x = ss.add_parser("gain"); x.add_argument("id"); x.add_argument("--db", type=float, required=True)

    s = sub.add_parser("clip")
    ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("src"); x.add_argument("--in", dest="in_s", type=float)
    x.add_argument("--out", dest="out_s", type=float); x.add_argument("--at", type=int)
    x = ss.add_parser("trim"); x.add_argument("id"); x.add_argument("--in", dest="in_s", type=float)
    x.add_argument("--out", dest="out_s", type=float); x.add_argument("--head", type=float)
    x.add_argument("--tail", type=float)
    x = ss.add_parser("split"); x.add_argument("id"); x.add_argument("--at", type=float, required=True)
    x = ss.add_parser("cut-out"); x.add_argument("id"); x.add_argument("--from", dest="frm", type=float, required=True)
    x.add_argument("--to", type=float, required=True)
    x = ss.add_parser("cover"); x.add_argument("id"); x.add_argument("--from", dest="frm", type=float, required=True)
    x.add_argument("--to", type=float, required=True); x.add_argument("--with", dest="src", required=True)
    x.add_argument("--src-in", type=float, required=True)
    x = ss.add_parser("rm"); x.add_argument("id")
    x = ss.add_parser("move"); x.add_argument("id"); x.add_argument("--to", type=int, required=True)
    x = ss.add_parser("audio"); x.add_argument("id"); x.add_argument("--lead", type=float)
    x.add_argument("--tail", type=float); x.add_argument("--gain", type=float)
    x.add_argument("--mute", action=argparse.BooleanOptionalAction, default=None)
    x = ss.add_parser("note"); x.add_argument("id"); x.add_argument("text")

    s = sub.add_parser("punch")
    ss = s.add_subparsers(dest="sub", required=True)
    for name in ("set", "key"):
        x = ss.add_parser(name); x.add_argument("id"); x.add_argument("--scale", type=float, required=True)
        x.add_argument("--x", type=float, default=0.5); x.add_argument("--y", type=float, default=0.5)
        if name == "key":
            x.add_argument("--t", type=float, required=True)
    x = ss.add_parser("clear"); x.add_argument("id")

    s = sub.add_parser("transition")
    ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("set"); x.add_argument("id"); x.add_argument("--type", required=True)
    x.add_argument("--frames", type=int, default=0); x.add_argument("--align", default="auto")

    s = sub.add_parser("overlay")
    ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("file"); x.add_argument("--start", type=float, required=True)
    x.add_argument("--end", type=float, required=True); x.add_argument("--x", default="(W-w)/2")
    x.add_argument("--y", default="(H-h)/2"); x.add_argument("--fade", type=float, default=0.1); x.add_argument("--tag")
    x = ss.add_parser("rm"); x.add_argument("id")
    x = ss.add_parser("clear"); x.add_argument("--tag")
    x = ss.add_parser("captions"); x.add_argument("--version", type=int); x.add_argument("--size", type=int)
    x.add_argument("--y", default="H*0.66-h/2"); x.add_argument("--max-chars", type=int, default=32)
    x = ss.add_parser("title"); x.add_argument("text"); x.add_argument("--start", type=float, required=True)
    x.add_argument("--end", type=float, required=True); x.add_argument("--size", type=int)
    x.add_argument("--y", default="(H-h)/2"); x.add_argument("--box", action="store_true")
    x = ss.add_parser("list")

    s = sub.add_parser("end"); s.add_argument("--fade-frames", type=int, required=True)
    sub.add_parser("show")
    sub.add_parser("cut-list")
    sub.add_parser("speech")
    s = sub.add_parser("render"); s.add_argument("--proxy", action="store_true")
    s.add_argument("--keep-segments", action="store_true")
    s = sub.add_parser("deliver"); s.add_argument("--audio", required=True); s.add_argument("--version", type=int)
    s.add_argument("--target", default="social")
    s = sub.add_parser("stills"); s.add_argument("--version", type=int)
    s = sub.add_parser("export-otio"); s.add_argument("--out", default="work/episode.otio")
    s = sub.add_parser("help"); s.add_argument("topic", nargs="?")
    return ap


def run(argv: list[str]) -> object:
    a = build_parser().parse_args(argv)
    if a.cmd == "help":
        return render_help(HELP, CRAFT, a.topic)
    if a.cmd == "init":
        p = Project.init(a.project, width=a.width, height=a.height, fps=a.fps)
        return {"ok": True, "project": str(p.root), "profile": p.data["profile"]}
    p = Project.load(a.project)
    res: object
    if a.cmd == "source":
        res = p.add_source(a.path, a.id, a.take) if a.sub == "add" else {"sources": p.set_take_gain(a.id, a.db)}
    elif a.cmd == "clip":
        if a.sub == "add":
            res = p.add_clip(a.src, a.in_s, a.out_s, a.at)
        elif a.sub == "trim":
            res = p.trim(a.id, a.in_s, a.out_s, a.head, a.tail)
        elif a.sub == "split":
            res = p.split(a.id, a.at)
        elif a.sub == "cut-out":
            res = p.cut_out(a.id, a.frm, a.to)
        elif a.sub == "cover":
            res = p.cover(a.id, a.frm, a.to, a.src, a.src_in)
        elif a.sub == "rm":
            p.remove(a.id); res = {"removed": a.id}
        elif a.sub == "move":
            p.move(a.id, a.to); res = {"order": [c["id"] for c in p.data["clips"]]}
        elif a.sub == "audio":
            res = p.set_audio(a.id, a.lead, a.tail, a.gain, a.mute)
        else:
            p.clip(a.id)["note"] = a.text; res = p.clip(a.id)
    elif a.cmd == "punch":
        if a.sub == "clear":
            p.clip(a.id)["punch"] = []; res = []
        else:
            res = p.set_punch(a.id, a.scale, a.x, a.y, a.t if a.sub == "key" else None)
    elif a.cmd == "transition":
        res = p.set_transition(a.id, a.type, a.frames, a.align)
        layout(p)  # validate handles now, not at render time
    elif a.cmd == "overlay":
        if a.sub == "add":
            res = p.add_overlay(a.file, a.start, a.end, x=a.x, y=a.y, fade=a.fade, tag=a.tag)
        elif a.sub == "rm":
            p.remove_overlay(a.id); res = {"removed": a.id}
        elif a.sub == "clear":
            res = {"removed": p.clear_overlays(a.tag)}
        elif a.sub == "captions":
            from cva.motion import add_captions
            res = add_captions(p, version=a.version, size=a.size, y=a.y, max_chars=a.max_chars)
        elif a.sub == "title":
            from cva.motion import add_title
            res = add_title(p, a.text, a.start, a.end, size=a.size, y=a.y, box=a.box)
        else:
            return p.data.get("overlays", [])
    elif a.cmd == "end":
        p.data["end"] = {"fade_frames": a.fade_frames}; res = p.data["end"]
    elif a.cmd == "show":
        return _summary(p)
    elif a.cmd == "cut-list":
        return cut_list(p)
    elif a.cmd == "speech":
        return timeline_speech(p)
    elif a.cmd == "render":
        from cva.vv.render import render
        return render(p, proxy=a.proxy, keep_segments=a.keep_segments)
    elif a.cmd == "deliver":
        from cva.vv.render import deliver
        return deliver(p, a.audio, version=a.version, target=a.target)
    elif a.cmd == "stills":
        from cva.media import stills_at
        recs = [r for r in p.data["renders"] if a.version in (None, r["v"])]
        if not recs:
            raise VVError("no render yet")
        r = recs[-1]
        cl = json.loads(p.abspath(r["cut_list"]).read_text())
        return stills_at(p.abspath(r["rough"]), cl["cut_times"], p.root / "analysis" / f"stills_v{r['v']}", fps=p.fps)
    elif a.cmd == "export-otio":
        from cva.vv.otio import export
        return {"otio": export(p, a.out)}
    else:
        raise VVError(f"unknown command {a.cmd}")
    p.save()
    return res


def main(argv: list[str] | None = None) -> int:
    from cva.config import load_env
    load_env()
    try:
        res = run(sys.argv[1:] if argv is None else argv)
    except (VVError, ValueError) as e:
        _out({"ok": False, "error": str(e)})
        return 1
    if isinstance(res, str):
        print(res)
    else:
        _out(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
