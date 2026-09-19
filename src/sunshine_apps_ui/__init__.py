# SPDX-License-Identifier: GPL-3.0-or-later
"""Manage the applications Sunshine offers.

A tile manager for Sunshine's apps.json, reached through Moonlight or at the
console -- both of which put the page on the host, which is why the listener
binds 127.0.0.1 and why that costs nothing.

It was two projects: this interface and bazzite-sunshine-manager, a fork of
wadiebs' importer, talking over a CLI contract. They were folded together; the
engine lives in core and still owns the file on its own. See NOTICE.
"""

from .version import display as version_display  # noqa: E402
from .version import version as _version

__version__ = _version()

# The plan document schema this version understands. Reject anything else rather
# than guessing at a shape we have not seen.
SUPPORTED_SCHEMA = 1


def _repair_streams() -> None:
    """Make sure this process can print, before anything tries to.

    pythonw.exe gives a process no stdout and no stderr -- they are None -- and
    any module that touches them while being imported takes the whole program
    down before it reaches main(). One did, and the result was a Start menu
    shortcut that did nothing at all and left nothing behind to explain it.

    Done here, at package import, so it is true for every entry point: the
    launcher, the server, the browser helper, and anything added later.
    """
    import os
    import sys

    if sys.stdout is not None and sys.stderr is not None:
        return
    target = None
    try:
        from .core import filemode
        from . import places
        os.makedirs(places.state_dir(), exist_ok=True)
        target = filemode.append_private(
            os.path.join(places.state_dir(), "launcher.log"))
    except Exception:                    # noqa: BLE001 - never fail to start
        try:
            target = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return
    if sys.stdout is None:
        sys.stdout = target
    if sys.stderr is None:
        sys.stderr = target


_repair_streams()
