"""Draw text cards as transparent PNGs. Run as a child process (see cva.motion.draw_cards) so the
dynamic loader can find libraqm for correct Devanagari / complex-script shaping."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

LATIN_FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/SFNS.ttf",
               "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
DEVANAGARI_FONTS = ["/System/Library/Fonts/Supplemental/ITFDevanagari.ttc",
                    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
                    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"]
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def pick_font(text: str, size: int, font: str | None) -> tuple[ImageFont.FreeTypeFont, str]:
    cands = ([font] if font else []) + (DEVANAGARI_FONTS if DEVANAGARI.search(text) else []) + LATIN_FONTS
    for f in cands:
        if f and Path(f).exists():
            try:
                kw = {"layout_engine": ImageFont.Layout.RAQM} if features.check("raqm") else {}
                # .ttc: index 1 is usually the bold face for ITF Devanagari; fall back to 0
                for idx in ((1, 0) if f.endswith(".ttc") else (0,)):
                    try:
                        return ImageFont.truetype(f, size, index=idx, **kw), f
                    except OSError:
                        continue
            except OSError:
                continue
    return ImageFont.load_default(size), "default"


def wrap(text: str, max_chars: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:  # squeeze into max_lines by re-wrapping wider
        return wrap(text, int(max_chars * 1.25) + 1, max_lines) if max_chars < 200 else lines[:max_lines]
    return lines


def draw(card: dict) -> dict:
    text = card["text"]
    size = int(card.get("size", 64))
    font, font_path = pick_font(text, size, card.get("font"))
    lines = wrap(text, int(card.get("max_chars", 32)), int(card.get("max_lines", 2)))
    stroke = int(card.get("stroke", max(2, size // 14)))
    pad = int(card.get("pad", size // 3))
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    boxes = [tmp.textbbox((0, 0), ln, font=font, stroke_width=stroke) for ln in lines]
    line_h = int(size * 1.25)
    w = max(b[2] - b[0] for b in boxes) + 2 * pad
    h = line_h * len(lines) + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if card.get("box"):
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=size // 4, fill=tuple(card["box"]))
    fill = tuple(card.get("color", (255, 255, 255, 255)))
    for i, (ln, b) in enumerate(zip(lines, boxes)):
        x = (w - (b[2] - b[0])) // 2 - b[0]
        y = pad + i * line_h + (line_h - size) // 2 - b[1] // 2
        d.text((x, y), ln, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 230))
    img.save(card["out"])
    return {"out": card["out"], "w": w, "h": h, "lines": lines, "font": font_path,
            "shaping": "raqm" if features.check("raqm") else "basic"}


if __name__ == "__main__":
    cards = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps([draw(c) for c in cards]))
