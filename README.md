# sunshine-apps-ui

Companion web UI for [bazzite-sunshine-manager](https://github.com/4o66/bazzite-sunshine-manager).

**Status: a tile manager.** The grid shows what Sunshine currently offers, a
scan stages what it found onto that same grid, and nothing reaches `apps.json`
until Apply.

## What this is

The importer is a CLI. It scans Steam and Heroic libraries and reconciles the
result into Sunshine's `apps.json`. This project is the front end for the part
that benefits from being seen rather than logged: the tiles themselves.

Everything is driven from the grid. A tile can be edited, hidden, cloned or
deleted; a scan marks what it found; new applications are added by hand. Each of
those queues a change and shows it on the tile, so what is about to happen is
visible in one place, and one Apply writes the file and asks Sunshine to re-read
it. Paths are chosen with a file picker rather than typed, and cover art is
chosen from what can actually be found for the game -- Steam's own library
cache, Valve's CDN, and SteamGridDB -- rather than from a path to a PNG.

It writes to `apps.json` only through the importer's `--mutate` contract: the
rules about ownership markers, tombstones and Sunshine's own defaults live in
one place, and this is not that place.

It is a separate repository on purpose. The two talk over a versioned JSON
contract (`sunshine-import --dry-run --json`), never by importing each other's
Python. That keeps release cadences independent, lets either side be rewritten
in another language, and avoids depending on the importer's package layout,
which currently claims the top-level names `common` and `importers`.

## Why a web UI and not a desktop app

Both target systems are hostile to conventional desktop toolkits:

- **Bazzite** (rpm-ostree) -- installing Qt/GTK Python bindings at runtime is a
  foot-gun on an immutable base.
- **SteamOS on a Legion Go S** -- runs a gamescope session where ordinary
  windows are second-class, and input is a gamepad at 10-foot viewing distance.

A local page is reachable from the console, a phone, or a laptop; it survives
gamescope; and it can be made gamepad-navigable with focus styling. It is also
launchable as a Sunshine app itself, via a kiosk browser.

## Security

The listener binds to `127.0.0.1` and **that is not configurable**. Loopback is
not the same as private, so it is not the only defence. See
[docs/security.md](docs/security.md).

## Running it

    pip install -e .
    sunshine-apps-ui --open

It finds `sunshine-import` on `PATH` (or takes `--importer PATH`) and asks it
what is in `apps.json` now. Arguments after `--` are passed through to the
importer when it scans:

    sunshine-apps-ui -- --no-heroic

The URL it prints carries a token generated for that run. Without it, every
request is refused.

## Layout

    src/sunshine_apps_ui/
      importer.py   runs sunshine-import and validates the plan schema
      security.py   token, Host and cross-site checks
      render.py     the pages
      server.py     the listener
      state.py      the queue of pending changes, and per-form drafts
      artwork.py    which images may be served, as an exact allowlist
    docs/security.md  threat model and the decisions behind it

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

It talks to
[bazzite-sunshine-manager](https://github.com/4o66/bazzite-sunshine-manager)
over a CLI contract rather than importing it, so the two remain separable.
