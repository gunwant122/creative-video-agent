#!/usr/bin/env python3
"""Fetch only the VSCO 2 CE instruments you need (SFZ + the samples it references), not the 3 GB library.

    python scripts/fetch_instruments.py --list
    python scripts/fetch_instruments.py core --dry-run
    python scripts/fetch_instruments.py Harp CelloEnsSusVib TubularBells
"""
from __future__ import annotations

import argparse
import http.client
import time
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO, BRANCH = "sgossner/VSCO-2-CE", "SFZ"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
DEST = Path(__file__).resolve().parent.parent / "assets" / "libs" / "VSCO-2-CE"

# a cinematic chamber palette: strings (sustain, spiccato, pizz, tremolo), harp, horn, timpani, bells
SETS = {
    "core": ["ViolinEnsSusVib", "ViolaEnsSusVib", "CelloEnsSusVib", "ContrabassSusVB", "CelloEnsSpic",
             "ViolinEnsTrem", "CelloEnsPizz", "Harp", "FHornSus", "Timpani", "TimpaniRolls", "TubularBells"],
    "minimal": ["CelloEnsSusVib", "ViolinEnsSusVib", "Harp", "Timpani"],
}


def get(url: str, tries: int = 5) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except (OSError, http.client.HTTPException) as e:
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} ({type(e).__name__})", file=sys.stderr)
            time.sleep(2 ** i)
    raise RuntimeError("unreachable")


def tree() -> dict[str, int]:
    data = json.loads(get(f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"))
    return {x["path"]: x.get("size", 0) for x in data["tree"] if x["type"] == "blob"}


def samples_of(sfz_text: str) -> list[str]:
    default = ""
    out = []
    for m in re.finditer(r"(default_path|sample)=(.+?)(?=\s+\w+=|\s*<|\s*$)", sfz_text, re.M):
        key, val = m.group(1), m.group(2).strip().replace("\\", "/")
        if key == "default_path":
            default = val
        else:
            out.append(str(Path(default) / val) if default else val)
    return sorted(set(out))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="instrument names (without .sfz) or a set: " + ", ".join(SETS))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    files = tree()
    if a.list or not a.names:
        print("\n".join(sorted(p[:-4] for p in files if p.endswith(".sfz"))))
        print("\nsets:", {k: len(v) for k, v in SETS.items()})
        return 0
    names = [n for x in a.names for n in SETS.get(x, [x])]
    total, plan = 0, []
    for n in names:
        sfz = f"{n}.sfz"
        if sfz not in files:
            print(f"unknown instrument {n}", file=sys.stderr)
            return 1
        text = get(RAW + urllib.parse.quote(sfz)).decode("utf-8", "replace")
        smp = [s for s in samples_of(text) if s in files]
        missing = [s for s in samples_of(text) if s not in files]
        size = sum(files[s] for s in smp)
        total += size
        plan.append((sfz, text, smp))
        print(f"{n:24s} {len(smp):4d} samples {size / 1e6:7.1f} MB" + (f"  ({len(missing)} unresolved)" if missing else ""))
    print(f"total {total / 1e6:.1f} MB -> {DEST}")
    if a.dry_run:
        return 0
    for sfz, text, smp in plan:
        (DEST / sfz).parent.mkdir(parents=True, exist_ok=True)
        (DEST / sfz).write_text(text)
        for s in smp:
            dst = DEST / s
            if dst.exists() and dst.stat().st_size == files[s]:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(get(RAW + urllib.parse.quote(s)))
        print(f"fetched {sfz}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
