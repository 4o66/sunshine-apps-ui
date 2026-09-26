# Why it is shaped this way

The decisions behind the program, kept out of the README so that stays about
what it is, how to install it and how to use it. `docs/backlog.md` is the
running record of decisions as they were made; this is the settled version.

## Why not just the importer it grew out of

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

## Two halves, one program

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
couch, on a television at ten feet; or sitting at the machine itself. The aim
is for the couch to need only a controller. It does not yet: a controller
reaches nothing (#32), and a mouse and keyboard, passed through by Moonlight,
are what work today. Either way the page is drawn on the host, by
the host. A browser in `--app` mode gets there with no toolkit; a terminal UI
would still need a window in that session and is miserable with a thumbstick.

The page is shown in a window of our own where we can make one, rather than in
a browser: a WebView2 control on Windows (`winhost.py`, compiled on the machine
by the `csc.exe` that is part of Windows, from source shipped in the package)
and a WebKitGTK view on Linux (`gtkhost.py`, ordinary Python -- GTK 4 and
WebKitGTK are already there and there is nothing to build or fetch). Either way
it is one window with one behaviour, instead of a table of per-browser flags
and whatever the user's browser was configured to do.

Nothing depends on it. No compiler, no WebView2 runtime, no GTK, a build that
fails, or a machine with no desktop libraries at all: the window is simply not
offered and the browser path runs exactly as it did.

Which is why the listener binds `127.0.0.1` and why that costs nothing. It only
ever has to be reachable from the machine it runs on, because both ways of
using it put you on that machine. See [docs/security.md](docs/security.md).

## Layout

    src/sunshine_apps_ui/
      core/           the engine: everything that reads or writes apps.json
        reconcile.py      what the program owns, and what you changed by hand
        run.py            a scan: the sources, the merge, the plan
        mutate.py         applying queued changes, and restoring a copy
        backups.py        copies taken before every write
        system_apps.py    Sunshine's own defaults, and finding them per platform
        sources/          where applications are discovered
        artwork_sources.py  every picture the picker can offer
        api.py            the only surface the interface may use
      engine.py       the seam: what the interface can ask of core
      security.py     token, Host and cross-site checks
      render.py       the pages
      server.py       the listener
      state.py        the queue of pending changes, and per-form drafts
      scanjob.py      a scan you can watch, on a thread
      artwork.py      which images may be served, as an exact allowlist
      i18n.py         which language this machine is in, and what to say in it
      tileart.py      fetching a language's tiles, and noticing stale ones
      launcher.py     opening the interface as a window, and taking it down
      gtkhost.py      that window on Linux: GTK 4 and WebKitGTK
      winhost.py      that window on Windows: WebView2, built by csc.exe
      winbrowser.py   the Windows browser fallback, and its helper
      installer.py    putting it in place, and removing it again
      interpreter.py  fetching a checked CPython where there is none
      credentials.py  asking for a secret without it reaching argv
      updates.py      asking GitHub what the newest release is
      legacy.py       finding the original importer, which cannot coexist
    assets/tiles/     the artwork, per language, plus a wordless set
    locales/          the strings, one file per language
    docs/             these documents

Every document: **security.md** (threat model and the decisions behind it),
**tile-art.md** (how the artwork is made, and how to match it),
**i18n.md** (adding a language), **releasing.md** (the version scheme),
**packaging.md** (why the update check cannot install anything yet),
**ai-usage.md** (how this was built and tested), **backlog.md** (decided, and
why).
