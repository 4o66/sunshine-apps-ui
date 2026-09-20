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
        # Only this directory. The real search adds the system ones, so on a
        # machine that genuinely has the toolkit -- the Arch image does --
        # "half a toolkit" was answered by the half installed on the machine
        # rather than by the half in the fixture.
        dirs = mock.patch.object(gtkhost, "_typelib_dirs", lambda: [self.tmp])
        dirs.start()
        self.addCleanup(dirs.stop)
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
        """With the sandbox stood in for: it is the third condition, and on a
        machine where it is genuinely blocked -- Ubuntu 24.04, measured -- the
        honest answer is False. That case is TheSandboxWebKitInsistsOnTest;
        this one is about the typelibs."""
        self.with_typelibs(*gtkhost.TYPELIBS)
        with mock.patch.object(os, "name", "posix"), \
                mock.patch.object(gtkhost, "sandbox_can_run", return_value=True):
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


class WhichPackagesTest(unittest.TestCase):
    """What to tell someone whose machine has no toolkit.

    Measured in containers on 2026-09-18: on Fedora and Arch the typelibs come
    with the runtime library, so a desktop already has them. On Debian 12 and
    Ubuntu 22.04/24.04 they do not -- installing libwebkitgtk-6.0-4 alone
    leaves no typelib at all -- so those machines use a browser until somebody
    installs two packages they would never guess at.
    """

    def family(self, text):
        import io
        return mock.patch("builtins.open", mock.mock_open(read_data=text))

    def test_ubuntu_is_told_about_the_gir_packages(self):
        with self.family('ID=ubuntu\nID_LIKE=debian\n'):
            line = gtkhost.how_to_install()
        self.assertIn("apt install", line)
        self.assertIn("gir1.2-webkit-6.0", line)
        self.assertIn("gir1.2-gtk-4.0", line)

    def test_debian_gets_the_same_answer(self):
        with self.family('ID=debian\n'):
            self.assertIn("gir1.2-webkit-6.0", gtkhost.how_to_install())

    def test_each_family_gets_a_command_with_a_verb(self):
        for ident, expected in (("fedora", "dnf install"), ("arch", "pacman -S"),
                                ("opensuse-tumbleweed", "zypper install")):
            with self.family("ID=%s\nID_LIKE=%s\n" % (ident, ident.split("-")[0])):
                line = gtkhost.how_to_install()
            self.assertIn(expected, line, ident)
            self.assertTrue(line.startswith("sudo "), line)

    def test_something_unrecognised_still_says_what_is_needed(self):
        with self.family("ID=plan9\n"):
            line = gtkhost.how_to_install()
        self.assertIn("GTK 4", line)
        self.assertIn("WebKitGTK", line)
        self.assertNotIn("sudo", line, "do not invent a package manager")

    def test_no_os_release_at_all_is_not_an_error(self):
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertIn("GTK 4", gtkhost.how_to_install())


class TheInstallerSaysWhichWindowYouGetTest(unittest.TestCase):
    def test_it_says_so_when_the_toolkit_is_there(self):
        """And the sandbox can run: on a machine where it cannot, the honest
        answer is a browser and an explanation, which is three lines."""
        from sunshine_apps_ui import installer
        with mock.patch.object(gtkhost, "toolkit_present", return_value=True), \
                mock.patch.object(gtkhost, "sandbox_can_run", return_value=True):
            lines = installer._provide_window_linux()
        self.assertEqual(len(lines), 1)
        self.assertIn("our own", lines[0])

    def test_without_the_toolkit_it_offers_to_install_it(self):
        """It used to only print the command. Now it asks -- see
        tests/test_install_offers.py for what it says while asking."""
        from sunshine_apps_ui import installer
        asked = []
        with mock.patch.object(gtkhost, "toolkit_present", return_value=False), \
                mock.patch.object(gtkhost, "_family", return_value="debian"):
            lines = installer._provide_window_linux(
                lambda detail, question: asked.append(question) or False)
        self.assertEqual(len(asked), 1, "it should have asked")
        self.assertIn("a browser", " ".join(lines))
        self.assertIn("sudo apt install", " ".join(lines))

    def test_it_does_not_need_a_display_to_answer(self):
        """The install is usually run over ssh, where there is no display.

        Asking `available()` here would report "a browser" for every machine
        installed remotely, including ones that will open our window the
        moment somebody sits at them.
        """
        from sunshine_apps_ui import installer
        environ = {k: v for k, v in os.environ.items()
                   if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.dict(os.environ, environ, clear=True), \
                mock.patch.object(gtkhost, "toolkit_present", return_value=True), \
                mock.patch.object(gtkhost, "sandbox_can_run", return_value=True):
            lines = installer._provide_window_linux()
        self.assertIn("our own", lines[0])


class TheSandboxWebKitInsistsOnTest(unittest.TestCase):
    """WebKitGTK aborts the whole process when it cannot have its sandbox.

    Measured 2026-09-19: on Ubuntu 24.04 the window died with

        bwrap: setting up uid map: Permission denied
        ERROR: Failed to fully launch dbus-proxy

    because unprivileged user namespaces are restricted there by default.
    Debian 13 and Arch allow them and the window works. This is not a failure
    that can be caught -- the process aborts -- so it has to be asked about
    beforehand, and the answer is to use a browser.
    """

    def switches(self, **files):
        real = open

        def fake(path, *args, **kwargs):
            if path in files:
                if files[path] is None:
                    raise OSError("no such knob")
                import io
                return io.StringIO(files[path])
            return real(path, *args, **kwargs)

        return mock.patch("builtins.open", fake)

    def test_ubuntus_restriction_is_recognised(self):
        with self.switches(**{
                "/proc/sys/kernel/apparmor_restrict_unprivileged_userns": "1\n",
                "/proc/sys/kernel/unprivileged_userns_clone": None}):
            self.assertFalse(gtkhost.sandbox_can_run())

    def test_debians_older_knob_is_recognised_the_other_way_round(self):
        with self.switches(**{
                "/proc/sys/kernel/apparmor_restrict_unprivileged_userns": None,
                "/proc/sys/kernel/unprivileged_userns_clone": "0\n"}):
            self.assertFalse(gtkhost.sandbox_can_run())

    def test_a_machine_that_allows_them_is_fine(self):
        with self.switches(**{
                "/proc/sys/kernel/apparmor_restrict_unprivileged_userns": "0\n",
                "/proc/sys/kernel/unprivileged_userns_clone": "1\n"}):
            self.assertTrue(gtkhost.sandbox_can_run())

    def test_no_knobs_at_all_means_no_restriction(self):
        with self.switches(**{
                "/proc/sys/kernel/apparmor_restrict_unprivileged_userns": None,
                "/proc/sys/kernel/unprivileged_userns_clone": None}):
            self.assertTrue(gtkhost.sandbox_can_run())

    def test_the_window_is_not_offered_where_the_sandbox_cannot_run(self):
        with mock.patch.object(gtkhost, "toolkit_present", return_value=True), \
                mock.patch.object(gtkhost, "sandbox_can_run", return_value=False), \
                mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            self.assertFalse(gtkhost.available())

    def test_the_installer_says_which_policy_it_is(self):
        """Otherwise it reads as "your distribution is unsupported"."""
        from sunshine_apps_ui import installer
        with mock.patch.object(gtkhost, "toolkit_present", return_value=True), \
                mock.patch.object(gtkhost, "sandbox_can_run", return_value=False):
            lines = installer._provide_window_linux()
        text = " ".join(lines)
        self.assertIn("a browser", text)
        self.assertIn("user namespaces", text)
        self.assertIn("Ubuntu 24.04", text)


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
        if gtkhost.available() or gtkhost.toolkit_present():
            # toolkit_present() as well as available(): a headless machine
            # that has the typelibs installed anyway -- the Arch and Ubuntu
            # cloud images -- goes past the check this is about and into
            # Gtk.init(), which aborts the process rather than returning a
            # code. Measured on both, 2026-09-19.
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
