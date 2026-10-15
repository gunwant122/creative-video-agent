"""Agent tools, bound to one project folder.

The editors are exposed the way Voyager exposes its CLIs: one tool per program taking an argument
list (`vv`, `vd`, `cva`), each with `help` pages. They run in-process (no shell), and every path
argument is confined to the project folder.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import subprocess
from pathlib import Path

from langchain_core.tools import tool
from langgraph.types import interrupt

from cva.ff import FFMPEG

MAX_OUT = 12000


class ToolError(ValueError):
    pass


def _confine(root: Path, args: list[str]) -> list[str]:
    """Reject arguments that point outside the project (absolute paths or '..')."""
    for a in args:
        if not isinstance(a, str):
            raise ToolError("all arguments must be strings")
        if a.startswith("-") or a.startswith("{") or a.startswith("["):
            continue
        if a.startswith("/") or a.startswith("~"):
            p = Path(a).expanduser().resolve()
            if root not in p.parents and p != root:
                raise ToolError(f"path outside the project: {a}")
        elif ".." in Path(a).parts:
            if root not in (root / a).resolve().parents:
                raise ToolError(f"path outside the project: {a}")
    return args


def _run_cli(main_run, root: Path, args: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    try:
        args = _confine(root, list(args))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            res = main_run(["-C", str(root), *args])
    except SystemExit:  # argparse usage errors
        return json.dumps({"ok": False, "error": (err.getvalue() or out.getvalue()).strip()[-2000:]})
    except Exception as e:  # tool errors go back to the model, not up the stack
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})
    text = res if isinstance(res, str) else json.dumps(res, indent=1, default=str, ensure_ascii=False)
    if len(text) > MAX_OUT:
        text = text[:MAX_OUT] + f"\n... [truncated {len(text) - MAX_OUT} chars; narrow the query]"
    return text


def _image_block(path: Path, max_side: int) -> dict:
    data = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf",
                           f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease",
                           "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                          capture_output=True, check=True).stdout
    return {"type": "image", "base64": base64.b64encode(data).decode(), "mime_type": "image/jpeg"}


def make_tools(project_root: str | Path) -> dict:
    root = Path(project_root).resolve()

    from cva.cli import run as cva_run
    from cva.vd.cli import run as vd_run
    from cva.vv.cli import run as vv_run

    @tool
    def vv(argv: list[str]) -> str:
        """Headless video editor for this episode (the editable timeline work/episode.vv.json).

        Pass the command line as a list, e.g. ["clip", "add", "v1", "--in", "0.3", "--out", "12.5"].
        Start with ["help", "jobs"] for the command for each editing job, and ["help"] for craft guides.
        Key commands: init, source add/gain, clip add/trim/split/cut-out/rm/move/audio, punch set/key,
        transition set, end, show, cut-list, speech, render [--proxy], deliver --audio, stills.
        """
        return _run_cli(vv_run, root, argv)

    @tool
    def vd(argv: list[str]) -> str:
        """Headless score workstation (the editable score work/score.vd.json, written in picture time).

        Pass the command line as a list, e.g. ["gen", "ostinato", "celli", "--pattern", "D2,A2", ...].
        Start with ["help", "jobs"]; craft guides: ["help", "video-scoring"], ["help", "underscore-dialogue"], etc.
        Key commands: init, cue import/add, section add, part add, phrase add/clear, chord add,
        gen ostinato/crescendo, hit place, retime, check, render, midi.
        """
        return _run_cli(vd_run, root, argv)

    @tool
    def cva(argv: list[str]) -> str:
        """Measure, mix and check media. Pass the command line as a list.

        media: probe, loudness, levels, silences, transcribe <file> --id <source>, scenes, spikes [--cuts],
               profile <reference episode> --save analysis/reference_style.json  (pacing/transitions/LUFS to match),
               watch <file> --mode glitches|listen|review [--start s --duration s] [--question "..."]
                     (a video model watches/listens; glitches mode slows 6x; timestamps approximate - confirm with zoom),
               contour <audio or video> [--every 3]  (short-term LUFS over time: the level map of a stem or mix),
               sheets <file> --out <dir> [--fps 3] [--start s --duration s], zoom <file> --t <s> --out <png>, still.
        mix:   level-takes [--target -16], clean <src> <out>, gain, duck <music> <out> --speech <json>,
               sum <out> --stem name=path[@gain_db] ..., master <src> <out> [--lufs -14 --tp -1], diagnose --stem ...
        qc:    gate <file> [--target social] [--cutlist work/cutlist_vN.json]
        Paths are relative to the project folder.
        """
        return _run_cli(cva_run, root, argv)

    @tool
    def view_images(paths: list[str], max_side: int = 1280) -> list:
        """Look at images (frame sheets, stills, zoom sheets). Use this to actually inspect picture -
        you cannot judge glitches, framing or transitions without looking. Up to 8 images per call;
        pass sheets.json time maps alongside to know which time each cell shows."""
        if len(paths) > 8:
            return [{"type": "text", "text": "At most 8 images per call."}]
        blocks: list = []
        for p in _confine(root, list(paths)):
            f = (root / p).resolve()
            if not f.exists():
                blocks.append({"type": "text", "text": f"missing: {p}"})
                continue
            blocks.append({"type": "text", "text": f"image: {p}"})
            blocks.append(_image_block(f, max_side))
        return blocks

    @tool
    def ask_user(questions: list[dict]) -> str:
        """Ask the user up to 3 questions that the footage cannot answer, and wait for the answers.

        Each question: {"id": "format", "question": "One episode or separate reels?",
                        "options": ["One episode", "Separate reels"], "default": "One episode"}.
        Always offer a default. Ask once, early, after analysis - not repeatedly.
        """
        if not questions:
            return "no questions given"
        answers = interrupt({"type": "questions", "questions": questions[:3]})
        return json.dumps(answers, ensure_ascii=False)

    @tool
    def report_render(version: int, summary: str, qc_passed: bool, cannot_judge: str) -> str:
        """Record a finished version for the user: what changed, whether the QC gate passed, and what
        you could not judge (always: listening). Appends to notes.md and shows it in the UI."""
        notes = root / "notes.md"
        entry = (f"\n## v{version}\n{summary.strip()}\n\nQC gate: {'PASS' if qc_passed else 'FAIL'}\n"
                 f"Not judged by the agent: {cannot_judge.strip()}\n")
        with notes.open("a") as fh:
            fh.write(entry)
        return json.dumps({"ok": True, "notes": "notes.md", "version": version})

    @tool
    def remotion(argv: list[str]) -> str:
        """Run Remotion for the motion-graphics project in work/motion/ (write its files with write_file first:
        package.json, remotion.config.ts, src/index.ts, src/Root.tsx, compositions).

        Allowed: ["install"] (npm install), ["compositions"], ["render", <CompositionId>, <out>, ...flags],
        ["still", <CompositionId>, <out.png>, "--frame", "30"]. Output paths are relative to work/motion/ and must stay
        inside the project, e.g. "../overlays/titles_v2.mov". For overlays render transparent ProRes:
        ["render", "Titles", "../overlays/titles.mov", "--codec=prores", "--prores-profile=4444",
         "--pixel-format=yuva444p10le"], then place it with vv overlay add.
        """
        mdir = root / "work" / "motion"
        if not argv or argv[0] not in ("install", "compositions", "render", "still"):
            return json.dumps({"ok": False, "error": "first argument must be install, compositions, render or still"})
        if not (mdir / "package.json").exists():
            return json.dumps({"ok": False, "error": "no Remotion project: write work/motion/package.json and src/ "
                                                     "first (see the remotion-best-practices skill)"})
        try:
            for a in argv[1:]:
                if not a.startswith("-") and ("/" in a or "." in a):
                    f = (mdir / a).resolve()
                    if root not in f.parents:
                        raise ToolError(f"path outside the project: {a}")
        except ToolError as e:
            return json.dumps({"ok": False, "error": str(e)})
        cmd = ["npm", "install", "--no-audit", "--no-fund"] if argv[0] == "install" else ["npx", "remotion", *argv]
        try:
            proc = subprocess.run(cmd, cwd=mdir, capture_output=True, text=True, timeout=1800)
        except FileNotFoundError:
            return json.dumps({"ok": False, "error": "Node.js (npm/npx) is not installed"})
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": "timed out after 30 min"})
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-30:])
        return json.dumps({"ok": proc.returncode == 0, "exit": proc.returncode, "log": tail[-4000:]})

    return {"vv": vv, "vd": vd, "cva": cva, "view_images": view_images, "ask_user": ask_user,
            "report_render": report_render, "remotion": remotion}
