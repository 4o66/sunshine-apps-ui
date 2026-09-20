# Backlog

**Open work lives in GitHub issues**, not here:
<https://github.com/4o66/sunshine-apps-ui/issues>. Moved there 2026-09-16, so
that what is left to do has one home and a state.

What stays in this file is the reasoning that outlives any one task: decisions
already taken, things that were tried, and facts about Sunshine that were
expensive to find out. Picking up an issue should not start from a blank page,
so the issues carry their own argument; this is the context underneath them.

## Releasing 0.1

**Held 2026-09-14. Ready but deliberately not cut.** Tracked in
[#2](https://github.com/4o66/sunshine-apps-ui/issues/2).

How the version is decided, and who decides how big a bump is, is in
`docs/releasing.md`.

## A dev branch

**Decided 2026-09-16. Not yet worth doing.** Tracked in
[#3](https://github.com/4o66/sunshine-apps-ui/issues/3).

## Run everywhere Sunshine runs

**Logged 2026-09-14.** The port is
[#4](https://github.com/4o66/sunshine-apps-ui/issues/4); macOS is
[#5](https://github.com/4o66/sunshine-apps-ui/issues/5) and Windows
[#6](https://github.com/4o66/sunshine-apps-ui/issues/6).

Today this targets Bazzite. Sunshine itself runs on Windows, macOS and every
Linux distribution, and nothing about managing `apps.json` is Bazzite-specific.

**SteamOS was a target and is not one -- dropped 2026-09-15.** This installs
where Sunshine is, which is the machine you stream *from*. A Legion Go S is a
Moonlight client: it streams *to*. SteamOS could host Sunshine -- it is
Arch-based, and the Arch package, the AppImage and Flathub would all work --
but there is no sign anyone does. Sunshine's repository does not mention
SteamOS, the Steam Deck or the word "deck" anywhere: not in its documentation,
its source, its README or its release automation, which publishes to Flathub,
Homebrew, pacman and winget. Arch is also its smallest Linux target at 1.6% of
downloads.

Absence of evidence is not proof nobody does it, but there is no positive
evidence and upstream plainly treats it as a non-target, so it is not worth the
effort. What survived the removal is the argument it was carrying: the "ten
feet, gamepad, gamescope" reasoning is about rendering **inside the stream**,
not about the client's operating system, and it holds for a Bazzite host on
its own.

### What is not tied to the platform

The reconciler, tombstones, the mutate contract, the plan document, the whole
web UI, and the artwork sources. That is most of the value, and it is already
stdlib-only Python. This is a port of the edges, not a rewrite -- and the edges
are enumerated in [#4](https://github.com/4o66/sunshine-apps-ui/issues/4).

## Windows, and what has been settled about it

**Decided 2026-09-15.** The work is
[#6](https://github.com/4o66/sunshine-apps-ui/issues/6) and its sub-issues.
What follows is why it is shaped that way.

Windows is the largest Sunshine population -- about 70% of downloads -- and the
real port.

### The thing that shapes everything else

Sunshine's `appdata()` on Windows is not per-user AppData. It is the directory
holding `Sunshine.exe`::

    GetModuleFileNameW(nullptr, sunshine_path, _countof(sunshine_path));
    return std::filesystem::path{sunshine_path}.remove_filename() / L"config"sv;

So `apps.json` lives in `C:\Program Files\Sunshine\config`, and
`SunshineService` runs as LocalSystem, launching `Sunshine.exe` into the user's
session with a duplicated SYSTEM token. Sunshine writes that file as an
elevated process; a program run by the user cannot.

Per-user install under a user-writable prefix -- the model this project rests
on everywhere else -- does not transfer.

### What was chosen

**Run elevated, launched by Sunshine.** An app entry with `"elevated": true`
gets the administrator token with no UAC prompt: Sunshine is already SYSTEM, so
it calls `WTSQueryUserToken` for the console session and, for an admin with UAC
enabled, swaps in the linked elevated token.

Rejected: a separate privileged service with an unprivileged interface talking
to it. It is the textbook answer and it costs IPC, a second thing to install
and uninstall, and a privileged surface that exists permanently rather than
only while the tile is open.

**Sunshine does not have to run as a service**, and that turns out to simplify
this rather than complicate it. Running it by hand is documented and supported
-- the portable "lite" zip is exactly that, with the service install a separate
optional step. What changes without it:

- `"elevated": true` stops meaning anything. The non-service path says so:
  "launch the process using CreateProcessW() -- this will inherit the elevation
  of whatever the user launched Sunshine with." Upstream's own documentation
  agrees that elevation is a service feature.
- No autostart before login, and no handling of session changes -- the service
  watches for them and restarts Sunshine into the new console session, so
  without it Sunshine stays bound to the session that launched it.

So there are two ways we end up able to write the file: as a service, with an
admin user, through the linked token; or hand-run, if Sunshine itself was
started elevated, because everything it launches inherits that.

**Which means we never need to detect the service.** One check of our own token
at startup answers the only question that matters -- can I write this file --
and covers both modes and every failure case without branching on how somebody
installed Sunshine. That check is
[#7](https://github.com/4o66/sunshine-apps-ui/issues/7), and it exists because
both ways of not getting elevation fail *silently*.

Do not require the non-service mode to obtain elevation. It would mean asking
people to reconfigure their whole Sunshine install for our benefit, giving up
autostart and session handling, and running every game as administrator to
solve a problem that `"elevated": true` solves for one entry.

**One codebase.** So the shell layer -- install, uninstall, the two credential
scripts, the kiosk launcher -- becomes Python, since bash is not there. More
work now and less forever, and it removes the pgrep/pkill/flatpak assumptions
from every platform at once rather than adding a second set for Windows.

**The browser must not inherit the elevation.** A browser launched by an
elevated process inherits its rights, and that is a far bigger surface than our
server running elevated. De-elevating it is a requirement of the port, not a
refinement: [#8](https://github.com/4o66/sunshine-apps-ui/issues/8).

**The cost of running elevated** belongs in `docs/security.md` when this is
built, and that argument needs rewriting rather than copying:
[#13](https://github.com/4o66/sunshine-apps-ui/issues/13).

### Do not restart Sunshine. Reload it.

Elevation is not what decides whether a restart works. `POST /api/restart`
needs only credentials, so an unelevated process can call it -- but what
happens next is decided by `platf::restart()`::

    // If we're running standalone, we have to respawn ourselves via CreateProcess().
    // If we're running from the service, we should just exit and let it respawn us.
    if (GetConsoleWindow() != nullptr) {
      atexit(restart_on_exit);
    }
    lifetime::exit_sunshine(0, true);

Three cases, and the third is a trap:

| Started as | Restart does |
|---|---|
| The service | Exits; the service respawns it. Works. |
| Standalone **with a console** (`sunshine` from cmd) | Respawns itself. Works. |
| Standalone **without a console** (shortcut, Start Menu, autostart) | `GetConsoleWindow()` is null, nothing is registered: **it exits and stays dead.** |

We do not call restart and should not start. Apply reloads by saving one
unchanged app, which triggers `proc::refresh` without terminating anything,
and that needs credentials rather than elevation -- so it works unelevated.

Which gives the summary worth keeping: **being unelevated does not break
reloading, it breaks writing.** Restarting is not a workaround for that, and
reaching for it risks shutting Sunshine down with no way back.

### Worth knowing

**Checked against Sunshine `v2026.914.233613` (released 2026-09-14) on
2026-09-16.** Everything this project depends on was unchanged from the
2026-09-11 tree these notes were written against: `process.cpp` (`apps.json`
parsing, `proc::refresh`, and the `bsm` markers surviving a read), `appdata()`,
`"elevated"`, `platf::restart()`, the service's job object, the web UI's own
sorting, and the shipped default entries. What did change is noted below.

`POST /api/config` rewrites `sunshine.conf`, and `file_apps` is a setting -- so
`apps.json` can be relocated through the API without touching the filesystem.
Not needed if we run elevated, but it is the escape hatch if elevation turns
out to be unacceptable.

`POST /api/covers/upload` writes into `appdata()/covers/`. Sunshine will store
cover art for us, elevated, on request -- so the artwork picker has a path that
needs no file access at all.

`saveApp()` still sorts `apps.json` by name on every write
(`confighttp.cpp:1163` in `v2026.914.233613`), so the file is reordered under
us. It does not matter: every consumer orders the list itself. The web UI has
its own sorting, moonlight-qt runs a case-insensitive `stable_sort` in
`NvComputer::sortAppList()` on every refresh, and moonlight-android does the
same in `AppGridAdapter.sortList()` on every `addApp()` -- all three confirmed
still true on 2026-09-16. A patch removing the sort was written and dropped for
this reason.

There is **no API that writes the `meta` block**. All endpoints were
enumerated -- 25 as of 2026-09-11, and **26 as of `v2026.914.233613`**, which
added `POST /api/reset-portal-token` (it deletes the saved XDG Portal restore
token, and is a no-op off Linux). None of them writes `meta`. `/api/apps` POST
replaces one app, DELETE removes one. The `bsm` markers ride inside each entry
and survive, but the managed list and the tombstones have no API path. Any
design that avoids writing the file directly has to put them somewhere else, and they then stop travelling with the file and
stop being in the backups.

## What generic Linux established

**Done 2026-09-15.** Tested on throwaway VMs on the Unraid host, built from
cloud images: Debian 13, Ubuntu 24.04, Fedora 43 and Arch, alongside Bazzite and
macOS. Python 3.10, 3.12, 3.13, 3.14. The full suite passes on all of them.

One note for whoever builds the next VM: Debian's genericcloud image will not
boot under SeaBIOS. GRUB loads, fails to start the kernel, and loops in its
menu with nothing on the serial console. It needs OVMF. Fedora, Ubuntu and
Arch all boot either way.

The interesting part was a real Sunshine, installed on Ubuntu 24.04 from
LizardByte's own `.deb`:

- Its default `apps.json` ships three entries -- Desktop, Low Res Desktop,
  Steam Big Picture. A scan added our three launchers and left all three of
  Sunshine's alone, which is the data loss this fork exists to prevent.
- Writing and reloading through Sunshine's own API worked with no restart.
- **Our ownership markers survive Sunshine reading the file back** -- three of
  six entries came back through `/api/apps` with their `bsm` key intact. That
  assumption was previously read out of Sunshine's source; it is now measured.

What actually needed changing was smaller than expected, and none of it was in
the engine:

- The launcher only knew Chrome-as-a-flatpak, which only Bazzite necessarily
  has. It now tries flatpak browsers, then natively installed Chromium-family
  ones, then Firefox, then `xdg-open`, and says so if there is nothing.
- `sunshine-apps-ui --scan` ran the kiosk launcher rather than the program,
  because the installed command is the launcher. Any argument now runs the
  program.

Still untested anywhere: **a desktop session.** Cloud images have no display, so
the browser launch, gamescope and the tile itself are still only exercised on
Bazzite. That gap is [#17](https://github.com/4o66/sunshine-apps-ui/issues/17).

## Taking over Sunshine's own three tiles

**Done 2026-09-19.** Sunshine ships `Desktop`, `Low Res Desktop` and `Steam Big
Picture`. Until now a scan left all three alone and added ours beside them, so
a fresh install produced two desktop tiles in two different styles and a grid
that plainly had two authors. The 2026-09-15 note above records that as the
correct outcome, and for its purpose -- never destroying somebody's config --
it was. It is not the right outcome for artwork nobody has ever touched.

They are now adopted: our names (`#1 Desktop`, `#2 Low Res Desktop`, `Zz Steam
Big Picture`), our artwork, our sort prefixes.

**The test for "untouched" is the artwork.** Sunshine writes a bare filename it
resolves against its own assets -- `desktop.png`, `steam.png`. Anything else is
a path somebody chose, so the entry is theirs and we pass it over. We looked at
the commands instead and rejected it: they are long, they vary by display
server, and a user who edited one has changed the least visible thing about the
tile. Artwork is what they change first and what this is about.

**We set the name and the artwork, and nothing else.** `Low Res Desktop` is a
`prep-cmd` that runs `xrandr` and undoes it afterwards; `Steam Big Picture` is
a detached launch with an undo that closes Big Picture again. That behaviour is
the entire point of those two tiles, we do not author it, and `_merge` leaves
any field the desired entry does not mention exactly as it found it.

**Two ordering traps, both covered by tests.** A claimed tile has to stay in the
desired set on the *second* scan, or reconcile reports it missing every run and
prunes it the moment the launcher source is prunable -- so `factory_takeovers`
looks for its own marker first and re-desires those. And a machine installed
before this existed holds both Sunshine's `Desktop` and our `#1 Desktop`; two
entries claiming one id leaves the loser disowned and sitting on the grid as a
duplicate, so reconcile declines any claim on an id we already hold. Ours wins,
Sunshine's copy stays foreign and untouched, and the user can hide it.

After the claim the ordinary divergence rule applies, so renaming one of them
is noticed and kept like any other edit.

One consequence worth knowing: `#2 Low Res Desktop` and `Zz Steam Big Picture`
exist only because Sunshine's entries did. Delete one and a rescan does **not**
offer it again, unlike our own launchers -- there is nothing left to claim.
Measured on Bazzite, 2026-09-19.

**So Settings has a button for it**, "Put the default tiles back". It runs an
ordinary scan with `BSM_RESTORE_DEFAULTS` on: the missing defaults are copied
from Sunshine's shipped `apps.json`, the takeover claims them on the way past,
and they land on the grid as pending changes. Nothing is written until Apply,
which is the same bargain as everything else here. If Sunshine's shipped file
cannot be found there is nothing to copy from, and the button says so instead
of starting a scan that would do nothing.

`restore_missing()` had to learn about the renames at the same time. It matches
defaults by name, so `Low Res Desktop` looks absent the moment it becomes `#2
Low Res Desktop`; restoring it would have added a second copy of a tile already
on the grid, and the claim on that copy would have been declined for an id we
already hold. It now takes the names we have taken over as present.

**Big Picture needed its own artwork.** It was sharing `steam.png` with `Zz
Steam`, so two tiles on one grid were the same picture. It is now the roundel
on a television rather than the desktop's monitor -- see `docs/tile-art.md` for
why those are different shapes and not the same one reused.

**Measured on `10.40.68.32`, both paths and the protection:**

| starting from | result |
|---|---|
| a fresh Sunshine `apps.json` | all three claimed, 12 tiles, none foreign, one desktop |
| an install predating this | Low Res and Big Picture claimed, bare `Desktop` left foreign |
| rescan of either | 12 unchanged, nothing added, nothing pruned |
| `Steam Big Picture` with the user's own artwork | no claim, kept foreign, untouched |

The adopted `prep-cmd` and `detached` values came back byte-identical to
`/usr/share/sunshine/apps.json` after the claim.
