# sunshine-apps-ui

Companion web UI for [bazzite-sunshine-manager](https://github.com/4o66/bazzite-sunshine-manager).

**Status: phase 1 — a read-only dashboard. It never writes to `apps.json`.**

## What this is

The importer is a CLI. It scans Steam and Heroic libraries and reconciles the
result into Sunshine's `apps.json`. This project is the front end for the part
that benefits from being seen rather than logged: *here is what is about to
change -- apply it or not.*

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

It finds `sunshine-import` on `PATH` (or take `--importer PATH`), runs it with
`--dry-run --json`, and renders the plan. Arguments after `--` are passed
through to the importer:

    sunshine-apps-ui -- --no-heroic

The URL it prints carries a token generated for that run. Without it, every
request is refused.

## Layout

    src/sunshine_apps_ui/
      importer.py   runs sunshine-import and validates the plan schema
      security.py   token, Host and cross-site checks
      render.py     the page
      server.py     the listener
    docs/security.md  threat model and the decisions behind it

## License

MIT. The CLI boundary means there is no derivative-work entanglement with the
parent project.
