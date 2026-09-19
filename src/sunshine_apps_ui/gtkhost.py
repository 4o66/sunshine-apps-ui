# SPDX-License-Identifier: GPL-3.0-or-later
"""A window of our own on Linux, the same idea as winhost on Windows.

On Windows this took 187 lines of C# and a compiler. Here it takes neither:
GTK 4 and WebKitGTK 6.0 are already on the machine, reachable from Python
through GObject introspection, so the window is a page of ordinary Python in
this package with nothing to fetch, nothing to build and nothing new to ship.

**Why bother, when Linux already had a browser.** The same reasons Windows
did. Driving a browser as a window costs a table of per-browser flags, a
seeded Firefox profile, a profile directory and a rule for every browser about
what "fullscreen" means, and it is at the mercy of whatever the user's browser
was configured to do. A window we own has one behaviour.

**And, as on Windows, nothing depends on it.** A machine without GTK 4 or
WebKitGTK -- an older distribution, a server with no desktop libraries -- is
offered no window here, and `open_browser` goes on to the browsers exactly as
it did. WebKitGTK 4.1 with GTK 3 is not driven from here on purpose: it is a
second API surface nothing available to test would exercise, and an untested
fallback is worse than an honest absence.
"""

import os
from typing import List, Optional

WINDOW_FLAG = "--app-window"

# What GObject introspection needs on disk for the imports below to work.
# Checked as files rather than by importing, because this is asked on the way
# to opening a window and importing gi costs a third of a second.
TYPELIBS = ("Gtk-4.0.typelib", "WebKit-6.0.typelib")

TYPELIB_DIRS = (
    "/usr/lib64/girepository-1.0",
    "/usr/lib/girepository-1.0",
    "/usr/lib/x86_64-linux-gnu/girepository-1.0",
    "/usr/lib/aarch64-linux-gnu/girepository-1.0",
)

# The starting page's own background, so the window does not flash white on a
# television before the page is in it.
BACKGROUND = (0x21 / 255, 0x25 / 255, 0x29 / 255, 1.0)

EXIT_NO_TOOLKIT = 3


def _typelib_dirs() -> List[str]:
    configured = [d for d in os.environ.get("GI_TYPELIB_PATH", "").split(os.pathsep) if d]
    return configured + list(TYPELIB_DIRS)


def toolkit_present() -> bool:
    """Is the toolkit installed? Asked without needing a display.

    Separate from `available` because the installer asks this over ssh, where
    there is no display and the answer would otherwise be "use a browser" on a
    machine that will do better than that the moment someone sits at it.

    Deliberately cheap -- `available` runs on every launch, before the window,
    and the person is waiting for it. Files on disk, not an import: importing
    gi costs a third of a second.
    """
    if os.name == "nt":
        return False
    try:
        import importlib.util
        if importlib.util.find_spec("gi") is None:
            return False
    except (ImportError, ValueError):
        return False
    directories = _typelib_dirs()
    return all(any(os.path.isfile(os.path.join(d, name)) for d in directories)
               for name in TYPELIBS)


def available() -> bool:
    """Is there a toolkit here, and somewhere to put a window?"""
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        # No display means no window, whatever is installed. Sunshine's own
        # session always has one; a bare ssh session does not, and should get
        # the browser's own answer about that rather than a GTK backtrace.
        return False
    return toolkit_present()


# What to install, per packaging family, when the toolkit is not here.
#
# Measured in containers on 2026-09-18, which is the only reason this list is
# specific: on Fedora and Arch the typelibs come with the runtime library, so
# a desktop already has them and nothing needs saying. On Debian and Ubuntu
# they are separate `gir1.2-*` packages that the library does not pull in --
# installing libwebkitgtk-6.0-4 alone leaves no typelib at all -- so those
# machines use a browser until someone asks for otherwise.
PACKAGES = {
    "debian": ("apt install", "gir1.2-gtk-4.0 gir1.2-webkit-6.0"),
    "fedora": ("dnf install", "gtk4 webkitgtk6.0 python3-gobject"),
    "arch": ("pacman -S", "gtk4 webkitgtk-6.0 python-gobject"),
    "suse": ("zypper install",
             "typelib-1_0-Gtk-4_0 typelib-1_0-WebKit-6_0 python3-gobject"),
}


def _family() -> str:
    """Which packaging family this is, from the machine's own description."""
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            fields = dict(
                line.rstrip("\n").split("=", 1) for line in handle
                if "=" in line and not line.startswith("#"))
    except OSError:
        return ""
    names = " ".join(fields.get(key, "").strip('"').lower()
                     for key in ("ID", "ID_LIKE"))
    for family in ("debian", "fedora", "arch", "suse"):
        if family in names:
            return family
    # Ubuntu says ID=ubuntu, ID_LIKE=debian, so the loop catches it; this is
    # for anything that names neither.
    return ""


def how_to_install() -> str:
    """One line telling someone how to get a window, or "" if we cannot say."""
    family = _family()
    if family not in PACKAGES:
        return ("install the GTK 4 and WebKitGTK 6.0 introspection typelibs "
                "for your distribution")
    command, packages = PACKAGES[family]
    return f"sudo {command} {packages}"


def command(url: str, profile: str, streamed: bool = True) -> List[str]:
    """How to start the window, as a command line.

    It carries ``--user-data-dir`` under the name a Chromium browser uses, and
    not because WebKit wants it: that is the string the launcher recognises its
    own windows by (``launcher.PROFILE_PATTERN``), and a window it cannot see
    is one its cleanup would leave running on top of its replacement.
    """
    import sys
    return [sys.executable, "-m", "sunshine_apps_ui", WINDOW_FLAG,
            f"--user-data-dir={profile}",
            "--fullscreen" if streamed else "--windowed", url]


def _is_ours(uri: str) -> bool:
    """Our own server and our own starting page; everything else is the web."""
    from urllib.parse import urlsplit

    if not uri:
        return True
    parts = urlsplit(uri)
    if parts.scheme == "file":
        return True
    if parts.scheme not in ("http", "https"):
        return False
    return parts.hostname in ("127.0.0.1", "::1", "localhost")


def main(argv: Optional[List[str]] = None) -> int:
    """Run the window. Returns a process exit code.

    Exit 3 says "no toolkit here", which is how the launcher knows to use a
    browser instead rather than showing a window that is not there.
    """
    args = list(argv if argv is not None else [])
    url, streamed, profile = "", True, ""
    for arg in args:
        if arg == "--fullscreen":
            streamed = True
        elif arg == "--windowed":
            streamed = False
        elif arg.startswith("--user-data-dir="):
            profile = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            url = url or arg

    if not url:
        print("No URL to show.", file=__import__("sys").stderr)
        return 2

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Gdk, Gio, Gtk, WebKit
    except (ImportError, ValueError) as e:
        print(f"No GTK 4 / WebKitGTK 6 here ({e}); a browser will be used "
              f"instead.", file=__import__("sys").stderr)
        return EXIT_NO_TOOLKIT

    # NON_UNIQUE because a second manager must be a second window, not a
    # message to the first. The launcher ends the previous one deliberately;
    # handing over to it would resurrect what was just closed.
    app = Gtk.Application(application_id="net.getonward.SunshineAppsUi",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(application):
        window = Gtk.ApplicationWindow(application=application)
        window.set_title("App Manager")
        window.set_default_size(1280, 800)

        session = None
        if profile:
            try:
                os.makedirs(profile, exist_ok=True)
                session = WebKit.NetworkSession(
                    data_directory=os.path.join(profile, "data"),
                    cache_directory=os.path.join(profile, "cache"))
            except Exception:                     # noqa: BLE001 - not worth failing for
                session = None
        view = (WebKit.WebView(network_session=session) if session is not None
                else WebKit.WebView())

        colour = Gdk.RGBA()
        colour.red, colour.green, colour.blue, colour.alpha = BACKGROUND
        view.set_background_color(colour)

        def retitle(*_):
            window.set_title(view.get_title() or "App Manager")

        view.connect("notify::title", retitle)

        def decide(_view, decision, decision_type):
            # The window is the app, not a browser: it has no address bar, so
            # a link that leaves the app would strand whoever followed it with
            # no way back. Anything not ours goes to the real browser.
            try:
                if decision_type == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
                    uri = decision.get_navigation_action().get_request().get_uri()
                    decision.ignore()
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                    return True
                if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
                    uri = decision.get_navigation_action().get_request().get_uri()
                    if not _is_ours(uri):
                        decision.ignore()
                        Gio.AppInfo.launch_default_for_uri(uri, None)
                        return True
            except Exception:                     # noqa: BLE001 - never block the page
                return False
            return False

        view.connect("decide-policy", decide)
        window.set_child(view)
        # Sean's rule, 2026-09-17: streamed through Moonlight nothing should
        # frame the page; opened at the machine, a window you cannot move or
        # close is hostile.
        if streamed:
            window.fullscreen()
        else:
            window.maximize()
        view.load_uri(url)
        window.present()

    app.connect("activate", on_activate)
    return app.run([])
