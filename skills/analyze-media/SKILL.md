---
name: analyze-media
description: Measure and inspect video/audio before and after editing - specs (resolution, fps, duration), loudness (LUFS, true peak), noise floor, word-timed transcripts, story order, scene changes, sudden-change/glitch candidates, frame-by-frame review sheets, and stills at cut points. Use at the start of every edit and for every review pass.
---

# Analyze media

Write every result to `analysis/` and finish with `analysis/summary.md` (format at the bottom). Other skills read that summary instead of re-measuring.

The `cva` tool wraps every recipe below: `cva media probe|loudness|levels|silences|transcribe|scenes|spikes|sheets|zoom|still` (see its tool description). The raw ffmpeg commands are here so you understand and can adapt them.

## 1. Specs
```bash
for f in src/*; do
  ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels \
    -show_entries format=duration -of json "$f" > "analysis/$(basename "$f").probe.json"
done
```
Flag mismatches in resolution, fps or sample rate between clips. `vv` conforms every clip to the project profile at render (scale + crop, frame rate), so pick the profile to match the majority of sources and note any clip that will be cropped.

## 2. Loudness and peaks
```bash
ffmpeg -hide_banner -nostats -i src/v1.mp4 -map 0:a -af ebur128=peak=true -f null - 2>&1 | tail -n 12
```
Record integrated LUFS, LRA and true peak per clip. A spread of more than ~3 LU between clips means levelling is needed (`mix-audio`).

## 3. Noise floor and content
```bash
ffmpeg -i src/v1.mp4 -map 0:a -af astats=measure_overall=Noise_floor+RMS_level+Peak_level:measure_perchannel=none -f null - 2>&1 | grep -E "Noise floor|RMS level|Peak level"
ffmpeg -i src/v1.mp4 -map 0:a -af silencedetect=noise=-45dB:d=0.4 -f null - 2>&1 | grep silence_
```
Noise floor above about -55 dBFS means noise reduction is worth it. Also note whether a clip already has music or effects baked in - that limits ducking and scoring.

## 4. Word-timed transcript
Extract 16 kHz mono first, then transcribe. Prefer one of:
```bash
ffmpeg -i src/v1.mp4 -vn -ac 1 -ar 16000 work/v1_16k.wav
# Apple Silicon:
mlx_whisper work/v1_16k.wav --model mlx-community/whisper-large-v3-turbo --word-timestamps True --output-format json --output-dir analysis/
# Elsewhere / better alignment:
whisperx work/v1_16k.wav --model large-v3 --compute_type int8 --output_format json --output_dir analysis/
```
Check each tool's `--help` - flags change between versions. Save as `analysis/<clip>.words.json`. From the transcripts, write the story order and flag clips whose order is ambiguous.

## 5. Scene changes and glitch candidates
Cuts inside a clip:
```bash
scenedetect -i src/v1.mp4 detect-adaptive list-scenes -o analysis/
```
Sudden picture changes, frame to frame (mean luma of the difference image):
```bash
ffmpeg -i renders/vN.mp4 -vf "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=analysis/diff_vN.txt" -an -f null -
```
Parse the file, compute a rolling median, and flag frames whose value is above ~4x the local median. Spikes **at** known cuts are expected; spikes **inside** a shot are glitch candidates for `edit-video/references/glitch-review.md`.

## 5b. Watch and listen with a video model
`cva media watch <file> --mode glitches|listen|review [--start s --duration s] [--question "..."]`
- `glitches`: silent copy slowed 6x, chunks of 20 s; returns candidate faults with times mapped back. Feed them
  into the zoom pass - never cut on a model timestamp alone.
- `listen`: normal speed with sound: buried dialogue, music too loud or fighting the voice, clicks, level jumps,
  mood mismatches. A second opinion with approximate times, weakest on judging intelligibility.
- `review`: full-speed editorial read: pacing, jumpy cuts, transitions, beats that land or miss.
Results are saved to `analysis/watch_<mode>_<file>_<start>.json`; the proxy-reported cost goes to the ledger
(about $0.10 per 2-minute episode for a glitch scan).

`cva media contour <file> --every 3` gives short-term loudness over time - the level map of a stem or mix.
Use it on the music stem against the speech regions to check the ducking and the build to the climax.

## 6. Frame review sheets
Whole piece at 3 fps, timestamped, 8x4 grid per sheet:
```bash
mkdir -p analysis/sheets_vN
ffmpeg -i renders/vN.mp4 -vf "fps=3,scale=240:-2,drawtext=text='%{pts\:hms}':x=4:y=4:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6,tile=8x4" \
  -an analysis/sheets_vN/sheet_%03d.png
```
Zoom on a suspect (+-1 s around 23.5 s at 8 fps):
```bash
ffmpeg -ss 22.5 -t 2 -i renders/vN.mp4 -vf "fps=8,scale=360:-2,drawtext=text='%{pts\:hms}':x=4:y=4:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6,tile=4x4" \
  -frames:v 1 -an analysis/zoom_23.5.png
```
With `-ss` before `-i` the drawn timestamp restarts at 0 - add the offset when logging. If `drawtext` complains about fonts, add `fontfile=/System/Library/Fonts/Supplemental/Arial.ttf`.

**If `drawtext` is missing** (`ffmpeg -filters | grep drawtext` is empty - common with minimal Homebrew builds), drop the `drawtext=...,` part and compute times instead: in sheet `N` (1-based) with `C` cells per sheet at `fps` R, cell `k` (0-based, left-to-right, top-to-bottom) is at `start + ((N-1)*C + k) / R` seconds. Write that mapping next to the sheets so the times are never guessed.

Look at every sheet. Automatic detection supplements your eyes; it does not replace them.

## 7. Stills at cuts
For each cut time `t` in the edit, grab `t - 2 frames` and `t + 2 frames` - `vv stills` does this for every cut of the latest render; `cva media still <file> --t <s> --out <jpg>` for one.

## `analysis/summary.md` format
```
## Clips
| clip | res | fps | dur | LUFS | TP | noise floor | content |
## Story order
v1 -> v2 -> ... (with one line per scene)
## Issues
- loudness spread -17 to -30 LUFS -> level to -16
- v6 has baked-in music -> duck gently, do not score over it
## Open questions for the user
```
