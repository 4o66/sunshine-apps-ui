# SPDX-License-Identifier: GPL-3.0-or-later
"""Where this keeps things, per platform.

One answer, in one place. The state directory was worked out independently in
four modules -- the queue, the launcher, the backups and the installer -- with
the same POSIX expression copied into each. That was fine while there was one
platform. It is not now: `~/.local/state` on Windows produces
``C:\\Users\\you/.local/state``, a real directory Windows will happily create,
in a place no Windows program keeps anything and no backup tool looks.

``XDG_STATE_HOME`` still wins everywhere, including on Windows. It is what the
tests set, and honouring it is also the only way to run two of these side by
side.
"""

import os


def state_home() -> str:
    """The base directory for state that is ours, not the user's documents."""
    override = os.getenv("XDG_STATE_HOME")
    if override:
        return override
    if os.name == "nt":
        import ntpath
        return os.getenv("LOCALAPPDATA") or ntpath.join(
            os.path.expanduser("~"), "AppData", "Local")
    return os.path.expanduser(os.path.join("~", ".local", "state"))


def state_dir() -> str:
    """Ours within it: the queue, the drafts, the backups, the browser profile."""
    if os.name == "nt":
        import ntpath
        return ntpath.join(state_home(), "sunshine-apps-ui")
    return os.path.join(state_home(), "sunshine-apps-ui")


def data_home() -> str:
    """Where a user's own application data belongs -- menu entries included.

    ``XDG_DATA_HOME`` or ``~/.local/share``, which is where every Linux desktop
    looks for a ``.desktop`` file it did not install itself.
    """
    override = os.getenv("XDG_DATA_HOME")
    if override:
        return override
    return os.path.expanduser(os.path.join("~", ".local", "share"))


def programs_home() -> str:
    """Where a per-user install of a program belongs.

    Windows has no ``~/.local`` convention worth pretending about, but it does
    have this one: ``%LOCALAPPDATA%\\Programs`` is where a per-user install goes,
    and it needs no administrator to write.
    """
    if os.name == "nt":
        import ntpath
        return ntpath.join(state_home(), "Programs")
    return os.path.expanduser(os.path.join("~", ".local"))
