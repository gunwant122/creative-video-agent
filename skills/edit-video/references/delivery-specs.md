# Delivery specs and the check gate

## Targets
| Platform | Picture | Audio loudness | True peak |
|---|---|---|---|
| Reels / TikTok / Shorts | 1080x1920, source fps (24/25/30), H.264 High, yuv420p | -14 LUFS integrated | <= -1 dBTP |
| YouTube (16:9) | 1920x1080 or 3840x2160, H.264/H.265 | -14 LUFS | <= -1 dBTP |
| Podcast / voice-only | - | -16 LUFS | <= -1 dBTP |
| Broadcast (EBU R128) | per spec | -23 LUFS | <= -1 dBTP |

Container: MP4, `+faststart`, AAC 48 kHz stereo, 192-320 kb/s. Video CRF 17-20 (x264 `preset slow`) for masters to be uploaded.

## Final encode (from the timeline render or a mixed master)
```bash
ffmpeg -i picture.mp4 -i mix_mastered.wav -map 0:v -map 1:a \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -profile:v high \
  -c:a aac -b:a 256k -ar 48000 -movflags +faststart -shortest renders/vN.mp4
```

## Check gate - every render, no exceptions
Run all of these and record the results in `notes.md`. Any FAIL means fix and re-render.

1. **Specs**
   ```bash
   ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels \
     -show_entries format=duration -of json renders/vN.mp4
   ```
   PASS: resolution, fps, pix_fmt, audio rate match the target.
2. **Loudness and true peak**
   ```bash
   ffmpeg -hide_banner -nostats -i renders/vN.mp4 -map 0:a -af ebur128=peak=true -f null - 2>&1 | tail -n 12
   ```
   PASS: integrated within +-1 LU of target, true peak <= -1 dBTP.
3. **Length** - matches the edit's expected duration (+-1 frame) and any platform max.
4. **Black / frozen frames** where none were intended
   ```bash
   ffmpeg -i renders/vN.mp4 -vf "blackdetect=d=0.1:pix_th=0.10,freezedetect=n=0.003:d=0.5" -an -f null - 2>&1 | grep -E "black_|freeze_"
   ```
   PASS: only the intended dips to black appear.
5. **Silence holes** where speech or music should be
   ```bash
   ffmpeg -i renders/vN.mp4 -af silencedetect=noise=-50dB:d=0.7 -vn -f null - 2>&1 | grep silence_
   ```
6. **Stills at every cut and transition** - extract one frame just before and after each cut (`analyze-media`) and look at them.
7. **Clipping** - no `-0.0 dBFS` peaks; `ebur128` true peak covers this.

## What you cannot check
You cannot listen. State this every time: music balance, emotional feel, and voice tone are for the user to judge by ear.
