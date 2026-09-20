# How this was built, and with what

This project's code was written almost entirely by an AI assistant (Anthropic's
Claude, driven from Claude Code) under direction, review and testing by a
human maintainer. That is stated here plainly because you are entitled to know
what you are installing, and because the interesting part is not *that* it was
used but *how it was constrained*.

## The division of labour

**The assistant wrote:** essentially all of the Python, the 187 lines of C# in
`src/sunshine_apps_ui/host/AppWindow.cs`, the tests, the documentation, and the
tile artwork generator. As of this writing: 41 modules, ~12,800 lines of
source, 33 test files, ~10,200 lines of tests.

**The maintainer did:** all of the direction, the design decisions, the
acceptance testing on real hardware, and the rejections. Every feature in here
exists because it was asked for, and several exist in their current shape
because the first attempt was sent back.

Both matter. The code is machine-written; the judgement about whether it is
any good is not.

## The rules it works under

These are enforced in the maintainer's standing instructions and are not
negotiable per-task:

- **Measure, do not infer.** Any claim about behaviour — timings, privilege
  levels, whether a fallback works — must come from running it on the target
  machine. Estimates are labelled as estimates. When a measurement contradicts
  an earlier claim, the correction is stated plainly rather than quietly
  folded in.
- **Never test as the built-in Administrator on Windows.** It receives an
  unfiltered token, so nothing about elevation or de-elevation measured there
  is true of a real machine. Testing uses a normal account with local admin.
- **Credentials are never typed into the session.** They are captured by a
  script the human runs, never passed inline, never echoed, never printed —
  including into logs and commit messages.
- **Destructive operations are confirmed first**, and backups are taken before
  anything is overwritten. `docker image prune` never with `-a`. No force-push
  without an explicit instruction and a bundle taken first.
- **Shared repositories are worked in a worktree**, never with `git add -A`,
  and a push is confirmed against the remote ref rather than against local
  `HEAD`.
- **Lab machines are powered down when testing finishes**, with their disks
  kept.
- **Artwork is not invented.** Designs are shown as mockups and approved before
  any code is written; logos are taken from their owners' published sources
  under stated licences, never redrawn from memory.

## Testing: what a machine checked, and what a person did

**Automated.** ~10,200 lines of tests to ~12,800 lines of source. They run on
every change and cover the things that are logic: the reconciler and its
divergence rules, the mutation contract, path handling across platforms,
version comparison, the localization fallback chains, command-line
construction for every browser and platform, tombstones, backups.

**What automated tests could not catch, and did not.** Almost everything that
made this program actually work on a television was found by running it on
real hardware:

- Whether a window appears at all, how long it takes, and whether closing it
  leaves anything behind.
- Integrity levels and de-elevation on Windows.
- That WebKitGTK aborts on Ubuntu 24.04 because its sandbox needs an
  unprivileged user namespace that the distribution restricts by default.
- That `Gtk.Application` could not register on a session bus, so no window
  ever appeared.
- That a page's own Content-Security-Policy silently refused its own inline
  script, leaving a progress display frozen at "0.0s".
- That text shaping is absent from the Pillow wheel shipped on Windows, so
  Arabic, Hebrew, Devanagari and Thai cannot be rendered correctly.

**Found by the human, in use, not by any test:** missing artwork on imported
games; an artwork message that demanded an API key for a picture already on
disk; a ten-second wait before the interface appeared; the window not being
fullscreen over Moonlight; no Start-menu entry; a console window left behind;
"apply changes" appearing to do nothing; the scan page frozen; the Steam logo
clipped at the bottom of a tile; a caption claiming something the picture
contradicted; a colour gradient that was actually two flat blocks; a penguin
that looked like a bad knock-off.

**Corrections the assistant made to its own claims**, after measuring: a
predicted ~300 ms window start that was actually 1.7 s; a set of GUI
measurements taken in Windows session 0, where no window can be seen, which
had to be thrown away entirely; three separate occasions where a test harness
was broken rather than the product, reported as product failures until proven
otherwise.

The honest summary: **the test suite is good at logic and blind to reality.**
Every platform-specific defect in this project's history was found by a person
running it, or by the assistant running it on the actual machine — never by the
unit tests.

## What this means for you

Read the code. It is commented heavily, including the reasoning for decisions
that look odd, and the measurements that led to them. Nothing here is
obfuscated or minified, the bundled interpreter is an unmodified published
CPython verified by checksum, and the only compiled artifact is built on your
machine from source in this repository.

If you find something wrong, the report link in the interface goes to the
issues page.
