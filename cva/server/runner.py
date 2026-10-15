"""Runs one project's agent in a worker thread and turns LangGraph updates into UI events."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from queue import Queue
from typing import Any, Iterator

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

THREAD = "main"
_SENTINEL = object()


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, dict) and b.get("type") == "image":
                parts.append("[image]")
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return str(content)


def _short(s: str, n: int = 600) -> str:
    return s if len(s) <= n else s[:n] + f" ... [{len(s) - n} more chars]"


class ProjectRunner:
    """One agent + checkpointer per project; one run at a time."""

    def __init__(self, root: Path, build=None):
        from cva.agent.graph import build_agent

        self.root = root
        self.lock = threading.Lock()
        conn = sqlite3.connect(str(root / "work" / "agent.sqlite"), check_same_thread=False)
        self.saver = SqliteSaver(conn)
        self.agent = (build or build_agent)(root, checkpointer=self.saver)
        self.cfg = {"configurable": {"thread_id": THREAD}, "recursion_limit": 400}
        self.answers: dict[str, object] = {}   # interrupt id -> answer, until every pending interrupt has one

    @property
    def busy(self) -> bool:
        return self.lock.locked()

    def state(self) -> dict:
        snap = self.agent.get_state(self.cfg)
        values = snap.values or {}
        interrupts = [{"id": i.id, **(i.value if isinstance(i.value, dict) else {"value": i.value})}
                      for i in (snap.interrupts or []) if i.id not in self.answers]
        msgs = []
        for m in values.get("messages", []):
            if isinstance(m, AIMessage) and _text(m.content).strip():
                msgs.append({"role": "assistant", "text": _text(m.content)})
            elif getattr(m, "type", "") == "human":
                msgs.append({"role": "user", "text": _text(m.content)})
        return {"todos": values.get("todos", []), "messages": msgs, "interrupts": interrupts, "busy": self.busy}

    def _resume_input(self, payload) -> Command | None:
        """Collect answers per interrupt id; return the Command once every pending interrupt is answered.

        Several interrupts can be pending at once (parallel subagents asking for cost approval, two
        questions in one step). LangGraph then needs {interrupt_id: answer} for all of them in one resume."""
        pending = list(self.agent.get_state(self.cfg).interrupts or [])
        if not pending:
            self.answers.clear()
            raise RuntimeError("nothing is waiting for an answer")
        iid = payload.get("interrupt_id")
        if iid is None:
            if len(pending) > 1:
                raise RuntimeError("several questions are pending; answer each card")
            iid = pending[0].id
        if iid not in {p.id for p in pending}:
            raise RuntimeError("that question was already answered or has expired - reload the page")
        self.answers[iid] = payload["resume"]
        if any(p.id not in self.answers for p in pending):
            return None
        resume = {p.id: self.answers[p.id] for p in pending}
        self.answers.clear()
        return Command(resume=resume)

    def run(self, payload) -> Iterator[dict]:
        """Yield UI events. payload: {"message": str} or {"resume": value, "interrupt_id": id}."""
        if not self.lock.acquire(blocking=False):
            yield {"type": "error", "text": "the agent is already working on this project"}
            return
        q: Queue = Queue()

        def work():
            try:
                if "resume" in payload:
                    inp = self._resume_input(payload)
                    if inp is None:
                        left = [p for p in self.agent.get_state(self.cfg).interrupts or [] if p.id not in self.answers]
                        q.put({"type": "waiting", "remaining": len(left)})
                        q.put({"type": "done", "waiting": True})
                        return
                else:
                    self.answers.clear()
                    inp = {"messages": [{"role": "user", "content": payload["message"]}]}
                for ns, update in self.agent.stream(inp, self.cfg, stream_mode="updates", subgraphs=True):
                    for ev in self._events(ns, update):
                        q.put(ev)
                snap = self.agent.get_state(self.cfg)
                for i in snap.interrupts or []:
                    q.put({"type": "interrupt", "id": i.id, "value": i.value})
                q.put({"type": "done", "waiting": bool(snap.interrupts)})
            except Exception as e:  # surface, don't crash the server
                q.put({"type": "error", "text": f"{type(e).__name__}: {e}"})
            finally:
                q.put(_SENTINEL)
                self.lock.release()

        threading.Thread(target=work, daemon=True).start()
        while (ev := q.get()) is not _SENTINEL:
            yield ev

    def _events(self, ns: tuple, update: dict) -> Iterator[dict]:
        agent = "director" if not ns else ns[-1].split(":")[0]
        for node, val in (update or {}).items():
            if not isinstance(val, dict):
                continue
            if "todos" in val and not ns:
                yield {"type": "todos", "todos": val["todos"]}
            msgs = val.get("messages") or []
            if not isinstance(msgs, list):
                msgs = [msgs]
            for m in msgs:
                if isinstance(m, AIMessage):
                    txt = _text(m.content).strip()
                    if txt:
                        yield {"type": "message" if not ns else "activity", "agent": agent, "text": txt}
                    for tc in m.tool_calls or []:
                        yield {"type": "tool_call", "agent": agent, "name": tc["name"],
                               "args": _short(json.dumps(tc["args"], ensure_ascii=False), 400)}
                elif isinstance(m, ToolMessage):
                    yield {"type": "tool_result", "agent": agent, "name": m.name,
                           "text": _short(_text(m.content))}
