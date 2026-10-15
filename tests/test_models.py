import base64
import io
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from PIL import Image

from cva.agent.graph import build_agent
from cva.models import ImageRelayMiddleware, ModelConfigError, needs_image_relay, resolve_model
from tests.test_agent import Scripted, call


@pytest.fixture
def lite_env(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.com/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test")


def test_resolve_openai_route(lite_env):
    m = resolve_model("litellm:gemini-2.5-pro")
    assert type(m).__name__ == "ChatOpenAI" and m.model_name == "gemini-2.5-pro"
    assert str(m.openai_api_base).rstrip("/") == "https://litellm.example.com/v1"
    assert needs_image_relay("litellm:x") and needs_image_relay(m)


def test_resolve_anthropic_route(lite_env):
    m = resolve_model("litellm-anthropic:claude-opus-5-5")
    assert type(m).__name__ == "ChatAnthropic" and m.anthropic_api_url == "https://litellm.example.com"
    assert not needs_image_relay("litellm-anthropic:x") and not needs_image_relay(m)


def test_missing_settings(monkeypatch):
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    with pytest.raises(ModelConfigError):
        resolve_model("litellm:x")


def test_image_relay_moves_images_to_user_message():
    img = {"type": "image", "base64": "AAAA", "mime_type": "image/jpeg"}
    msgs = [HumanMessage("look"),
            AIMessage(content="", tool_calls=[{"name": "view_images", "args": {}, "id": "1", "type": "tool_call"}]),
            ToolMessage(content=[{"type": "text", "text": "image: a.jpg"}, img], tool_call_id="1", name="view_images")]
    out = ImageRelayMiddleware()._rewrite(msgs)
    assert isinstance(out[2], ToolMessage) and isinstance(out[2].content, str) and "1 image(s)" in out[2].content
    assert isinstance(out[3], HumanMessage) and out[3].content[1] == img


class FakeImages:
    def __init__(self):
        self.calls = []
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 50, 50)).save(buf, "PNG")
        self.b64 = base64.b64encode(buf.getvalue()).decode()

    @property
    def with_raw_response(self):
        return self

    def generate(self, **kw):
        self.calls.append(kw)
        outer = self

        class Raw:
            headers = {"x-litellm-response-cost": "0.04"}

            def parse(self):
                class D:
                    b64_json = outer.b64
                    url = None

                class R:
                    data = [D()]
                return R()
        return Raw()


class FakeLite:
    def __init__(self):
        self.images = FakeImages()


def test_image_generate_through_proxy_is_gated_and_costed(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    monkeypatch.setenv("CVA_IMAGE_MODEL", "imagen-4")
    fake = FakeLite()
    model = Scripted(messages=iter([
        call("task", {"subagent_type": "generator", "description": "make a title background"}, 1),
        call("image_generate", {"prompt": "regency candlelit hall, empty, painterly", "out_name": "title_bg"}, 2),
        AIMessage(content="done"), AIMessage(content="ok")]))
    agent = build_agent(tmp_path, model=model, subagent_model=model, checkpointer=InMemorySaver(),
                        gen_kwargs={"lite_client_factory": lambda: fake})
    cfg = {"configurable": {"thread_id": "i"}, "recursion_limit": 50}
    out = agent.invoke({"messages": [{"role": "user", "content": "title bg"}]}, cfg)
    intr = out["__interrupt__"][0].value
    assert intr["type"] == "cost_approval" and intr["operation"] == "image_generate:imagen-4"
    assert fake.images.calls == []                                  # nothing before approval
    agent.invoke(Command(resume={"approved": True}), cfg)
    assert fake.images.calls[0]["model"] == "imagen-4"
    assert (tmp_path / "assets/generated/title_bg_0.png").exists()
    led = json.loads((tmp_path / "assets/generated/ledger.json").read_text())[-1]
    assert led["estimate_usd"] == 0.04 and led["cost_source"] == "proxy-reported"


def test_claude_routes_drop_stale_thinking_blocks(lite_env):
    for spec in ("litellm-anthropic:anthropic/claude-sonnet-5-5", "anthropic:claude-opus-5-5"):
        m = resolve_model(spec)
        assert m.thinking["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
        assert "thinking-binding-controls-2026-08-01" in m.betas
