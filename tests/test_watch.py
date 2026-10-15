import json

from cva.media.watch import contour, watch
from tests.conftest import make_clip


class FakeRaw:
    def __init__(self, payload):
        self.headers = {"x-litellm-response-cost": "0.002"}
        self._p = payload

    def parse(self):
        p = self._p

        class M:
            content = p

        class C:
            message = M()

        class R:
            choices = [C()]
        return R()


class FakeClient:
    def __init__(self, payloads):
        self.sent, self.payloads = [], list(payloads)
        self.chat = self
        self.completions = self
        self.with_raw_response = self

    def create(self, model, messages):
        self.sent.append((model, messages))
        return FakeRaw(self.payloads.pop(0))


def test_glitch_times_map_back_through_slowdown_and_chunks(tmp_path):
    clip = make_clip(tmp_path / "a.mov", dur=4.0, w=270, h=480)
    c = FakeClient([json.dumps({"events": [{"t": 6.0, "end": 7.2, "kind": "morph", "what": "hand", "severity": "high"}],
                                "notes": "one fault"}),
                    "```json\n" + json.dumps({"events": [{"t": 3.0, "kind": "flash", "what": "x", "severity": "low"}],
                                             "notes": ""}) + "\n```"])
    r = watch(clip, mode="glitches", chunk=2.0, slow=6, client=c, model="m")
    assert [(e["t"], e["end"]) for e in r["events"]] == [(1.0, 1.2), (2.5, 2.5)]   # 6/6, 2 + 3/6
    assert r["cost_usd"] == 0.004 and len(c.sent) == 2
    assert c.sent[0][1][0]["content"][1]["type"] == "file"


def test_listen_mode_keeps_real_time_and_survives_bad_json(tmp_path):
    clip = make_clip(tmp_path / "a.mov", dur=3.0, w=270, h=480)
    c = FakeClient(["music too loud from 1.5 s, not json"])
    r = watch(clip, mode="listen", client=c, model="m")
    assert r["events"] == [] and "music too loud" in r["notes"][0]


def test_contour_tracks_level(tmp_path):
    clip = make_clip(tmp_path / "a.mov", dur=8.0, volume_db=-20)
    pts = contour(clip, every=2)
    vals = [p["lufs_s"] for p in pts if p["lufs_s"] is not None]
    assert len(vals) >= 2 and max(vals) - min(vals) < 1.5
