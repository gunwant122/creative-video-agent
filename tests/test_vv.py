"""vv timeline tests. Sources encode their frame number in brightness (luma = 3*N), so we can
read back exactly which source frame landed on each output frame."""
import subprocess

import numpy as np
import pytest
import soundfile as sf

from cva.ff import FFMPEG, ffmpeg
from cva.vv.layout import cut_list, layout
from cva.vv.project import Project, VVError
from cva.vv.render import render

F = 24


def counter_clip(path, dur=3.0, freq=220, vol=-20):
    ffmpeg("-f", "lavfi", "-i", f"color=c=black:s=64x64:r={F}:d={dur},geq=lum='16+3*N':cb=128:cr=128",
           "-f", "lavfi", "-i", f"sine=f={freq}:d={dur}:sample_rate=48000",
           "-af", f"volume={vol}dB,aformat=channel_layouts=stereo",
           "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", "-g", "1", "-c:a", "pcm_s16le", "-shortest", str(path))


def frame_ids(path):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf", "extractplanes=y", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 64 * 64)
    return [int(round((m - 16) / 3)) for m in fr[:, 16 * 64:48 * 64].mean(axis=1)]


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "src").mkdir()
    counter_clip(tmp_path / "src" / "a.mov", freq=220, vol=-20)
    counter_clip(tmp_path / "src" / "b.mov", freq=330, vol=-30)
    p = Project.init(tmp_path, width=64, height=64, fps=F)
    p.add_source("src/a.mov")
    p.add_source("src/b.mov")
    return p


def test_frame_exact_cuts(proj):
    proj.add_clip("a", in_s=10 / F, out_s=20 / F)
    proj.add_clip("b", in_s=5 / F, out_s=15 / F)
    r = render(proj)
    ids = frame_ids(proj.root / r["picture"])
    assert ids == list(range(10, 20)) + list(range(5, 15))
    assert r["cut_times"] == [round(10 / F, 3)]


def test_dissolve_center_keeps_cut_point_and_length(proj):
    proj.add_clip("a", in_s=10 / F, out_s=30 / F)
    c = proj.add_clip("b", in_s=10 / F, out_s=30 / F)
    proj.set_transition(c["id"], "dissolve", 6)
    lay = layout(proj)
    assert lay["items"][1]["tin"]["align"] == "center"
    assert lay["items"][0]["post"] == 3 and lay["items"][1]["pre"] == 3
    ids = frame_ids(proj.root / render(proj)["picture"])
    assert len(ids) == 40
    assert ids[:17] == list(range(10, 27))       # untouched A before the dissolve
    assert ids[23:] == list(range(13, 30))       # untouched B after it


def test_dissolve_refused_without_handles(proj):
    proj.add_clip("a")                           # to the very end of a
    c = proj.add_clip("b")                       # from the very start of b
    proj.set_transition(c["id"], "dissolve", 8)
    with pytest.raises(VVError, match="does not fit"):
        layout(proj)


def test_dissolve_auto_aligns_to_spare_side(proj):
    proj.add_clip("a")                           # no handle after a
    c = proj.add_clip("b", in_s=12 / F, out_s=40 / F)
    proj.set_transition(c["id"], "dissolve", 8)
    assert layout(proj)["items"][1]["tin"]["align"] == "pre"


def test_dip_to_black(proj):
    proj.add_clip("a", in_s=0, out_s=24 / F)
    c = proj.add_clip("b", in_s=0, out_s=24 / F)
    proj.set_transition(c["id"], "dip", 12)
    r = render(proj)
    assert r["black_spans"] == [[round(18 / F, 3), round(30 / F, 3)]]
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(proj.root / r["picture"]), "-vf", "format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 64 * 64).mean(axis=1)
    assert fr[23] < 20 and fr[24] < 20          # black around the cut


def test_split_and_cut_out_share_take_gain(proj):
    c = proj.add_clip("a")
    proj.set_take_gain("a", 6.0)
    first, second = proj.cut_out(c["id"], 1.0, 1.5)
    lay = layout(proj)
    assert [x["gain_db"] for x in lay["audio"]] == [6.0, 6.0]
    assert lay["items"][1]["in"] == 36
    assert abs(lay["duration"] - (72 - 12) / F) < 1e-9


def test_l_cut_audio_runs_past_picture(proj):
    a = proj.add_clip("a", in_s=0, out_s=1.0)
    proj.add_clip("b", in_s=0, out_s=1.0)
    proj.set_audio(a["id"], tail=0.5)
    proj.set_audio(proj.data["clips"][1]["id"], lead=-0.5)   # b's own audio starts 0.5 s late
    lay = layout(proj)
    aa, bb = lay["audio"]
    assert aa["src_end"] == 1.5 and aa["tl_start"] == 0.0
    assert bb["tl_start"] == 1.5 and bb["src_start"] == 0.5


def test_dialogue_stem_levels_and_length(proj):
    proj.add_clip("a", in_s=0, out_s=1.0)
    proj.add_clip("b", in_s=0, out_s=1.0)
    r = render(proj)
    x, sr = sf.read(proj.root / r["dialogue"])
    assert sr == 48000 and len(x) == 96000
    rms = lambda s: 20 * np.log10(np.sqrt(np.mean(s ** 2)))
    assert 8 < rms(x[10000:40000]) - rms(x[58000:88000]) < 12   # a is 10 dB louder than b


def test_static_punch_keeps_profile_size(proj):
    c = proj.add_clip("a", in_s=0, out_s=1.0)
    proj.set_punch(c["id"], 1.25, x=0.6, y=0.4)
    r = render(proj)
    from cva.media import probe
    v = probe(proj.root / r["picture"])["video"]
    assert (v["width"], v["height"]) == (64, 64)


def test_animated_punch_renders(proj):
    c = proj.add_clip("a", in_s=0, out_s=1.0)
    proj.set_punch(c["id"], 1.0, t=0.0)
    proj.set_punch(c["id"], 1.3, t=0.8)
    r = render(proj)
    assert len(frame_ids(proj.root / r["picture"])) == 24


def test_cut_list_and_versions(proj):
    proj.add_clip("a", in_s=0, out_s=1.0)
    r1 = render(proj, proxy=True)
    proj.add_clip("b", in_s=0, out_s=0.5)
    r2 = render(proj)
    assert (r1["v"], r2["v"]) == (1, 2)
    cl = cut_list(proj)
    assert cl["duration"] == 1.5 and cl["cut_times"] == [1.0]
    assert (proj.root / "work/history/episode_v1.vv.json").exists()


def test_cover_keeps_words_continuous_and_in_sync(proj):
    c = proj.add_clip("a", in_s=0, out_s=2.0)
    first, cut, second = proj.cover(c["id"], 0.5, 1.0, "b", 1.0)
    lay = layout(proj)
    assert abs(lay["duration"] - 2.0) < 1e-9                       # same length: cutaway replaces the span
    a1, a2 = lay["audio"]                                          # cutaway is muted
    assert a1["src_start"] == 0.0 and abs(a1["src_end"] - 1.0) < 1e-6   # a's audio runs to the glitch end
    assert abs(a2["tl_start"] - 1.0) < 1e-6 and abs(a2["src_start"] - 1.0) < 1e-6  # then continues in sync
    ids = frame_ids(proj.root / render(proj)["picture"])
    assert ids[:12] == list(range(0, 12)) and ids[12:24] == list(range(24, 36))  # b's frames 24..35 cover
    assert ids[24:] == list(range(24, 48))
