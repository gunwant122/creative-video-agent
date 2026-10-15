---
name: edit-video
description: Start here for any video editing job - assembling clips into an episode or reel, trimming, transitions, fixing AI-generation glitches, dialogue-based cuts, captions, or a final social/delivery render. Routes each job to the right tool (vv timeline, FFmpeg, Remotion) and the right craft reference, and defines the analyse -> edit -> check loop every job follows.
---

# Edit Video (router)

This skill decides *how* to do a job. Detailed craft lives in `references/`; read only the ones the job needs.

## Every job follows this loop

1. **Analyse first** - load the `analyze-media` skill. Never cut before you know specs, loudness, story order and where speech is.
2. **Ask at most 2-3 questions** the analysis cannot answer (one piece or several? captions? target platform? music yes/no?). Offer a default for each.
3. **Edit in the project file**, never by re-encoding sources directly. The project file is the source of truth; renders are disposable.
4. **Render a numbered version** (`renders/v1.mp4`, `v2.mp4`, ...). Never overwrite sources or a previous version.
5. **Check** - run the delivery checks in `references/delivery-specs.md` and look at stills at every cut. A render that fails a check is not done.
6. **Report** what you did, what you checked, and what you could not judge (you cannot hear - say so about music balance and feel).

## Routing

| Job | Tool | Skill / reference |
|---|---|---|
| Measure specs, loudness, noise, find speech, find glitches | FFmpeg, WhisperX, PySceneDetect | `analyze-media` |
| Multi-clip assembly, trims, split edits, punch-ins, dissolves, dips, cutaways | `vv` timeline | `timeline` (`vv help jobs`) |
| Stills, sheets, one-off measurements | `cva media` | `analyze-media` |
| Paid fixes: voice isolation, sound effects, shot regeneration | ElevenLabs / fal | `generate-media` |
| Dialogue cleanup, levelling, music ducking, mastering | FFmpeg filter chains | `mix-audio` |
| Original score, impacts, risers | MIDI + sampled orchestra | `make-music` |
| Titles, animated captions, lower thirds, overlays | Remotion | `motion-graphics` |

Rule of thumb: **anything with more than one clip goes in the timeline project.** FFmpeg is for measuring, inspecting and preparing single assets.

## Craft references

| File | Read when |
|---|---|
| `references/edit-craft.md` | Any assembly or re-cut: trims, pacing, J/L cuts, punch-ins, transitions |
| `references/speech-edits.md` | Cutting on transcript word timings, removing pauses or fillers |
| `references/glitch-review.md` | Source is AI-generated, or a review found visual faults |
| `references/caption-craft.md` | Captions or on-screen text were requested |
| `references/delivery-specs.md` | Before every final render, and for the check gate |

## Hard rules

- Sources are read-only. Work files go in `work/`, renders in `renders/`, analysis in `analysis/`.
- Every hard cut gets a short audio fade (10-20 ms) so it does not click.
- Never cut inside a word. Use the transcript word timings.
- If a fix would lose dialogue, prefer a split edit, punch-in or cutaway over a trim.
- Keep a `notes.md` changelog per version: what changed and why.
