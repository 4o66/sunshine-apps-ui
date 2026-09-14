# Security posture

## The listener binds to 127.0.0.1, and that is not configurable

There is deliberately **no option** to change the bind address. Not a flag, not an
env var, not a config key. A server that can rewrite `apps.json` and execute an
import is a remote-code-execution surface; the one-line mistake of setting
`0.0.0.0` "just to test from my laptop" is the whole vulnerability. Removing the
knob removes the mistake. Sunshine itself models this with
`origin_web_ui_allowed = pc`.

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

## Prefer launch-on-demand over an always-on service

The server should start when the UI is opened and exit when the browser closes,
rather than running permanently as a systemd user unit. A process that is not
running has no attack surface, and the Sunshine app entry launches it anyway.

## Credentials

Applying changes without restarting Sunshine requires posting to Sunshine's own
API, which needs its web-UI credentials. Those are read from a mode-600 file or
prompted per session. Never on argv -- the parent project got this wrong with
`--sgdb-key`, which leaks into `ps` output and shell history. That one now has
`--save-sgdb-key`, which reads the key on stdin and stores it the same way.

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
