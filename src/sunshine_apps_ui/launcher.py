# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening the interface as a window, and taking it down again.

This is what Sunshine's tile runs. It starts the server, opens a browser
showing nothing but this, and stays until one of the two goes -- then takes the
other with it.

It was a bash script. It is Python because the same thing has to work on
Windows, where there is no bash, no pgrep and no flatpak; writing it twice
would mean two descriptions of one careful piece of behaviour, and they would
drift. Everything platform-specific is named and kept in one place here.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import List, Optional, Sequence, Tuple

WINDOWS = os.name == "nt"

# Chromium keys its single-instance lock on the profile directory, so giving
# this window its own profile is what makes the browser a real child process we
# can wait on. Sharing the default profile hands the URL to whatever browser is
# already running and returns immediately, leaving a window pointed at a server
# we then shut down.
#
# The same applies to our own profile the second time round, which is why
# stop_previous has to end the last browser before starting this one.
PROFILE_LEAF = os.path.join("sunshine-apps-ui", "browser-profile")

# The browser is identified by the one thing unique to it: the profile it was
# started with. Never by the launcher's pid -- a signal to `flatpak run` does
# not reach the browser inside the sandbox, which is how a window outlives the
# session that opened it.
#
# Matched by the tail of the path rather than the whole of it, because on an
# ostree system /home is a symlink to /var/home and the same directory has two
# spellings. A browser started under one would not match a pattern built from
# the other, and the point here is not to miss it.
PROFILE_PATTERN = r"(--user-data-dir=|--profile )[^ ]*sunshine-apps-ui/browser-profile"

# A server we started earlier, which a relaunch has to end. Written to match the
# command SERVER_COMMAND builds and nothing else -- the launcher itself carries
# no --port, so this cannot match the process doing the matching. There is a
# test that these two agree, because they silently stopped agreeing once: adding
# --serve to the command left the pattern matching nothing, and every relaunch
# quietly left the previous server running.
SERVER_PATTERN = r"sunshine_apps_ui .*--port"


def server_command(port: str = "0") -> List[str]:
    return [sys.executable, "-m", "sunshine_apps_ui", "--serve", "--port", port]

# Flatpak first: on an immutable system it is the one that is really there, and
# its network is the host's, so loopback means this machine.
FLATPAK_BROWSERS = ("com.google.Chrome", "com.brave.Browser",
                    "com.vivaldi.Vivaldi", "org.chromium.Chromium",
                    "com.microsoft.Edge")

# Chromium-family browsers take --app and --user-data-dir, which is what makes
# the window ours to find and to close.
CHROMIUM_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium",
                     "chromium-browser", "brave-browser", "vivaldi-stable",
                     "microsoft-edge-stable")

# Last, because --kiosk has no equivalent of --app: Firefox takes over the
# screen rather than giving us a window, which is right on a television and
# wrong on a desktop.
FIREFOX_BROWSERS = ("firefox", "firefox-esr")

START_TIMEOUT = 15.0        # for the server to print its URL
APPEAR_TIMEOUT = 30.0       # for the browser's window to exist
STOP_TIMEOUT = 10.0         # for a previous browser to go quietly

_URL = re.compile(r"http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]+")


def state_dir() -> str:
    base = os.getenv("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "sunshine-apps-ui")


def profile_dir() -> str:
    return os.path.join(state_dir(), "browser-profile")


def log_path() -> str:
    base = os.getenv("XDG_RUNTIME_DIR") or ("" if WINDOWS else "/tmp")
    if not base:
        base = os.path.join(os.getenv("TEMP") or os.path.expanduser("~"))
    return os.path.join(base, "sunshine-apps-ui.log")


# ------------------------------------------------------- finding processes ---


def _pgrep(pattern: str) -> List[int]:
    """Process ids whose command line matches, for this user only."""
    if WINDOWS:                                  # no pgrep; see _windows_matches
        return _windows_matches(pattern)
    try:
        result = subprocess.run(
            ["pgrep", "-u", str(os.getuid()), "-f", "--", pattern],
            capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(line) for line in result.stdout.split() if line.isdigit()]


def _windows_matches(pattern: str) -> List[int]:
    """The same question on Windows, which has no pgrep.

    Kept separate and honest: a job object is the right way to end the browser
    there, and this exists only so the "is one already running" check has an
    answer on every platform.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             "Select-Object ProcessId,CommandLine | ConvertTo-Csv -NoTypeInformation"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    expression = re.compile(pattern)
    for line in result.stdout.splitlines()[1:]:
        pid, _, rest = line.partition(",")
        if expression.search(rest):
            try:
                found.append(int(pid.strip().strip('"')))
            except ValueError:
                continue
    return found


def browsers() -> List[int]:
    """Any browser holding our profile, however it was started."""
    return _pgrep(PROFILE_PATTERN)


def _end(pids: Sequence[int], hard: bool = False) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL if hard and not WINDOWS else signal.SIGTERM)
        except (OSError, ProcessLookupError):
            continue


def stop_previous() -> None:
    """Replace the previous session rather than stacking one on top of it.

    Both halves matter. An old server left running means two listeners; an old
    browser left running means this launch hands its URL to that browser, gets
    a window in someone else's process, and returns immediately -- so the
    launcher exits and takes down the server it just started, leaving every
    window dead.
    """
    _end(_pgrep(SERVER_PATTERN))
    if not browsers():
        return
    _end(browsers())
    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        if not browsers():
            return
        time.sleep(0.25)
    # Still there: it is not going to exit politely, and starting anyway would
    # hand the URL to it.
    _end(browsers(), hard=True)
    time.sleep(1)


# ------------------------------------------------------------ the browser ---


def _spawn(command: List[str]) -> Optional[subprocess.Popen]:
    try:
        return subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


def _flatpak_installed(app: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    return subprocess.run(["flatpak", "info", app],
                          capture_output=True).returncode == 0


def open_browser(url: str, profile: str) -> Tuple[Optional[subprocess.Popen], str]:
    """Open *url* as a window of its own. Returns (process, how)."""
    for app in FLATPAK_BROWSERS:
        if _flatpak_installed(app):
            process = _spawn(["flatpak", "run", app,
                              f"--user-data-dir={profile}", "--no-first-run",
                              f"--app={url}", "--start-fullscreen"])
            if process:
                return process, f"flatpak {app}"

    for binary in CHROMIUM_BROWSERS:
        path = shutil.which(binary)
        if path:
            process = _spawn([path, f"--user-data-dir={profile}",
                              "--no-first-run", f"--app={url}",
                              "--start-fullscreen"])
            if process:
                return process, binary

    for binary in FIREFOX_BROWSERS:
        path = shutil.which(binary)
        if path:
            process = _spawn([path, "--profile", profile, "--kiosk", url])
            if process:
                return process, binary

    return None, ""


# ---------------------------------------------------------------- the run ---


def _read_url(log_file: str, server: subprocess.Popen) -> str:
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as handle:
                found = _URL.search(handle.read())
            if found:
                return found.group(0)
        except OSError:
            pass
        if server.poll() is not None:
            return ""
        time.sleep(0.25)
    return ""


def launch(argv: Optional[List[str]] = None) -> int:
    """Start the server, open a window on it, and stay until one of them goes."""
    stop_previous()
    profile = profile_dir()
    os.makedirs(profile, exist_ok=True)
    log_file = log_path()

    environment = dict(os.environ)
    # Says "you are being watched through a stream", which changes what the
    # pages say about disconnecting.
    environment["BSM_UI_VIA_SUNSHINE"] = "1"

    with open(log_file, "w", encoding="utf-8") as handle:
        server = subprocess.Popen(server_command(), stdout=handle,
                                  stderr=subprocess.STDOUT, env=environment)

    browser = None
    ours: List[int] = []
    try:
        url = _read_url(log_file, server)
        if not url:
            print(f"The interface did not start; see {log_file}", file=sys.stderr)
            return 1

        browser, how = open_browser(url, profile)
        if not browser:
            return _no_browser(url, server)
        print(f"Opened with {how}", file=sys.stderr)

        # Give the window a moment to exist before watching for it to go, and
        # remember which processes are ours.
        deadline = time.monotonic() + APPEAR_TIMEOUT
        while time.monotonic() < deadline and not browsers():
            if browser.poll() is not None:
                break
            time.sleep(0.5)
        ours = browsers()

        # Stay until one of the two goes; the other is taken down below.
        #
        # Waiting on the browser process alone was wrong twice over. A launcher
        # such as `flatpak run` can hand off and return while the window stays
        # up, which would shut the server down under a live page. And the
        # server can stop on its own -- it does exactly that after applying --
        # which would leave the window showing a page that no longer loads.
        while browsers() and server.poll() is None:
            time.sleep(1)
        return 0
    finally:
        _shut_down(server, browser, ours)


def _no_browser(url: str, server: subprocess.Popen) -> int:
    """Nothing that can be opened as a window. Say where it is and hold it open."""
    opener = shutil.which("xdg-open") or ("start" if WINDOWS else "")
    if opener:
        print("No browser found that can be opened as a window; handing the URL "
              "to the desktop instead.", file=sys.stderr)
        print("Closing the page will not stop the interface.", file=sys.stderr)
        if WINDOWS:
            os.startfile(url)                    # noqa: S606 - a URL, by design
        else:
            _spawn([opener, url])
    else:
        print("No browser found. The interface is running at:", file=sys.stderr)
        print(f"  {url}", file=sys.stderr)
    try:
        server.wait()
    except KeyboardInterrupt:
        pass
    return 0


def _shut_down(server: subprocess.Popen,
               browser: Optional[subprocess.Popen],
               ours: Optional[Sequence[int]] = None) -> None:
    """Take down whichever of the two is still up.

    Only ever our own browser. Ending every process holding the profile would
    reach one a successor has just started: a relaunch ends this session, and
    this session's cleanup would then kill the window that replaced it. The
    pids are recorded when our browser appears, so leaving does not disturb
    whatever came after.
    """
    if browser is not None and browser.poll() is None:
        try:
            browser.terminate()
        except OSError:
            pass
    # By profile as well, for the reason at the top: ending the launcher does
    # not end the browser it started.
    _end(ours if ours is not None else browsers())
    if server.poll() is None:
        try:
            server.terminate()
            server.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                server.kill()
            except OSError:
                pass
