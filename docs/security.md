# Security posture

This was written when the server was always unprivileged. On Windows it is not:
`apps.json` lives in Sunshine's own directory under Program Files, so writing it
needs administrator rights, and Sunshine grants them to a tile marked
`"elevated"`. That changes what several of the defences below are *for*, so the
Windows case is stated first and the rest is read in its light.

## On Windows the server runs elevated, and that raises the stakes of everything else

Not by choice, and not avoidably: it is the only way to write the file this
program exists to manage. What follows from it:

**Every defence below stops being defence in depth and becomes load-bearing.**
Unprivileged, a flaw in this server gets an attacker what the user already has.
Elevated, the same flaw gets them administrator. The bind address, the token and
the origin checks are no longer three layers over a small prize; they are the
only things between a bug here and rights nothing else on the desktop has.

**The window never inherits those rights.** Whatever renders the page is a far
larger surface than this server is -- a general-purpose engine with a JIT, a
network stack and, in a browser's case, extensions -- and running one as
administrator would give away everything the elevation was for. When the
launcher is elevated it does not start the window itself: it asks the task
scheduler for a medium-integrity helper, and the helper starts it. Measured:
launcher High, helper Medium, browser Medium, with its sandboxed children at Low.

**This holds for our own window too**, which is the one on Windows by default
now (`winhost.py`, issue #25). It is the same path -- the helper starts it, and
nothing about it is exempt. Measured on the rig 2026-09-18 with an elevated
launcher: launcher High (S-1-16-12288), window process Medium (S-1-16-8192),
with WebView2's own children below that. A window that could only be opened by
giving it administrator would not be worth having.

Two things that looked like they did this and do not, recorded so nobody
re-derives them: `ShellExecuteW` and `Shell.Application`'s ShellExecute both
start the target with *our* token when the caller is elevated. Proved with
notepad, which came up High. It appeared to work when tested with a browser only
because **Edge and Chrome refuse to run elevated and relaunch themselves
de-elevated** -- Firefox and Opera do not, and would have inherited
administrator while the measurement said otherwise.

**Being unelevated is a supported state, not a failure.** A standard account, or
a Sunshine started by hand, leaves us unable to write. That is checked once at
startup and said on the page, rather than discovered at the first write after
somebody has queued a dozen changes. Reading, scanning and reloading still work:
they go through Sunshine's own API, which needs credentials rather than rights.

**Restarting Sunshine is not a workaround for any of this.** `POST /api/restart`
needs only credentials, so an unelevated process can call it -- and on a
standalone Sunshine started without a console it exits and stays dead. Changes
are applied by saving one unchanged app, which triggers a reload without
terminating anything.

## The listener binds to 127.0.0.1, and that is not configurable

There is deliberately **no option** to change the bind address. Not a flag, not an
env var, not a config key. A server that can rewrite `apps.json` and execute an
import is a remote-code-execution surface; the one-line mistake of setting
`0.0.0.0` "just to test from my laptop" is the whole vulnerability. Removing the
knob removes the mistake. Sunshine itself models this with
`origin_web_ui_allowed = pc`.

On Windows it is worse than remote code execution: it is remote code execution
as administrator. The knob stays absent.

**Nothing is given up by it**, which is what makes the decision easy to hold.
There are two ways to use this and both are local to the host: through Moonlight,
where the page is drawn in the session Sunshine is streaming, or at the console,
where it is drawn on the machine in front of you. In both the browser is on the
same machine as the server. A remote binding would not enable a use we have; it
would only add a way to be wrong.

The **port** is configurable. The address is not.

## Loopback is not the same as private

Binding to 127.0.0.1 stops remote hosts. It does not stop:

1. **Other local users.** Any process on the machine, running as any user, can
   reach a loopback port. Mitigation: a per-session bearer token, generated at
   startup, required on every request.
2. **DNS rebinding.** A web page the user visits can resolve a hostname it
   controls to 127.0.0.1 and make the *browser* issue requests to this server,
   from outside our origin. Loopback binding does nothing about this.
   Mitigation: reject any request whose `Host` header is not exactly
   `127.0.0.1:<port>` or `localhost:<port>`.
3. **Cross-site requests from any open tab.** Mitigation: require
   `Sec-Fetch-Site: same-origin` (or a matching `Origin`) on every
   state-changing request, plus a CSRF token. Sunshine implements this pattern
   in `confighttp.cpp`; copy it rather than invent one.

## The token is only as private as the places it is written

It authenticates every request, so anywhere it appears is somewhere it can be
taken from. Three places it could have leaked, and what each does now:

- **The server's log.** The server prints its URL so the launcher can find it,
  and the URL carries the token. That log used to be `/tmp/sunshine-apps-ui.log`,
  created with whatever the umask allowed -- a fixed name, in a directory every
  local user can read, holding the credential that answers threat 1 above. It is
  now in the per-user state directory, created mode 600, and opened with
  `O_NOFOLLOW`: a fixed path in a shared directory is also somewhere another
  user can get there first with a symlink, and an elevated launcher following one
  is an arbitrary-file-overwrite.
- **A command line.** The Windows browser helper is told where to go by a file
  written mode 600, not by an argument. `argv` is readable by every process on
  the machine, which would make the token public to exactly the audience the
  token exists to exclude.
- **The browser's own profile.** The window gets a profile directory of its own
  under our state directory, not the user's everyday one -- which also happens to
  be what makes the browser a process we can wait on and close.

## Prefer launch-on-demand over an always-on service

The server starts when the UI is opened and exits when the browser closes,
rather than running permanently. A process that is not running has no attack
surface, and the Sunshine app entry launches it anyway. This matters more on
Windows than anywhere else: an elevated listener that exists only while somebody
is looking at the page is a much smaller thing to get wrong than one that is
always up.

## Credentials

Applying changes without restarting Sunshine requires posting to Sunshine's own
API, which needs its web-UI credentials. They are stored in a file only the owner
can read, and never on argv -- the parent project got this wrong with
`--sgdb-key`, which leaks into `ps` output and shell history. That one now has
`--save-sgdb-key`, which reads the key on stdin and stores it the same way.

**"Only the owner can read it" means something different on Windows**, and the
POSIX version of the check was worse than useless there. Python reports a
synthetic mode on Windows, so `st_mode & 0o077` is always zero and the guard
passed no matter who could read the file; `os.chmod` only toggles the read-only
attribute and never touches the ACL that actually decides. A credentials file
created in Sunshine's own directory inherits that directory's ACL -- under
Program Files, readable by every authenticated account. The check now reads the
DACL and compares **SIDs, not names** (names are localised), refuses when the ACL
cannot be read rather than assuming it is fine, and verifies the owner -- because
an entry granting access to "the owner" is only safe while that is you.

## Images are served from an allowlist, never from a path

`/art` takes a path, but it does not inspect it: the path has to be in a set
rebuilt from the current `apps.json`, the pending queue, and the importer's two
artwork cache directories on every request. There is no `..` check because there
is nothing for `..` to escape -- a path that is not in the set is simply not
found. Adding a source of images means adding it to that set, not relaxing a
rule.

The artwork picker is a case in point. A candidate it has fetched is referred to
by nothing yet, so it is allowed by enumerating what is in the cache directory,
which is still an exact set of filenames rather than a prefix match.

**Windows spells the same file several ways** -- `C:\x\y.png`, `c:/x/y.png` and
`C:\X\Y.PNG` are one file -- so an allowlist of exact strings refused images it
should have served, including Sunshine's own default tiles. Comparison is done
on a normalised key there. It is still an exact set of paths taken from
`apps.json`: normalising the spelling is not the same as loosening the rule, and
POSIX is deliberately left case-sensitive, because there those really are three
different files.

## What this program does not do, and should not start doing

- **Serve anything by path.** See above. Every file this serves is in a set
  built from configuration.
- **Run a command it was given.** The importers generate command lines; the HTTP
  surface never executes one it was handed.
- **List directories itself.** `/browse` proxies to Sunshine's own file browser,
  with Sunshine's credentials and Sunshine's rights. That keeps one thing true
  that is worth keeping: an elevated *listener* of ours is not also an elevated
  *file browser* of ours.
- **Bind anywhere but loopback**, or take the token from anywhere but a header
  or the query string of a page we handed out.
