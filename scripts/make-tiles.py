#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the tile artwork. Run by hand when the art changes; never at runtime.

    python3 scripts/make-tiles.py            # the English set and the wordless one
    python3 scripts/make-tiles.py --lang fr  # a set for another language

The specification every number here comes from is docs/tile-art.md, which also
records where each mark came from and under what licence. The marks themselves
are in assets/marks/, vendored so a rebuild needs no network.

Adding a language: put its strings in locales/<code>.json, then run this with
--lang <code>. It writes assets/tiles/<code>/. Only do that for a script that
renders correctly -- see docs/tile-art.md; the wordless set exists because most
scripts do not.
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKS = os.path.join(ROOT, "assets", "marks")
TILES = os.path.join(ROOT, "assets", "tiles")
LOCALES = os.path.join(ROOT, "locales")

W, H = 600, 800
GLYPH_TOP, GLYPH_H, GLYPH_MAXW = 150, 330, 420
MARGIN = 48

# Arial Bold on macOS; DejaVu Sans Bold is the usual Linux stand-in. If neither
# is here, say so rather than silently drawing in something else: the fitted
# sizes in docs/tile-art.md are for this face.
FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
)
FONT = next((p for p in FONTS if os.path.isfile(p)), "")

DARK, LIGHT = (33, 33, 33), (117, 117, 117)
SUN = [(253, 209, 7), (248, 154, 28), (242, 98, 34), (239, 62, 35)]
GREY_MID, GREY = (154, 160, 168), (108, 117, 125)

def background():
    bg = Image.new("RGB", (W, H))
    px = bg.load()
    # Distance along the diagonal, normalised, with the plateau Sunshine has.
    span = (W + H) * 0.86
    for y in range(H):
        for x in range(W):
            t = min(1.0, (x + y) / span)
            px[x, y] = tuple(int(DARK[i] + (LIGHT[i] - DARK[i]) * t) for i in range(3))
    return bg


def place(tile, mark, box_h=330, top=150):
    """Centre a mark in the upper area, scaled to a common optical size."""
    ratio = mark.width / mark.height
    h = box_h
    w = int(h * ratio)
    if w > 420:
        w, h = 420, int(420 / ratio)
    resized = mark.resize((w, h), Image.LANCZOS)
    tile.paste(resized, ((W - w) // 2, top + (box_h - h) // 2), resized)


MARGIN = 48                          # keep the name clear of the edges


def caption(tile, name):
    draw = ImageDraw.Draw(tile)
    if "\n" in name:
        lines = [part.strip().upper() for part in name.split("\n")]
    else:
        words = name.upper().split()
        lines = ([words[0], " ".join(words[1:])]
                 if len(name) > 11 and len(words) > 1 else [" ".join(words)])

    def width_of(line, font, spacing):
        text = (" " * spacing).join(line) if spacing else line
        box = draw.textbbox((0, 0), text, font=font)
        return box[2] - box[0], text

    # Sunshine's art letter-spaces its captions. Keep that where it fits and
    # give it up before letting a name run off the tile.
    for spacing in (1, 0):
        for size in range(66, 33, -2):
            font = ImageFont.truetype(FONT, size)
            rendered = [width_of(l, font, spacing) for l in lines]
            if all(w <= W - 2 * MARGIN for w, _ in rendered):
                y = 600 if len(lines) == 2 else 630
                for w, text in rendered:
                    draw.text(((W - w) / 2, y), text, font=font, fill="white")
                    y += size + 14
                return
    raise ValueError("no size fits %r" % name)


def rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def our_mark():
    """Design D: three covers on a shelf, the near one lit."""
    s = 4
    m = Image.new("RGBA", (100 * s, 100 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    for x, y, h, colour in ((64, 30, 46, GREY), (39, 25, 52, GREY_MID)):
        rounded(d, [x * s, y * s, (x + 30) * s, (y + h) * s], 6 * s, colour + (255,))
    # The lit one, painted as a vertical ramp through Sunshine's palette.
    lit = Image.new("RGBA", (30 * s, 60 * s), (0, 0, 0, 0))
    lp = lit.load()
    stops = SUN                       # four stops, evenly spaced down the face
    for yy in range(lit.height):
        t = yy / max(1, lit.height - 1) * (len(stops) - 1)
        i = min(int(t), len(stops) - 2)
        k = t - i
        a, b = stops[i], stops[i + 1]
        colour = tuple(int(round(a[c] + (b[c] - a[c]) * k)) for c in range(3))
        for xx in range(lit.width):
            lp[xx, yy] = colour + (255,)
    mask = Image.new("L", lit.size, 0)
    rounded(ImageDraw.Draw(mask), [0, 0, lit.width - 1, lit.height - 1], 6 * s, 255)
    m.paste(lit, (12 * s, 20 * s), mask)
    return m.resize((460, 460), Image.LANCZOS)


def glyph_monitor():
    s, size = 4, 100
    m = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    rounded(d, [8 * s, 18 * s, 92 * s, 74 * s], 7 * s, (255, 255, 255, 255))
    rounded(d, [17 * s, 27 * s, 83 * s, 65 * s], 3 * s, (0, 0, 0, 0))
    d.rectangle([44 * s, 72 * s, 56 * s, 86 * s], fill=(255, 255, 255, 255))
    rounded(d, [32 * s, 84 * s, 68 * s, 94 * s], 5 * s, (255, 255, 255, 255))
    return m


def glyph_restart():
    s, size = 4, 100
    m = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    d.ellipse([14 * s, 14 * s, 86 * s, 86 * s], outline=(255, 255, 255, 255),
              width=10 * s)
    # Break the ring at the top-right, then put an arrowhead there.
    d.pieslice([14 * s, 14 * s, 86 * s, 86 * s], -85, -5, fill=(0, 0, 0, 0),
               outline=(0, 0, 0, 0), width=0)
    d.rectangle([50 * s, 0, 100 * s, 22 * s], fill=(0, 0, 0, 0))
    d.polygon([(46 * s, 2 * s), (46 * s, 34 * s), (78 * s, 18 * s)],
              fill=(255, 255, 255, 255))
    return m


def build(name, mark, filename, box_h=330, top=150):
    tile = background()
    if mark is not None:
        place(tile, mark, box_h, top)
    caption(tile, name)
    path = os.path.join(OUT, filename)
    tile.save(path)
    return path



def _platform_glyph(name, size):
    """Drawn here, simply, rather than shipping anyone's brand asset."""
    s = 4
    m = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    white = (255, 255, 255, 255)
    if name == "windows":
        # Four panes, the shape Windows has used since 8.
        gap, pane = 6 * s, (size // 2 - 5) * s
        for col in range(2):
            for row in range(2):
                x = col * (pane + gap)
                y = row * (pane + gap)
                d.rectangle([x, y, x + pane, y + pane], fill=white)
    elif name == "linux":
        tux = Image.open(os.path.join(MARKS, "tux.png")).convert("RGBA")
        h = int(size * s * 0.98)
        w = int(h * tux.width / tux.height)
        tux = tux.resize((w, h), Image.LANCZOS)
        m.paste(tux, ((size * s - w) // 2, (size * s - h) // 2), tux)
        return m
    elif name == "linux_drawn":
        # A penguin, in the plainest terms: body, head, beak, feet.
        cx = size * s / 2
        d.ellipse([cx - 26 * s, 24 * s, cx + 26 * s, 92 * s], fill=white)
        d.ellipse([cx - 18 * s, 2 * s, cx + 18 * s, 40 * s], fill=white)
        d.polygon([(cx - 7 * s, 26 * s), (cx + 7 * s, 26 * s), (cx, 36 * s)],
                  fill=(0, 0, 0, 0))
        d.ellipse([cx - 11 * s, 12 * s, cx - 3 * s, 22 * s], fill=(0, 0, 0, 0))
        d.ellipse([cx + 3 * s, 12 * s, cx + 11 * s, 22 * s], fill=(0, 0, 0, 0))
        d.ellipse([cx - 30 * s, 84 * s, cx - 6 * s, 98 * s], fill=white)
        d.ellipse([cx + 6 * s, 84 * s, cx + 30 * s, 98 * s], fill=white)
    elif name == "macos":
        apple = Image.open(os.path.join(MARKS, "apple.png")).convert("RGBA")
        h = int(size * s * 0.92)
        w = int(h * apple.width / apple.height)
        apple = apple.resize((w, h), Image.LANCZOS)
        m.paste(apple, ((size * s - w) // 2, (size * s - h) // 2), apple)
        return m
    elif name == "macos_drawn":
        # Two overlapping lobes make an apple; a bite out of the right, a leaf
        # on top. Drawn plainly -- it stands for "this is a Mac", no more.
        cx = size * s / 2
        d.ellipse([cx - 34 * s, 28 * s, cx + 10 * s, 94 * s], fill=white)
        d.ellipse([cx - 10 * s, 28 * s, cx + 34 * s, 94 * s], fill=white)
        d.rectangle([cx - 12 * s, 40 * s, cx + 12 * s, 90 * s], fill=white)
        d.ellipse([cx + 22 * s, 44 * s, cx + 58 * s, 80 * s], fill=(0, 0, 0, 0))
        d.rectangle([cx - 6 * s, 14 * s, cx + 2 * s, 32 * s], fill=(0, 0, 0, 0))
        d.polygon([(cx + 1 * s, 30 * s), (cx + 6 * s, 8 * s),
                   (cx + 20 * s, 14 * s), (cx + 9 * s, 31 * s)], fill=white)
    return m


def glyph_monitor_for(platform=None):
    """The monitor, with the host's platform showing on the screen."""
    s, size = 4, 100
    m = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    # A 5-unit bezel, not 9: the screen is the subject, the frame is not.
    rounded(d, [8 * s, 16 * s, 92 * s, 74 * s], 6 * s, (255, 255, 255, 255))
    rounded(d, [13 * s, 21 * s, 87 * s, 69 * s], 3 * s, (0, 0, 0, 0))
    d.rectangle([46 * s, 74 * s, 54 * s, 86 * s], fill=(255, 255, 255, 255))
    rounded(d, [34 * s, 86 * s, 66 * s, 93 * s], 3 * s, (255, 255, 255, 255))
    if platform is not None:
        mark = (platform if isinstance(platform, Image.Image)
                else _platform_glyph(platform, 100))
        box = 30 * s
        ratio = mark.width / mark.height
        w = box if ratio >= 1 else int(box * ratio)
        h = box if ratio <= 1 else int(box / ratio)
        mark = mark.resize((w, h), Image.LANCZOS)
        m.paste(mark, ((100 * s - w) // 2, 23 * s + (44 * s - h) // 2), mark)
    return m


def glyph_tv(inner=None):
    """A television, for Big Picture.

    Deliberately not the monitor: Big Picture and the desktop are two tiles on
    the same grid, and a Steam roundel inside the desktop's monitor would read
    as "the desktop, with Steam on it". A television is wider, sits on feet
    rather than a pedestal, and is what Big Picture is for.
    """
    s, size = 4, 100
    m = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(m)
    rounded(d, [4 * s, 14 * s, 96 * s, 76 * s], 6 * s, (255, 255, 255, 255))
    rounded(d, [9 * s, 19 * s, 91 * s, 71 * s], 3 * s, (0, 0, 0, 0))
    # Two feet, near the corners, and no rail between them: with a bar across
    # the bottom it stopped being a television and became a monitor on a
    # stand, which is the glyph this one exists not to be.
    d.polygon([(8 * s, 90 * s), (22 * s, 76 * s), (31 * s, 76 * s),
               (17 * s, 90 * s)], fill=(255, 255, 255, 255))
    d.polygon([(92 * s, 90 * s), (78 * s, 76 * s), (69 * s, 76 * s),
               (83 * s, 90 * s)], fill=(255, 255, 255, 255))
    if inner is not None:
        # Larger than the monitor's 30: this screen is wider, and a mark that
        # left as much dead glass as the desktop tile does reads as an empty
        # television rather than one with something on it.
        box = 42 * s
        ratio = inner.width / inner.height
        w = box if ratio >= 1 else int(box * ratio)
        h = box if ratio <= 1 else int(box / ratio)
        sized = inner.resize((w, h), Image.LANCZOS)
        m.paste(sized, ((100 * s - w) // 2, 19 * s + (52 * s - h) // 2), sized)
    return m


# --- the marks we ship ------------------------------------------------------

def mark(name):
    return Image.open(os.path.join(MARKS, name)).convert("RGBA")


def distro_mark(name):
    return Image.open(os.path.join(MARKS, "distro", name + ".png")).convert("RGBA")


DISTROS = ("arch", "bazzite", "debian", "fedora", "mint", "ubuntu")


def build_worded(out_dir, strings):
    """One set, with captions, in one language."""
    made = []

    def write(key, glyph, filename, second_line=False):
        text = strings.get(key, key)
        if second_line and "desktop_low_res" in strings:
            text = strings["desktop_low_res"]
        tile = background()
        place(tile, glyph)
        caption(tile, text)
        path = os.path.join(out_dir, filename)
        tile.save(path)
        made.append(filename)

    write("app_manager", our_mark(), "app-manager.png")
    write("steam", mark("steam.png"), "steam.png")
    write("steam_big_picture", glyph_tv(mark("steam.png")),
          "steam-bigpicture.png")
    write("heroic", mark("heroic.png"), "heroic.png")
    write("reboot_host", glyph_restart(), "reboot-host.png")
    for platform in ("windows", "macos", "linux"):
        write("desktop", glyph_monitor_for(platform), "desktop-%s.png" % platform)
        write("desktop_low_res", glyph_monitor_for(platform),
              "desktop-lowres-%s.png" % platform, second_line=True)
    for name in DISTROS:
        glyph = glyph_monitor_for(distro_mark(name))
        write("desktop", glyph, "desktop-%s.png" % name)
        write("desktop_low_res", glyph, "desktop-lowres-%s.png" % name,
              second_line=True)
    return made


def build_wordless(out_dir):
    """The set with no text, which is right in every language."""
    made = []

    def write(glyph, filename, box=430):
        tile = background()
        ratio = glyph.width / glyph.height
        h = box
        w = int(h * ratio)
        if w > 470:
            w, h = 470, int(470 / ratio)
        sized = glyph.resize((w, h), Image.LANCZOS)
        tile.paste(sized, ((W - w) // 2, (H - h) // 2), sized)
        tile.save(os.path.join(out_dir, filename))
        made.append(filename)

    write(our_mark(), "app-manager.png")
    write(mark("steam.png"), "steam.png")
    write(glyph_tv(mark("steam.png")), "steam-bigpicture.png")
    write(mark("heroic.png"), "heroic.png")
    write(glyph_restart(), "reboot-host.png")
    for platform in ("windows", "macos", "linux"):
        write(glyph_monitor_for(platform), "desktop-%s.png" % platform)
    for name in DISTROS:
        write(glyph_monitor_for(distro_mark(name)), "desktop-%s.png" % name)
    # No caption means no "(Low Res)" either, so the same picture serves both.
    for name in list(made):
        if name.startswith("desktop-"):
            src = Image.open(os.path.join(out_dir, name))
            src.save(os.path.join(out_dir, name.replace("desktop-", "desktop-lowres-")))
    return made


def build_template(out_dir):
    """Canvases for somebody adding text by hand.

    The *worded* layout with no words: the mark sits in the glyph box with the
    caption area empty below it. Built from the wordless set it would be
    misleading -- there the mark is centred in the whole tile, because there is
    nothing underneath to balance against, and text added under it would sit
    too low.
    """
    made = []

    def write(glyph, filename):
        tile = background()
        place(tile, glyph)
        tile.save(os.path.join(out_dir, filename))
        made.append(filename)

    write(our_mark(), "app-manager.png")
    write(mark("steam.png"), "steam.png")
    write(glyph_tv(mark("steam.png")), "steam-bigpicture.png")
    write(mark("heroic.png"), "heroic.png")
    write(glyph_restart(), "reboot-host.png")
    for platform in ("windows", "macos", "linux"):
        write(glyph_monitor_for(platform), "desktop-%s.png" % platform)
    for name in DISTROS:
        write(glyph_monitor_for(distro_mark(name)), "desktop-%s.png" % name)
    return made


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="en",
                        help="language code; must have locales/<code>.json")
    parser.add_argument("--wordless-only", action="store_true")
    parser.add_argument("--template", action="store_true",
                        help="rebuild assets/tiles/_template (canvases for "
                             "hand-lettering a language we cannot render)")
    args = parser.parse_args(argv)

    if not FONT:
        print("No suitable bold font found. Looked for:\n  " +
              "\n  ".join(FONTS), file=sys.stderr)
        return 2

    if args.template:
        out = os.path.join(TILES, "_template")
        os.makedirs(out, exist_ok=True)
        made = build_template(out)
        print("template: %d canvases in %s" % (len(made), out))
        return 0

    wordless_dir = os.path.join(TILES, "_wordless")
    os.makedirs(wordless_dir, exist_ok=True)
    made = build_wordless(wordless_dir)
    print("wordless: %d tiles in %s" % (len(made), wordless_dir))
    if args.wordless_only:
        return 0

    catalogue = os.path.join(LOCALES, args.lang + ".json")
    if not os.path.isfile(catalogue):
        print("No catalogue at %s. Copy locales/en.json and translate it."
              % catalogue, file=sys.stderr)
        return 2
    with open(catalogue, encoding="utf-8") as handle:
        strings = (json.load(handle).get("tiles") or {})
    strings = {k: v for k, v in strings.items() if not k.startswith("_")}

    out_dir = os.path.join(TILES, args.lang)
    os.makedirs(out_dir, exist_ok=True)
    made = build_worded(out_dir, strings)
    print("%s: %d tiles in %s" % (args.lang, len(made), out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
