# Loudness levelling and mastering

## Levelling a clip or stem to a target (two-pass loudnorm)
Pass 1 - measure:
```bash
ffmpeg -hide_banner -i in.wav -af loudnorm=I=-16:TP=-2:LRA=11:print_format=json -f null - 2>&1 | tail -n 12
```
Pass 2 - apply with the measured values (linear mode keeps dynamics, it is just gain):
```bash
ffmpeg -i in.wav -af "loudnorm=I=-16:TP=-2:LRA=11:measured_I=<input_i>:measured_TP=<input_tp>:measured_LRA=<input_lra>:measured_thresh=<input_thresh>:offset=<target_offset>:linear=true" \
  -ar 48000 -c:a pcm_s24le out.wav
```
loudnorm upsamples internally to 192 kHz - always set `-ar 48000` on output. If pass 2 reports `normalization_type: dynamic`, the true-peak target could not be met with linear gain: add peak control (compressor/limiter) before it.

## Summing stems
```bash
ffmpeg -i work/dialogue_clean_vN.wav -i work/music_ducked_vN.wav -i work/fx_vN.wav -filter_complex "\
[0:a]volume=0dB[d];[1:a]volume=-2dB[m];[2:a]volume=-3dB[f];\
[d][m][f]amix=inputs=3:normalize=0:duration=longest[mix]" \
  -map "[mix]" -c:a pcm_s24le work/premix_vN.wav
```
Start with dialogue at 0 dB. For music, a sane starting point is music-only passages measuring around -18 to -20 LUFS against -16 LUFS dialogue (measure a music-only stretch with `ebur128`), then adjust by measurement.

## Mastering
Targets: -14 LUFS / -1 dBTP social and YouTube; -16 voice; -23 broadcast.
```bash
# measure premix, then:
ffmpeg -i work/premix_vN.wav -af "alimiter=limit=0.84:attack=3:release=60:level=false,loudnorm=I=-14:TP=-1:LRA=11:measured_I=..:measured_TP=..:measured_LRA=..:measured_thresh=..:offset=..:linear=true" \
  -ar 48000 -c:a pcm_s24le work/master_vN.wav
```
Measure the limiter's work: compare premix true peak to the limiter ceiling. More than ~5 dB of limiting means the mix needs more compression earlier.

## Verify
```bash
ffmpeg -i work/master_vN.wav -af ebur128=peak=true -f null - 2>&1 | tail -n 12
```
PASS: integrated within +-1 LU of target, true peak <= -1 dBTP. Record both in `notes.md`.
