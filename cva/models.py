"""Model resolution, including a LiteLLM proxy.

Model specs (CVA_MODEL, CVA_SUBAGENT_MODEL, CVA_VISION_MODEL):
  anthropic:<model>          direct Anthropic API (ANTHROPIC_API_KEY)
  litellm:<model>            LiteLLM proxy, OpenAI-compatible /v1/chat/completions - any model the proxy serves
  litellm-anthropic:<model>  LiteLLM proxy, Anthropic-compatible /v1/messages - best for Claude models via the proxy
                             (keeps images inside tool results, prompt caching, etc.)
Anything else is passed to LangChain's init_chat_model as-is.

Proxy settings: LITELLM_BASE_URL (e.g. https://llm.example.com) and LITELLM_API_KEY (a LiteLLM virtual key).
"""
from __future__ import annotations

import os

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents.middleware import AgentMiddleware


class ModelConfigError(RuntimeError):
    pass


def litellm_settings() -> tuple[str, str]:
    base = os.environ.get("LITELLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LITELLM_API_KEY", "")
    if not base:
        raise ModelConfigError("LITELLM_BASE_URL is not set (add it to .env)")
    if not key:
        raise ModelConfigError("LITELLM_API_KEY is not set (add it to .env)")
    return base, key


def _openai_base(base: str) -> str:
    return base if base.endswith("/v1") else base + "/v1"


# Claude thinking blocks are bound to the exact system prompt + tool list that produced them. A paused
# conversation resumed under changed prompts/tools (a code update, an edited brief.md) would 400; with
# drop_block the stale blocks are dropped (that request only), and the conversation itself is kept.
THINKING = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
THINKING_BETAS = ["thinking-binding-controls-2026-08-01"]


def _claude(name: str, **kw):
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=name, max_retries=3, max_tokens=16000, thinking=dict(THINKING),
                         betas=list(THINKING_BETAS), **kw)


def resolve_model(spec):
    """Turn a spec string into a chat model; pass model objects through unchanged."""
    if not isinstance(spec, str):
        return spec
    provider, _, name = spec.partition(":")
    if provider == "litellm":
        from langchain_openai import ChatOpenAI
        base, key = litellm_settings()
        return ChatOpenAI(model=name, base_url=_openai_base(base), api_key=key, max_retries=3, timeout=600)
    if provider == "litellm-anthropic":
        base, key = litellm_settings()
        root = base[:-3] if base.endswith("/v1") else base
        # LiteLLM accepts the virtual key as x-api-key on its Anthropic-compatible route
        return _claude(name, anthropic_api_url=root, api_key=key)
    if provider == "anthropic":
        return _claude(name)
    return spec  # let deepagents / init_chat_model handle others


def needs_image_relay(spec) -> bool:
    """OpenAI-style chat APIs reject images inside tool results."""
    if isinstance(spec, str):
        return spec.startswith("litellm:") or spec.startswith("openai:")
    return type(spec).__name__ in ("ChatOpenAI", "AzureChatOpenAI")


def _has_image(content) -> bool:
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") in ("image", "image_url")
                                             for b in content)


class ImageRelayMiddleware(AgentMiddleware):
    """Move images out of tool results into a user message right after them (OpenAI-compatible models).

    The tool result keeps a text note so the model knows which call produced which images."""

    def _rewrite(self, messages: list) -> list:
        out, pending = [], []
        for m in messages:
            if pending and not isinstance(m, ToolMessage):
                out.append(HumanMessage(content=[{"type": "text", "text": "Images returned by the tool calls above:"},
                                                 *pending]))
                pending = []
            if isinstance(m, ToolMessage) and _has_image(m.content):
                text = [b for b in m.content if isinstance(b, dict) and b.get("type") == "text"]
                imgs = [b for b in m.content if isinstance(b, dict) and b.get("type") in ("image", "image_url")]
                note = "\n".join(b["text"] for b in text) + f"\n[{len(imgs)} image(s) attached in the next message]"
                out.append(m.model_copy(update={"content": note}))
                pending += imgs
            else:
                out.append(m)
        if pending:
            out.append(HumanMessage(content=[{"type": "text", "text": "Images returned by the tool calls above:"},
                                             *pending]))
        return out

    def wrap_model_call(self, request, handler):
        if any(isinstance(m, ToolMessage) and _has_image(m.content) for m in request.messages):
            request = request.override(messages=self._rewrite(request.messages))
        return handler(request)

    async def awrap_model_call(self, request, handler):
        if any(isinstance(m, ToolMessage) and _has_image(m.content) for m in request.messages):
            request = request.override(messages=self._rewrite(request.messages))
        return await handler(request)


def list_litellm_models() -> list[dict]:
    """Models the proxy exposes, with their mode (chat / image_generation / ...) when /model/info allows."""
    import json
    import urllib.request

    base, key = litellm_settings()
    root = base[:-3] if base.endswith("/v1") else base
    hdr = {"Authorization": f"Bearer {key}"}
    try:
        req = urllib.request.Request(root + "/model/info", headers=hdr)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())["data"]
        return [{"id": d.get("model_name"), "mode": (d.get("model_info") or {}).get("mode"),
                 "backend": (d.get("litellm_params") or {}).get("model")} for d in data]
    except Exception:
        req = urllib.request.Request(_openai_base(base) + "/models", headers=hdr)
        with urllib.request.urlopen(req, timeout=20) as r:
            return [{"id": d["id"], "mode": None, "backend": None} for d in json.loads(r.read())["data"]]


__all__ = ["resolve_model", "needs_image_relay", "ImageRelayMiddleware", "list_litellm_models", "AIMessage"]


def main() -> int:
    """List the models your LiteLLM proxy serves (reads .env; never prints the key)."""
    from cva.server.app import load_dotenv

    load_dotenv()
    try:
        models = list_litellm_models()
    except ModelConfigError as e:
        print(e)
        return 1
    except Exception as e:
        print(f"could not reach the proxy: {type(e).__name__}: {e}")
        return 1
    for m in sorted(models, key=lambda m: (str(m["mode"]), str(m["id"]))):
        print(f"{str(m['mode'] or '?'):18s} {m['id']:45s} {m['backend'] or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
