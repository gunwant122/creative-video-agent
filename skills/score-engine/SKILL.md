---
name: score-engine
description: Entry point for vd, the headless score workstation - the editable score (work/score.vd.json) in picture time (60 bpm, 1 beat = 1 second), cues imported from the cut list, parts with sampled patches (SFZ via sfizz, SF2 via FluidSynth), phrases, chords, ostinati, crescendos, hits and risers placed on cues, score checks, stems, MIDI export and retiming after a re-cut.
---

# Score engine (vd)

`vd` is the workstation. The `vd` tool takes the command line as a list: `vd(["cue", "import", "--cutlist", "work/cutlist_v2.json"])`.

## Start here
- `vd help jobs` - every scoring job and its command
- Craft: `vd help video-scoring`, `vd help underscore-dialogue`, `vd help writing`, `vd help cinematic`, `vd help climaxes`, `vd help orchestra-ranges`

## Workflow
1. `vd init`; `vd cue import --cutlist work/cutlist_vN.json --speech work/speech_regions_vN.json`.
2. Add story beats from the transcript: `vd cue add rise --t 31.2 --beat "..."`; mark dry moments with `--dry`.
3. Sections (`vd section add`) with key, palette, mood; parts (`vd part add <name> --patch <sfz> --role melody|pad|bass|pluck|perc --pan --reverb`).
4. Notes: `vd phrase add`, `vd chord add`, `vd gen ostinato`, `vd gen crescendo`. Pitches as names (D4, Bb2) or MIDI numbers.
5. Hits: `vd hit place <file> --cue cut:<clip>` (impact starts on the cut); risers `--align end --kind riser` (end on the cut). Earlier hits quieter (`--gain -6`), the last one biggest.
6. `vd check` until no issues: ranges, loud notes in the voice range under speech, hit sync (<= 20 ms), escalation, dry air.
7. `vd render` -> `work/music_mN.wav` + `work/stems/mN/`. Parts without a patch use a labelled preview synth: fine for timing, not for delivery.
8. Re-cut: `vd retime --from <old cut list> --to <new cut list>` maps every note and hit through source time; hits tied to cut cues snap to the new cuts. Then `vd check` and `vd render` again.

## Libraries
Patches live in `assets/libs/` (VSCO 2 CE and VCSL, CC0 - installed by `scripts/setup.sh`). Find a patch with
`ls assets/libs/...`; read its key range from the SFZ (`lokey`/`hikey`) before writing for it.
`vd midi` exports the whole score for a human composer.
