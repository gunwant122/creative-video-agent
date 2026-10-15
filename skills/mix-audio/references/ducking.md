# Ducking music under speech

Default: music sits **8 dB lower** whenever someone speaks, ramping down in ~150 ms before the first word and back up over ~500 ms after the last.

## Method A - envelope from the transcript (preferred, exact)
1. From the word-timed transcripts and the edit's clip offsets, build speech regions in timeline seconds. Merge regions separated by < 0.8 s so the music does not pump between words.
2. Generate a gain envelope (1.0 = full, 0.398 = -8 dB) with ramps, and multiply the music by it. Python with numpy + soundfile:
```python
import numpy as np, soundfile as sf
music, sr = sf.read("work/music_vN.wav", always_2d=True)
duck = 10 ** (-8 / 20)
env = np.ones(len(music))
for start, end in regions:                       # seconds, merged
    a, b = int((start - 0.15) * sr), int((end + 0.10) * sr)
    down, up = int(0.15 * sr), int(0.50 * sr)
    a = max(a, 0)
    env[a:a + down] = np.minimum(env[a:a + down], np.linspace(1, duck, len(env[a:a + down])))
    env[a + down:b] = np.minimum(env[a + down:b], duck)
    env[b:b + up] = np.minimum(env[b:b + up], np.linspace(duck, 1, len(env[b:b + up])))
sf.write("work/music_ducked_vN.wav", music * env[:, None], sr, subtype="PCM_24")
```
3. Save the regions to `work/speech_regions_vN.json` - the composer uses them too.

## Method B - sidechain compressor (quick, approximate)
```bash
ffmpeg -i work/music_vN.wav -i work/dialogue_vN.wav -filter_complex "\
[1:a]asplit=2[dlg][key];\
[0:a][key]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=400:makeup=1[ducked];\
[dlg][ducked]amix=inputs=2:normalize=0[out]" -map "[out]" -c:a pcm_s24le work/premix_vN.wav
```
Reacts to all dialogue sound (breaths, noise) and its depth varies with the voice level. Use when there is no transcript.

## Beyond level: spectral room
Ducking is level only. For dense music under speech also cut the music 2-4 dB around 1-4 kHz while speech is present (or permanently, for the cue). The composer should already keep busy material out of the voice range - see `make-music/references/underscore-dialogue.md`.

## Effects
Impacts and risers on cuts usually should **not** duck - they mark structure. If one lands on a line, move it or reduce it by hand rather than ducking it.
