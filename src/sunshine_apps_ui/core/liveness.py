# SPDX-License-Identifier: GPL-3.0-or-later
"""Which Sunshine config tree is live, asked of Sunshine rather than of mtimes.

Ranking trees by when their files last changed cannot tell a fresh install
that has never run from an abandoned one, and is fooled by anything else that
touches the files. Issue #19. Two better witnesses, where they exist:

* a running `sunshine` process, which is the live one by definition;
* an enabled service, which is the one that will run.

Both are read for what they *execute*, never for what they are called. The
native RPM's unit is named app-dev.lizardbyte.app.Sunshine.service -- aliased
sunshine.service, running /usr/bin/sunshine -- and looks exactly like a
Flatpak's. Its autostart entry has a Flatpak-style name too, and only runs
`systemctl start --u sunshine`.

The native process is also mostly opaque: Sunshine is installed with file
capabilities for KMS capture, which makes it non-dumpable, so its open files,
environment and executable link are all "Permission denied", even to the user
it runs as. Measured on the Bazzite box, 2026-09-26. Its command line is still
readable, and that plus Sunshine's own default is what this goes on.

Linux only. Elsewhere there is nothing here and the ranking stands.
"""

import configparser
import os
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Sequence

# The Flatpak ids Sunshine has shipped under, for a sandboxed process whose id
# cannot be read.
FLATPAK_IDS = ("dev.lizardbyte.app.Sunshine", "dev.lizardbyte.Sunshine")


def _flatpak_tree(home: str, app_id: str) -> str:
    return os.path.join(home, ".var", "app", app_id, "config", "sunshine")


def _native_tree(home: str, environ: Optional[Dict[str, str]] = None) -> str:
    """Where Sunshine itself looks: $XDG_CONFIG_HOME/sunshine, else ~/.config."""
    base = (environ or {}).get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "sunshine")


def tree_for_command(argv: Sequence[str], home: str,
                     environ: Optional[Dict[str, str]] = None,
                     flatpak_id: str = "") -> List[str]:
    """The config tree a Sunshine command line would read, or [] if it is not one.

    A list because a sandboxed process whose app id cannot be read could be
    either Flatpak; the caller keeps whichever of those exists.
    """
    argv = [a for a in argv if a]
    if not argv:
        return []
    name = os.path.basename(argv[0])

    if name == "flatpak":
        if "run" not in argv:
            return []
        rest = argv[argv.index("run") + 1:]
        app = next((a for a in rest if not a.startswith("-")), "")
        return [_flatpak_tree(home, app)] if "sunshine" in app.lower() else []

    if name != "sunshine":
        return []

    # Sunshine takes its config file as the one positional argument; the tree
    # is the directory holding it.
    config = next((a for a in argv[1:] if a.endswith(".conf")
                   and not a.startswith("-")), "")
    if config:
        return [os.path.dirname(os.path.abspath(os.path.expanduser(config)))]

    if argv[0].startswith("/app/"):
        ids = [flatpak_id] if flatpak_id else list(FLATPAK_IDS)
        return [_flatpak_tree(home, app) for app in ids]
    return [_native_tree(home, environ)]


def _read(path: str, binary: bool = False):
    try:
        with open(path, "rb" if binary else "r") as handle:
            return handle.read()
    except OSError:
        return None


def _flatpak_id(pid_dir: str) -> str:
    """The app id of a sandboxed process, if its .flatpak-info can be read."""
    text = _read(os.path.join(pid_dir, "root", ".flatpak-info"))
    if not text:
        return ""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error:
        return ""
    return parser.get("Application", "name", fallback="")


def running_trees(home: str, proc: str = "/proc") -> List[str]:
    """Config trees read by a `sunshine` running as this user."""
    found: List[str] = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return found
    me = os.getuid()
    for pid in pids:
        pid_dir = os.path.join(proc, pid)
        if (_read(os.path.join(pid_dir, "comm")) or "").strip() != "sunshine":
            continue
        try:
            if os.stat(pid_dir).st_uid != me:
                continue
        except OSError:
            continue
        raw = _read(os.path.join(pid_dir, "cmdline"), binary=True) or b""
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        # Unreadable for the capability-holding native binary, which is the
        # usual case; readable for anything else.
        env_raw = _read(os.path.join(pid_dir, "environ"), binary=True)
        environ = None
        if env_raw:
            environ = dict(item.decode("utf-8", "replace").partition("=")[::2]
                           for item in env_raw.split(b"\0") if b"=" in item)
        for tree in tree_for_command(argv, home, environ, _flatpak_id(pid_dir)):
            if tree not in found:
                found.append(tree)
    return found


def _systemctl(args: List[str]) -> str:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True,
                              text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def service_trees(home: str,
                  systemctl: Callable[[List[str]], str] = _systemctl) -> List[str]:
    """Config trees an enabled user service would start Sunshine on.

    Every enabled unit is asked what it runs -- in one call -- rather than
    guessing which of them is Sunshine's from the names.
    """
    listing = systemctl(["list-unit-files", "--type=service", "--state=enabled",
                         "--no-legend", "--plain"])
    units = [line.split()[0] for line in listing.splitlines() if line.split()]
    if not units:
        return []
    shown = systemctl(["show", "-p", "Id", "-p", "ExecStart", *units])
    found: List[str] = []
    for line in shown.splitlines():
        if not line.startswith("ExecStart="):
            continue
        # { path=/usr/bin/sunshine ; argv[]=/usr/bin/sunshine ; ignore_errors=no ; ... }
        _, _, after = line.partition("argv[]=")
        argv = after.split(" ; ", 1)[0].split()
        for tree in tree_for_command(argv, home):
            if tree not in found:
                found.append(tree)
    return found


def evidence(home: str) -> Dict[str, List[str]]:
    """What Sunshine itself says about which tree is live. Empty off Linux."""
    if not sys.platform.startswith("linux"):
        return {"running": [], "service": []}
    running = running_trees(home)
    # A service is only asked when nothing is running: what is running already
    # answers the question, and asking costs two subprocesses.
    return {"running": running, "service": [] if running else service_trees(home)}
