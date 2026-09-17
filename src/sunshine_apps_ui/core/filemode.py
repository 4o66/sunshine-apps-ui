# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeping a secrets file to its owner, on either kind of filesystem.

Two files hold secrets: the Sunshine credentials and the SteamGridDB key. Both
were created mode 600 and refused if ``st_mode & 0o077`` showed anyone else
could read them.

On Windows that check is worse than useless. Python reports a synthetic mode
there, so the bits are always clear and the test passes no matter who can read
the file; ``os.chmod`` only toggles the read-only attribute and does not touch
the ACL, which is what actually decides access. A file created in Sunshine's
config directory inherits that directory's ACL, and under Program Files that
grants read to every authenticated user. So the guard would have reported
"secure" about a password readable by anyone with an account.

This module answers the same two questions on both systems:

* **Is it private?** POSIX reads the mode. Windows walks the DACL and compares
  each entry's SID against the three that may legitimately have access -- the
  owner, SYSTEM and Administrators. SIDs, not names, because names are
  localised and "Administrators" is "Administratoren" on a German install.
* **Create it private.** POSIX opens with 0600. Windows creates the file, then
  removes inherited entries and grants those same three SIDs, so nothing the
  parent directory allows survives.
"""

import os
import subprocess
import sys
from typing import List, Optional, Tuple

# Access that may exist on a secrets file without it being a leak.
SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
# These two name the owner rather than a principal: CREATOR OWNER is the
# placeholder an inherited entry carries, and OWNER RIGHTS is the access the
# current owner has. Windows puts them on files created in a user's own
# directories. Accepting them is only sound because the owner is checked too --
# "whoever owns this may read it" is a leak if that is not us.
CREATOR_OWNER_SID = "S-1-3-0"
OWNER_RIGHTS_SID = "S-1-3-4"


def on_windows() -> bool:
    return os.name == "nt"


def _apis():
    """advapi32 and kernel32 with their prototypes declared.

    Not optional. Undeclared, ctypes treats every argument as a C int, and
    GetCurrentProcess()'s pseudo-handle is truncated on a 64-bit build -- so the
    call fails with ERROR_INVALID_HANDLE and the guard answers "cannot tell"
    about a file it never actually looked at. This was found by running on the
    rig; it cannot be found from macOS, where none of it executes.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_wchar_p)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    return advapi32, kernel32


def current_user_sid() -> Optional[str]:
    """The SID of the account we are running as, as a string."""
    if not on_windows():
        return None
    import ctypes
    from ctypes import wintypes

    TOKEN_QUERY = 0x0008
    TokenUser = 1
    advapi32, kernel32 = _apis()

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, TokenUser, buffer,
                                            size.value, ctypes.byref(size)):
            return None
        # TOKEN_USER is a SID_AND_ATTRIBUTES: the SID pointer comes first.
        sid_pointer = ctypes.c_void_p.from_buffer(buffer).value
        return _sid_to_string(sid_pointer)
    finally:
        kernel32.CloseHandle(token)


def _sid_to_string(sid_pointer) -> Optional[str]:
    import ctypes
    advapi32, kernel32 = _apis()
    text = ctypes.c_wchar_p()
    # ConvertSidToStringSidW: the W matters. Letting ctypes pick the ANSI entry
    # point and then reading the result as wide characters returns mojibake.
    if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid_pointer),
                                           ctypes.byref(text)):
        return None
    try:
        return text.value
    finally:
        kernel32.LocalFree(text)


def owner_sid(path: str) -> Optional[str]:
    """Who owns the file, as a string SID."""
    import ctypes

    SE_FILE_OBJECT = 1
    OWNER_SECURITY_INFORMATION = 0x00000001
    advapi32, kernel32 = _apis()

    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        path, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION,
        ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
    if status != 0:
        raise OSError(f"could not read the owner of {path} (error {status})")
    try:
        return _sid_to_string(owner.value)
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


def dacl_sids(path: str) -> List[str]:
    """Every SID with an entry in the file's DACL, as strings."""
    import ctypes
    from ctypes import wintypes

    SE_FILE_OBJECT = 1
    DACL_SECURITY_INFORMATION = 0x00000004
    advapi32, kernel32 = _apis()

    class ACL(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", wintypes.WORD), ("AceCount", wintypes.WORD),
                    ("Sbz2", wintypes.WORD)]

    class ACE_HEADER(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", wintypes.WORD)]

    class ACCESS_ALLOWED_ACE(ctypes.Structure):
        _fields_ = [("Header", ACE_HEADER), ("Mask", wintypes.DWORD),
                    ("SidStart", wintypes.DWORD)]

    dacl_pointer = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        None, None, ctypes.byref(dacl_pointer), None, ctypes.byref(descriptor))
    if status != 0:
        raise OSError(f"could not read the permissions of {path} (error {status})")
    try:
        if not dacl_pointer:
            # No DACL at all means no protection whatsoever.
            return ["<none>"]
        dacl = ctypes.cast(dacl_pointer, ctypes.POINTER(ACL))
        found = []
        for index in range(dacl.contents.AceCount):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl_pointer, index, ctypes.byref(ace)):
                continue
            entry = ctypes.cast(ace, ctypes.POINTER(ACCESS_ALLOWED_ACE)).contents
            sid = _sid_to_string(ctypes.addressof(entry) +
                                 ACCESS_ALLOWED_ACE.SidStart.offset)
            if sid:
                found.append(sid)
        return found
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


def check_private(path: str) -> Tuple[bool, str]:
    """(is_private, what to say if not). The message names the fix."""
    if not on_windows():
        mode = os.stat(path).st_mode & 0o077
        if mode:
            return False, (f"{path} is readable by others "
                           f"(mode {oct(os.stat(path).st_mode & 0o777)}). "
                           f"Run: chmod 600 {path}")
        return True, ""

    allowed = {SYSTEM_SID, ADMINISTRATORS_SID, CREATOR_OWNER_SID, OWNER_RIGHTS_SID}
    mine = current_user_sid()
    if mine:
        allowed.add(mine)
    try:
        owner = owner_sid(path)
        if owner and owner not in (mine, SYSTEM_SID, ADMINISTRATORS_SID):
            return False, (f"{path} is owned by {owner}, not by you. Anything granted "
                           f"to the owner is granted to them, so this cannot be "
                           f"treated as private.")
        sids = dacl_sids(path)
    except OSError as e:
        # Refusing to guess: an unreadable ACL is not evidence of a safe one.
        return False, f"{str(e)} -- cannot confirm that only you can read it."
    extra = [sid for sid in sids if sid not in allowed]
    if extra:
        return False, (
            f"{path} can be read by more than you: {', '.join(sorted(set(extra)))}. "
            f"It is in Sunshine's own directory, so it inherited that directory's "
            f"permissions. Re-save it, or run: "
            f'icacls "{path}" /inheritance:r /grant:r "{mine or "%USERNAME%"}:F"')
    return True, ""


def _lock_down_windows(path: str) -> None:
    """Strip inherited access and grant only the three that may have it."""
    mine = current_user_sid()
    grants = [f"*{SYSTEM_SID}:F", f"*{ADMINISTRATORS_SID}:F"]
    if mine:
        grants.append(f"*{mine}:F")
    # icacls rather than building an ACL by hand: it ships with Windows, and
    # the *SID syntax sidesteps the localised account names that make every
    # name-based version of this wrong on a non-English install.
    subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", *grants],
                   check=True, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def open_private(path: str):
    """Open a file for writing that only its owner may read.

    For the server's log, which carries the session token in the URL it prints.
    Two properties, and the second is the one that is easy to miss:

    * **Mode 600 from creation**, so the token is never in a world-readable file.
    * **O_NOFOLLOW**, so a symlink someone else left at that path is refused
      rather than followed. A fixed name in a shared directory is a place
      anybody can get there first, and a launcher that runs elevated following
      one is an arbitrary-file-overwrite.
    """
    flags = (os.O_WRONLY | os.O_CREAT | os.O_TRUNC
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    handle = os.open(path, flags, 0o600)
    if not on_windows():
        os.chmod(path, 0o600)
    else:
        _lock_down_windows(path)
    return os.fdopen(handle, "w", encoding="utf-8")


def write_private(path: str, text: str) -> str:
    """Write a secret, private from the moment it exists.

    Never widen-then-narrow: that leaves a window in which the file is readable,
    and the secret is in it.
    """
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(text)
    if on_windows():
        # The file exists and is empty-of-protection until this runs, but it is
        # inside a directory only an administrator can write, and the content is
        # already there either way -- doing it before the write would be lost by
        # the create.
        _lock_down_windows(path)
    else:
        os.chmod(path, 0o600)
    return path
