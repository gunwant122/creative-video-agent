"""cva: measuring, mixing and checking. `cva media ...`, `cva mix ...`, `cva qc ...`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cva")
    ap.add_argument("-C", "--project", default=".")
    sub = ap.add_subparsers(dest="group", required=True)

    m = sub.add_parser("media").add_subparsers(dest="cmd", required=True)
    x = m.add_parser("probe"); x.add_argument("paths", nargs="+")
    x = m.add_parser("loudness"); x.add_argument("paths", nargs="+")
    x = m.add_parser("levels"); x.add_argument("path")
    x = m.add_parser("silences"); x.add_argument("path"); x.add_argument("--noise", type=float, default=-45)
    x = m.add_parser("transcribe"); x.add_argument("path"); x.add_argument("--id"); x.add_argument("--language")
    x = m.add_parser("scenes"); x.add_argument("path")
    x = m.add_parser("spikes"); x.add_argument("path"); x.add_argument("--cuts", help="cut list json to label cuts")
    x = m.add_parser("sheets"); x.add_argument("path"); x.add_argument("--out", required=True)
    x.add_argument("--fps", type=float, default=3); x.add_argument("--start", type=float, default=0.0)
    x.add_argument("--duration", type=float)
    x = m.add_parser("zoom"); x.add_argument("path"); x.add_argument("--t", type=float, required=True)
    x.add_argument("--out", required=True); x.add_argument("--fps", type=float, default=8)
    x = m.add_parser("still"); x.add_argument("path"); x.add_argument("--t", type=float, required=True)
    x.add_argument("--out", required=True)
    x = m.add_parser("profile"); x.add_argument("path"); x.add_argument("--save", help="write JSON here")
    x = m.add_parser("watch"); x.add_argument("path"); x.add_argument("--mode", default="glitches",
                                                                      choices=["glitches", "listen", "review"])
    x.add_argument("--start", type=float, default=0.0); x.add_argument("--duration", type=float)
    x.add_argument("--question"); x.add_argument("--model"); x.add_argument("--slow", type=int, default=6)
    x = m.add_parser("contour"); x.add_argument("path"); x.add_argument("--every", type=float, default=3.0)

    m = sub.add_parser("mix").add_subparsers(dest="cmd", required=True)
    x = m.add_parser("level-takes"); x.add_argument("--target", type=float, default=-16)
    x = m.add_parser("clean"); x.add_argument("src"); x.add_argument("out")
    x.add_argument("--no-denoise", action="store_true"); x.add_argument("--deess", action="store_true")
    x.add_argument("--mud-db", type=float, default=-3); x.add_argument("--presence-db", type=float, default=2)
    x = m.add_parser("gain"); x.add_argument("src"); x.add_argument("out"); x.add_argument("--to-lufs", type=float)
    x.add_argument("--db", type=float)
    x = m.add_parser("duck"); x.add_argument("music"); x.add_argument("out"); x.add_argument("--speech", required=True)
    x.add_argument("--depth", type=float, default=-8)
    x = m.add_parser("sum"); x.add_argument("out"); x.add_argument("--stem", action="append", required=True,
                                                                    help="name=path[@gain_db]")
    x = m.add_parser("master"); x.add_argument("src"); x.add_argument("out")
    x.add_argument("--lufs", type=float, default=-14); x.add_argument("--tp", type=float, default=-1)
    x = m.add_parser("diagnose"); x.add_argument("--stem", action="append", required=True)

    m = sub.add_parser("qc").add_subparsers(dest="cmd", required=True)
    x = m.add_parser("gate"); x.add_argument("path"); x.add_argument("--target", default="social")
    x.add_argument("--cutlist"); x.add_argument("--max-duration", type=float)
    return ap


def _stems(specs: list[str], root: Path) -> dict:
    out = {}
    for s in specs:
        name, rest = s.split("=", 1)
        path, _, g = rest.partition("@")
        out[name] = (str(root / path), float(g) if g else 0.0)
    return out


def run(argv: list[str]) -> object:
    a = build_parser().parse_args(argv)
    root = Path(a.project).resolve()
    P = lambda p: str(Path(p) if Path(p).is_absolute() else root / p)
    if a.group == "media":
        from cva import media
        if a.cmd == "probe":
            return [media.probe(P(p)) for p in a.paths]
        if a.cmd == "loudness":
            return {p: media.ebur128(P(p)) for p in a.paths}
        if a.cmd == "levels":
            return media.levels(P(a.path))
        if a.cmd == "silences":
            return media.silences(P(a.path), noise_db=a.noise)
        if a.cmd == "transcribe":
            from cva.media.transcribe import transcribe
            sid = a.id or Path(a.path).stem
            out = root / "analysis" / f"{sid}.words.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            r = transcribe(P(a.path), out, language=a.language)
            return {"out": str(out), "text": r["text"], "words": len(r["words"]), "language": r["language"]}
        if a.cmd == "scenes":
            return media.scenes(P(a.path))
        if a.cmd == "spikes":
            cuts = json.loads(Path(P(a.cuts)).read_text())["cut_times"] if a.cuts else None
            return media.change_spikes(P(a.path), known_cuts=cuts)
        if a.cmd == "sheets":
            r = media.sheets(P(a.path), P(a.out), fps=a.fps, start=a.start, duration=a.duration)
            return {k: r[k] for k in ("sheets", "fps", "labelled")} | {"time_map": str(Path(P(a.out)) / "sheets.json")}
        if a.cmd == "zoom":
            return media.zoom_sheet(P(a.path), a.t, P(a.out), fps=a.fps)
        if a.cmd == "still":
            return {"still": media.still(P(a.path), a.t, P(a.out))}
        if a.cmd == "watch":
            from cva.gen import Ledger
            from cva.media.watch import watch
            res = watch(P(a.path), mode=a.mode, start=a.start, duration=a.duration, question=a.question,
                        model=a.model, slow=a.slow, ledger=Ledger(root))
            out = root / "analysis" / f"watch_{a.mode}_{Path(a.path).stem}_{int(a.start)}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
            return {**res, "saved": str(out.relative_to(root))}
        if a.cmd == "contour":
            from cva.media.watch import contour
            return contour(P(a.path), every=a.every)
        if a.cmd == "profile":
            from cva.media.profile import style_profile
            prof = style_profile(P(a.path))
            if a.save:
                Path(P(a.save)).parent.mkdir(parents=True, exist_ok=True)
                Path(P(a.save)).write_text(json.dumps(prof, indent=1))
            return prof
    if a.group == "mix":
        from cva import mix
        if a.cmd == "level-takes":
            from cva.vv.project import Project
            return mix.level_takes(Project.load(root), a.target)
        if a.cmd == "clean":
            return mix.clean(P(a.src), P(a.out), denoise=not a.no_denoise, deess=a.deess, mud_db=a.mud_db,
                             presence_db=a.presence_db)
        if a.cmd == "gain":
            g = a.db if a.db is not None else mix.gain_to(P(a.src), a.to_lufs)["gain_db"]
            return {"out": mix.apply_gain(P(a.src), P(a.out), g), "gain_db": g}
        if a.cmd == "duck":
            return mix.duck(P(a.music), P(a.speech), P(a.out), depth_db=a.depth)
        if a.cmd == "sum":
            return mix.sum_stems(_stems(a.stem, root), P(a.out))
        if a.cmd == "master":
            return mix.master(P(a.src), P(a.out), lufs=a.lufs, tp=a.tp)
        if a.cmd == "diagnose":
            return mix.diagnose(_stems(a.stem, root))
    if a.group == "qc":
        from cva.qc import gate
        cl = json.loads(Path(P(a.cutlist)).read_text()) if a.cutlist else {}
        return gate(P(a.path), target=a.target, expected_duration=cl.get("duration"),
                    allowed_black=cl.get("black_spans"), max_duration=a.max_duration)
    raise SystemExit("unknown command")


def main(argv: list[str] | None = None) -> int:
    from cva.config import load_env
    load_env()
    try:
        res = run(sys.argv[1:] if argv is None else argv)
    except Exception as e:  # report as JSON so agents can read failures
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps(res, indent=1, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
