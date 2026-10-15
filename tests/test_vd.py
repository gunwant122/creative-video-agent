import json
from pathlib import Path

import pytest

import numpy as np
import soundfile as sf

from cva.vd.check import check
from cva.vd.render import render, sfizz_bin
from cva.vd.score import Score, TimeMap


def cutlist(clips):
    """clips: [(id, src, src_in, src_out)] laid end to end."""
    out, t = [], 0.0
    for cid, src, a, b in clips:
        out.append({"clip": cid, "src": src, "start": t, "end": t + (b - a), "src_in": a, "src_out": b,
                    "transition_in": {"type": "cut", "frames": 0}})
        t += b - a
    return {"duration": t, "fps": 24, "clips": out, "cut_times": [c["start"] for c in out[1:]], "black_spans": []}


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def test_timemap_follows_source_after_trim():
    old = cutlist([("c1", "a", 0, 10), ("c2", "b", 0, 10)])
    new = cutlist([("c1", "a", 0, 8), ("c2", "b", 1, 10)])      # A trimmed by 2 s, B head by 1 s
    tm = TimeMap(old, new)
    assert abs(tm(10.0) - 8.0) < 1e-6        # old cut -> new cut
    assert abs(tm(15.0) - 12.0) < 1e-6       # inside B: source 5 s -> new 8 + 4
    assert abs(tm(4.0) - 4.0) < 1e-6         # inside A, untouched


def test_timemap_compresses_removed_span():
    old = cutlist([("c1", "a", 0, 10)])
    new = cutlist([("c1", "a", 0, 4), ("c9", "a", 6, 10)])      # 2 s pause cut out
    tm = TimeMap(old, new)
    assert abs(tm(7.0) - 5.0) < 1e-6
    assert 3.99 <= tm(5.0) <= 4.01           # inside the removed span collapses to the join


def test_retime_moves_hits_onto_new_cuts(tmp_path):
    s = Score.init(tmp_path)
    write(tmp_path / "work/cl1.json", cutlist([("c1", "a", 0, 10), ("c2", "b", 0, 10)]))
    write(tmp_path / "work/cl2.json", cutlist([("c1", "a", 0, 8.5), ("c2", "b", 0, 10)]))
    s.import_cues("work/cl1.json")
    s.add_part("celli", role="bass")
    s.add_notes("celli", [{"p": "D2", "t": 9.0, "d": 1.0, "v": 70}, {"p": "A2", "t": 12.0, "d": 2.0, "v": 70}])
    s.add_hit("hit.wav", 10.0, cue="cut:c2")
    s.add_hit("riser.wav", 10.0, align="end", cue="cut:c2", kind="riser")
    r = s.retime("work/cl1.json", "work/cl2.json")
    assert r["hits_snapped_to_cues"] == 1
    assert [round(h["t"], 3) for h in s.data["hits"]] == [8.5, 8.5]
    assert abs(s.data["notes"]["celli"][1]["t"] - 10.5) < 1e-3


def test_check_flags_voice_clash_range_and_sync(tmp_path):
    s = Score.init(tmp_path)
    write(tmp_path / "work/cl.json", cutlist([("c1", "a", 0, 10), ("c2", "b", 0, 10)]))
    write(tmp_path / "work/sp.json", {"regions": [[2.0, 4.0]]})
    s.import_cues("work/cl.json", "work/sp.json")
    s.add_part("violins", role="melody")
    s.add_notes("violins", [{"p": "D5", "t": 2.5, "d": 1, "v": 90},      # loud, voice range, under speech
                            {"p": "C2", "t": 6.0, "d": 1, "v": 50}])     # below violin range
    s.add_hit("boom.wav", 10.05, cue="cut:c2")                           # 50 ms late
    r = check(s)
    kinds = {i["type"] for i in r["issues"]}
    assert {"voice_clash", "range", "hit_sync"} <= kinds


def test_render_preview_places_hit_on_cue(tmp_path):
    s = Score.init(tmp_path)
    write(tmp_path / "work/cl.json", cutlist([("c1", "a", 0, 2), ("c2", "b", 0, 2)]))
    s.import_cues("work/cl.json")
    s.add_part("pad", role="pad")
    s.gen_chords("pad", [(0.0, 3.0, ["D3", "A3", "F4"])], v=40)
    click = np.zeros((4800, 2)); click[0] = 0.9
    sf.write(tmp_path / "click.wav", click, 48000)
    s.add_hit("click.wav", s.cue("cut:c2")["t"], cue="cut:c2")
    s.data["parts"]["pad"]["reverb"] = 0.0
    rec = render(s)
    assert "warning" in rec                                   # preview synth is flagged
    hits, _ = sf.read(tmp_path / rec["stems"]["hits"])
    assert int(np.argmax(np.abs(hits[:, 0]))) == 2 * 48000
    music, sr = sf.read(tmp_path / rec["music"])
    assert len(music) == 4 * 48000 and np.max(np.abs(music)) <= 10 ** (-3 / 20) + 1e-3


LIBS = Path(__file__).resolve().parent.parent / "assets" / "libs" / "VSCO-2-CE"


@pytest.mark.skipif(not (sfizz_bin() and (LIBS / "Timpani.sfz").exists() and (LIBS / "CelloEnsSusVib.sfz").exists()),
                    reason="needs sfizz_render and VSCO instruments (scripts/fetch_instruments.py)")
def test_real_sampled_render(tmp_path):
    (tmp_path / "assets").symlink_to(LIBS.parent.parent)
    s = Score.init(tmp_path)
    write(tmp_path / "work/cl.json", cutlist([("c1", "a", 0, 4), ("c2", "b", 0, 4)]))
    s.import_cues("work/cl.json")
    s.add_part("celli", "assets/libs/VSCO-2-CE/CelloEnsSusVib.sfz", role="bass")
    s.add_part("timp", "assets/libs/VSCO-2-CE/Timpani.sfz", role="perc", reverb=0.0)
    assert s.data["parts"]["celli"]["mapped"] == [36, 77]
    s.gen_chords("celli", [(0.0, 4.0, ["D2", "A2"])], v=60)
    s.add_notes("timp", [{"p": "D2", "t": 4.0, "d": 1.0, "v": 110}])
    assert check(s)["ok"]
    rec = render(s)
    assert rec["engines"] == {"celli": "sfizz", "timp": "sfizz"} and "warning" not in rec
    x, sr = sf.read(tmp_path / rec["stems"]["timp"])
    e = np.abs(x).max(axis=1)
    assert abs(np.argmax(e > 0.1 * e.max()) / sr - 4.0) < 0.02          # the hit lands on the cut
    assert rec["limited_by"] == "peak" or abs(rec["loudness_lufs"] + 20) < 0.6
