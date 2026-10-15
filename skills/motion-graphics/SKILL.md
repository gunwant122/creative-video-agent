---
name: motion-graphics
description: Titles, captions (including Hindi/Devanagari), lower thirds, end cards, logos and animated motion graphics on the edit - quick text cards with vv overlay title/captions, or animated Remotion overlays rendered with the remotion tool and placed on the vv overlay track.
---

# Motion graphics (router)

## Quick path (default): text cards on the vv overlay track
| Job | Command |
|---|---|
| Title / chapter card | `vv overlay title "Episode 4" --start 0.5 --end 3.5 [--box] [--y "H*0.2"]` |
| Captions | `vv overlay captions [--version N] [--size 64] [--y "H*0.66-h/2"]` - cards from the render's timeline words |
| Logo, sticker, any PNG/MOV | `vv overlay add file --start s --end s --x "W-w-40" --y 40 [--fade 0.2] [--tag name]` |
| Inspect / remove | `vv overlay list`, `vv overlay rm o3`, `vv overlay clear --tag captions` |

Overlays composite at the next `vv render`. Captions follow the edit: after any re-cut, render, then run
`vv overlay captions` again (it replaces the previous captions). Devanagari is shaped correctly when libraqm is
installed; the result says `"shaping": "raqm"`.

## Animated graphics: Remotion
Use when the brief wants motion (kinetic type, animated lower thirds, maps). Remotion builds the graphics;
the vv overlay track composites them.

## Which Remotion skill
The official skills from `remotion-dev/skills` are installed alongside this one. Load the one that fits:

| Job | Skill |
|---|---|
| Not sure / general | `remotion-best-practices` |
| New Remotion project | `remotion-create` |
| Captions from a transcript | `remotion-captions` |
| Rendering | `remotion-render` |
| Audio/video assets inside a composition | `remotion-multimedia` |
| API lookups | `remotion-docs` |

## Conventions
- The Remotion project lives in `work/motion/`. Match the edit: same width, height and fps as the timeline profile.
- Drive every animation from `useCurrentFrame()`; no CSS transitions or timers.
- Read times from the edit (cut times, `work/cue_sheet.json`, transcript words) and pass them as input props - don't hard-code them.
- Text placement follows the safe zones in `edit-video/references/caption-craft.md`.

## Transparent overlay render
With the `remotion` tool (runs in `work/motion/`):
```
remotion(["install"])
remotion(["render", "Titles", "../overlays/titles_vN.mov", "--codec=prores", "--prores-profile=4444", "--pixel-format=yuva444p10le"])
```

## Place it on the edit
`vv overlay add work/overlays/titles_vN.mov --start 0 --end 4 --x 0 --y 0`, then `vv render` and check stills
inside each overlay's window.
