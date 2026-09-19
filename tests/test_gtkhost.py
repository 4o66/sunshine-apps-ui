# SPDX-License-Identifier: GPL-3.0-or-later
"""A window of our own on Linux.

The Windows one needed a compiler and 187 lines of C#; this one needs neither,
because GTK 4 and WebKitGTK are already on the machine and reachable from
Python. What is tested here is the part that is decisions rather than GTK: that
a machine without the toolkit keeps the browser, that the window is one the
launcher can recognise and clean up, and that it does not outlive the launcher
-- which it did, on the first build, on Bazzite.

Measured there, in the real session: app on screen 1.31-1.98 s, closed in
0.11 s, and gone 0.03 s after the launcher was killed outright.
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import gtkhost, launcher  # noqa: E402


class CommandTest(unittest.TestCase):
    URL = "http://127.0.0.1:47999/?token=abc"
    PROFILE = os.path.join("/home/sean/.local/state", "sunshine-apps-ui",
                           "browser-profile")

    def command(self, streamed):
        return gtkhost.command(self.URL, self.PROFILE, streamed=streamed)

    def test_the_launcher_can_recognise_its_own_window(self):
        """It is how the cleanup finds a window left over from last time.

        The flag is spelled the way a Chromium browser spells it for exactly
        this reason -- launcher.PROFILE_PATTERN is what looks for it.
        """
        line = " ".join(self.command(streamed=True))
        self.assertTrue(re.search(launcher.PROFILE_PATTERN, line),
                        "the launcher would not recognise its own window")

    def test_it_is_not_mistaken_for_the_server(self):
        """Both are `python -m sunshine_apps_ui`; only one carries --port."""
        line = " ".join(self.command(streamed=True))
        self.assertIsNone(re.search(launcher.SERVER_PATTERN, line),
                          "stop_previous would kill the window as a stale server")

    def test_streamed_has_no_frame_and_local_keeps_one(self):
        """Sean's rule, 2026-09-17."""
        self.assertIn("--fullscreen", self.command(streamed=True))
        self.assertIn("--windowed", self.command(streamed=False))

    def test_it_runs_this_package_with_this_interpreter(self):
        command = self.command(streamed=True)
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:4], ["-m", "sunshine_apps_ui", gtkhost.WINDOW_FLAG])
        self.assertEqual(command[-1], self.URL)


class AvailableTest(unittest.TestCase):
    def setUp(self):
        self.environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.environ)))
        self.tmp = tempfile.mkdtemp()

    def with_typelibs(self, *names, gi=True):
        for name in names:
            open(os.path.join(self.tmp, name), "w").close()
        os.environ["GI_TYPELIB_PATH"] = self.tmp
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        # This Mac has no PyGObject, so say whether it is there rather than
        # testing whichever machine happens to run the suite.
        import importlib.util
        patched = mock.patch.object(importlib.util, "find_spec",
                                    return_value=object() if gi else None)
        patched.start()
        self.addCleanup(patched.stop)

    def test_no_display_means_no_window_whatever_is_installed(self):
        self.with_typelibs(*gtkhost.TYPELIBS)
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("DISPLAY", None)
        self.assertFalse(gtkhost.available())

    def test_a_display_and_both_typelibs_is_enough(self):
        self.with_typelibs(*gtkhost.TYPELIBS)
        with mock.patch.object(os, "name", "posix"):
            self.assertTrue(gtkhost.available())

    def test_half_a_toolkit_is_not_enough(self):
        """WebKitGTK without GTK 4, which is an ordinary state on older distros."""
        self.with_typelibs(gtkhost.TYPELIBS[0])
        with mock.patch.object(os, "name", "posix"):
            self.assertFalse(gtkhost.available())

    def test_no_pygobject_means_no_window(self):
        self.with_typelibs(*gtkhost.TYPELIBS, gi=False)
        with mock.patch.object(os, "name", "posix"):
            self.assertFalse(gtkhost.available())

    def test_never_on_windows(self):
        self.with_typelibs(*gtkhost.TYPELIBS)
        with mock.patch.object(os, "name", "nt"):
            self.assertFalse(gtkhost.available())


class WhatIsOursTest(unittest.TestCase):
    """The window has no address bar, so a link that leaves it strands you."""

    def test_our_own_server_and_page_stay_in_the_window(self):
        for uri in ("http://127.0.0.1:47999/?token=a", "http://localhost:80/",
                    "file:///home/sean/.local/state/sunshine-apps-ui/starting.html"):
            self.assertTrue(gtkhost._is_ours(uri), uri)

    def test_the_web_does_not(self):
        for uri in ("https://www.steamgriddb.com/", "http://192.168.1.5/",
                    "https://example.com"):
            self.assertFalse(gtkhost._is_ours(uri), uri)

    def test_nothing_exotic_is_treated_as_ours(self):
        for uri in ("javascript:alert(1)", "data:text/html,hi", "ftp://host/x"):
            self.assertFalse(gtkhost._is_ours(uri), uri)


class MainTest(unittest.TestCase):
    def test_no_url_is_an_error_not_a_window(self):
        self.assertEqual(gtkhost.main(["--windowed"]), 2)

    def test_a_machine_without_the_toolkit_says_so_in_its_exit_code(self):
        """3 is "use a browser instead", which is what the launcher does."""
        if gtkhost.available():
            self.skipTest("this machine has the toolkit")
        self.assertEqual(gtkhost.main(["http://127.0.0.1:1/"]),
                         gtkhost.EXIT_NO_TOOLKIT)


class LauncherPrefersItButNeverNeedsItTest(unittest.TestCase):
    def setUp(self):
        self.spawned = []

        def fake_spawn(command, env=None, die_with_us=False):
            self.spawned.append({"command": command, "env": env,
                                 "die_with_us": die_with_us})
            return mock.Mock(poll=lambda: None)

        patched = mock.patch.object(launcher, "_spawn", fake_spawn)
        patched.start()
        self.addCleanup(patched.stop)
        windows = mock.patch.object(launcher, "WINDOWS", False)
        windows.start()
        self.addCleanup(windows.stop)

    def open(self, available, **kwargs):
        with mock.patch.object(gtkhost, "available", return_value=available), \
                mock.patch.object(launcher, "_flatpak_installed", return_value=True):
            return launcher.open_browser("http://127.0.0.1:1/", "/p", **kwargs)

    def test_it_is_used_when_the_toolkit_is_there(self):
        process, how = self.open(True)
        self.assertEqual(how, launcher.OUR_WINDOW)
        self.assertIn(gtkhost.WINDOW_FLAG, self.spawned[0]["command"])

    def test_the_browser_is_used_when_it_is_not(self):
        process, how = self.open(False)
        self.assertNotEqual(how, launcher.OUR_WINDOW)
        self.assertNotIn(gtkhost.WINDOW_FLAG, " ".join(self.spawned[0]["command"]))

    def test_a_caller_can_ask_for_a_browser_specifically(self):
        """Which is what launch() does after watching our window fail."""
        process, how = self.open(True, own_window=False)
        self.assertNotEqual(how, launcher.OUR_WINDOW)

    def test_the_window_is_given_the_path_to_import_this_package(self):
        """sys.path does not survive into a child: without it, it exits 1."""
        self.open(True)
        env = self.spawned[0]["env"]
        self.assertIsNotNone(env)
        self.assertIn(launcher.package_path(), env.get("PYTHONPATH", "").split(os.pathsep))

    def test_the_window_is_told_to_die_with_us(self):
        self.open(True)
        self.assertTrue(self.spawned[0]["die_with_us"])


class NothingOutlivesTheLauncherTest(unittest.TestCase):
    """It did, on Bazzite: terminating the launcher left the window on screen.

    SIGTERM kills the process where it stands, so the `finally` that closes the
    window and stops the server never ran -- and Sunshine ends an app by
    signalling it, so that is the ordinary way this exits, not an edge case.
    """

    def test_a_termination_signal_becomes_an_orderly_exit(self):
        before = signal.getsignal(signal.SIGTERM)
        try:
            launcher._leave_on_signal()
            handler = signal.getsignal(signal.SIGTERM)
            self.assertNotIn(handler, (signal.SIG_DFL, signal.SIG_IGN),
                             "SIGTERM would kill us before the teardown runs")
            with self.assertRaises(SystemExit):
                handler(signal.SIGTERM, None)
        finally:
            signal.signal(signal.SIGTERM, before)

    def test_it_does_not_fail_where_it_cannot_install_one(self):
        """A thread, or a platform without SIGHUP. Neither is worth refusing to run."""
        with mock.patch.object(signal, "signal", side_effect=ValueError("not main")):
            launcher._leave_on_signal()

    def test_the_child_is_asked_to_die_with_us_only_where_that_exists(self):
        """PR_SET_PDEATHSIG is Linux's job object; elsewhere there is nothing to set."""
        seen = {}

        def fake_popen(command, **kwargs):
            seen.update(kwargs)
            return mock.Mock()

        with mock.patch.object(launcher.subprocess, "Popen", fake_popen):
            with mock.patch.object(launcher.sys, "platform", "darwin"):
                launcher._spawn(["true"], die_with_us=True)
                self.assertIsNone(seen.get("preexec_fn"))
            with mock.patch.object(launcher.sys, "platform", "linux"):
                launcher._spawn(["true"], die_with_us=True)
                self.assertIs(seen.get("preexec_fn"), launcher._die_with_us)

    def test_an_ordinary_spawn_is_left_alone(self):
        seen = {}

        def fake_popen(command, **kwargs):
            seen.update(kwargs)
            return mock.Mock()

        with mock.patch.object(launcher.subprocess, "Popen", fake_popen):
            launcher._spawn(["true"])
        self.assertIsNone(seen.get("preexec_fn"))


class TheWindowFlagIsRoutedBeforeArgparseTest(unittest.TestCase):
    """Its arguments are the window's, including a URL argparse would eat."""

    def test_the_flag_reaches_the_host(self):
        from sunshine_apps_ui import __main__ as entry
        with mock.patch.object(gtkhost, "main", return_value=7) as ran:
            code = entry.main([gtkhost.WINDOW_FLAG, "--windowed",
                               "http://127.0.0.1:1/?token=x"])
        self.assertEqual(code, 7)
        self.assertEqual(ran.call_args[0][0],
                         ["--windowed", "http://127.0.0.1:1/?token=x"])


if __name__ == "__main__":
    unittest.main()
