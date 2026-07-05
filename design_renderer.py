"""
Renders a simple, original typography design as a transparent PNG suitable
for print-on-demand (t-shirts, mugs, tote bags, etc).

This deliberately keeps things simple: centered text, wrapped to fit, on a
transparent background so it can sit on any product/garment color. No
external images or fonts with unclear licensing are used - only DejaVu Sans
Bold, which ships under a permissive license and is installed via apt in the
GitHub Actions workflow.
"""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]

CANVAS_SIZE = (2000, 2000)  # print-resolution square canvas


def _find_font(size):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    # fall back so local testing without the font installed still works
    return ImageFont.load_default()


def render_design(text, out_path, text_color="#111111", bg_color=None, max_chars_per_line=14):
    img = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0) if bg_color is None else bg_color)
    draw = ImageDraw.Draw(img)

    wrapped = textwrap.fill(text.upper(), width=max_chars_per_line)
    lines = wrapped.split("\n")

    font_size = 220
    font = _find_font(font_size)

    # shrink until the block fits within the canvas with margin
    margin = 200
    while font_size > 40:
        font = _find_font(font_size)
        line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        widths = [b[2] - b[0] for b in line_sizes]
        line_height = max(b[3] - b[1] for b in line_sizes) * 1.25
        total_height = line_height * len(lines)
        if max(widths) <= CANVAS_SIZE[0] - margin and total_height <= CANVAS_SIZE[1] - margin:
            break
        font_size -= 10

    line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_height = max(b[3] - b[1] for b in line_sizes) * 1.25
    total_height = line_height * len(lines)
    y = (CANVAS_SIZE[1] - total_height) / 2

    for line, box in zip(lines, line_sizes):
        w = box[2] - box[0]
        x = (CANVAS_SIZE[0] - w) / 2
        draw.text((x, y), line, font=font, fill=text_color)
        y += line_height

    img.save(out_path, "PNG")
    return out_path
