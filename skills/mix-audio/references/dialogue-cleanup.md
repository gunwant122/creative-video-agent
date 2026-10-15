# Dialogue cleanup

## Default chain
```bash
ffmpeg -i work/dialogue_raw.wav -af "\
highpass=f=80:poles=2,\
equalizer=f=250:t=q:w=1.0:g=-3,\
afftdn=nr=10:nf=-50:tn=1,\
deesser=i=0.3,\
acompressor=threshold=-20dB:ratio=3:attack=10:release=120:makeup=2,\
alimiter=limit=0.891:attack=5:release=50:level=false" \
  -ar 48000 -c:a pcm_s24le work/dialogue_clean.wav
```

| Stage | What it does | Adjust when |
|---|---|---|
| `highpass` 80 Hz | Removes rumble, handling noise, HVAC | Deep male voice: 60-70 Hz. Thin voice: up to 100 Hz |
| `equalizer` 250 Hz -3 dB | Reduces "mud" / boxiness | Voice sounds hollow: lessen or skip |
| `afftdn` | Broadband noise reduction | Noise floor < -60 dBFS: skip. Watery/robotic artefacts: lower `nr` |
| `equalizer` 3.5 kHz +2 dB | Presence: clarity on phone speakers | Harsh or sibilant voice: skip |
| `deesser` | Tames harsh "s" | Only if sibilance is obvious in the spectrum |
| `acompressor` 3:1 | Evens out phrase-to-phrase level | Already even (LRA < 5): skip |
| `alimiter` -1 dBFS | Catches stray peaks | Should reduce < 5 dB; if more, compress first |

`afftdn` with `tn=1` tracks the noise as it goes. For a fixed setting instead, find the quietest 0.5 s with `silencedetect`, measure its RMS level with `astats`, and set `nf` to that value.

**Stronger option for heavy noise:** `arnndn=m=<model.rnnn>` (RNNoise; model files from the `rnnoise-models` repo). It can hurt natural tone - use only when `afftdn` is not enough.

The `cva mix clean` default chain is: 80 Hz high-pass, 350 Hz -3 dB, 3.5 kHz +2 dB, light afftdn (AI voices go watery
when pushed), a leveller compressor (2.5:1), a fast peak compressor (6:1 above -10 dB) and a -1 dBFS limiter. The
peak compressor here is what keeps the final master's limiter under ~5 dB.

## Clip-to-clip matching
Process each clip separately when the clips differ a lot (different noise, different loudness), then level each to -16 LUFS before assembly. Process the stem as a whole when the clips are similar.

## Peak control check
After the chain, measure true peak and how hard the limiter worked:
```bash
ffmpeg -i work/dialogue_clean.wav -af ebur128=peak=true -f null - 2>&1 | tail -n 12
```
If the final master's limiter later has to pull more than ~5 dB, add or strengthen the compressor here.
