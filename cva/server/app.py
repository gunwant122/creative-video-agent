"""FastAPI server: projects, uploads, agent chat over SSE, and media/report serving."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from cva.server.runner import ProjectRunner

WEB = Path(__file__).resolve().parent.parent.parent / "web"
BRIEF_TEMPLATE = """# House style

<!-- The agent reads this before every episode in this project. Examples: -->
- Platform: Reels / Shorts (9:16), master -14 LUFS
- Transitions: dissolves within a scene, dips to black between scenes
- Music: orchestral underscore; no melody under dialogue; a sting on every cliffhanger
- Captions: none
- Paid generation budget: ask before spending
- Reference episode (optional): put it in src/reference/ and name it here so the agent matches its pacing
"""


def projects_root() -> Path:
    p = Path(os.environ.get("CVA_PROJECTS", "projects")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_app(build=None) -> FastAPI:
    app = FastAPI(title="Creative Video Agent")
    runners: dict[str, ProjectRunner] = {}

    def proj(name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            raise HTTPException(400, "bad project name")
        p = projects_root() / name
        if not p.is_dir():
            raise HTTPException(404, "no such project")
        return p

    def runner(name: str) -> ProjectRunner:
        if name not in runners:
            runners[name] = ProjectRunner(proj(name), build=build)
        return runners[name]

    def sse(events):
        def gen():
            for ev in events:
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------- projects ----------
    @app.get("/api/projects")
    def list_projects():
        out = []
        for p in sorted(projects_root().iterdir()):
            if p.is_dir() and (p / "src").is_dir():
                out.append({"name": p.name, "clips": len([f for f in (p / "src").iterdir() if f.is_file()]),
                            "renders": len([f for f in (p / "renders").glob("v*.mp4") if "_" not in f.stem])
                            if (p / "renders").exists() else 0})
        return out

    @app.post("/api/projects")
    def create_project(name: str = Body(..., embed=True)):
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", name):
            raise HTTPException(400, "use letters, numbers, - and _")
        p = projects_root() / name
        if p.exists():
            raise HTTPException(409, "exists")
        for d in ("src", "work", "analysis", "renders", "assets/hits"):
            (p / d).mkdir(parents=True)
        (p / "brief.md").write_text(BRIEF_TEMPLATE)
        return {"name": name}

    @app.get("/api/projects/{name}/brief")
    def get_brief(name: str):
        f = proj(name) / "brief.md"
        return {"text": f.read_text() if f.exists() else ""}

    @app.put("/api/projects/{name}/brief")
    def put_brief(name: str, text: str = Body(..., embed=True)):
        (proj(name) / "brief.md").write_text(text)
        runners.pop(name, None)  # memory is loaded at build time
        return {"ok": True}

    @app.put("/api/projects/{name}/budget")
    def put_budget(name: str, limit_usd: float | None = Body(None, embed=True)):
        f = proj(name) / "work" / "budget.json"
        f.write_text(json.dumps({"limit_usd": limit_usd}))
        return {"ok": True}

    @app.post("/api/projects/{name}/upload")
    async def upload(name: str, files: list[UploadFile]):
        dst = proj(name) / "src"
        saved = []
        for uf in files:
            fn = re.sub(r"[^A-Za-z0-9_.\-]", "_", Path(uf.filename or "clip").name)
            with (dst / fn).open("wb") as fh:
                shutil.copyfileobj(uf.file, fh)
            saved.append(fn)
        return {"saved": saved}

    # ---------- state ----------
    @app.get("/api/projects/{name}/state")
    def state(name: str):
        p = proj(name)
        vvf = p / "work" / "episode.vv.json"
        renders = json.loads(vvf.read_text()).get("renders", []) if vvf.exists() else []
        qc = {}
        for f in sorted((p / "renders").glob("v*_qc.json")) if (p / "renders").exists() else []:
            qc[f.stem.split("_")[0]] = json.loads(f.read_text())
        images = []
        if (p / "analysis").exists():
            for f in sorted((p / "analysis").rglob("*")):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    images.append(str(f.relative_to(p)))
        watch = []
        for f in sorted((p / "analysis").glob("watch_*.json")) if (p / "analysis").exists() else []:
            try:
                w = json.loads(f.read_text())
                watch.append({"file": f.name, "mode": w.get("mode"), "model": w.get("model"),
                              "events": w.get("events", []), "notes": w.get("notes", [])})
            except (OSError, ValueError):
                pass
        ledger = p / "assets" / "generated" / "ledger.json"
        budget = p / "work" / "budget.json"
        r = runners.get(name)
        agent_state = r.state() if r else None
        return {
            "name": name,
            "sources": sorted(f.name for f in (p / "src").iterdir() if f.is_file()),
            "renders": renders, "qc": qc, "images": images[-300:], "watch": watch,
            "notes": (p / "notes.md").read_text() if (p / "notes.md").exists() else "",
            "glitches": (p / "analysis" / "glitches.md").read_text() if (p / "analysis" / "glitches.md").exists() else "",
            "ledger": json.loads(ledger.read_text()) if ledger.exists() else [],
            "budget": json.loads(budget.read_text()) if budget.exists() else {"limit_usd": None},
            "agent": agent_state,
        }

    @app.get("/api/projects/{name}/history")
    def history(name: str):
        return runner(name).state()

    # ---------- agent ----------
    @app.post("/api/projects/{name}/chat")
    def chat(name: str, message: str = Body(..., embed=True)):
        return sse(runner(name).run({"message": message}))

    @app.post("/api/projects/{name}/resume")
    def resume(name: str, value: dict | list | str | bool = Body(..., embed=True),
               interrupt_id: str | None = Body(None, embed=True)):
        payload = {"resume": value}
        if interrupt_id:
            payload["interrupt_id"] = interrupt_id
        return sse(runner(name).run(payload))

    # ---------- files ----------
    @app.get("/files/{name}/{path:path}")
    def files(name: str, path: str):
        p = proj(name)
        f = (p / path).resolve()
        if p not in f.parents or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (WEB / "index.html").read_text()

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()


def load_dotenv(path: Path | None = None) -> None:
    """KEY=value lines from the repo's .env (and ./.env); real env vars win."""
    from cva.config import load_env
    load_env(path)


def main():
    import uvicorn

    load_dotenv()
    uvicorn.run("cva.server.app:app", host=os.environ.get("CVA_HOST", "127.0.0.1"),
                port=int(os.environ.get("CVA_PORT", "8765")), reload=False)


if __name__ == "__main__":
    main()
