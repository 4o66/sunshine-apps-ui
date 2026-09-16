# sunshine-apps-ui

Manage the applications Sunshine offers, from a page you reach through
Moonlight or at the console.

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

Hiding and deleting differ, and the difference outlives the click. A deletion
is not recorded, so the next scan sees the application as new and offers it
again. Hiding writes a tombstone, and every later scan obeys it -- which is the
point, but it also means a hidden tile cannot come back by rescanning. The
manager's own tile is the case where that bites: installing offers to unhide it
rather than leaving you to wonder why reinstalling changed nothing.

A copy of `apps.json` is taken before every write, the last ten are kept, and
any of them can be restored -- previewed on the grid first, like any other
change.

### Why not just the importer it grew out of

Not because it imports everything -- it does not. It has a default blacklist
(Proton, SteamVR, soundtracks, demos, dedicated servers) and you can add your
own games by app id or by regular expression, in a file or an environment
variable. Excluding a game is possible there.

It is *where* and *when* that does not fit. A blacklist is something you declare
in advance, in a config file, about games you are not looking at -- you cannot
sit in front of the grid on your television and say "not that one". And every
run rewrites `apps.json` from scratch, so a decision made anywhere else does not
survive: delete a tile in Sunshine's own web UI and the next run puts it back,
edit a field by hand and the next run overwrites it, and Sunshine's own default
entries are removed outright.

That is the mismatch, for how I use Moonlight. The decisions I make are about
particular games, and I make them after seeing them. Some do not play well over
a stream. Some I would not choose to play that way even when they do. Some I
would rather not have on a television in the living room at all. And often I
just want a handful of my library there rather than the whole thing.

So the hiding has to be remembered, which a tool that rewrites the file every
run cannot do. The tombstones, the ownership markers and the queue all exist
for that one reason.

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

**It has to render inside the session Sunshine is streaming.** There are two
ways to reach this and they are the same place: through Moonlight, from the
couch, on a television at ten feet with a gamepad mapped to arrows and Enter;
or sitting at the machine itself. Either way the page is drawn on the host, by
the host. A browser in `--app` mode gets there with no toolkit; a terminal UI
would still need a window in that session and is miserable with a thumbstick.

Which is why the listener binds `127.0.0.1` and why that costs nothing. It only
ever has to be reachable from the machine it runs on, because both ways of
using it put you on that machine. See [docs/security.md](docs/security.md).

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
    docs/releasing.md the version scheme, and how a release is cut
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
