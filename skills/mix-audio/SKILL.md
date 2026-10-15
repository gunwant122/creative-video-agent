---
name: mix-audio
description: Sound editing and mixing for video - dialogue cleanup (rumble/mud EQ, noise reduction, de-essing), levelling clips to a common loudness, peak control, fades at cuts, ducking music under speech, combining dialogue/music/effects stems, and mastering to platform loudness (-14 LUFS social, -16 voice, -23 broadcast). All with FFmpeg filter chains.
---

# Mix audio (router)

Work in stems, at 48 kHz, 24-bit WAV, until the final encode:
- `work/dialogue_vN.wav` - from the timeline render
- `work/music_vN.wav` - from `make-music` (or a licensed track)
- `work/fx_vN.wav` - impacts, risers, ambience (optional)

## Order of operations
1. **Clean** each dialogue clip or the dialogue stem -> `references/dialogue-cleanup.md`
2. **Level** dialogue to a common loudness (default -16 LUFS) -> `references/loudness-mastering.md`
3. **Fades** at every cut (10-20 ms), longer at scene changes
4. **Duck** music and fx under speech -> `references/ducking.md`
5. **Sum** stems and **master** to the delivery target -> `references/loudness-mastering.md`
6. **Measure** the result - the check gate in `edit-video/references/delivery-specs.md`
7. **Listen (second opinion)** - `cva media watch <render> --mode listen`, and `cva media contour` on the music stem
   and the mix. Treat model listening notes as leads to check against measurements, not verdicts.

## Rules
- Measure before and after every processing step; record numbers in `notes.md`.
- Gentle beats heavy: if a step needs more than ~6 dB of gain reduction, fix the step before it instead.
- Never normalise to 0 dBFS. Leave headroom until mastering.
- Keep each chain in a script (`work/mix_vN.sh`) so the next version reruns it unchanged.
- You cannot listen yourself. A listening model gives a second opinion; report the measured numbers and its notes,
  and say that balance and tone need the user's ears.
