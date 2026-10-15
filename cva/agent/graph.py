"""The Deep Agents graph: a Director plus specialist subagents, bound to one project folder."""
from __future__ import annotations

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import TodoListMiddleware

from cva.agent import prompts
from cva.agent.tools import make_tools
from cva.gen import make_gen_tools
from cva.helpdocs import skills_root
from cva.models import ImageRelayMiddleware, needs_image_relay, resolve_model

DIRECTOR_MODEL = os.environ.get("CVA_MODEL", "anthropic:claude-opus-5-5")
SUBAGENT_MODEL = os.environ.get("CVA_SUBAGENT_MODEL", "anthropic:claude-sonnet-5-5")

SKILLS = ["/skills/"]


def subagent_specs(t: dict, g: dict, model) -> list[dict]:
    common = [t["view_images"]]
    mw = [ImageRelayMiddleware()] if needs_image_relay(model) else []
    specs = [
        {"name": "analyst", "description": "Measures media: specs, loudness, noise, word-timed transcripts, "
                                           "scene and glitch scans, frame sheets and stills. Returns facts.",
         "system_prompt": prompts.ANALYST, "tools": [t["cva"], *common], "skills": SKILLS, "model": model},
        {"name": "editor", "description": "Builds and re-cuts the vv timeline: assembly, trims, split edits, "
                                          "punch-ins, transitions, glitch fixes, proxy/full renders, stills at cuts.",
         "system_prompt": prompts.EDITOR, "tools": [t["vv"], t["cva"], *common], "skills": SKILLS, "model": model},
        {"name": "sound", "description": "Take levelling, dialogue cleanup, ducking, stem diagnosis, mastering "
                                         "and delivery with the QC gate.",
         "system_prompt": prompts.SOUND, "tools": [t["cva"], t["vv"]], "skills": SKILLS, "model": model},
        {"name": "composer", "description": "Writes, checks, renders and retimes the vd score to picture.",
         "system_prompt": prompts.COMPOSER, "tools": [t["vd"], t["cva"]], "skills": SKILLS, "model": model},
        {"name": "motion", "description": "Titles, captions and overlays with Remotion.",
         "system_prompt": prompts.MOTION, "tools": [t["vv"], t["remotion"], t["cva"], *common], "skills": SKILLS,
         "model": model},
        {"name": "generator", "description": "PAID generation with ElevenLabs and fal (sound effects, voice "
                                             "isolation, TTS, music, Scribe transcripts, shot regeneration, upscaling). "
                                             "Every call asks the user to approve the cost.",
         "system_prompt": prompts.GENERATOR, "tools": [*g.values(), t["cva"], *common], "skills": SKILLS,
         "model": model},
    ]
    if mw:
        for s in specs:
            s["middleware"] = list(mw)
    return specs


def build_agent(project: str | Path, *, model=None, subagent_model=None, checkpointer=None, store=None,
                gen_kwargs: dict | None = None):
    root = Path(project).resolve()
    (root / "work").mkdir(parents=True, exist_ok=True)
    t = make_tools(root)
    g = make_gen_tools(root, **(gen_kwargs or {}))
    backend = CompositeBackend(
        default=FilesystemBackend(root_dir=root, virtual_mode=True),
        routes={"/skills/": FilesystemBackend(root_dir=skills_root(), virtual_mode=True)},
    )
    memory = ["/brief.md"] if (root / "brief.md").exists() else []
    director_spec = model or os.environ.get("CVA_MODEL", DIRECTOR_MODEL)
    sub_spec = subagent_model or os.environ.get("CVA_SUBAGENT_MODEL", SUBAGENT_MODEL)
    director = resolve_model(director_spec)
    sub_model = resolve_model(sub_spec)
    middleware = [TodoListMiddleware()]  # the live plan shown in the UI
    if needs_image_relay(director_spec):
        middleware.append(ImageRelayMiddleware())
    return create_deep_agent(
        model=director,
        tools=[t["ask_user"], t["report_render"], t["view_images"], t["vv"], t["cva"]],
        system_prompt=prompts.DIRECTOR,
        middleware=middleware,
        subagents=subagent_specs(t, g, sub_model),
        skills=SKILLS,
        memory=memory,
        backend=backend,
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/src/**", "/skills/**"], mode="deny"),
        ],
        checkpointer=checkpointer,
        store=store,
        name="director",
    )
