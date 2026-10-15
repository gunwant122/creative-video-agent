from cva.media import change_spikes, ebur128, levels, probe, sheets, silences, stills_at
from cva.media.transcribe import speech_regions


def test_probe(media_dir):
    p = probe(media_dir / "a.mov")
    assert p["video"]["width"] == 540 and p["video"]["height"] == 960
    assert p["video"]["fps"] == 24
    assert p["audio"]["sample_rate"] == 48000
    assert abs(p["duration"] - 4.0) < 0.05


def test_loudness_differs_between_clips(media_dir):
    a = ebur128(media_dir / "a.mov")["integrated_lufs"]
    b = ebur128(media_dir / "b.mov")["integrated_lufs"]
    assert a is not None and b is not None
    assert 10 < a - b < 14  # 12 dB apart by construction


def test_levels_and_silence(media_dir):
    lv = levels(media_dir / "a.mov")
    assert lv["peak_dbfs"] < -15
    assert silences(media_dir / "a.mov") == []


def test_change_spikes_finds_a_join(tmp_path, media_dir):
    from cva.ff import ffmpeg
    from tests.conftest import make_clip
    make_clip(tmp_path / "red.mov", color="red", dur=2)
    make_clip(tmp_path / "blue.mov", color="blue", dur=2)
    ffmpeg("-i", tmp_path / "red.mov", "-i", tmp_path / "blue.mov", "-filter_complex",
           "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
           tmp_path / "joined.mp4")
    sp = change_spikes(tmp_path / "joined.mp4")
    assert any(abs(s["t"] - 2.0) < 0.1 for s in sp)
    labelled = change_spikes(tmp_path / "joined.mp4", known_cuts=[2.0])
    assert all(s["kind"] == "cut" for s in labelled if abs(s["t"] - 2.0) < 0.1)


def test_sheets_time_map(tmp_path, media_dir):
    meta = sheets(media_dir / "a.mov", tmp_path / "sheets", fps=3, cols=4, rows=2)
    assert len(meta["sheets"]) == 2  # 12 frames / 8 cells
    assert meta["map"][9]["t"] == 3.0 and meta["map"][9]["cell"] == 1


def test_stills_at(tmp_path, media_dir):
    res = stills_at(media_dir / "a.mov", [1.0, 2.0], tmp_path / "stills", fps=24)
    assert len(res) == 2


def test_speech_regions_merge():
    words = [{"word": "a", "start": 0.0, "end": 0.4}, {"word": "b", "start": 0.6, "end": 1.0},
             {"word": "c", "start": 3.0, "end": 3.5}]
    assert speech_regions(words) == [[0.0, 1.0], [3.0, 3.5]]
    assert speech_regions(words, offset=10) == [[10.0, 11.0], [13.0, 13.5]]


def test_style_profile_counts_shots_and_dips(tmp_path):
    from cva.ff import ffmpeg
    from cva.media.profile import style_profile
    from tests.conftest import make_clip
    for i, c in enumerate(["red", "black", "blue", "green"]):
        make_clip(tmp_path / f"{i}.mov", color=c, dur=0.5 if c == "black" else 2)
    ins = sum([["-i", str(tmp_path / f"{i}.mov")] for i in range(4)], [])
    ffmpeg(*ins, "-filter_complex", "".join(f"[{i}:v][{i}:a]" for i in range(4)) + "concat=n=4:v=1:a=1[v][a]",
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(tmp_path / "ref.mp4"))
    p = style_profile(tmp_path / "ref.mp4")
    assert p["dips_to_black"] == 1
    assert p["shots"] >= 3 and p["cuts_per_minute"] > 0
    assert p["loudness"]["integrated_lufs"] is not None
