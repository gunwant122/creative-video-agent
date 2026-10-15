import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from cva.agent.graph import build_agent
from cva.server.app import create_app
from tests.conftest import make_clip
from tests.test_agent import Scripted, call


def events(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def test_project_flow_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("CVA_PROJECTS", str(tmp_path))
    script = iter([
        call("ask_user", {"questions": [{"id": "captions", "question": "Captions?", "options": ["No", "Yes"],
                                         "default": "No"}]}, 1),
        call("write_todos", {"todos": [{"content": "Analyse clips", "status": "in_progress"},
                                       {"content": "Assemble v1", "status": "pending"}]}, 2),
        call("vv", {"argv": ["init", "--width", "270", "--height", "480"]}, 3),
        call("vv", {"argv": ["source", "add", "src/v1.mov"]}, 4),
        call("vv", {"argv": ["clip", "add", "v1", "--in", "0.2", "--out", "3.0"]}, 5),
        call("vv", {"argv": ["render", "--proxy"]}, 6),
        AIMessage(content="Proxy v1 is up for review."),
    ])
    model = Scripted(messages=script)
    app = create_app(build=lambda root, checkpointer: build_agent(root, model=model, subagent_model=model,
                                                                   checkpointer=checkpointer))
    c = TestClient(app)
    assert c.post("/api/projects", json={"name": "ep1"}).status_code == 200
    clip = make_clip(tmp_path / "v1.mov", w=270, h=480)
    r = c.post("/api/projects/ep1/upload", files=[("files", ("v1.mov", clip.read_bytes(), "video/quicktime"))])
    assert r.json()["saved"] == ["v1.mov"]

    ev = events(c.post("/api/projects/ep1/chat", json={"message": "make an episode"}))
    assert ev[-1] == {"type": "done", "waiting": True}
    assert any(e["type"] == "interrupt" and e["value"]["type"] == "questions" for e in ev)

    ev = events(c.post("/api/projects/ep1/resume", json={"value": {"captions": "No"}}))
    kinds = [e["type"] for e in ev]
    assert "todos" in kinds and "tool_call" in kinds
    assert ev[-2] == {"type": "message", "agent": "director", "text": "Proxy v1 is up for review."}

    s = c.get("/api/projects/ep1/state").json()
    assert s["renders"][0]["proxy"] is True
    assert s["agent"]["todos"][0]["content"] == "Analyse clips"
    rough = s["renders"][0]["rough"]
    assert c.get(f"/files/ep1/{rough}").status_code == 200
    assert c.get("/files/ep1/../../etc/passwd").status_code == 404
    assert "Creative Video Agent" in c.get("/").text
    h = c.get("/api/projects/ep1/history").json()
    assert h["messages"][0] == {"role": "user", "text": "make an episode"}


def test_two_pending_questions_are_answered_by_id(tmp_path, monkeypatch):
    """Parallel interrupts (two cards at once) must resume together, keyed by interrupt id."""
    monkeypatch.setenv("CVA_PROJECTS", str(tmp_path))
    two = AIMessage(content="", tool_calls=[
        {"name": "ask_user", "args": {"questions": [{"id": "fmt", "question": "Format?", "default": "Reels"}]},
         "id": "c1", "type": "tool_call"},
        {"name": "ask_user", "args": {"questions": [{"id": "cap", "question": "Captions?", "default": "No"}]},
         "id": "c2", "type": "tool_call"}])
    model = Scripted(messages=iter([two, AIMessage(content="Thanks, starting.")]))
    app = create_app(build=lambda root, checkpointer: build_agent(root, model=model, subagent_model=model,
                                                                   checkpointer=checkpointer))
    c = TestClient(app)
    c.post("/api/projects", json={"name": "ep2"})
    ev = events(c.post("/api/projects/ep2/chat", json={"message": "go"}))
    cards = [e for e in ev if e["type"] == "interrupt"]
    assert len(cards) == 2 and all(e["id"] for e in cards)

    ev = events(c.post("/api/projects/ep2/resume", json={"value": {"fmt": "Reels"}, "interrupt_id": cards[0]["id"]}))
    assert {"type": "waiting", "remaining": 1} in ev                 # holds until every card is answered
    assert len(c.get("/api/projects/ep2/history").json()["interrupts"]) == 1

    ev = events(c.post("/api/projects/ep2/resume", json={"value": {"cap": "No"}, "interrupt_id": cards[1]["id"]}))
    assert not [e for e in ev if e["type"] == "error"], ev
    assert ev[-2]["text"] == "Thanks, starting."
    tool_results = [e["text"] for e in ev if e["type"] == "tool_result" and e["name"] == "ask_user"]
    assert any("Reels" in t for t in tool_results) and any('"No"' in t for t in tool_results)
