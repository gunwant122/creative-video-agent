#!/usr/bin/env bash
# One-time setup on macOS (Apple Silicon or Intel). Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== system tools (Homebrew) =="
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list cmake >/dev/null 2>&1 || brew install cmake
brew list ninja >/dev/null 2>&1 || brew install ninja
brew list fluid-synth >/dev/null 2>&1 || brew install fluid-synth
brew list libraqm >/dev/null 2>&1 || brew install libraqm   # Devanagari / complex-script captions
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q " drawtext "; then
  echo "note: this ffmpeg has no drawtext/subtitles (built without freetype/libass)."
  echo "      Frame sheets fall back to a computed time map; for labelled sheets install a full build, e.g."
  echo "      brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg"
fi

echo "== python env =="
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[agent,server,gen,otio,dev]"
if [ "$(uname -m)" = "arm64" ]; then .venv/bin/pip install -q -e ".[transcribe]"; else .venv/bin/pip install -q whisperx; fi

echo "== sfizz_render (SFZ player, built from source - not in Homebrew) =="
if [ ! -x tools/bin/sfizz_render ]; then
  mkdir -p tools/bin
  [ -d tools/sfizz ] || git clone -q --depth 1 --recurse-submodules --shallow-submodules https://github.com/sfztools/sfizz.git tools/sfizz
  cmake -S tools/sfizz -B tools/sfizz/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DSFIZZ_JACK=OFF -DSFIZZ_RENDER=ON \
    -DSFIZZ_SHARED=OFF -DSFIZZ_TESTS=OFF -DSFIZZ_BENCHMARKS=OFF -DSFIZZ_DEMOS=OFF -DSFIZZ_DEVTOOLS=OFF \
    -DPLUGIN_LV2=OFF -DPLUGIN_VST3=OFF -DPLUGIN_AU=OFF -DPLUGIN_PUREDATA=OFF >/dev/null
  ninja -C tools/sfizz/build sfizz_render >/dev/null
  cp tools/sfizz/build/library/bin/sfizz_render tools/bin/
fi

echo "== orchestra samples (VSCO 2 CE, CC0) - only the instruments you need =="
# the full library is ~3 GB; 'core' is a ~510 MB cinematic chamber palette. See --list for all 75 instruments.
.venv/bin/python scripts/fetch_instruments.py core --dry-run
read -r -p "Download the core palette now? [y/N] " yn
if [ "${yn:-n}" = "y" ]; then .venv/bin/python scripts/fetch_instruments.py core; fi
mkdir -p assets/hits
printf '%s\n' "- VSCO 2 Community Edition - Versilian Studios - CC0 - https://github.com/sgossner/VSCO-2-CE (SFZ branch)" \
  "- Add CC0 hits (timpani, booms, cymbals, risers) to assets/hits/ and list their source here." > assets/CREDITS.md

echo "== Remotion skills (optional, needs Node) =="
if command -v npx >/dev/null; then
  (cd skills && npx --yes skills add remotion-dev/skills) || echo "could not add remotion-dev/skills - add later with: npx skills add remotion-dev/skills"
fi

echo "== keys =="
[ -f .env ] || cat > .env <<'EOF'
# ANTHROPIC_API_KEY=...
# ELEVENLABS_API_KEY=...   (optional, paid generation)
# FAL_KEY=...              (optional, paid generation)
EOF
echo "Edit .env with your keys, then run: .venv/bin/python -m cva.server.app  (http://127.0.0.1:8765)"
