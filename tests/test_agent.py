"""Agent wiring with a scripted model: interrupts, real tools, subagent handoff, images, cost gate."""
import io
import json
import shutil

import numpy as np
import pytest
import soundfile as sf
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from cva.agent.graph import build_agent
from tests.conftest import make_clip


class Scripted(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def call(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}])


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    make_clip(tmp_path / "src" / "v1.mov", w=270, h=480, freq=220, volume_db=-22)
    make_clip(tmp_path / "src" / "v2.mov", w=270, h=480, freq=330, volume_db=-30)
    (tmp_path / "brief.md").write_text("# House style\n- Always hard cuts.\n")
    return tmp_path


def tool_msgs(state):
    return [m for m in state["messages"] if isinstance(m, ToolMessage)]


def test_director_end_to_end(project):
    script = iter([
        call("ask_user", {"questions": [{"id": "format", "question": "One episode or reels?",
                                         "options": ["One episode", "Reels"], "default": "One episode"}]}, 1),
        call("task", {"subagent_type": "analyst", "description": "Probe src/v1.mov and report specs."}, 2),
        call("cva", {"argv": ["media", "probe", "src/v1.mov"]}, 3),          # analyst's tool call
        AIMessage(content="v1: 270x480 24fps, 4.0 s."),                       # analyst's answer
        call("vv", {"argv": ["init", "--width", "270", "--height", "480", "--fps", "24"]}, 4),
        call("vv", {"argv": ["source", "add", "src/v1.mov"]}, 5),
        call("vv", {"argv": ["source", "add", "src/v2.mov"]}, 6),
        call("cva", {"argv": ["mix", "level-takes", "--target", "-16"]}, 7),
        call("vv", {"argv": ["clip", "add", "v1", "--in", "0.25", "--out", "3.5"]}, 8),
        call("vv", {"argv": ["clip", "add", "v2", "--in", "0.5", "--out", "3.75"]}, 9),
        call("vv", {"argv": ["render"]}, 10),
        call("cva", {"argv": ["mix", "master", "work/dialogue_v1.wav", "work/master_v1.wav"]}, 11),
        call("vv", {"argv": ["deliver", "--audio", "work/master_v1.wav"]}, 12),
        call("vv", {"argv": ["stills"]}, 13),
        call("view_images", {"paths": ["analysis/stills_v1/cut_0003.250_b.jpg"]}, 14),
        call("report_render", {"version": 1, "summary": "Assembly, levelled, mastered.", "qc_passed": True,
                               "cannot_judge": "listening"}, 15),
        AIMessage(content="v1 is ready."),
    ])
    model = Scripted(messages=script)
    agent = build_agent(project, model=model, subagent_model=model, checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 100}
    out = agent.invoke({"messages": [{"role": "user", "content": "Cut these into an episode."}]}, cfg)
    assert out["__interrupt__"][0].value["type"] == "questions"
    out = agent.invoke(Command(resume={"format": "One episode"}), cfg)

    tm = tool_msgs(out)
    by_name = {m.name: m for m in tm}
    assert "One episode" in by_name["ask_user"].content
    assert "270x480" in by_name["task"].content or "270" in by_name["task"].content
    deliver = json.loads([m for m in tm if m.name == "vv" and '"pass"' in str(m.content)][-1].content)
    assert deliver["pass"], deliver["summary"]
    img = by_name["view_images"].content
    assert any(isinstance(b, dict) and b.get("type") == "image" for b in img)
    assert (project / "renders" / "v1.mp4").exists()
    assert "QC gate: PASS" in (project / "notes.md").read_text()
    assert out["messages"][-1].content == "v1 is ready."


def test_tools_refuse_paths_outside_project(project):
    from cva.agent.tools import make_tools
    t = make_tools(project)
    res = json.loads(t["cva"].invoke({"argv": ["media", "probe", "/etc/hosts"]}))
    assert res["ok"] is False and "outside the project" in res["error"]
    res = json.loads(t["vv"].invoke({"argv": ["source", "add", "../x.mp4"]}))
    assert res["ok"] is False


class FakeSFX:
    def __init__(self):
        buf = io.BytesIO()
        sf.write(buf, np.zeros((4800, 2)), 48000, format="WAV")
        self.wav = buf.getvalue()

    def convert(self, **kw):
        self.kw = kw
        return iter([self.wav])


class FakeEL:
    def __init__(self):
        self.text_to_sound_effects = FakeSFX()


@pytest.mark.parametrize("approved", [True, False])
def test_generator_cost_gate(project, approved):
    fake = FakeEL()
    script = iter([
        call("task", {"subagent_type": "generator", "description": "Make a deep boom for the scene change."}, 1),
        call("el_sound_effect", {"text": "deep cinematic boom", "out_name": "boom", "duration_s": 2.0}, 2),
        AIMessage(content="done"),
        AIMessage(content="ok"),
    ])
    model = Scripted(messages=script)
    agent = build_agent(project, model=model, subagent_model=model, checkpointer=InMemorySaver(),
                        gen_kwargs={"el_client_factory": lambda: fake})
    cfg = {"configurable": {"thread_id": f"g{approved}"}, "recursion_limit": 50}
    out = agent.invoke({"messages": [{"role": "user", "content": "add a boom"}]}, cfg)
    intr = out["__interrupt__"][0].value
    assert intr["type"] == "cost_approval" and intr["service"] == "elevenlabs"
    agent.invoke(Command(resume={"approved": approved}), cfg)
    ledger = json.loads((project / "assets/generated/ledger.json").read_text())
    assert ledger[-1]["status"] == ("done" if approved else "declined")
    assert (project / "assets/generated/boom.wav").exists() is approved
    if not approved:
        assert not hasattr(fake.text_to_sound_effects, "kw")   # nothing was called, nothing spent


def test_remotion_tool_guards(project):
    from cva.agent.tools import make_tools
    t = make_tools(project)
    assert "no Remotion project" in t["remotion"].invoke({"argv": ["compositions"]})
    assert "first argument" in t["remotion"].invoke({"argv": ["exec", "rm"]})
    (project / "work" / "motion").mkdir(parents=True)
    (project / "work" / "motion" / "package.json").write_text("{}")
    assert "outside the project" in t["remotion"].invoke({"argv": ["render", "X", "../../../out.mov"]})


def test_ledger_survives_parallel_writers(tmp_path):
    import threading
    from cva.gen import Ledger
    led = Ledger(tmp_path)
    ths = [threading.Thread(target=lambda i=i: [led.add({"status": "done", "estimate_usd": 0.01, "i": i, "k": k})
                                                for k in range(20)]) for i in range(9)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert len(led.entries()) == 180 and led.spent_usd() == 1.8


class FakeFal:
    def __init__(self):
        self.calls = []

    def upload_file(self, path):
        return f"https://fal.media/{path.name}"

    def subscribe(self, endpoint, arguments):
        self.calls.append((endpoint, arguments))
        return {"text": "Tell me everything.", "language_code": "eng",
                "words": [{"text": "Tell", "start": 1.0, "end": 1.2, "type": "word"},
                          {"text": " ", "start": 1.2, "end": 1.25, "type": "spacing"},
                          {"text": "me", "start": 1.25, "end": 1.4, "type": "word"}]}


def test_transcribe_paid_is_one_approval_for_all_clips(project):
    fal = FakeFal()
    script = iter([
        call("task", {"subagent_type": "generator", "description": "transcribe all clips"}, 1),
        call("transcribe_paid", {"sources": ["src/v1.mov", "src/v2.mov"]}, 2),
        AIMessage(content="done"), AIMessage(content="ok")])
    model = Scripted(messages=script)
    agent = build_agent(project, model=model, subagent_model=model, checkpointer=InMemorySaver(),
                        gen_kwargs={"fal_module": fal})
    cfg = {"configurable": {"thread_id": "tp"}, "recursion_limit": 50}
    out = agent.invoke({"messages": [{"role": "user", "content": "transcribe"}]}, cfg)
    assert len(out["__interrupt__"]) == 1                       # one card for both clips
    v = out["__interrupt__"][0].value
    assert v["details"]["files"] == 2 and fal.calls == []
    agent.invoke(Command(resume={"approved": True}), cfg)
    assert len(fal.calls) == 2 and fal.calls[0][0] == "fal-ai/elevenlabs/speech-to-text/scribe-v2"
    w = json.loads((project / "analysis" / "v1.words.json").read_text())
    assert [x["word"] for x in w["words"]] == ["Tell", "me"] and w["backend"] == "fal-scribe-v2"
    assert (project / "analysis" / "v2.words.json").exists()
