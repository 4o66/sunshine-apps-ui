# SPDX-License-Identifier: GPL-3.0-or-later
"""Can we write apps.json, and if not, why not.

Asked once at startup, because the alternative is discovering it at the write --
after someone has queued a dozen changes. That is the wrong end.

The question is deliberately "can I write this file", not "is Sunshine running as
a service" or "am I elevated". One check of our own token and the file answers
every case at once, and it does not care how somebody installed Sunshine. On
Windows there are two ways to end up able to write it -- launched by the service
with ``"elevated": true``, or launched by a Sunshine that was itself started
elevated -- and both look identical from here, which is the point.

Elevation is only consulted to *explain* a refusal. Two Windows cases fail
silently, and an unexplained failure is the thing this module exists to prevent:

* A **non-administrator account** gets no elevation and no error. Sunshine logs
  "Sunshine will retain the same access level as the current user and will not
  elevate it" and launches us unprivileged anyway.
* **Sunshine started by hand** rather than as the service cannot elevate anything:
  ``WTSQueryUserToken`` needs a SYSTEM caller, so there is no token to swap in.

Being unelevated does not break reloading -- that goes through Sunshine's own API
and needs credentials, not rights. It breaks writing. Restarting Sunshine is not
a workaround and risks shutting it down with no way back.
"""

import os
import sys
import tempfile
from typing import NamedTuple, Optional

from .core.api import apps_json_path


class Privilege(NamedTuple):
    """What we may do to apps.json, and a sentence saying why."""

    can_write: bool
    elevated: Optional[bool]   # None where the question does not apply
    detail: str                # empty when everything is fine
    headline: str = ""         # short form, for a banner heading

    @property
    def read_only(self) -> bool:
        return not self.can_write


def is_elevated() -> Optional[bool]:
    """True/False on Windows, None elsewhere.

    Nothing outside Windows has a second token to compare against: a POSIX
    process either has the rights to write the file or it does not, and
    ``can_write`` already says so.
    """
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes

    TOKEN_QUERY = 0x0008
    TokenElevation = 20
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        elevation = wintypes.DWORD()
        size = wintypes.DWORD()
        ok = advapi32.GetTokenInformation(
            token, TokenElevation, ctypes.byref(elevation),
            ctypes.sizeof(elevation), ctypes.byref(size))
        if not ok:
            return None
        return bool(elevation.value)
    finally:
        kernel32.CloseHandle(token)


def _can_write_file(path: str) -> bool:
    """Open it for writing without changing a byte.

    ``os.access`` is not an answer on Windows, where it reports the read-only
    attribute and ignores the ACL that actually decides this. Opening the file
    is the only honest test, and r+b neither truncates it nor moves its mtime.
    """
    try:
        with open(path, "r+b"):
            return True
    except OSError:
        return False


def _can_write_dir(path: str) -> bool:
    try:
        handle, temp = tempfile.mkstemp(prefix=".write-test-", dir=path)
    except OSError:
        return False
    os.close(handle)
    try:
        os.unlink(temp)
    except OSError:
        pass
    return True


def check(conf_dir: str) -> Privilege:
    """Whether apps.json can be written, and the sentence to show if not."""
    apps_json = apps_json_path(conf_dir)
    if os.path.exists(apps_json):
        writable = _can_write_file(apps_json)
    else:
        # Nothing to write yet is not a failure: Sunshine creates the file on
        # first run, and a directory we can write is the same answer.
        writable = os.path.isdir(conf_dir) and _can_write_dir(conf_dir)

    elevated = is_elevated()
    if writable:
        return Privilege(True, elevated, "", "")

    if elevated is False:
        return Privilege(
            False, False,
            f"This is running without administrator rights, and {apps_json} "
            f"belongs to Sunshine's own directory, which only an administrator "
            f"may write. Sunshine grants those rights to a tile marked "
            f'"elevated" -- but only when it is running as its service and the '
            f"account is an administrator. Started by hand, or from a standard "
            f"account, it launches this with your own rights and says so only in "
            f"its log. Reading, scanning and reloading still work; nothing can "
            f"be saved.",
            "Changes cannot be saved")

    if elevated is True:
        return Privilege(
            False, True,
            f"This is running as administrator and still cannot write "
            f"{apps_json}. That is a permissions problem on the file itself "
            f"rather than a missing right -- check who owns it.",
            "Changes cannot be saved")

    return Privilege(
        False, None,
        f"{apps_json} cannot be written by this user. Reading, scanning and "
        f"reloading still work; nothing can be saved.",
        "Changes cannot be saved")


def startup_line(state: Privilege, conf_dir: str) -> str:
    """One line for the log, said at startup rather than at the first write."""
    if state.can_write:
        where = "as administrator" if state.elevated else "as this user"
        return f"apps.json is writable {where}: {apps_json_path(conf_dir)}"
    return f"READ-ONLY: {state.detail}"
