---
name: make-music
description: Start here for any music or score for a video - deciding whether to compose an original score, use a library track, or leave silence, then scoring to picture - story beats, cue sheet, motif, orchestration, hits on cuts, risers into cuts, underscoring dialogue, building climaxes, and retiming the score after a re-cut. Routes to craft references and to the score-engine tool.
---

# Make music (router)

## Choose the route
| Situation | Route |
|---|---|
| Narrative piece, emotional arc, cuts to hit | **Compose** with `score-engine` (default) |
| User supplied or licensed a track | **Edit the track** to picture (cut on bar lines, fade tails) in `mix-audio` |
| Clips already contain music | Do **not** score over it. At most add hits/risers between scenes |
| Informational / talking head | Light bed or nothing - ask the user |

## Composing workflow
1. **Beat map.** `vd cue import` brings in every cut and the speech regions. From `analysis/summary.md` and the transcript, add the story beats with exact timeline times (`vd cue add`): emotional turns, silent moments, the climax, dry moments. Conceptually:
   ```json
   [{"t": 0.0,  "beat": "hospital opens", "mood": "fragile", "speech": true},
    {"t": 31.2, "beat": "she rises (8 s silent)", "mood": "hope", "speech": false, "feature": true},
    {"t": 52.0, "beat": "council - cut", "hit": "impact", "riser_into": true}]
   ```
2. **Concept.** Key, tempo, palette and one main motif. Write it in `work/score_notes.md` before any notes. Read `references/writing.md` and the genre reference (`references/cinematic.md`).
3. **Compose** section by section in the vd score (see `score-engine`, `vd help jobs`). Times in seconds, aligned to the cue sheet.
4. **Under dialogue**, follow `references/underscore-dialogue.md`. Silent "feature" moments are where the theme goes.
5. **Structure** - hits and risers per `references/video-scoring.md`; the build per `references/climaxes.md`.
6. **Render** stems, hand them to `mix-audio` for ducking and mastering.
7. **After a re-cut**, `vd retime --from <old cut list> --to <new cut list>`: every note and hit is mapped to the new edit (no recomposing), hits on cuts snap to the new cuts. Then `vd check`.

## Craft references
| File | Read when |
|---|---|
| `references/video-scoring.md` | Always - hits, risers, sync rules |
| `references/underscore-dialogue.md` | Any cue under speech |
| `references/writing.md` | Always - motif, harmony, development |
| `references/cinematic.md` | Drama, period, epic, emotional pieces |
| `references/climaxes.md` | Building to a finale or big reveal |
| `references/orchestra-ranges.md` | Choosing notes for each instrument |

You cannot hear the result. Check it by reading the MIDI back (note ranges, density under speech, hit times vs cut times) and say that feel and balance are for the user to judge.
