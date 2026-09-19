# Tile art: how it is made, so the next one matches

Every tile this program writes into `apps.json` is built to one template. This
is that template, written down, because artwork that cannot be reproduced is
artwork that drifts: the next person adds a tile, eyeballs it, and the grid
stops looking like a set.

Sunshine draws the grid, so the template follows **Sunshine's own** art
(`/usr/share/sunshine/desktop.png`) rather than inventing a look beside it.
Everything below was sampled from that file.

## The canvas

| | |
|---|---|
| Size | **600 × 800** — what Sunshine's own tiles are, not 600 × 900 |
| Format | PNG, 8-bit RGB, no alpha (the background is always opaque) |
| Background | linear gradient along the diagonal, top-left to bottom-right |
| From | `#212121` at the top-left corner |
| To | `#757575`, reached at **86 %** of the diagonal and flat after that |

The ramp is computed per pixel as `t = min(1, (x + y) / ((600 + 800) × 0.86))`,
then `colour = dark + (light − dark) × t`. The plateau is not decoration: it is
what Sunshine's own file does, and without it the bottom-right corner is
lighter than the tiles beside it.

Sunshine tints *some* of its own tiles — its `steam.png` is a blue-grey version
of the same ramp. We use the neutral one for every tile, so ours read as one
family.

## The layout

| | |
|---|---|
| Side margins | **48 px**, and no caption may cross them |
| Glyph box | **420 × 330**, horizontally centred, **top at y = 150** |
| Glyph scaling | fit inside the box, preserving aspect; centred within it |
| Caption, one line | top at **y = 630** |
| Caption, two lines | top at **y = 600**, second line at `y + size + 14` |

A name of more than eleven characters that has a space in it is split after the
first word: `Sunshine App Manager` becomes `SUNSHINE` / `APP MANAGER`.

## The caption

| | |
|---|---|
| Face | **Arial Bold** (`/System/Library/Fonts/Supplemental/Arial Bold.ttf`) |
| Case | upper |
| Colour | `#ffffff` |
| Size | the largest of **66, 64, … 34** that fits |
| Letter-spacing | one space between characters — dropped before the size is reduced below what fits |
| Alignment | centred on x = 300 |

Letter-spacing is done by joining the characters with a space rather than by a
tracking setting, because that is what the renderer offers and it matches
Sunshine's own captions. The fitting rule is: try spaced at every size first,
and only then try unspaced. What that produces today:

| tile | lines | size | spaced | widest line |
|---|---|---|---|---|
| Sunshine App Manager | 2 | 48 | yes | 491 px |
| Steam | 1 | 66 | yes | 303 px |
| Heroic | 1 | 66 | yes | 347 px |
| Desktop | 1 | 66 | yes | 427 px |
| Restart | 1 | 66 | yes | 420 px |

If a rebuild produces different numbers from these, something has changed —
the font, the margins, or the rule — and the difference is worth explaining
before it is committed.

## The marks

| tile | mark | where it came from |
|---|---|---|
| Sunshine App Manager | three covers on a shelf | ours, drawn for this project |
| Steam | the Steam roundel | Sunshine's `steam.png` (LizardByte, GPL-3.0) |
| Heroic | the Heroic shield | Heroic Games Launcher `public/icon.png` (GPL-3.0) |
| Desktop | a monitor, with the host's platform on the screen | ours |
| Restart | a circular arrow | ours |

Both borrowed marks come from GPL-3.0 projects, which is compatible with this
one. That covers the copyright in the artwork. The **trademarks** are not ours
and are used only to identify what each tile launches — the README says so in
as many words, and nothing here implies endorsement.

### Our own mark

Design D, on a 100 × 100 grid, drawn at 460 px for the tile:

| rect | x | y | w | h | radius | fill |
|---|---|---|---|---|---|---|
| back | 64 | 30 | 30 | 46 | 6 | `#6c757d` |
| middle | 39 | 25 | 30 | 52 | 6 | `#9aa0a8` |
| front | 12 | 20 | 30 | 60 | 6 | vertical ramp |

The front cover's ramp runs `#FDD107 → #F89A1C` over its top half and
`#F26222 → #EF3E23` over its bottom half — the four colours of Sunshine's own
icon, in order, so the set sits beside it without clashing.

### The platform glyph

The Desktop tile says which machine you are looking at. The platform's mark sits
on the monitor's screen, fitted into **30 × 30 units** of the monitor's 100-unit
grid and centred in the screen area, which is inset from the bezel so nothing
crosses it.

**On Linux the distribution's own logo is used, taken from the machine.**
`/etc/os-release` carries a `LOGO=` key — `LOGO=bazzite-logo` on Bazzite — and
the icon is already installed under `/usr/share/icons/hicolor/<size>/`, usually
as `<logo>-icon.png`. Read the largest one available. Nothing is shipped for
this and nothing is fetched: the machine already has its own logo, and every
distribution gets the right one without us keeping a list.

Fall back to the penguin we ship when there is no `LOGO=`, when the icon cannot
be found, or when Pillow is not available to composite it. Windows is four
panes and macOS an apple, both drawn here rather than shipping a brand asset.

## Rebuilding

`scripts/make-tiles.py` produces every file in `assets/tiles/` from the values
above. It is run by hand when the art changes, not at install time and never at
scan time: the tiles ship with the program, and nothing is downloaded.

*(The art and this specification were settled first, on 2026-09-19; the script
and the assets land with the change that stops the scan-time download.)*

It needs Pillow and the font named above. On a machine without Arial Bold,
substitute a grotesque of similar width and **re-record the table above**,
because the fitted sizes will change.

## What this replaced

Until 2026-09-19 these four tiles were downloaded **at scan time** from
`github.com/wadiebs/bazzite-sunshine-manager`, a repository we do not control,
and two of them carried Steam's and Heroic's logos with no licence recorded.
A scan reached out to a stranger's repository for artwork it then wrote into
the user's `apps.json`. That is the thing this template exists to have stopped.
