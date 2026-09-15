# Backlog

Things decided but not built. Each says what it is, why it matters, and what is
already known about the shape of it -- so picking one up does not start from a
blank page.

## Run everywhere Sunshine runs

**Logged 2026-09-14. Not started.**

Today this targets Bazzite, and a second target (a Legion Go S on SteamOS) is
assumed but untested. Sunshine itself runs on Windows, macOS and every Linux
distribution, and nothing about managing `apps.json` is Bazzite-specific. The
tool should follow.

### What is actually tied to the platform

Worth being precise, because most of the code is not:

- **Config directory discovery.** `detect_sunshine_config_dir()` knows about
  `~/.config/sunshine` and two Flatpak paths. Windows uses
  `%ProgramFiles%\Sunshine\config` (a machine-wide location, not a per-user
  one); macOS uses `~/.config/sunshine` under Homebrew but `/Applications` for
  the app bundle.
- **The launcher script.** `sunshine-apps-ui-launch` is bash, uses `pkill`,
  `pgrep` and `flatpak run`, and assumes a Chrome flatpak. None of that exists
  on Windows.
- **Steam and Heroic discovery.** Library paths and the `steam -applaunch`
  command differ per platform; the Steam library cache layout does not.
- **File modes.** The mode-600 checks on the credentials and SteamGridDB key
  files are POSIX. Windows needs an ACL check or an honest admission that it
  does not have one.
- **`install` / `uninstall`.** Per-user under `~/.local` is right for Linux and
  macOS. Windows has no equivalent convention worth pretending about.

### What is not tied to the platform

The reconciler, tombstones, the mutate contract, the plan document, the whole
web UI, and the artwork sources. That is most of the value, and it is already
stdlib-only Python. This is a port of the edges, not a rewrite.

### Open questions

- **Which platform second?** SteamOS is the one already promised and the
  closest (same shell, same paths, gamescope instead of a normal session).
  Windows is the largest Sunshine population and the most work.
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

1. SteamOS, on the Legion Go S. Mostly confirming what already works.
2. Generic Linux: remove the Bazzite assumptions from discovery and the
   installer, and say what is required instead.
3. macOS: paths and the browser launch; no Flatpak to worry about.
4. Windows: the real port. Config discovery, the launcher, file permissions,
   and an installer that suits the platform rather than imitating ours.
