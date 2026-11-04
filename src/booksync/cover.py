"""Guarantee every imported EPUB has a cover worth showing.

Google returns a 128x184 grey placeholder for uploads it never generated art for.
That is worse than a plain typographic cover, so we detect it and draw our own.
"""
from __future__ import annotations

import colorsys
import hashlib
import io

from PIL import Image, ImageDraw, ImageFont, ImageStat

TITLE_FONT = "/System/Library/Fonts/NewYork.ttf"
AUTHOR_FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
WIDTH, HEIGHT = 1200, 1800


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def usable(data: bytes | None) -> bool:
    if not data:
        return False
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return False
    # Google's placeholder for uploads with no art is 128x184 and almost flat.
    if min(image.size) < 300:
        return False
    stat = ImageStat.Stat(image.convert("RGB"))
    return max(stat.stddev) >= 6


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = (text or "Untitled").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make(title: str, author: str | None) -> bytes:
    seed = int(hashlib.sha256((title or "").encode()).hexdigest()[:8], 16)
    hue = (seed % 360) / 360.0
    back = colorsys.hsv_to_rgb(hue, 0.45, 0.22)
    fore = colorsys.hsv_to_rgb(hue, 0.22, 0.97)
    bg = tuple(int(c * 255) for c in back)
    fg = tuple(int(c * 255) for c in fore)

    image = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(image)

    margin = 120
    title_font = _font(TITLE_FONT, 104)
    lines = _wrap(draw, title, title_font, WIDTH - 2 * margin)[:9]
    line_height = 138
    y = (HEIGHT - len(lines) * line_height) // 2 - 40
    for line in lines:
        draw.text((margin, y), line, font=title_font, fill=fg)
        y += line_height

    if author:
        draw.rectangle([margin, HEIGHT - margin - 118, margin + 170, HEIGHT - margin - 113],
                       fill=fg)
        draw.text((margin, HEIGHT - margin - 92), author, font=_font(AUTHOR_FONT, 48), fill=fg)

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90, optimize=True)
    return buffer.getvalue()


def ensure(path, fetched: bytes | None) -> bool:
    """Give the EPUB a cover worth displaying. Returns True when the file changed."""
    from . import epub

    if usable(epub.cover_bytes(path)) and not epub.has_duplicate_cover(path):
        return False
    if not usable(epub.cover_bytes(path)):
        meta = epub.read_meta(path)
        data = fetched if usable(fetched) else make(meta.title, meta.author)
    else:
        data = epub.cover_bytes(path)
    return epub.inject_cover(path, data)
