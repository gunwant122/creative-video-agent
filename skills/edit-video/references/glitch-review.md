# Glitch review (AI-generated footage)

AI video fails in characteristic ways: morphing hands and faces, objects popping in or out, sudden texture or lighting jumps, warped text, limbs merging, eyes drifting, a frame or two of garbage at clip boundaries.

## Three-pass review
0. **Model scan - `cva media watch <render> --mode glitches`.** A video model watches a 6x slowed, silent copy
   (about 6 real frames per second sampled), so faults shorter than a third of a second are caught. It returns
   candidate timestamps (+-0.3 s). It does not replace passes 1-2: it can miss slow morphs and can report
   camera moves as faults.
1. **Coarse pass - 3 fps.** Make frame sheets of the whole render (`analyze-media` -> frame sheets, `fps=3`). Look at every sheet. Log every suspect moment with its timestamp in `analysis/glitches.md`.
2. **Fine pass - 8 fps (or every frame).** For each suspect (from the model scan, the sheets, the change
   detector, or a timestamp the user gave you), make a sheet of +-1 s around it at 8 fps or full frame rate. Confirm or dismiss it. Record the exact first and last bad frame.

Also run the automatic detector (`analyze-media` -> sudden-change detection). A spike inside a shot (not at a cut) is a strong glitch candidate. The detector finds pops; only your eyes find slow morphs, so never skip the sheets.

## Not every change is a glitch
Before logging, rule out: camera parallax (background objects shifting with a camera move), a person entering
frame naturally, consistent costume or set design (a two-tone dress is not a morph), lighting changes motivated
by the scene. Log these as "checked - not a glitch" so the next pass does not re-open them.
Also run scene detection on each source: AI clips often hide internal cuts that should be treated as cuts.

## Log format (`analysis/glitches.md`)
```
| # | time (s) | clip | frames | what | severity | fix |
| 1 | 23.42-23.58 | v3 | 4 | hand merges with cup | high | punch-in 115% to crop hand |
```
Severity: **high** = a viewer will notice on a phone; **low** = only visible frame-by-frame. Fix all highs; fix lows only if cheap.

## Repair options, least to most invasive
| Fix | Use when | Dialogue cost |
|---|---|---|
| Trim head/tail | Glitch is in the first/last frames of a clip | None if outside speech |
| Punch-in / reframe | Fault is at the frame edge | None |
| L-cut / J-cut | Fault is during speech; another shot exists for the picture | None |
| Cutaway (`vv clip cover`) | Any fault; a fitting shot exists | None |
| Morph cut (4-frame dissolve) | A small jump after removing frames | None |
| Start the shot late | Fault in the opening frames (things still forming) | None if before the line |
| Dissolve across it | Fault is short (<= 6 frames) at a natural soft moment | None |
| Remove silent pause | Fault sits in a pause between lines | None |
| Hold frame (freeze <= 8 frames) | Very short pop, static shot | None, but risky - check the sheet |
| Cut the line | Nothing else works | Loses dialogue - ask the user first |

## What you still cannot judge
Whether a fault is *noticeable at full speed on a phone*, and whether a dissolve *feels* smooth. Ask the
model with `--mode review` for a second opinion, then say plainly that the user should check those moments.
When the user gives a timestamp, zoom there frame by frame before answering.

## Verify
After fixing, re-render, rebuild sheets around every fixed timestamp, and confirm. Update the log's `fix` column with what you did and the version it landed in.
