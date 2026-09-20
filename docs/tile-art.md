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
| Steam Big Picture | the roundel on a television | ours, around the same roundel |
| Heroic | the Heroic shield | Heroic Games Launcher `public/icon.png` (GPL-3.0) |
| Desktop | a monitor, with the host's platform on the screen | ours |
| Restart | a circular arrow | ours |
| Desktop, on macOS | the Apple mark | rendered from Apple's own published path (apple.com global nav) |
| Desktop, on Linux | the distribution's logo | read from the machine (`os-release` `LOGO=`) |
| Desktop, on Windows | four panes | ours |
| Desktop, fallback | Tux | Larry Ewing, Simon Budig, Garrett LeSage (Attribution) |

Both borrowed marks come from GPL-3.0 projects, which is compatible with this
one. That covers the copyright in the artwork. The **trademarks** are not ours
and are used only to identify what each tile launches — the README says so in
as many words, and nothing here implies endorsement.

### The television, and why it is not the monitor

Big Picture sits on the same grid as the desktop tiles, so it cannot be the
monitor glyph with a Steam roundel in it -- that reads as "the desktop, with
Steam on it", which is a different tile. The television is wider (a 4-unit
bezel against the monitor's 8, on the same 100 x 100 grid), stands on two short
splayed feet, with nothing joining them, rather than a pedestal, and carries the mark at 42
units against the monitor's 30, because a wider screen with the same mark on
it looks switched off.

It is drawn by `glyph_tv()` and takes any mark, so a second Big-Picture-like
tile would be built the same way.

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

**On Linux the distribution's own logo is used, taken from the machine.** It is
already installed; we neither ship it nor fetch it. Finding it takes a chain,
because distributions do not agree:

1. `LOGO=` in `/etc/os-release`, then look for `<logo>.svg`, `<logo>.png` or
   `<logo>-icon.png` under `/usr/share/icons/hicolor/<size>/apps/` and
   `/usr/share/pixmaps/`. Prefer the plain name over `-text` and `-dark`
   variants, and the largest size available.
2. Failing that, the same search for `<ID>-logo.*` and `<ID>.*`, where `ID` is
   the `ID=` field. This is what catches Debian.
3. Failing that, the penguin.

Measured on 2026-09-19, which is why the chain has three links and not one:

| distribution | `LOGO=` | icon present | found by |
|---|---|---|---|
| Bazzite (desktop) | `bazzite-logo` | yes | step 1 |
| Ubuntu 24.04 | `ubuntu-logo` | yes | step 1 |
| Arch | `archlinux-logo` | yes | step 1 |
| Debian 13 | **absent** | `debian-logo.png` | step 2 |
| Fedora 43 (cloud) | `fedora-logo-icon` | **no** | step 3 |

The Fedora row is the useful one: a minimal or cloud install may name a logo it
does not have. A desktop install has it — Bazzite is Fedora and does. The
penguin is not a rare path to be hand-waved; it is what a server-shaped machine
gets.

Windows is four panes, drawn here. **macOS is Apple's own mark**, rendered from
the path Apple publishes in the global navigation on `apple.com` — the same
nominative basis as Steam's and Heroic's marks, and recorded in the README with
them.

## Check the marks before every major release

**Logos change.** Fedora's changed in 2021, Ubuntu's in 2022, Windows' in 2021,
and a tile carrying last decade's mark looks like abandonware. Before cutting a
major or minor release, look at each mark we ship and confirm it is still the
current one:

| mark | where it comes from | licence |
|---|---|---|
| Steam roundel | Sunshine's own `steam.png` | GPL-3.0 (LizardByte) |
| Heroic shield | Heroic Games Launcher `public/icon.png` | GPL-3.0 |
| Apple | the path Apple publishes in apple.com's global nav | trademark, nominative use |
| Windows | four panes, drawn here | ours |
| Tux | Larry Ewing, Simon Budig, Garrett LeSage | Attribution |
| Arch | Arch "Crystal" icon | GPL |
| Debian | Debian OpenLogo (swirl) | CC BY-SA 3.0 |
| Fedora | Fedora icon (2021) | public domain |
| Linux Mint | logo without wordmark | CC BY 3.0 |
| Ubuntu | logo, no wordmark (2022) | GPL-3.0 |

openSUSE is deliberately absent: the available artwork is GFDL, which is a poor
fit for bundling, and an openSUSE desktop carries its own icon, which step 1
finds.

This check is in `docs/releasing.md` as part of cutting a release, so it is not
a thing to remember unaided.

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

## Swapping a tile between worded and wordless

The artwork picker offers **both of our tiles** for any entry of ours: the
worded one from the language in Settings, and the wordless one. Which is
wanted is a preference and not a fact about the machine — a French speaker may
well prefer the English tile to a wordless one, and there is no way for us to
know — so both are offered and neither is assumed.

They come before anything on a network, because for these entries the shipped
picture is the right answer and it is already on the disk. A game is offered
none of them.

Two things this changed elsewhere, both worth knowing:

- The SteamGridDB note used to begin "No artwork was found for this one".
  That read correctly while SteamGridDB was the last resort, and became false
  the moment our own tiles appeared on the same page. `_sgdb()` no longer
  claims anything about what was found — it cannot know — and
  `find_candidates()` adds the lead only when there is genuinely nothing.
- "In use" compares the candidate's **origin** as well as its cached copy. A
  picture from a network is used from the cache, so the entry points there;
  one of ours is used from where it lies, and comparing only the cache left
  the tile actually in use labelled "choose".
