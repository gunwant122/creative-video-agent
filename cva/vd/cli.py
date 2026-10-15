"""vd: headless score workstation. Every command prints JSON (text for `help`)."""
from __future__ import annotations

import argparse
import json
import sys

from cva.helpdocs import render_help
from cva.vd.score import Score, VDError, note_number

HELP = {
    "jobs": """
Scoring jobs -> commands. Times are seconds on the edit's timeline (tempo is fixed at 60: 1 beat = 1 s).

Start           vd init ; vd cue import --cutlist work/cutlist_v2.json --speech work/speech_regions_v2.json
Story beats     vd cue add rise --t 31.2 --beat "she rises, 8 s silent" ; vd cue add tell --t 70.1 --dry --dry-len 1.5
Sections        vd section add hospital --start 0 --end 31.2 --key Dm --palette "harp, soft strings"
Parts           vd part add violins --patch assets/libs/VSCO-2-CE/Strings/1st\\ Violins/...sfz --role melody --pan -0.4
                roles: melody | pad | bass | pluck | perc   (pan -1..1, reverb send 0..1)
Notes           vd phrase add violins --notes '[{"p":"D5","t":31.4,"d":1.5,"v":62}, ...]' --section rise
Chords / pads   vd chord add strings --t 0 --d 4 --notes D3,A3,F4 --v 45
Ostinato        vd gen ostinato celli --pattern D2,D2,A2,D3 --from 40 --to 52 --step 0.25 --v 72 --accent 10
Crescendo       vd gen crescendo celli --from 44 --to 52 --v0 55 --v1 100
Hits / risers   vd hit place assets/hits/boom.wav --cue cut:c6            (impact starts ON the cut)
                vd hit place assets/hits/riser.wav --cue cut:c6 --align end --kind riser   (ends ON the cut)
Re-cut          vd retime --from work/cutlist_v2.json --to work/cutlist_v3.json   (maps notes; no recomposing)
Check           vd check          (ranges, loud notes in the voice range under speech, hit sync, escalation, dry air)
Render          vd render         -> work/music_mN.wav + work/stems/mN/*.wav (to mix-audio for ducking)
Export          vd midi --out work/score.mid   (for a human in a DAW)
""",
}

CRAFT = {
    "video-scoring": "make-music/references/video-scoring.md",
    "underscore-dialogue": "make-music/references/underscore-dialogue.md",
    "writing": "make-music/references/writing.md",
    "cinematic": "make-music/references/cinematic.md",
    "climaxes": "make-music/references/climaxes.md",
    "orchestra-ranges": "make-music/references/orchestra-ranges.md",
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vd", description="Headless score workstation (picture-time score -> stems).")
    ap.add_argument("-C", "--project", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("show")

    s = sub.add_parser("cue"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("import"); x.add_argument("--cutlist", required=True); x.add_argument("--speech")
    x = ss.add_parser("add"); x.add_argument("name"); x.add_argument("--t", type=float, required=True)
    x.add_argument("--beat", default=""); x.add_argument("--dry", action="store_true")
    x.add_argument("--dry-len", type=float, default=2.0)

    s = sub.add_parser("section"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("name"); x.add_argument("--start", type=float, required=True)
    x.add_argument("--end", type=float, required=True); x.add_argument("--key"); x.add_argument("--palette")
    x.add_argument("--mood")

    s = sub.add_parser("part"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("name"); x.add_argument("--patch"); x.add_argument("--role", default="pad")
    x.add_argument("--pan", type=float, default=0.0); x.add_argument("--gain", type=float, default=0.0)
    x.add_argument("--reverb", type=float, default=0.25); x.add_argument("--program", type=int, default=48)
    x.add_argument("--range", nargs=2)

    s = sub.add_parser("phrase"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("part"); x.add_argument("--notes", required=True)
    x.add_argument("--section"); x.add_argument("--offset", type=float, default=0.0)
    x = ss.add_parser("clear"); x.add_argument("part"); x.add_argument("--section")
    x.add_argument("--from", dest="t0", type=float); x.add_argument("--to", dest="t1", type=float)

    s = sub.add_parser("chord"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("add"); x.add_argument("part"); x.add_argument("--t", type=float, required=True)
    x.add_argument("--d", type=float, required=True); x.add_argument("--notes", required=True)
    x.add_argument("--v", type=int, default=50); x.add_argument("--section")

    s = sub.add_parser("gen"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("ostinato"); x.add_argument("part"); x.add_argument("--pattern", required=True)
    x.add_argument("--from", dest="t0", type=float, required=True); x.add_argument("--to", dest="t1", type=float, required=True)
    x.add_argument("--step", type=float, required=True); x.add_argument("--v", type=int, default=70)
    x.add_argument("--accent", type=int, default=0); x.add_argument("--section")
    x = ss.add_parser("crescendo"); x.add_argument("part")
    x.add_argument("--from", dest="t0", type=float, required=True); x.add_argument("--to", dest="t1", type=float, required=True)
    x.add_argument("--v0", type=int, required=True); x.add_argument("--v1", type=int, required=True)

    s = sub.add_parser("hit"); ss = s.add_subparsers(dest="sub", required=True)
    x = ss.add_parser("place"); x.add_argument("file"); x.add_argument("--t", type=float); x.add_argument("--cue")
    x.add_argument("--align", default="start"); x.add_argument("--gain", type=float, default=0.0)
    x.add_argument("--kind", default="impact")
    x = ss.add_parser("clear"); x.add_argument("--cue")

    s = sub.add_parser("retime"); s.add_argument("--from", dest="old", required=True); s.add_argument("--to", dest="new", required=True)
    sub.add_parser("check")
    s = sub.add_parser("render"); s.add_argument("--tag")
    s = sub.add_parser("midi"); s.add_argument("--out", default="work/score.mid")
    s = sub.add_parser("help"); s.add_argument("topic", nargs="?")
    return ap


def run(argv: list[str]) -> object:
    a = build_parser().parse_args(argv)
    if a.cmd == "help":
        return render_help(HELP, CRAFT, a.topic)
    if a.cmd == "init":
        s = Score.init(a.project)
        return {"ok": True, "score": str(s.root / "work/score.vd.json")}
    s = Score.load(a.project)
    if a.cmd == "show":
        d = dict(s.data)
        d["notes"] = {k: {"count": len(v), "span": [v[0]["t"], v[-1]["t"] + v[-1]["d"]] if v else None}
                      for k, v in s.data["notes"].items()}
        return d
    if a.cmd == "cue":
        res = s.import_cues(a.cutlist, a.speech) if a.sub == "import" else s.add_cue(
            a.name, a.t, a.beat, **({"dry": True, "dry_len": a.dry_len} if a.dry else {}))
    elif a.cmd == "section":
        res = s.add_section(a.name, a.start, a.end, key=a.key, palette=a.palette, mood=a.mood)
    elif a.cmd == "part":
        rng = tuple(note_number(x) for x in a.range) if a.range else None
        res = s.add_part(a.name, a.patch, role=a.role, pan=a.pan, gain_db=a.gain, reverb=a.reverb,
                         program=a.program, rng=rng)
    elif a.cmd == "phrase":
        if a.sub == "add":
            res = {"added": s.add_notes(a.part, json.loads(a.notes), section=a.section, offset=a.offset)}
        else:
            res = {"removed": s.clear_notes(a.part, a.section, a.t0, a.t1)}
    elif a.cmd == "chord":
        ps = [x.strip() for x in a.notes.split(",")]
        res = {"added": s.gen_chords(a.part, [(a.t, a.d, ps)], v=a.v, section=a.section)}
    elif a.cmd == "gen":
        if a.sub == "ostinato":
            res = {"added": s.gen_ostinato(a.part, [x.strip() for x in a.pattern.split(",")], a.t0, a.t1, a.step,
                                           a.v, a.accent, a.section)}
        else:
            res = {"changed": s.gen_crescendo(a.part, a.t0, a.t1, a.v0, a.v1)}
    elif a.cmd == "hit":
        if a.sub == "clear":
            before = len(s.data["hits"])
            s.data["hits"] = [h for h in s.data["hits"] if a.cue and h.get("cue") != a.cue]
            res = {"removed": before - len(s.data["hits"])}
        else:
            if a.t is None and not a.cue:
                raise VDError("give --t or --cue")
            t = a.t if a.t is not None else s.cue(a.cue)["t"]
            res = s.add_hit(a.file, t, align=a.align, gain_db=a.gain, cue=a.cue, kind=a.kind)
    elif a.cmd == "retime":
        res = s.retime(a.old, a.new)
    elif a.cmd == "check":
        from cva.vd.check import check
        return check(s)
    elif a.cmd == "render":
        from cva.vd.render import render
        return render(s, tag=a.tag)
    elif a.cmd == "midi":
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(initial_tempo=60)
        for name, notes in s.data["notes"].items():
            inst = pretty_midi.Instrument(program=s.data["parts"][name].get("program", 48), name=name)
            inst.notes = [pretty_midi.Note(velocity=n["v"], pitch=n["p"], start=n["t"], end=n["t"] + n["d"]) for n in notes]
            pm.instruments.append(inst)
        out = s.abspath(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        pm.write(str(out))
        return {"midi": str(out)}
    else:
        raise VDError(f"unknown command {a.cmd}")
    s.save()
    return res


def main(argv: list[str] | None = None) -> int:
    from cva.config import load_env
    load_env()
    try:
        res = run(sys.argv[1:] if argv is None else argv)
    except (VDError, ValueError, KeyError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(res if isinstance(res, str) else json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
