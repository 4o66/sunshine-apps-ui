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

from . import security

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
PROFILE_PATTERN = (r"(--user-data-dir=|--profile )[^ ]*sunshine-apps-ui"
                   r"[/\\]browser-profile")

# A server we started earlier, which a relaunch has to end. Written to match the
# command SERVER_COMMAND builds and nothing else -- the launcher itself carries
# no --port, so this cannot match the process doing the matching. There is a
# test that these two agree, because they silently stopped agreeing once: adding
# --serve to the command left the pattern matching nothing, and every relaunch
# quietly left the previous server running.
SERVER_PATTERN = r"sunshine_apps_ui .*--port"


def server_command(port: str = "0", token_file: str = "") -> List[str]:
    command = [sys.executable, "-m", "sunshine_apps_ui", "--serve", "--port", port]
    if token_file:
        command += ["--token-file", token_file]
    return command


def free_port() -> int:
    """A port nothing is using, chosen before the server exists.

    So that the URL can be known -- and a window opened on it -- while the
    server is still starting. Something else could take it in the moment
    between closing this socket and the server binding; the server says so if
    that happens, and the next launch picks another.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((security.BIND_HOST, 0))
        return int(probe.getsockname()[1])


STARTING_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>App Manager</title>
<style>
:root{{color-scheme:light dark}}
body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#212529;color:#f8f9fa;
font:1rem/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.box{{text-align:center}}
.ring{{width:44px;height:44px;margin:0 auto 1rem;border-radius:50%;
border:3px solid rgba(255,255,255,.18);border-top-color:#ffc400;
animation:spin 900ms linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
p{{margin:0;color:#adb5bd;font-size:.95rem}}
</style></head>
<body><div class="box"><div class="ring"></div><p>Starting the app manager...</p></div>
<script>
// The server is coming up beside this page. Ask until it answers, then go --
// no-cors because we only need to know that something replied, not to read it.
const target = {url!r};
async function ready() {{
  try {{ await fetch(target, {{mode: 'no-cors', cache: 'no-store'}}); return true; }}
  catch (e) {{ return false; }}
}}
(async function poll() {{
  for (let i = 0; i < 600; i++) {{
    if (await ready()) {{ location.replace(target); return; }}
    await new Promise(r => setTimeout(r, 100));
  }}
  document.querySelector('p').textContent =
    'The app manager did not start. Its log is in the state directory.';
  document.querySelector('.ring').style.display = 'none';
}})();
</script></body></html>
"""


def write_starting_page(url: str) -> str:
    """A page to show while the server starts, so a window appears at once."""
    from . import places
    directory = places.state_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "starting.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(STARTING_PAGE.format(url=url))
    return path


def package_path() -> str:
    """The directory this package lives in, for a child process to import from.

    The installed command puts the installed copy on sys.path and hands over --
    but sys.path does not survive into a child, so a server started without
    this says "No module named sunshine_apps_ui" and the launcher reports that
    the interface did not start. The shell version set PYTHONPATH and this has
    to as well.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def server_environment(base: Optional[dict] = None) -> dict:
    environment = dict(os.environ if base is None else base)
    existing = environment.get("PYTHONPATH", "")
    ours = package_path()
    if ours not in existing.split(os.pathsep):
        environment["PYTHONPATH"] = (f"{ours}{os.pathsep}{existing}" if existing
                                     else ours)
    # Says "you are being watched through a stream", which changes what the
    # pages say about disconnecting. Asked of Sunshine rather than asserted:
    # this used to be set whenever the launcher ran, so opening the manager at
    # the machine still warned about interrupting a stream that was not there.
    from .winbrowser import launched_by_sunshine
    environment["BSM_UI_VIA_SUNSHINE"] = "1" if launched_by_sunshine() else "0"
    return environment

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
    from . import places
    return places.state_dir()


def profile_dir() -> str:
    return os.path.join(state_dir(), "browser-profile")


def log_path() -> str:
    """Where the server's output goes -- which includes the session token.

    Not /tmp, and not %TEMP%. The server prints its URL, the URL carries the
    token, and the token is the whole of the authentication for a server that
    can rewrite apps.json. A fixed name in a directory everyone can write is two
    problems at once: anybody may read what lands there, and anybody may get
    there first with a symlink pointing somewhere we would then overwrite -- as
    an elevated process, on Windows.

    The state directory is ours and per-user. The file is opened mode 600 and
    with O_NOFOLLOW; see core.filemode.open_private.
    """
    from . import places
    directory = places.state_dir()
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "server.log")


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


def _server_record_path() -> str:
    from . import places
    return os.path.join(places.state_dir(), "server.pid")


def remember_server(process) -> None:
    """Write down the server we just started, so the next run can end it cheaply.

    Without this, finding a server left by a previous launch means enumerating
    every process on the machine -- which on Windows is a WMI query costing
    several seconds, on every single launch, to discover that there usually is
    not one.
    """
    try:
        os.makedirs(os.path.dirname(_server_record_path()), exist_ok=True)
        started = 0
        if WINDOWS:
            from . import winbrowser
            started = winbrowser.process_start_time(process.pid)
        with open(_server_record_path(), "w", encoding="utf-8") as handle:
            handle.write(f"{process.pid}\n{sys.executable}\n{started}\n")
    except OSError:
        pass


def _stop_recorded_server() -> bool:
    """End the server named in the record. True if there was one to end."""
    try:
        with open(_server_record_path(), "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        pid = int(lines[0])
        image = lines[1] if len(lines) > 1 else ""
        started = int(lines[2]) if len(lines) > 2 else 0
    except (OSError, ValueError, IndexError):
        return False
    if not pid or pid == os.getpid():
        return False
    if WINDOWS:
        from . import winbrowser
        # A pid is not an identity, and neither is a pid plus an image when
        # every process involved is the same python.exe -- a recycled number
        # passed that test and something innocent was terminated. The moment it
        # started is what makes it unique.
        if not winbrowser.is_same_process(pid, image, started):
            return False
    _end([pid])
    return True


def stop_previous() -> None:
    """Replace the previous session rather than stacking one on top of it.

    Both halves matter. An old server left running means two listeners; an old
    browser left running means this launch hands its URL to that browser, gets
    a window in someone else's process, and returns immediately -- so the
    launcher exits and takes down the server it just started, leaving every
    window dead.
    """
    # The one we wrote down, first and cheaply. The scan below is the fallback
    # for a server started by some earlier version that left no record.
    stopped = _stop_recorded_server()
    if not (WINDOWS and stopped):
        _end(_pgrep(SERVER_PATTERN))

    if WINDOWS:
        # Nothing to hunt for. A previous launcher that held the job itself took
        # its browser down when it went -- that is what kill-on-close means --
        # so the only thing that can still be up is a helper, and it says so in
        # a file. Enumerating every process to discover that took two and a half
        # seconds off every launch and usually found nothing.
        from . import winbrowser
        if winbrowser.stop_helper(profile_dir()):
            deadline = time.monotonic() + STOP_TIMEOUT
            while time.monotonic() < deadline and browser_is_up(profile_dir()):
                time.sleep(0.25)
        return

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


def _die_with_us() -> None:
    """Ask Linux to signal this child when we die, however we die.

    The equivalent of the Windows job object, which takes the window down with
    the launcher even if the launcher is killed outright. A handler cannot do
    this: SIGKILL runs no handler, and Sunshine ending an app is not always
    polite. Set in the child between fork and exec.
    """
    try:
        import ctypes

        PR_SET_PDEATHSIG = 1
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(
            PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except Exception:              # noqa: BLE001 - a nicety, never a blocker
        pass


def _spawn(command: List[str], env: Optional[dict] = None,
           die_with_us: bool = False) -> Optional[subprocess.Popen]:
    before = None
    if die_with_us and sys.platform.startswith("linux"):
        before = _die_with_us
    try:
        return subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=env,
                                preexec_fn=before)   # noqa: S606 - see _die_with_us
    except (OSError, subprocess.SubprocessError):
        return None


def _flatpak_installed(app: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    return subprocess.run(["flatpak", "info", app],
                          capture_output=True).returncode == 0


def _as_url(path: str) -> str:
    from urllib.request import pathname2url
    return "file:" + pathname2url(os.path.abspath(path))


# Set when the browser is held by a medium-integrity helper rather than by us,
# which is how an elevated launcher avoids handing its rights to a browser.
_HELPER_HOLDS_IT = "helper"


OUR_WINDOW = "our own window"


def open_browser(target: str, profile: str, as_file: bool = False,
                 own_window: bool = True) -> Tuple[Optional[subprocess.Popen], str]:
    """Open *target* as a window of its own. Returns (process, how).

    *target* is a URL, or a path to a local page when as_file is set -- which is
    how the window appears before the server it will show has started.

    *own_window* is how the caller asks for a browser specifically, having
    already tried ours and watched it fail.
    """
    url = _as_url(target) if as_file else target
    if WINDOWS:
        return _open_browser_windows(url, profile)

    # Our own window first, where the toolkit for one exists. It is absent on
    # a machine without GTK 4 and WebKitGTK, and then this is exactly what it
    # always was -- which is why the browser path below stays.
    from . import gtkhost, winbrowser
    if own_window and gtkhost.available():
        # Our own window is this package, so it needs to be able to import
        # it: sys.path does not survive into a child, and without this the
        # window says "No module named sunshine_apps_ui" and exits 1.
        process = _spawn(gtkhost.command(
            url, profile, streamed=winbrowser.launched_by_sunshine()),
            env=server_environment(), die_with_us=True)
        if process:
            return process, OUR_WINDOW

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


def _open_browser_windows(url: str, profile: str) -> Tuple[Optional[subprocess.Popen], str]:
    """Windows: per-browser flags, a job object, and no elevation for the browser.

    Everything specific to this lives in winbrowser, including why each browser
    needs a different flag and why the elevated case needs a helper.
    """
    from . import privilege, winbrowser

    if not winbrowser.find_browsers():
        return None, ""

    if privilege.is_elevated():
        # Our rights came from Sunshine so that we could write apps.json. The
        # browser must not inherit them: it is a far bigger surface than we are.
        if winbrowser.start_helper_de_elevated(url, profile):
            return None, _HELPER_HOLDS_IT
        print("Could not start the browser de-elevated; refusing to run it as "
              "administrator.", file=sys.stderr)
        return None, ""

    process, how, job = winbrowser.start_browser(
        url, profile, streamed=winbrowser.launched_by_sunshine())
    if process is None:
        return None, ""
    # Held for as long as this launcher runs: closing the last handle is what
    # takes the browser down with us, including if we are killed.
    global _JOB
    _JOB = job
    return process, how


_JOB = None                                   # the job the browser lives in


def winbrowser_helper_pid(profile: str) -> int:
    if not WINDOWS:
        return 0
    from . import winbrowser
    return winbrowser.read_helper_pid(profile)


def browser_is_up(profile: str) -> bool:
    """Is our browser still there?

    Asked once a second while the window is open, so how it is asked matters.
    On Windows there are two exact answers available for nothing:

    * when we started the browser, it is in a job of ours -- ask the job;
    * when a helper started it (the elevated case), the helper is holding that
      job and goes when the browser does -- ask whether the helper is alive.

    Only when neither applies does this fall back to `browsers()`, which
    enumerates every process on the machine through WMI and takes two and a half
    seconds. That was being called in two polling loops whose sleeps were half a
    second and one second, which is where most of the ten seconds the maintainer measured
    went, and all of the lag on closing the window.
    """
    if not WINDOWS:
        return bool(browsers())

    from . import winbrowser
    if _JOB is not None:
        # A window on screen, not a process still running. Edge leaves
        # background processes behind when its window closes, and waiting for
        # those meant the window went and nothing else did.
        return winbrowser.job_is_showing(_JOB)

    pid = winbrowser.read_helper_pid(profile)
    if pid:
        return winbrowser.process_alive(pid)

    return bool(browsers())


# ---------------------------------------------------------------- the run ---


def _read_url(log_file: str, server: subprocess.Popen) -> str:
    """The URL the server printed, from its log.

    No longer how the launcher finds it -- the launcher chooses the port and
    the token itself now, so that a window can be opened before the server
    exists. Kept because it is still how a person finds the URL of a server
    started by hand, and because --serve prints it for exactly that reason.
    """
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


def _leave_on_signal() -> None:
    """Make a termination signal an orderly exit, so the teardown happens.

    Without this, SIGTERM kills the launcher where it stands: the ``finally``
    that closes the window and stops the server never runs, and both are left
    behind. Measured on Bazzite -- terminating the launcher left the window on
    screen with nothing holding it.

    Sunshine ends an app by signalling it, so this is the ordinary way this
    program exits, not an edge case.
    """
    def leave(signum, frame):      # noqa: ARG001 - the handler's signature
        raise SystemExit(0)

    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, leave)
        except (OSError, ValueError):
            # Not the main thread, or not a signal this platform has. The
            # teardown is still done on every ordinary exit.
            pass


def launch(argv: Optional[List[str]] = None) -> int:
    """Open a window at once, start the server behind it, and stay until one goes.

    The window comes first deliberately. The maintainer, timing it: "it needs to open
    nearly instantly, even if just to show a spinning please wait." Most of the
    wait is the browser starting, which happens whatever we do -- so the
    browser is started first, on a page that spins, and the server comes up
    beside it. The page goes to the real one as soon as anything answers.

    That means knowing the URL before the server exists, so the port and the
    token are chosen here and handed over: the token in a file, because argv is
    readable by every process on the machine.
    """
    _leave_on_signal()
    stop_previous()
    profile = profile_dir()
    os.makedirs(profile, exist_ok=True)
    log_file = log_path()

    from . import places
    from .core import filemode

    port = free_port()
    token = security.new_token()
    url = f"http://{security.BIND_HOST}:{port}/?token={token}"
    token_file = os.path.join(places.state_dir(), "session-token")
    filemode.write_private(token_file, token)

    browser = None
    ours: List[int] = []
    server = None
    try:
        page = write_starting_page(url)
        browser, how = open_browser(page, profile, as_file=True)
        environment = server_environment()
        with filemode.open_private(log_file) as handle:
            server = subprocess.Popen(
                server_command(str(port), token_file), stdout=handle,
                stderr=subprocess.STDOUT, env=environment)
        remember_server(server)

        if not browser and how != _HELPER_HOLDS_IT:
            return _no_browser(url, server)
        print(f"Opened with {how}", file=sys.stderr)

        # Give the window a moment to exist before watching for it to go, and
        # remember which processes are ours.
        deadline = time.monotonic() + APPEAR_TIMEOUT
        while time.monotonic() < deadline and not browser_is_up(profile):
            if browser is not None and browser.poll() is not None:
                break
            time.sleep(0.5)

        # Our own window can still fail after we have started it: the toolkit
        # is there but will not run, a display goes away, a library is half
        # installed. It exits rather than hanging, and the launcher would
        # otherwise see "nothing on screen" and take everything down, leaving
        # a tile that appears to do nothing at all. A browser is exactly the
        # fallback we kept the browser path for.
        if (how == OUR_WINDOW and browser is not None
                and browser.poll() is not None and not browser_is_up(profile)):
            print(f"Our own window exited ({browser.returncode}); "
                  f"falling back to a browser.", file=sys.stderr)
            browser, how = open_browser(page, profile, as_file=True,
                                        own_window=False)
            if not browser and how != _HELPER_HOLDS_IT:
                return _no_browser(url, server)
            print(f"Opened with {how}", file=sys.stderr)
            deadline = time.monotonic() + APPEAR_TIMEOUT
            while time.monotonic() < deadline and not browser_is_up(profile):
                if browser is not None and browser.poll() is not None:
                    break
                time.sleep(0.5)
        # Which processes are ours, for the teardown that cannot use the job --
        # asked once, here, rather than once a second. On Windows with a job or
        # a helper this is not needed at all.
        ours = [] if (WINDOWS and (_JOB is not None or
                                   winbrowser_helper_pid(profile))) else browsers()

        # Stay until one of the two goes; the other is taken down below.
        #
        # Waiting on the browser process alone was wrong twice over. A launcher
        # such as `flatpak run` can hand off and return while the window stays
        # up, which would shut the server down under a live page. And the
        # server can stop on its own -- it does exactly that after applying --
        # which would leave the window showing a page that no longer loads.
        # A quarter of a second, because the question is now free and the
        # answer is what decides how long closing the window takes.
        while browser_is_up(profile) and server.poll() is None:
            time.sleep(0.25)
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


def _shut_down(server: Optional[subprocess.Popen],
               browser: Optional[subprocess.Popen],
               ours: Optional[Sequence[int]] = None) -> None:
    """Take down whichever of the two is still up.

    Only ever our own browser. Ending every process holding the profile would
    reach one a successor has just started: a relaunch ends this session, and
    this session's cleanup would then kill the window that replaced it. The
    pids are recorded when our browser appears, so leaving does not disturb
    whatever came after.
    """
    # On Windows the job is the teardown: terminating it takes every descendant,
    # including the process Firefox and Opera respawn after exiting the one we
    # started. That respawn is exactly what pid-tracking loses.
    global _JOB
    if _JOB is not None:
        try:
            _JOB.terminate()
            _JOB.close()
        except OSError:
            pass
        _JOB = None

    if browser is not None and browser.poll() is None:
        try:
            browser.terminate()
        except OSError:
            pass
    # By profile as well, for the reason at the top: ending the launcher does
    # not end the browser it started.
    _end(ours if ours is not None else browsers())
    # The server may never have been started: the window is opened first now,
    # and anything that goes wrong before it exists still comes through here.
    if server is not None and server.poll() is None:
        try:
            server.terminate()
            server.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                server.kill()
            except OSError:
                pass
