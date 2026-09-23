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

**On Linux the distribution's own logo is used, from the set we vendor.** The
lookup is two steps and then a fallback:

1. `ID=` in `/etc/os-release`, matched against `desktop-<id>.png` in the tile
   set. `ID=bazzite` gets `desktop-bazzite.png`.
2. Failing that, `desktop-linux.png` — the penguin, which is right anywhere.

**It used to read the logo off the machine**, through `LOGO=` in `os-release`
and a hunt under `/usr/share/icons/hicolor` and `/usr/share/pixmaps`. That is
gone, and this is why: tiles are now rendered here and shipped, so there is no
compositing on the host, no dependency on Pillow being installed there, and
every machine of a given distribution gets the same tile rather than whichever
icon pack happened to be installed. The measurements that justified vendoring
are worth keeping, because they are what the old chain ran into, taken
2026-09-19:

| distribution | `LOGO=` | icon present on the machine |
|---|---|---|
| Bazzite (desktop) | `bazzite-logo` | yes |
| Ubuntu 24.04 | `ubuntu-logo` | yes |
| Arch | `archlinux-logo` | yes |
| Debian 13 | **absent** | `debian-logo.png`, under another name |
| Fedora 43 (cloud) | `fedora-logo-icon` | **no** |

Two of five machines could not answer the question they were being asked:
Debian names no logo at all, and Fedora's cloud image names one it does not
have. A distribution we ship no mark for still gets the penguin, which is what
a server-shaped machine gets and not a rare path to be hand-waved.

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

## The SteamGridDB key goes in Settings

The note the picker shows when no key is stored **names no command**, and this
is deliberate rather than a wording preference. It named `sunshine-import`
first, which is the previous project's command and does not exist here; then
this program's own, which on Windows is a `.cmd` in the install directory that
is not on `PATH`. Both were wrong for the same underlying reason: this runs as
a Sunshine tile, on a television, driven by a gamepad, and there is nothing
there to type a command into.

So **Settings holds a field for the key**, and the picker holds a link to
Settings. `POST /settings/sgdb-key` hands what was typed to the same
`api.save_sgdb()` the command line uses, so the key is checked against the API
before it is stored and is written mode 600 either way — one path, not two that
drift. The page says *whether* a key is stored and never renders the key back.

`--save-sgdb-key` stays. It is how a key gets onto a headless machine, and it
reads the key on stdin rather than taking it on argv (`docs/security.md`).

## SteamGridDB is fetched on demand, a page at a time

**There is no ranking, and there cannot be one.** `_sgdb()` used to sort by the
`score` field and keep the best twelve. Measured against the live API on
2026-09-22: `score` and `upvotes` are **zero on every item of every game
tried** — 300 items across six pages of Cyberpunk 2077 alone. The sort compared
equal keys, and a stable sort left the order exactly as it arrived, so it had
never chosen a best anything. The grids endpoints take no sort or order
parameter either (`styles`, `dimensions`, `mimes`, `types`, `nsfw`, `humor`,
`epilepsy`, `oneoftag`, `page`, `limit` — and that is all), so the server
cannot rank for us. Issue #30.

What replaced it:

- **`find_candidates()` no longer calls SteamGridDB at all.** It is the only
  source that is a network round trip to a third party, and opening the picker
  usually wants none of it — what is already on the disk is normally right.
  `sgdb_page()` fetches, when somebody presses **Show SteamGridDB art**. The
  button appears only when a key is stored; without one the picker shows the
  link to Settings instead.
- **48 at a time, in the API's own order**, in a modal over the picker, with
  Back and Next. Cyberpunk 2077 has 689.
- **`limit` is sent with `page`, and this matters.** The API pages by whatever
  limit it is given; with none it pages by its own 50, and taking 48 of each
  would drop two items every page, silently, forever. `limit` is capped at 50 —
  asking for 100 returns 50.
- **The name lookup is not paged.** `/search/autocomplete/` resolves a game id
  and has no page 2; asking for one returns nothing, which would have made
  every page turn past the first claim there was no artwork — but only for
  entries found by name rather than by appid, which is the hardest kind of bug
  to notice.
- **The sheet needs no script.** The page is served `script-src 'self'` with no
  inline script, and is driven by a gamepad on a television. So the server
  renders `<dialog open>` when the address says the sheet is up, and every
  control in it is a link. #28 is why that is not negotiable. An open dialog in
  the markup paints no `::backdrop`, so a veil is drawn behind it.

## Where the SteamGridDB key comes from

Settings explains it, because nobody arrives knowing: a free account, then
**Preferences** from the menu under your name, then **API**
(<https://www.steamgriddb.com/profile/preferences/api>). Through Moonlight that
address is also a QR code — a television has no address bar and no keyboard, so
the phone in your hand is the way in, the same reasoning as the bug-report
page. At the machine it is just a link; a QR code there would be clutter.

Whether the offer belongs on the picker at all was the open half of issue #22.
It stays, because with the library-cache layout fixed most Steam games never
reach it — the ones that do are GOG and Epic, where there is genuinely no
keyless source and the person looking at an empty picker has no other way to
learn one exists.
