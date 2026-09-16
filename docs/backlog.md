# Backlog

Things decided but not built. Each says what it is, why it matters, and what is
already known about the shape of it -- so picking one up does not start from a
blank page.

## Releasing 0.1

**Held 2026-09-14. Ready but deliberately not cut.**

Both projects are versioned and could be released today -- `2.0+4o66.0.1.0` for
the importer fork, `0.1.0` here. The decision was to wait, possibly until after
the port below.

Two things to remember when picking this up:

- **This repository is private and the importer fork is not.** Tagging the fork
  is therefore already a public release, so either both go out or neither does.
  A release naming a companion nobody can open is not a release.
- **The history was audited on 2026-09-14** and holds no keys, tokens,
  credentials, internal hostnames or addresses; the only commit identity is the
  GitHub noreply address. That audit is only good as of that date -- redo it
  before publishing rather than trusting this line.

## Run everywhere Sunshine runs

**Logged 2026-09-14. Not started.**

Today this targets Bazzite. Sunshine itself runs on Windows, macOS and every
Linux distribution, and nothing about managing `apps.json` is Bazzite-specific.
The tool should follow.

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

### What is actually tied to the platform

Worth being precise, because most of the code is not:

- **Config directory discovery.** `detect_sunshine_config_dir()` knows about
  `~/.config/sunshine` and two Flatpak paths. Windows uses
  `%ProgramFiles%\Sunshine\config` (a machine-wide location, not a per-user
  one); macOS uses `~/.config/sunshine` under Homebrew but `/Applications` for
  the app bundle.
- **The launcher.** ~~bash, `pkill`, `pgrep`, `flatpak run`~~ -- **done
  2026-09-15.** It is Python now (`launcher.py`), for exactly this reason: one
  description of a careful piece of behaviour rather than two that drift. What
  remains platform-specific is named and in one place there, and Windows still
  needs a job object in place of `pgrep` and a de-elevated child.
- **Steam and Heroic discovery.** Library paths and the `steam -applaunch`
  command differ per platform; the Steam library cache layout does not.
- **File modes.** The mode-600 checks on the credentials and SteamGridDB key
  files are POSIX. Windows needs an ACL check or an honest admission that it
  does not have one.
- **`install` / `uninstall`.** Python now, not bash. Per-user under `~/.local`
  is right for Linux and macOS; Windows has no equivalent convention worth
  pretending about, and gets an installer of its own.

### What is not tied to the platform

The reconciler, tombstones, the mutate contract, the plan document, the whole
web UI, and the artwork sources. That is most of the value, and it is already
stdlib-only Python. This is a port of the edges, not a rewrite.

### Windows, and what has been settled about it

**Decided 2026-09-15.** Windows is the largest Sunshine population -- about 70%
of downloads -- and the real port. What follows is decided; what is still open
is at the end.

#### The thing that shapes everything else

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

#### What was chosen

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
installed Sunshine.

Do not require the non-service mode to obtain elevation. It would mean asking
people to reconfigure their whole Sunshine install for our benefit, giving up
autostart and session handling, and running every game as administrator to
solve a problem that `"elevated": true` solves for one entry.

**Two silent degradations to handle explicitly**, because both fail quietly:

- A **non-admin account gets no elevation and no error**. Sunshine logs
  "Sunshine will retain the same access level as the current user and will not
  elevate it" and launches us unprivileged anyway. We would fail at the write
  with nothing on screen to say why.
- **It only works when Sunshine is running as the service.** Started by hand --
  common when troubleshooting -- `WTSQueryUserToken` fails from a non-SYSTEM
  process and there is nothing to elevate with.

Check our own token at startup and say so on the page. Discovering this at the
write is the wrong end.

**The cost, which belongs in docs/security.md when this is built:** the HTTP
server would run elevated. Loopback binding and the per-session token stop
being defence in depth and become the only thing between a flaw and rights we
do not otherwise have. That argument is currently written assuming an
unprivileged server, and it will need revisiting rather than copying.

**Install as a standard Windows application**, registered in Add/Remove
Programs. Sunshine packages itself with CPack and NSIS; mirroring that is the
obvious precedent and settles the "no ~/.local convention" problem.

**One codebase.** So the shell layer -- install, uninstall, the two credential
scripts, the kiosk launcher -- becomes Python, since bash is not there. More
work now and less forever, and it removes the pgrep/pkill/flatpak assumptions
from every platform at once rather than adding a second set for Windows.

#### The browser must not inherit the elevation

Availability is not the problem it is on Linux: Edge ships with Windows and is
Chromium-based, so `--app=` and `--user-data-dir=` work. There is always a
browser.

The problem is that a browser launched by an elevated process inherits its
rights, and a browser running as administrator is a far bigger surface than our
server running as administrator -- a general-purpose program with a JIT, a
network stack and extensions, on the user's desktop. `--app` narrows what the
window is *for*; it does not stop someone opening a normal window in an
administrator browser.

So **launch the browser de-elevated**: take the non-elevated linked token (or
the shell's) and `CreateProcessWithTokenW`. Only the server holds the
privilege. Treat this as a requirement of the port, not a refinement.

The teardown needs rewriting too -- `pgrep`/`pkill` by profile path has no
Windows equivalent -- and Sunshine shows the better answer. `sunshinesvc.cpp`
puts its child in a **job object with kill-on-close**::

    // Kill Sunshine.exe when the final job object handle is closed
    job_limit_info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

That is stronger than what we do on Linux: the OS guarantees the browser dies
with us even if we are killed rather than exiting.

#### Do not restart Sunshine. Reload it.

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
reaching for it risks shutting Sunshine down with no way back. Check the token
at startup, so this is discovered before someone queues a dozen changes rather
than after.

#### When Windows lands, say so in the README

There is a second reason this diverged from the importer it grew out of, and it
is deliberately not written down yet: that one targeted Bazzite alone, and this
was meant to be worth having on Windows too. That is a claim about what this
does, so it goes in when Windows actually works -- not while it is a plan.

#### Still open

- **Shipping a Python interpreter.** Windows users will not have one. PyInstaller
  or equivalent, which makes the launcher an .exe and adds perhaps 15 MB.
- **Credential file permissions.** Four places check `st_mode & 0o077` and
  create files mode 600. Windows has no equivalent; this needs a real ACL check
  or an honest statement that there is not one. It is security-relevant, so it
  should not quietly become a no-op.
- **The artwork allowlist matches paths as exact strings.** Correct on POSIX,
  wrong on Windows, where `C:\x\y.png`, `c:/x/y.png` and `C:\X\Y.PNG` are one
  file. Loosening it carelessly weakens the allowlist, which is the whole
  mechanism.
- Steam and Heroic library paths; `cmd` as a Windows command line; and `Zz
  Reboot`, which runs `systemctl reboot`.

#### Worth knowing

`POST /api/config` rewrites `sunshine.conf`, and `file_apps` is a setting -- so
`apps.json` can be relocated through the API without touching the filesystem.
Not needed if we run elevated, but it is the escape hatch if elevation turns
out to be unacceptable.

`POST /api/covers/upload` writes into `appdata()/covers/`. Sunshine will store
cover art for us, elevated, on request -- so the artwork picker has a path that
needs no file access at all.

There is **no API that writes the `meta` block**. All 25 endpoints were
enumerated: `/api/apps` POST replaces one app, DELETE removes one. The `bsm`
markers ride inside each entry and survive, but the managed list and the
tombstones have no API path. Any design that avoids writing the file directly
has to put them somewhere else, and they then stop travelling with the file and
stop being in the backups.

### Open questions

- **Which platform second?** macOS is the smaller job and Windows the larger.
  SteamOS was the obvious answer until it turned out not to be a host.
- **How to launch the browser on Windows.** No flatpak, no `pkill`. Probably
  `start` plus a job object, or give up on kiosk mode and open a normal tab.
- **How to test it.** Everything platform-specific found so far was found on
  real hardware, not in tests -- the library cache layout, the `/home` symlink,
  the flatpak process tree. A Windows port without a Windows machine to try it
  on would be guesswork.
- **Does the importer stay a separate project?** Probably not. Upstream is
  explicitly a Bazzite tool, and making the importer cross-platform means
  reworking most of what is platform-specific in it -- which is most of what
  this fork has not already replaced. The likely answer is to fold the fork
  into this project directly and stop maintaining two.

  That is a real decision with costs on both sides, so it is written down here
  rather than assumed:

  - **For folding in.** One repository, one version number, one test suite, one
    install. The CLI contract exists to keep two projects honest about their
    boundary; with one project it is overhead, and every change that spans both
    -- which by now is most of them -- currently costs two commits, two
    deploys and two test runs.
  - **Against.** The contract is also what keeps `apps.json` rules in exactly
    one place, and what would let either side be rewritten in another language.
    Folding in means the discipline has to be kept by intent instead of by
    construction.
  - **What it costs upstream.** The fork stops being a fork: no more rebasing
    onto wadiebs' commits, and the existing PRs become moot. Given upstream has
    not replied to them, that is a smaller loss than it looks -- but it should
    be a decision, not a drift. Attribution and the MIT licence stay either way,
    and the merged project has to keep saying which upstream it came from.

  If it is folded in, do it *before* the port rather than during: a port and a
  merge at the same time means no known-good state to compare against.

### Suggested order

1. **Generic Linux -- done, 2026-09-15.** See below.
2. macOS: paths and the browser launch; no Flatpak to worry about.
3. Windows: the real port. Config discovery, the launcher, file permissions,
   and an installer that suits the platform rather than imitating ours.

### What generic Linux established

Tested on throwaway VMs on the Unraid host, built from cloud images: Debian 13,
Ubuntu 24.04, Fedora 43 and Arch, alongside Bazzite and macOS. Python 3.10,
3.12, 3.13, 3.14. The full suite passes on all of them.

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

Still untested anywhere: a desktop session. Cloud images have no display, so
the browser launch, gamescope and the tile itself are still only exercised on
Bazzite.
