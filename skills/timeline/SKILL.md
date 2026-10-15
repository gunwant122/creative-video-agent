---
name: timeline
description: Entry point for vv, the headless video editor - the editable episode timeline (work/episode.vv.json) with clip order, trims, split edits (J/L-cuts), cut-outs, punch-ins and push-ins, handle-aware dissolves, morph cuts, dips to black, per-take gain, versioned renders, cut lists, timeline speech regions and delivery with the QC gate.
---

# Timeline (vv)

`vv` is the editor. The project file is the source of truth; renders are disposable and numbered.
The `vv` tool takes the command line as a list: `vv(["clip", "add", "v1", "--in", "0.3", "--out", "12.5"])`.

## Start here
- `vv help jobs` - the command for each editing job (assembly, trims, L/J-cuts, picture-only cuts, punch-ins, transitions, delivery)
- `vv help project` - files a render writes (cut list, speech regions, history snapshot)
- Craft: `vv help edit-craft`, `vv help speech-edits`, `vv help glitch-review`, `vv help captions`, `vv help delivery`

## Rules the tool enforces
- Times you pass are seconds; `--in/--out` are **source** times. The file stores frames at the profile fps.
- Dissolves borrow handle frames; `--align auto` picks centre, then pre (all from the incoming clip), then post. If no side has enough spare frames, the command is refused with the numbers - shorten the dissolve or trim to free handles.
- Gain belongs to the take (`vv source gain`): every piece split from one take keeps the same level.
- Each clip's audio can lead (`--lead`, J-cut) or trail (`--tail`, L-cut) its picture; a negative value starts/ends it inside the picture instead.
- Every cut gets a 3-frame anti-click audio fade automatically.

## Typical loop
1. `vv init --width 1080 --height 1920 --fps <source fps>`; `vv source add src/<file>` for each clip.
2. `cva mix level-takes --target -16` (sets take gains).
3. Assemble, then `vv render --proxy`; look at stills (`vv stills`) and sheets.
4. Refine; `vv render` for a full version -> picture + dialogue stem + cut list + speech regions.
5. Hand the dialogue stem and speech regions to sound; `vv deliver --audio <master>` runs the QC gate.

## Picture-only cut (hide a morph, keep the line)
`vv clip cover c3 --from <glitch start> --to <glitch end> --with <other source> --src-in <its start>`
replaces exactly those frames with a muted cutaway of the same length (a listener, a reaction, an insert)
while c3's audio keeps running over it - an L-cut with sync intact and no words lost. Pick a cutaway from
the same scene; check the joins with stills.

`vv export-otio` hands the timeline to Premiere / Resolve / Final Cut if a human editor takes over.
