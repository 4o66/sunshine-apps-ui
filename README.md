# sunshine-apps-ui

Manage the applications Sunshine offers, from a page you can reach from the
console, a phone, or the stream itself.

**Status: a tile manager.** The grid shows what Sunshine currently offers, a
scan stages what it found onto that same grid, and nothing reaches `apps.json`
until Apply.

## What this is

A tile manager for Sunshine's `apps.json`. It scans Steam and Heroic libraries,
reconciles what it finds against what is already there, and shows the result as
the grid of tiles Moonlight will display.

Everything is driven from that grid. A tile can be edited, hidden, cloned or
deleted; a scan marks what it found; new applications are added by hand; cover
art is chosen from what can actually be found for the game -- Steam's own
library cache, Valve's CDN, SteamGridDB -- rather than from a path to a PNG.
Each of those queues a change and shows it on the tile, so what is about to
happen is visible in one place, and one Apply writes the file and asks Sunshine
to re-read it.

A copy of `apps.json` is taken before every write, the last ten are kept, and
any of them can be restored -- previewed on the grid first, like any other
change.

### Two halves, one program

The engine (`src/sunshine_apps_ui/core`) owns `apps.json`: the reconciler that
decides what the tool owns and what you have changed by hand, the tombstones
that keep a deleted app deleted, and the rules about Sunshine's own defaults.
Nothing outside `core` writes that file.

It began as a separate program, [bazzite-sunshine-manager] by wadiebs, spoken to
over a CLI contract. The contract was worth having while there were two
projects; with one it bought a subprocess per request and two of everything
else. The boundary survives as a package rather than a process.

[bazzite-sunshine-manager]: https://github.com/wadiebs/bazzite-sunshine-manager

**The original cannot be installed alongside this.** It rewrites `apps.json`
from scratch on every run, which removes everything it did not generate itself:
Sunshine's own defaults, anything you added by hand, and every record of what
you have hidden. `scripts/install` refuses while it is present, and offers to
remove it. Sunshine's own web UI, by contrast, is safe to use -- it reads each
app whole and writes the whole file back. The one thing to know is that
deleting an app there is not recorded as a deletion, so the next scan offers it
back.

## Why a web UI and not a desktop app

Two reasons, and the second is the real one.

**Bazzite is rpm-ostree.** Installing Qt or GTK Python bindings at runtime on an
immutable base is a foot-gun. This has no runtime dependencies at all: stdlib
`http.server` and nothing else.

**It has to render inside the stream.** The point of the Sunshine tile is that
you reach this from the couch, through Moonlight, on a television -- so it draws
in whatever session Sunshine is streaming, at ten feet, with a gamepad mapped to
arrows and Enter. That is true whatever the machine at the other end is running.
A browser in `--app` mode gets there with no toolkit; a terminal UI would still
need a window in that session and is miserable with a thumbstick.

It is also reachable from a laptop, though only through an SSH tunnel: the
listener is hardcoded to `127.0.0.1` and there is no option to change it. See
[docs/security.md](docs/security.md).

## Security

The listener binds to `127.0.0.1` and **that is not configurable**. Loopback is
not the same as private, so it is not the only defence. See
[docs/security.md](docs/security.md).

## Running it

    scripts/install

Everything lands under `~/.local` and nothing needs root -- both target systems
have an operating system you do not install into. Then launch it from the
Sunshine tile it creates, or by running the command with no arguments, which is
what that tile does:

    sunshine-apps-ui

The URL it prints carries a token generated for that run. Without it, every
request is refused.

Credentials, when you want them. Both read the secret from the terminal without
echoing it, and neither ever takes one as an argument:

    sunshine-apps-ui --save-credentials   # Sunshine's web UI login, for reloads
    sunshine-apps-ui --save-sgdb-key      # SteamGridDB, for community artwork

Scanning without opening the interface, for scripts:

    sunshine-apps-ui --serve                # the interface, without a window
    sunshine-apps-ui --scan                 # scan, write, and reload Sunshine
    sunshine-apps-ui --scan --dry-run       # report what would change
    sunshine-apps-ui --scan -- IMPORT_HEROIC=0

## Layout

    src/sunshine_apps_ui/
      core/         the engine: everything that reads or writes apps.json
        reconcile.py    what the tool owns, and what you changed by hand
        mutate.py       applying queued changes, and restoring a copy
        backups.py      copies taken before every write
        sources/        where applications are discovered
        api.py          the only surface the interface may use
      engine.py     the seam: what the interface can ask of core
      security.py   token, Host and cross-site checks
      render.py     the pages
      server.py     the listener
      state.py      the queue of pending changes, and per-form drafts
      artwork.py    which images may be served, as an exact allowlist
      legacy.py     finding the original importer, which cannot coexist
      launcher.py   opening the interface as a window, and taking it down
      installer.py  putting it in place, and removing it again
      credentials.py  asking for a secret without it reaching argv
    docs/security.md  threat model and the decisions behind it
    docs/backlog.md   decided, not built

## License

GPL-3.0-or-later.

    sunshine-apps-ui, a tile manager for Sunshine.
    Copyright (C) 2026 4o66

    This program is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by the Free
    Software Foundation, either version 3 of the License, or (at your option)
    any later version.

    This program is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
    FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
    more details.

    You should have received a copy of the GNU General Public License along
    with this program. If not, see <https://www.gnu.org/licenses/>.

GPL rather than AGPL deliberately. The network clause is what separates them,
and it could barely apply here: the listener is hardcoded to `127.0.0.1` and
there is no option to change it, so hosting a modified copy as a service means
first removing the property this whole design rests on. GPLv3 also keeps the
door open to code moving into [Sunshine](https://github.com/LizardByte/Sunshine)
itself, which is GPLv3 and could not take AGPL code.

The engine is derived from MIT-licensed work by wadiebs. That notice is
preserved verbatim in `LICENSE.upstream-MIT`, and `NOTICE` explains the
arrangement.
