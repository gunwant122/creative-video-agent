# Creative Video Agent

An open, self-hosted take on the "headless editor + headless DAW + skills" workflow: a Deep Agents harness
that turns AI-generated drama clips into a finished, scored, social-ready episode, with a web UI.

```
Browser UI ──SSE──> FastAPI ──> Director agent (plans, asks ≤3 questions, enforces analyse → edit → check)
                                   ├─ analyst    cva media: specs, LUFS, noise, transcripts, glitch scans, sheets
                                   ├─ editor     vv: editable timeline, split edits, cutaways, punch-ins, dissolves, dips
                                   ├─ sound      cva mix: take levelling, cleanup, ducking, mastering, QC gate
                                   ├─ composer   vd: score in picture time, hits on cuts, retime after re-cuts
                                   ├─ motion     vv overlay titles/captions; Remotion for animated graphics
                                   └─ generator  ElevenLabs + fal, every call cost-approved by the user
```

## The tools (usable without the agent)

| Tool | What it is | Project file |
|---|---|---|
| `vv` | Headless video editor: JSON timeline compiled to ffmpeg. Frame-exact trims, J/L-cuts, `clip cover` (picture-only cut with a same-length cutaway), static/animated punch-ins, handle-aware dissolves (refuses ones that don't fit), dips, per-take gain, an overlay track (titles, captions incl. Devanagari, logos, Remotion renders), numbered renders with cut lists and timeline speech regions, `deliver` + QC gate, OTIO export. | `work/episode.vv.json` |
| `vd` | Headless score workstation: notes in picture time (60 bpm), cues from the cut list, sfizz/FluidSynth rendering of CC0 orchestra samples (preview synth fallback), hits/risers on cues, `check` (ranges, voice-range clashes under speech, hit sync, escalation, dry air), `retime` across re-cuts. | `work/score.vd.json` |
| `cva` | `media` (measure/inspect, `profile` a reference episode), `mix` (clean, level-takes, duck, sum, master, diagnose), `qc gate`. | — |

`vv help jobs` and `vd help jobs` list a command for every editing / scoring job; `vv help <topic>` and
`vd help <topic>` print the craft guides from `skills/` (one source for agent and humans).

## Skills

Router skills + reference files, loaded on demand by every agent (`skills/`):
`edit-video` (loop, routing, edit craft, speech edits, glitch review, captions, delivery), `analyze-media`,
`timeline` (vv), `mix-audio`, `make-music` (scoring craft, underscoring dialogue, motif writing, cinematic,
climaxes, orchestra ranges), `score-engine` (vd), `motion-graphics`, `generate-media`.
Per-project house style lives in `projects/<name>/brief.md`, loaded into the Director as memory.

## Setup

```bash
scripts/setup.sh
```
Then put `ANTHROPIC_API_KEY` (and optionally `ELEVENLABS_API_KEY`, `FAL_KEY`) in `.env`.

Run the web UI:
```bash
.venv/bin/python -m cva.server.app
```
Open http://127.0.0.1:8765, create a project, upload clips under Sources, and describe the episode.

Or run the same agent from the terminal:
```bash
.venv/bin/python -m cva.agent.chat projects/my-episode
```

Models: Director `anthropic:claude-opus-5-5`, subagents `anthropic:claude-sonnet-5-5`
(override with `CVA_MODEL` / `CVA_SUBAGENT_MODEL`).

### Using a LiteLLM proxy
Set `LITELLM_BASE_URL` and `LITELLM_API_KEY` in `.env`, list what the proxy serves, then pick models:
```bash
.venv/bin/python -m cva.models
```
- `CVA_MODEL=litellm-anthropic:<claude model>` - Claude via the proxy's Anthropic-compatible route (recommended:
  images in tool results, prompt caching).
- `CVA_MODEL=litellm:<any model>` - any chat model via the OpenAI-compatible route; tool-result images are relayed
  automatically. The model must support tool calling and vision.
- `CVA_IMAGE_MODEL=<image model>` - used by the `image_generate` / `image_edit` tools (cost-gated; the
  proxy-reported cost goes into the ledger).

## Tests

```bash
.venv/bin/python -m pytest -q        # 42 tests: frame-exact edits, mixing targets, retime, agent + server flows
scripts/smoke.sh                     # whole tool chain on synthetic clips, ends with the QC gate
```

## Notes and limits
- The agent cannot hear. It composes and mixes by measurement and reasoning; the UI has a "listen and tell the agent" box.
- Orchestral parts render through `sfizz_render` (built from source by setup.sh) with VSCO 2 CE samples fetched
  per instrument (`scripts/fetch_instruments.py core` is ~510 MB; the full library is ~3 GB). Parts without a
  patch use a labelled preview synth - good for timing, not for delivery.
- Paid generation uses the ElevenLabs and fal SDKs with API keys (the hosted MCP connectors use browser OAuth,
  which suits Claude Code / Claude apps but not a server running jobs). Every paid call needs a "yes" in the UI.
- Homebrew's default ffmpeg lacks `drawtext`/`subtitles`; frame sheets then use a computed time map.
