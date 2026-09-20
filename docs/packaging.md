# Packaging, and why the update check cannot install anything

**Status: there is no package.** The update check in Settings asks GitHub what
the newest release is and tells you. It cannot install it, and the page says
so rather than offering a button that would fail.

This is the honest state of things, written down so the gap is deliberate
rather than forgotten.

## What is shipped today

`scripts/make-release` builds two archives of the same tree:

| file | for |
|---|---|
| `sunshine-apps-ui.zip` | the Windows one-paste install |
| `sunshine-apps-ui.tar.gz` | the Linux install |

The filenames carry no version, because the install instructions point at
`releases/latest/download/<name>` and that only resolves if the name is the
same every time. The directory *inside* each archive carries the version, so
an extracted copy is identifiable.

`docs/` and `tests/` are left out of both: a person installing this does not
need the decision record or the test suite, and both are on GitHub.

## What updating means right now

Download the new archive and run the installer over the top. It installs to
the same place, keeps your `apps.json` alone — the installer never writes it —
and leaves your preferences where they are, under the state directory rather
than the program directory.

On Windows, Add/Remove Programs lists the installed copy; installing a newer
one updates that entry rather than adding a second.

## What a real update would need, in order

1. **A signed or checksummed artifact per platform.** The archive is already
   built reproducibly from a clean tree; what is missing is a published digest
   the program can verify before it unpacks anything.
2. **A way to replace a running program.** On Windows the installer cannot
   overwrite files the running manager has open, so an update has to stage the
   new copy and swap it after exit. On Linux it is simpler but the same shape.
3. **A rollback.** Every write to `apps.json` is backed up; an update that
   replaces the program deserves the same courtesy.

Until those exist, the check tells you a release is there and links to what
changed. That is less than an updater and more than silence.
