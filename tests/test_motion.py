import json
import subprocess

import numpy as np
import pytest

from cva.ff import FFMPEG, ffmpeg
from cva.motion import add_captions, add_title, chunk_captions, draw_cards
from cva.vv.project import Project
from cva.vv.render import render


def gray_clip(path, dur=3.0, w=270, h=480):
    ffmpeg("-f", "lavfi", "-i", f"color=c=0x404040:s={w}x{h}:r=24:d={dur}",
           "-f", "lavfi", "-i", f"sine=f=220:d={dur}:sample_rate=48000", "-af", "aformat=channel_layouts=stereo",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(path))


def frame_max(path, t, w=270, h=480):
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-vf", "extractplanes=y", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return int(np.frombuffer(raw, np.uint8).reshape(h, w).max())


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "src").mkdir()
    gray_clip(tmp_path / "src" / "a.mov")
    p = Project.init(tmp_path, width=270, height=480, fps=24)
    p.add_source("src/a.mov")
    p.add_clip("a")
    return p


def test_chunking_breaks_on_pauses_and_length():
    words = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate("She was taken from her crib.".split())]
    words += [{"word": "Tell", "start": 4.0, "end": 4.3}, {"word": "me.", "start": 4.35, "end": 4.6}]
    cards = chunk_captions(words)
    assert [c["text"] for c in cards] == ["She was taken from her crib.", "Tell me."]
    assert cards[0]["end"] < cards[1]["start"]
    assert all(c["end"] - c["start"] >= 0.8 - 1e-9 for c in cards)


def test_title_overlay_composites_only_in_its_window(proj):
    add_title(proj, "EPISODE 4", 1.0, 2.0)
    r = render(proj)
    pic = proj.root / r["picture"]
    assert frame_max(pic, 0.5) < 80          # plain gray before
    assert frame_max(pic, 1.5) > 200         # white title on screen
    assert frame_max(pic, 2.5) < 80          # gone after


def test_captions_from_timeline_words(proj):
    (proj.root / "analysis").mkdir()
    words = [{"word": "Hello", "start": 0.5, "end": 0.9}, {"word": "there.", "start": 0.95, "end": 1.3},
             {"word": "Again", "start": 2.2, "end": 2.6}]
    (proj.root / "analysis" / "a.words.json").write_text(json.dumps({"words": words}))
    render(proj, proxy=True)
    res = add_captions(proj)
    assert res["cards"] == 2
    ovs = [o for o in proj.data["overlays"] if o["tag"] == "captions"]
    assert [round(o["start"], 2) for o in ovs] == [0.5, 2.2]
    res2 = add_captions(proj)                # re-running replaces, not duplicates
    assert len([o for o in proj.data["overlays"] if o["tag"] == "captions"]) == res2["cards"] == 2
    r = render(proj)
    assert frame_max(proj.root / r["picture"], 1.0) > 200


def test_devanagari_card_is_shaped(tmp_path):
    d = draw_cards([{"text": "मैं हर घर जला दूँगा", "out": str(tmp_path / "hi.png"), "size": 48}])[0]
    assert d["font"] != "default"
    if d["shaping"] != "raqm":
        pytest.skip("libraqm not installed: Devanagari renders without complex shaping")
    assert (tmp_path / "hi.png").exists() and d["w"] > 100
