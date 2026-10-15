"""Synthetic media fixtures. testsrc2 draws a running frame counter; tones stand in for dialogue."""
from __future__ import annotations

from pathlib import Path

import pytest

from cva.ff import ffmpeg


def make_clip(path: Path, *, dur: float = 4.0, fps: int = 24, w: int = 540, h: int = 960, freq: int = 220,
              volume_db: float = -20.0, color: str | None = None) -> Path:
    vsrc = f"color=c={color}:s={w}x{h}:r={fps}:d={dur}" if color else f"testsrc2=s={w}x{h}:r={fps}:d={dur}"
    ffmpeg("-f", "lavfi", "-i", vsrc,
           "-f", "lavfi", "-i", f"sine=f={freq}:d={dur}:sample_rate=48000",
           "-af", f"volume={volume_db}dB,aformat=channel_layouts=stereo",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "1",
           "-c:a", "pcm_s16le", "-shortest", str(path))
    return path


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("media")
    make_clip(d / "a.mov", freq=220, volume_db=-20)
    make_clip(d / "b.mov", freq=330, volume_db=-32)
    make_clip(d / "c.mov", freq=440, volume_db=-26, dur=3.0)
    return d
