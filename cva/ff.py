"""Thin helpers around the ffmpeg / ffprobe binaries."""
from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class FFError(RuntimeError):
    pass


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, return the completed process. stderr tail is included in errors."""
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise FFError(f"{Path(str(args[0])).name} failed ({proc.returncode}):\n{tail}")
    return proc


def ffmpeg(*args, check: bool = True) -> subprocess.CompletedProcess:
    return run([FFMPEG, "-hide_banner", "-nostdin", "-y", *args], check=check)


def ffmpeg_analyse(*args) -> str:
    """Run an analysis pass (output to null) and return stderr, where filters print."""
    proc = run([FFMPEG, "-hide_banner", "-nostdin", "-nostats", *args], check=True)
    return proc.stderr


def ffprobe_json(path: str | Path) -> dict:
    proc = run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(proc.stdout)


@functools.cache
def has_filter(name: str) -> bool:
    proc = run([FFMPEG, "-hide_banner", "-filters"], check=False)
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines() if line.strip())


def ensure_dir(p: str | Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p
