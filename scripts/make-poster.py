#!/usr/bin/env python3
"""Draw the poster Sunshine shows for this manager's own tile.

Committed as a script rather than only as a PNG so the image can be redrawn
when the name changes -- which is exactly what went wrong the first time: the
tile was renamed and its artwork went on saying "APPS IMPORT".

    python3 scripts/make-poster.py assets/poster.png

600x900 because that is the shape Moonlight lays tiles out in, and the size
every other cover in this project is normalised to.
"""

import sys
from PIL import Image, ImageDraw, ImageFont

SIZE = (600, 900)
EDGE = (65, 76, 89)        # sampled from the poster this replaces, so the
CENTRE = (47, 56, 67)      # tile does not change character, only its wording
INK = (255, 255, 255)

LINES = ("APP", "MANAGER")
TRACKING = 10              # the original's letters are noticeably spaced

FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("No bold sans font found; add one to FONTS")


def _background() -> Image.Image:
    """A soft radial vignette, lighter at the edges than in the middle."""
    image = Image.new("RGB", SIZE, EDGE)
    pixels = image.load()
    cx, cy = SIZE[0] / 2, SIZE[1] / 2
    longest = (cx ** 2 + cy ** 2) ** 0.5
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            distance = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / longest
            pixels[x, y] = tuple(
                round(c + (e - c) * distance) for c, e in zip(CENTRE, EDGE))
    return image


def _tiles(draw: ImageDraw.ImageDraw) -> None:
    """A grid of tiles, with one picked out: what this thing manages.

    The icon it replaces was a download arrow, which said "import" -- the one
    thing this is no longer only for.
    """
    cols, rows = 3, 3
    side, gap = 96, 26
    width = cols * side + (cols - 1) * gap
    height = rows * side + (rows - 1) * gap
    left = (SIZE[0] - width) // 2
    top = 210
    for row in range(rows):
        for col in range(cols):
            x = left + col * (side + gap)
            y = top + row * (side + gap)
            box = (x, y, x + side, y + side)
            if (row, col) == (1, 1):
                draw.rounded_rectangle(box, radius=16, fill=INK)
            else:
                draw.rounded_rectangle(box, radius=16, outline=INK, width=7)


def _caption(draw: ImageDraw.ImageDraw) -> None:
    font = _font(84)
    baseline = 656
    for index, line in enumerate(LINES):
        widths = [draw.textlength(ch, font=font) for ch in line]
        total = sum(widths) + TRACKING * (len(line) - 1)
        x = (SIZE[0] - total) / 2
        y = baseline + index * 104
        for ch, width in zip(line, widths):
            draw.text((x, y), ch, font=font, fill=INK)
            x += width + TRACKING


def main(argv):
    destination = argv[1] if len(argv) > 1 else "assets/poster.png"
    image = _background()
    draw = ImageDraw.Draw(image)
    _tiles(draw)
    _caption(draw)
    image.save(destination, format="PNG")
    print(f"wrote {destination} ({image.size[0]}x{image.size[1]})")


if __name__ == "__main__":
    main(sys.argv)
