# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening the interface as a window on Windows, and being sure it closes.

Three things are different here and each was measured on the rig (issue #15)
rather than reasoned about, because every one of them contradicts what the
obvious implementation would do.

**The browsers do not share a flag.** Edge and Chrome take ``--app=<url>`` and
give a window with no tabs and no address bar. Opera is Chromium-family and
**ignores ``--app`` completely** -- it opens an ordinary window, with Speed Dial,
a sidebar and a "make Opera your everyday browser" prompt, and never loads the
page. It honours ``--kiosk``. Firefox takes ``--kiosk`` too. So "Chromium-family"
is not a category that can be treated as one case.

**A fresh Firefox profile opens onboarding, not the page.** Kiosk mode fills the
screen with "Welcome to Firefox / Terms of Use" and our grid behind it, which on
a television with a gamepad is a dead end. The profile is seeded before first
launch so that cannot happen.

**Teardown is a job object, not a process tree.** Opera and Firefox both exit
their launched process and respawn, so the pid we started is gone within seconds
while the browser is still on screen -- tracking it would lose them. A job with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` catches every descendant, including the
respawn, and the OS takes them all down when the job's last handle closes *even
if we are killed rather than exiting*. Measured on all four browsers.

**The elevated case needs a helper.** When Sunshine grants us the administrator
token, anything we start plainly inherits it, and a browser running as
administrator is a far bigger surface than our server is: a general-purpose
program with a JIT, a network stack and extensions, on the user's desktop.
Handing it Explorer's token de-elevates it correctly but the browser then fails
to finish starting -- ``CreateProcessWithTokenW`` goes through the Secondary
Logon service, and Chromium does not survive the trip. What does work is asking
Explorer to start a *helper* at medium integrity, and letting the helper own the
job and the browser. The helper is this same program, run with ``--browser-helper``.
"""

import json
import os
import subprocess
import sys
import time
from typing import Dict, List, NamedTuple, Optional, Tuple

WINDOWS = os.name == "nt"


def launched_by_sunshine() -> bool:
    """Did Sunshine's tile start us, or did somebody open this at the machine?

    Sunshine puts its own variables in the environment of everything it launches
    (src/process.cpp). Their presence is the honest test; asserting it ourselves
    is not, which is what BSM_UI_VIA_SUNSHINE used to do -- it was set whenever
    the launcher ran, so opening this locally still warned about interrupting a
    stream that was not there.
    """
    return any(os.environ.get(name) for name in
               ("SUNSHINE_APP_ID", "SUNSHINE_CLIENT_NAME", "SUNSHINE_APP_NAME"))

# Enough to stop a fresh profile showing onboarding instead of the page. Without
# this, kiosk mode opens on the Terms of Use screen.
FIREFOX_PREFS = """// Written by sunshine-apps-ui. A fresh profile otherwise opens
// kiosk mode on the onboarding screen, which cannot be dismissed from a gamepad.
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("trailhead.firstrun.didSeeAboutWelcome", true);
"""


class Browser(NamedTuple):
    name: str
    path: str
    kind: str          # "webview2" | "app" | "kiosk-chromium" | "kiosk-firefox"

    def command(self, url: str, profile: str, streamed: bool = True) -> List[str]:
        """The command line, which depends on where this will be looked at.

        Streamed through Moonlight, nothing should frame the page: fullscreen,
        no border, no title bar. Opened at the machine from the Start menu, a
        window you cannot move or close is hostile -- so it fills the screen and
        keeps its frame. The maintainer's rule, 2026-09-17.
        """
        if self.kind == "webview2":
            # Our own window (winhost). It takes the profile under the same
            # name a Chromium browser does, deliberately: that is the string
            # the launcher recognises its own windows by.
            return [self.path, f"--user-data-dir={profile}",
                    "--fullscreen" if streamed else "--windowed", url]
        if self.kind == "app":
            window = "--start-fullscreen" if streamed else "--start-maximized"
            return [self.path, f"--user-data-dir={profile}", "--no-first-run",
                    "--no-default-browser-check", f"--app={url}", window]
        if self.kind == "kiosk-chromium":
            # Opera. --app is accepted on the command line and ignored, which is
            # worse than being rejected: it looks like it worked.
            command = [self.path, f"--user-data-dir={profile}", "--no-first-run"]
            # Kiosk has no way out, which is right on a television and wrong on
            # a desktop.
            return command + (["--kiosk", url] if streamed else [url])
        command = [self.path, "--profile", profile, "--no-remote"]
        return command + (["--kiosk", url] if streamed else [url])


def _candidates() -> List[Tuple[str, str, List[str]]]:
    """(name, kind, paths) in the order they are preferred.

    Edge first because it ships with Windows: there is always one, which is the
    problem Linux has and Windows does not.
    """
    local = os.environ.get("LOCALAPPDATA", "")
    x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return [
        ("edge", "app", [os.path.join(x86, "Microsoft", "Edge", "Application", "msedge.exe"),
                         os.path.join(files, "Microsoft", "Edge", "Application", "msedge.exe")]),
        ("chrome", "app", [os.path.join(files, "Google", "Chrome", "Application", "chrome.exe"),
                           os.path.join(x86, "Google", "Chrome", "Application", "chrome.exe"),
                           os.path.join(local, "Google", "Chrome", "Application", "chrome.exe")]),
        ("opera", "kiosk-chromium", [os.path.join(local, "Programs", "Opera", "opera.exe"),
                                     os.path.join(files, "Opera", "opera.exe")]),
        ("firefox", "kiosk-firefox", [os.path.join(files, "Mozilla Firefox", "firefox.exe"),
                                      os.path.join(x86, "Mozilla Firefox", "firefox.exe")]),
    ]


def _registered(executable: str) -> str:
    """Where Windows says a program is, for an install in none of the usual places."""
    try:
        import winreg
    except ImportError:
        return ""
    key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, key) as handle:
                path = str(winreg.QueryValueEx(handle, "")[0]).strip('"')
                if path and os.path.isfile(path):
                    return path
        except OSError:
            continue
    return ""


def find_browsers() -> List[Browser]:
    """Every window we can open, best first.

    Our own comes first when it is there: it is on screen in a third of a
    second against a browser's three and a half, and needs none of the flag
    table below. It is simply absent on a machine with no WebView2 runtime or
    where the build did not happen, and then this is exactly what it always
    was -- which is the whole reason the browser path stays.
    """
    found: List[Browser] = []
    ours = _own_window()
    if ours is not None:
        found.append(ours)
    for name, kind, paths in _candidates():
        for path in paths:
            if path and os.path.isfile(path):
                found.append(Browser(name, path, kind))
                break
        else:
            registered = _registered(os.path.basename(paths[0]))
            if registered:
                found.append(Browser(name, registered, kind))
    return found


def _own_window() -> Optional[Browser]:
    """The window we built at install time, if it is here and usable."""
    try:
        from . import winhost
        if not winhost.available():
            return None
        return Browser("our own window", winhost.host_exe(winhost.install_root()),
                       "webview2")
    except Exception:                    # noqa: BLE001 - never block the browser
        return None


def seed_firefox_profile(profile: str) -> None:
    """Make a fresh profile open the page rather than the onboarding screen."""
    try:
        os.makedirs(profile, exist_ok=True)
        with open(os.path.join(profile, "user.js"), "w", encoding="utf-8") as handle:
            handle.write(FIREFOX_PREFS)
    except OSError:
        # Not fatal: worst case the first launch shows onboarding once.
        pass


# ------------------------------------------------------------- job objects ---


def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Declared, always. Undeclared, ctypes passes every argument as a C int and
    # a 64-bit handle is truncated on the way in -- which fails in a way that
    # looks like the API refusing rather than like a bug here.
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _extended_limit_struct():
    import ctypes
    from ctypes import wintypes

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    return EXTENDED


class KillOnCloseJob:
    """A job whose processes die when its last handle closes.

    Which is the guarantee Sunshine's own service relies on for Sunshine.exe,
    and is stronger than anything a process tree offers: it survives us being
    killed rather than exiting.
    """

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    def __init__(self) -> None:
        import ctypes

        self._kernel32 = _kernel32()
        self.handle = self._kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(f"CreateJobObject failed: {ctypes.get_last_error()}")
        extended = _extended_limit_struct()()
        extended.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
                self.handle, self.JobObjectExtendedLimitInformation,
                ctypes.byref(extended), ctypes.sizeof(extended)):
            raise OSError(f"SetInformationJobObject failed: {ctypes.get_last_error()}")

    def assign_pid(self, pid: int) -> bool:
        PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
        handle = self._kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE,
                                            False, pid)
        if not handle:
            return False
        try:
            return bool(self._kernel32.AssignProcessToJobObject(self.handle, handle))
        finally:
            self._kernel32.CloseHandle(handle)

    def terminate(self) -> None:
        if self.handle:
            self._kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


# ---------------------------------------------------------------- starting ---


def start_browser(url: str, profile: str,
                  browser: Optional[Browser] = None,
                  streamed: bool = True) -> Tuple[Optional[subprocess.Popen], str, Optional[KillOnCloseJob]]:
    """Start a browser and put it in a kill-on-close job. (process, how, job).

    The process is started suspended and assigned before it runs, so that every
    child it spawns is inside the job from the first instruction. Assigning
    afterwards does not work: Chromium's own sandbox jobs get in the way, and a
    measurement on the rig accepted 1 process out of 14.
    """
    chosen = browser or next(iter(find_browsers()), None)
    if chosen is None:
        return None, "", None
    if chosen.kind == "kiosk-firefox":
        seed_firefox_profile(profile)

    job = KillOnCloseJob()
    CREATE_SUSPENDED = 0x00000004
    try:
        process = subprocess.Popen(
            chosen.command(url, profile, streamed=streamed),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_SUSPENDED)
    except (OSError, subprocess.SubprocessError):
        job.close()
        return None, "", None

    if not job.assign_pid(process.pid):
        # Without the job there is no teardown guarantee, and a browser that
        # cannot be closed is worse than one that never opened.
        process.kill()
        job.close()
        return None, "", None

    _resume(process.pid)
    return process, chosen.name, job


def _resume(pid: int) -> None:
    """Let a suspended process run, now that it is inside the job."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPTHREAD = 0x00000004
    THREAD_SUSPEND_RESUME = 0x0002

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot:
        return
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        ok = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                thread = kernel32.OpenThread(THREAD_SUSPEND_RESUME, False,
                                             entry.th32ThreadID)
                if thread:
                    kernel32.ResumeThread(thread)
                    kernel32.CloseHandle(thread)
            ok = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)


# ------------------------------------------------------- the medium helper ---


def write_request(url: str, profile: str, where: str) -> str:
    """Put the request in a file, and hand the helper its path.

    Two reasons, both learned the hard way:

    * **The URL carries the session token.** On a command line it is readable by
      every process on the machine, which undoes the point of minting a token at
      all. In a file created private, it is not. The file is deleted as soon as
      it has been read.
    * **Task Scheduler mangles embedded quotes.** A JSON payload in the action's
      arguments arrived at Python with its escaping altered, and the helper
      exited 1 before opening anything. A path has no quoting to get wrong.

    The launcher's pid travels with it so the helper can go when the launcher
    does: without that, an elevated launcher that is killed leaves a browser on
    screen with nothing holding it.
    """
    from .core import filemode

    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, "browser-request.json")
    filemode.write_private(path, json.dumps(
        {"url": url, "profile": profile, "parent": os.getpid(),
         "streamed": launched_by_sunshine()}))
    return path


def helper_command(request_path: str) -> List[str]:
    return [sys.executable, "-m", "sunshine_apps_ui", "--browser-helper",
            request_path]


TASK_NAME = "sunshine-apps-ui-browser"


def start_helper_de_elevated(url: str, profile: str) -> bool:
    """Start the helper at medium integrity, through the task scheduler.

    Measured on the rig, because two more obvious routes do not work:

    * ``ShellExecuteW`` starts the target with *our* token. An elevated launcher
      produced a High helper.
    * ``Shell.Application``'s ShellExecute -- the "ask Explorer" trick -- does the
      same when the caller is elevated, because the shell object is created in
      our own process rather than marshalled into Explorer's. Proved with
      notepad, which came up High. It *looked* like it worked when tested with a
      browser, and that is a trap worth naming: **Edge and Chrome refuse to run
      elevated and relaunch themselves de-elevated**, so they come out Medium
      however they were started. Firefox and Opera do not, and would have
      inherited administrator rights while the test said otherwise.

    A scheduled task with ``RunLevel Limited`` genuinely produces a medium
    process in the user's own session.

    The registration is left in place, under one known name, and overwritten on
    each launch. Removing it after starting the helper was tried and is wrong:
    unregistering a task terminates the instance it is running, which killed the
    helper three seconds in and took the browser with it. ``uninstall`` removes
    the task.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    command = helper_command(write_request(url, profile, os.path.dirname(profile)))
    arguments = subprocess.list2cmdline(command[1:])

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    # A task inherits nothing of ours -- not PYTHONPATH, not the working
    # directory -- so `-m sunshine_apps_ui` would fail to import and the helper
    # would exit before it started anything. Running it from the directory the
    # package lives under is what puts it on sys.path.
    script = (
        f"$action = New-ScheduledTaskAction -Execute {quote(command[0])} "
        f"-Argument {quote(arguments)} -WorkingDirectory {quote(root)}; "
        f"$principal = New-ScheduledTaskPrincipal "
        f"-UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) "
        f"-LogonType Interactive -RunLevel Limited; "
        f"Register-ScheduledTask -TaskName {quote(TASK_NAME)} -Action $action "
        f"-Principal $principal -Force | Out-Null; "
        f"Start-ScheduledTask -TaskName {quote(TASK_NAME)}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def process_alive(pid: int) -> bool:
    """Is that process still running? Asked of the launcher, from the helper."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _read_request(payload: str) -> Optional[Dict]:
    """The request, from the file the launcher wrote. Deleted once read.

    A JSON string is still accepted, because it is what the tests pass and what
    a person debugging this by hand would type.
    """
    if os.path.isfile(payload):
        try:
            with open(payload, "r", encoding="utf-8") as handle:
                request = json.load(handle)
        except (OSError, ValueError):
            return None
        try:
            os.unlink(payload)         # it holds the session token
        except OSError:
            pass
        return request if isinstance(request, dict) else None
    try:
        request = json.loads(payload)
    except ValueError:
        return None
    return request if isinstance(request, dict) else None


def relaunch_elevated() -> bool:
    """Start the manager again, as administrator, and let it replace us.

    The "runas" verb is what raises the UAC prompt; there is no other way to
    gain rights a process was not given. Nothing is torn down here: the new
    instance runs stop_previous() as every launch does, which ends this server
    and this browser. A relaunch is already a thing this program knows how to
    do; this one just happens to be elevated.
    """
    import ctypes

    from .installer import paths

    command = paths()["command"]
    if not os.path.isfile(command):
        return False
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    SW_SHOWNORMAL = 1
    result = shell32.ShellExecuteW(None, "runas", command, None, None, SW_SHOWNORMAL)
    # Above 32 means it started. 1223 is ERROR_CANCELLED: the UAC prompt was
    # refused, which is an answer rather than a failure.
    return int(result or 0) > 32


def helper_pid_path(profile: str) -> str:
    """Where the helper records that it is the one holding the browser."""
    return os.path.join(os.path.dirname(profile), "browser-helper.pid")


def read_helper_pid(profile: str) -> int:
    return read_helper_record(profile)[0]


def read_helper_record(profile: str):
    """(pid, image, start time) of the helper that recorded itself, or (0, "", 0).

    All three, because a pid on its own is not an identity and neither is a pid
    plus an image when every process here is the same python.exe.
    """
    try:
        with open(helper_pid_path(profile), "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        return (int(lines[0].strip() or 0),
                lines[1].strip() if len(lines) > 1 else "",
                int(lines[2].strip()) if len(lines) > 2 else 0)
    except (OSError, ValueError, IndexError):
        return 0, "", 0


def process_image(pid: int) -> str:
    """The executable a process is running, for checking a pid is still who we think."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def process_start_time(pid: int) -> int:
    """When a process began, as a FILETIME. Identity, where a pid alone is not.

    Every process here runs the same python.exe, so comparing images proves
    nothing: a recycled pid passes that test and gets terminated. It happened --
    a launcher ended something innocent and exited. A pid plus the moment it
    started is unique for as long as anyone cares.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return 0
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def is_same_process(pid: int, image: str, started: int) -> bool:
    """Is that pid still the process we wrote down, rather than a new one?"""
    if not pid or pid == os.getpid() or not process_alive(pid):
        return False
    if started and process_start_time(pid) != started:
        return False
    running = process_image(pid)
    if image and running and os.path.normcase(running) != os.path.normcase(image):
        return False
    return True


def stop_helper(profile: str) -> bool:
    """End a helper left by an earlier run. True if one was there and is now gone.

    Only the helper needs ending: it holds the job, and the job takes the browser
    with it. A launcher that held the job itself needs nothing done at all --
    kill-on-close means its browser died when it did.
    """
    import ctypes
    from ctypes import wintypes

    pid, image, started = read_helper_record(profile)
    if not is_same_process(pid, image, started):
        # Gone, or the number has been reused. Either way, not ours to end.
        return False

    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        kernel32.TerminateProcess(handle, 1)
        return True
    finally:
        kernel32.CloseHandle(handle)


def job_pids(job: "KillOnCloseJob") -> List[int]:
    """Every process currently in the job."""
    import ctypes
    from ctypes import wintypes

    class ID_LIST(ctypes.Structure):
        _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD),
                    ("NumberOfProcessIdsInList", wintypes.DWORD),
                    ("ProcessIdList", ctypes.c_size_t * 512)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL

    info = ID_LIST()
    returned = wintypes.DWORD()
    JobObjectBasicProcessIdList = 3
    if not kernel32.QueryInformationJobObject(
            job.handle, JobObjectBasicProcessIdList, ctypes.byref(info),
            ctypes.sizeof(info), ctypes.byref(returned)):
        return []
    count = min(info.NumberOfProcessIdsInList, 512)
    return [int(info.ProcessIdList[i]) for i in range(count)]


def has_visible_window(pids) -> bool:
    """Does any of those processes have a window on screen?

    The question that matters, and not the one asked before. "Is anything from
    the browser still running" stays true after the window is closed: Edge
    leaves background and crash-handler processes behind, so the launcher waited
    for them for ever -- the window went, the console stayed, and the stream
    never ended. Measured on the rig: six seconds after closing the window,
    five msedge, two python and two cmd were still alive.

    A window closing is what a person means by closing the program, so that is
    what is watched.
    """
    import ctypes
    from ctypes import wintypes

    wanted = set(pids)
    if not wanted:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]

    found = []

    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in wanted:
            found.append(hwnd)
            return False          # one is enough
        return True

    user32.EnumWindows(ENUMPROC(visit), 0)
    return bool(found)


def job_is_showing(job: "KillOnCloseJob") -> bool:
    """Is the browser still on screen? Not merely still running."""
    return has_visible_window(job_pids(job))


def job_is_occupied(job: "KillOnCloseJob") -> bool:
    """Does the job still hold anything at all?"""
    return _job_has_processes(job)


# For the window to exist, not merely the process. The launcher allows the
# same; the helper did not, and that was a bug -- see helper_main.
APPEAR_TIMEOUT = 30.0


def helper_main(payload: str) -> int:
    """Run as the medium-integrity child: own the job, hold the browser.

    Exiting closes the job's last handle, which is what kills the browser -- so
    this stays for exactly as long as the window should, and no longer.
    """
    request = _read_request(payload)
    if request is None:
        return 2
    process, how, job = start_browser(str(request.get("url", "")),
                                      str(request.get("profile", "")),
                                      streamed=bool(request.get("streamed", True)))
    if process is None or job is None:
        return 1
    parent = request.get("parent")
    profile = str(request.get("profile", ""))
    pid_file = helper_pid_path(profile) if profile else ""
    if pid_file:
        try:
            os.makedirs(os.path.dirname(pid_file), exist_ok=True)
            with open(pid_file, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n{sys.executable}\n"
                             f"{process_start_time(os.getpid())}\n")
        except OSError:
            pid_file = ""
    try:
        # Wait for a window to appear before treating its absence as "the
        # window has been closed". Without this the helper asks the instant
        # after starting it, before any process has had time to put anything on
        # screen, sees nothing, and takes down the window it has just opened.
        #
        # Found on the rig on 2026-09-18 with the WebView2 window, which puts a
        # window up in a fifth of a second and still lost this race every time:
        # the launcher reported "Opened with helper" and nothing ever appeared.
        # The bug is not the window's -- nothing could have won it -- and it is
        # only on the elevated path, because the launcher's own loop has always
        # had the wait this one was missing.
        appeared = time.monotonic() + APPEAR_TIMEOUT
        while time.monotonic() < appeared and not job_is_showing(job):
            if not job_is_occupied(job):
                break            # it exited outright; there is nothing coming
            time.sleep(0.1)

        while True:
            # Firefox and Opera exit the process we started and respawn, so the
            # pid we have is not the browser for long. The job knows who is
            # left; ask it rather than trusting that pid.
            # The window, not the processes: Edge keeps some alive after it
            # closes, and waiting for those kept the whole thing up.
            if not job_is_showing(job):
                break
            # And go when the launcher goes, however it went. A parent of 0 or
            # None means nobody asked us to follow one -- not "the launcher is
            # already gone", which is what treating it as a pid would say.
            if isinstance(parent, int) and parent > 0 and not process_alive(parent):
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        job.terminate()
        job.close()
        if pid_file:
            try:
                os.unlink(pid_file)
            except OSError:
                pass
    return 0


def _job_has_processes(job: KillOnCloseJob) -> bool:
    import ctypes
    from ctypes import wintypes

    class BASIC_ACCOUNTING(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64),
                    ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", wintypes.DWORD),
                    ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD),
                    ("TotalTerminatedProcesses", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL

    info = BASIC_ACCOUNTING()
    returned = wintypes.DWORD()
    JobObjectBasicAccountingInformation = 1
    if not kernel32.QueryInformationJobObject(
            job.handle, JobObjectBasicAccountingInformation,
            ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)):
        return False
    return info.ActiveProcesses > 0
