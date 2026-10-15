#!/usr/bin/env bash
# End-to-end smoke test of the tool chain (no agent): edit -> level -> clean -> score -> duck -> master -> deliver.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HERE/.venv/bin"
P="${1:-$(mktemp -d)/episode}"
mkdir -p "$P/src"
q="-hide_banner -loglevel error -y"
for i in 1 2 3; do
  ffmpeg $q -f lavfi -i "testsrc2=s=1080x1920:r=24:d=6" -f lavfi -i "sine=f=$((200*i)):d=6:sample_rate=48000" \
    -af "volume=-$((14+6*i))dB,aformat=channel_layouts=stereo" -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
    -c:a aac -shortest "$P/src/v$i.mp4"
done
mkdir -p "$P/assets/hits"
ffmpeg $q -f lavfi -i "sine=f=55:d=1.5:sample_rate=48000" -af "afade=t=out:st=0:d=1.5,aformat=channel_layouts=stereo" "$P/assets/hits/boom.wav"

j() { "$@" > /tmp/cva_smoke_out.json || { cat /tmp/cva_smoke_out.json; exit 1; }; }
cd "$P"
j "$BIN/vv" init --fps 24
for i in 1 2 3; do j "$BIN/vv" source add "src/v$i.mp4"; done
j "$BIN/vv" clip add v1 --in 0.25 --out 5.5
j "$BIN/vv" clip add v2 --in 0.5 --out 5.0
j "$BIN/vv" clip add v3 --in 0.2 --out 5.8
j "$BIN/vv" transition set c2 --type dissolve --frames 8
j "$BIN/vv" transition set c3 --type dip --frames 16
j "$BIN/vv" punch set c2 --scale 1.15 --x 0.55 --y 0.45
j "$BIN/vv" end --fade-frames 24
j "$BIN/vv" overlay title "EPISODE 4" --start 0.5 --end 3.0 --y "H*0.2"
j "$BIN/cva" mix level-takes --target -16
"$BIN/vv" render | tee /tmp/cva_render.json | head -5
V=$(python3 -c "import json;print(json.load(open('/tmp/cva_render.json'))['v'])")
j "$BIN/cva" mix clean "work/dialogue_v$V.wav" "work/dialogue_clean_v$V.wav"

# a tiny score with a hit on the scene change
echo '{"regions": [[0.5, 4.5], [6.0, 9.5]]}' > "work/speech_manual.json"
j "$BIN/vd" init
j "$BIN/vd" cue import --cutlist "work/cutlist_v$V.json" --speech work/speech_manual.json
LIB="$HERE/assets/libs/VSCO-2-CE"
if [ -f "$LIB/CelloEnsSusVib.sfz" ] && [ -f "$LIB/Harp.sfz" ]; then   # real samples when fetched
  ln -sfn "$HERE/assets/libs" assets/libs
  j "$BIN/vd" part add strings --patch assets/libs/VSCO-2-CE/Harp.sfz --role pluck
  j "$BIN/vd" part add celli --patch assets/libs/VSCO-2-CE/CelloEnsSusVib.sfz --role bass
else
  j "$BIN/vd" part add strings --role pad
  j "$BIN/vd" part add celli --role bass
fi
j "$BIN/vd" chord add strings --t 0 --d 9 --notes D3,A3,F4 --v 40
j "$BIN/vd" gen ostinato celli --pattern D2,D2,A2,D2 --from 9.8 --to 15.5 --step 0.25 --v 60
j "$BIN/vd" hit place assets/hits/boom.wav --cue cut:c3
"$BIN/vd" check | head -3
"$BIN/vd" render --tag m1 | head -3
j "$BIN/cva" mix duck work/music_m1.wav work/music_ducked.wav --speech work/speech_manual.json
j "$BIN/cva" mix sum work/premix.wav --stem "dialogue=work/dialogue_clean_v$V.wav" --stem "music=work/music_ducked.wav@-4"
"$BIN/cva" mix master work/premix.wav work/master.wav | grep -E '"(pass|integrated_lufs|true_peak_dbtp)"'
"$BIN/vv" deliver --audio work/master.wav | grep -E '^ "(file|pass|summary)"|PASS|FAIL'
echo "project: $P"
