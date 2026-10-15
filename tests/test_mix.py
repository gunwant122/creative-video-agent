import numpy as np
import soundfile as sf

from cva.media.loudness import ebur128
from cva.mix import clean, diagnose, duck, duck_envelope, gain_to, master, sum_stems

SR = 48000


def tone(path, f=220, dur=4.0, db=-20, noise_db=None):
    t = np.arange(int(dur * SR)) / SR
    x = 10 ** (db / 20) * np.sin(2 * np.pi * f * t)
    if noise_db is not None:
        x = x + 10 ** (noise_db / 20) * np.random.default_rng(0).standard_normal(len(t))
    sf.write(str(path), np.stack([x, x], 1), SR, subtype="PCM_24")
    return path


def test_gain_to_target(tmp_path):
    g = gain_to(tone(tmp_path / "a.wav", db=-30), -16)
    assert 10 < g["gain_db"] < 16


def test_clean_runs_and_controls_peaks(tmp_path):
    r = clean(tone(tmp_path / "a.wav", db=-3, noise_db=-45), tmp_path / "c.wav")
    assert r["after"]["true_peak_dbtp"] < r["before"]["true_peak_dbtp"]


def test_duck_depth_is_8db_in_speech(tmp_path):
    m = tone(tmp_path / "m.wav", f=440, dur=6.0, db=-20)
    duck(m, [[2.0, 3.0]], tmp_path / "d.wav")
    x, _ = sf.read(tmp_path / "d.wav")
    rms = lambda s: 20 * np.log10(np.sqrt(np.mean(s ** 2)))
    assert abs(rms(x[int(2.2 * SR):int(2.8 * SR)]) - rms(x[int(0.2 * SR):int(1.0 * SR)]) + 8) < 0.2
    assert abs(rms(x[int(4.5 * SR):int(5.5 * SR)]) - rms(x[int(0.2 * SR):int(1.0 * SR)])) < 0.1  # recovered


def test_envelope_ramps_are_smooth():
    env = duck_envelope(SR * 4, SR, [[1.0, 2.0]])
    assert np.max(np.abs(np.diff(env))) < 1e-3


def test_sum_master_hits_social_target(tmp_path):
    d = tone(tmp_path / "d.wav", f=220, db=-18)
    m = tone(tmp_path / "m.wav", f=330, db=-24)
    sum_stems({"dialogue": (str(d), 0), "music": (str(m), -3)}, tmp_path / "pre.wav")
    r = master(tmp_path / "pre.wav", tmp_path / "master.wav", lufs=-14, tp=-1)
    assert r["pass"], r
    chk = ebur128(tmp_path / "master.wav")
    assert abs(chk["integrated_lufs"] + 14) <= 0.5 and chk["true_peak_dbtp"] <= -1.0


def test_diagnose_finds_driver(tmp_path):
    d = tone(tmp_path / "d.wav", f=220, db=-6)
    m = tone(tmp_path / "m.wav", f=330, db=-26)
    r = diagnose({"dialogue": (str(d), 0), "music": (str(m), 0)})
    assert r["driver"] == "dialogue"
