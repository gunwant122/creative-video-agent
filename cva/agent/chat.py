"""Terminal harness: `cva-chat <project folder>` - same agent and events as the web UI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from cva.server.app import load_dotenv
from cva.server.runner import ProjectRunner


def _answer(v: dict):
    if v.get("type") == "questions":
        out = {}
        for q in v["questions"]:
            opts = q.get("options") or []
            hint = f" [{' / '.join(opts)}]" if opts else ""
            a = input(f"? {q['question']}{hint} (default: {q.get('default', '')}) > ").strip()
            out[q["id"]] = a or q.get("default", "")
        return out
    if v.get("type") == "cost_approval":
        est = v.get("estimate", {})
        print(f"$ {v['service']} {v['operation']}: {json.dumps(v.get('details'))[:400]}")
        print(f"  cost: {('~$' + str(est['usd'])) if est.get('usd') is not None else est.get('note', 'unknown')}")
        return {"approved": input("  approve and spend? [y/N] > ").strip().lower() in ("y", "yes")}
    return input(f"{v} > ")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: cva-chat <project folder>   (needs src/ with clips; ANTHROPIC_API_KEY in env or .env)")
        return 2
    load_dotenv()
    root = Path(argv[0]).resolve()
    for d in ("src", "work", "analysis", "renders"):
        (root / d).mkdir(parents=True, exist_ok=True)
    r = ProjectRunner(root)
    print(f"project {root} - type a request, Ctrl-D to quit")
    while True:
        try:
            msg = input("\nyou > ").strip()
        except EOFError:
            return 0
        if not msg:
            continue
        payloads: list[dict] = [{"message": msg}]
        while payloads:
            pending = []
            for payload in payloads:
                for ev in r.run(payload):
                    t = ev["type"]
                    if t == "message":
                        print(f"\n{ev['text']}")
                    elif t == "tool_call":
                        print(f"  · {ev['agent']} → {ev['name']} {ev['args'][:160]}")
                    elif t == "todos":
                        print("  plan: " + " | ".join(f"[{'x' if x['status'] == 'completed' else ' '}] {x['content']}"
                                                      for x in ev["todos"]))
                    elif t == "interrupt":
                        pending.append(ev)
                    elif t == "error":
                        print(f"  ! {ev['text']}")
            # answer every pending card; the runner resumes once all of them are in
            payloads = [{"resume": _answer(ev["value"]), "interrupt_id": ev["id"]} for ev in pending]


if __name__ == "__main__":
    sys.exit(main())
