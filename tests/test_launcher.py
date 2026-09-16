# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening the interface as a window, and taking it down again.

This was a bash script, and it earned its tests the hard way: a relaunch left
the previous browser running, which took the URL, opened a window in its own
process and let the new launcher exit -- taking down the server it had just
started and leaving every window dead.

Those lessons are the tests. They are about behaviour rather than about the
text of a script, which is why they survived the move to Python unchanged in
meaning.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import launcher  # noqa: E402

# A command line that looks like our browser, spelled the way an ostree system
# might: /home is a symlink to /var/home, so the same profile has two names and
# a pattern built from one must still match the other.
OSTREE_SPELLING = ("--user-data-dir=/var/home/u/.local/state/"
                   "sunshine-apps-ui/browser-profile")


class ProfileMatchingTest(unittest.TestCase):
    """The browser is found by its profile, never by the pid that started it."""

    def _matches(self, command_line: str) -> bool:
        import re
        return bool(re.search(launcher.PROFILE_PATTERN, command_line))

    def test_a_chromium_browser_is_recognised(self):
        self.assertTrue(self._matches(
            "chrome --user-data-dir=/home/u/.local/state/"
            "sunshine-apps-ui/browser-profile --app=http://127.0.0.1:1/"))

    def test_firefox_spells_it_differently_and_is_still_recognised(self):
        self.assertTrue(self._matches(
            "firefox --profile /home/u/.local/state/sunshine-apps-ui/"
            "browser-profile --kiosk http://127.0.0.1:1/"))

    def test_the_other_spelling_of_the_same_path_matches(self):
        """/home is a symlink to /var/home on an ostree system."""
        self.assertTrue(self._matches("chrome " + OSTREE_SPELLING))

    def test_somebody_elses_browser_does_not_match(self):
        self.assertFalse(self._matches(
            "chrome --user-data-dir=/home/u/.config/google-chrome"))

    def test_our_own_server_is_not_a_browser(self):
        self.assertFalse(self._matches("python3 -m sunshine_apps_ui --port 0"))


class StopPreviousTest(unittest.TestCase):
    """Relaunching replaces the previous session rather than stacking on it."""

    def setUp(self):
        self.ended = []
        self.alive = []

    def _patched(self, rounds):
        """browsers() answers from *rounds*, one call at a time."""
        answers = iter(rounds)

        def browsers():
            try:
                return next(answers)
            except StopIteration:
                return []

        return mock.patch.object(launcher, "browsers", browsers)

    def test_the_previous_server_is_ended(self):
        with mock.patch.object(launcher, "_pgrep", return_value=[4242]) as found, \
             mock.patch.object(launcher, "_end") as ended, \
             mock.patch.object(launcher, "browsers", return_value=[]):
            launcher.stop_previous()
        self.assertIn("sunshine_apps_ui --port", found.call_args[0][0])
        ended.assert_called_once_with([4242])

    def test_nothing_running_is_not_an_error(self):
        with mock.patch.object(launcher, "_pgrep", return_value=[]), \
             mock.patch.object(launcher, "browsers", return_value=[]):
            launcher.stop_previous()

    def test_a_previous_browser_is_ended(self):
        with mock.patch.object(launcher, "_pgrep", return_value=[]), \
             self._patched([[99], []]), \
             mock.patch.object(launcher, "_end") as ended:
            launcher.stop_previous()
        self.assertTrue(ended.called)

    def test_one_that_will_not_go_is_killed_rather_than_left(self):
        """Starting while it lives hands it our URL, which is the whole bug."""
        with mock.patch.object(launcher, "_pgrep", return_value=[]), \
             mock.patch.object(launcher, "browsers", return_value=[7]), \
             mock.patch.object(launcher, "_end") as ended, \
             mock.patch.object(launcher.time, "sleep"), \
             mock.patch.object(launcher.time, "monotonic",
                               side_effect=[0, 0, 100, 100]):
            launcher.stop_previous()
        self.assertTrue(any(call.kwargs.get("hard") for call in ended.mock_calls),
                        "it was never killed")


class BrowserChoiceTest(unittest.TestCase):
    """Which browser it opens, on machines that are not Bazzite.

    Only Bazzite necessarily has Chrome as a flatpak. Every other distribution
    Sunshine ships packages for installs browsers natively, and trying only
    flatpak meant falling through to xdg-open and losing the window this waits
    on -- which is what tells it when to shut the server down.
    """

    def setUp(self):
        self.spawned = []

        def spawn(command):
            self.spawned.append(command)
            return mock.Mock(poll=lambda: None)

        patched = mock.patch.object(launcher, "_spawn", spawn)
        patched.start()
        self.addCleanup(patched.stop)

    def test_flatpak_is_preferred_when_it_is_there(self):
        with mock.patch.object(launcher, "_flatpak_installed",
                               lambda app: app == "com.google.Chrome"), \
             mock.patch.object(launcher.shutil, "which", return_value="/usr/bin/chromium"):
            _, how = launcher.open_browser("http://x/", "/p")
        self.assertEqual(how, "flatpak com.google.Chrome")

    def test_a_native_browser_is_used_when_flatpak_has_none(self):
        with mock.patch.object(launcher, "_flatpak_installed", return_value=False), \
             mock.patch.object(launcher.shutil, "which",
                               lambda b: "/usr/bin/chromium" if b == "chromium" else None):
            _, how = launcher.open_browser("http://x/", "/p")
        self.assertEqual(how, "chromium")

    def test_chromium_gets_its_own_profile_and_its_own_window(self):
        with mock.patch.object(launcher, "_flatpak_installed", return_value=False), \
             mock.patch.object(launcher.shutil, "which",
                               lambda b: "/usr/bin/chromium" if b == "chromium" else None):
            launcher.open_browser("http://x/", "/p")
        command = self.spawned[0]
        self.assertIn("--user-data-dir=/p", command)
        self.assertIn("--app=http://x/", command)

    def test_firefox_is_a_fallback_rather_than_a_peer(self):
        """--kiosk has no equivalent of --app: it takes the screen rather than
        giving us a window."""
        with mock.patch.object(launcher, "_flatpak_installed", return_value=False), \
             mock.patch.object(launcher.shutil, "which",
                               lambda b: "/usr/bin/firefox" if b == "firefox" else None):
            _, how = launcher.open_browser("http://x/", "/p")
        self.assertEqual(how, "firefox")
        self.assertIn("--kiosk", self.spawned[0])

    def test_no_browser_at_all_is_reported_rather_than_guessed_at(self):
        with mock.patch.object(launcher, "_flatpak_installed", return_value=False), \
             mock.patch.object(launcher.shutil, "which", return_value=None):
            process, how = launcher.open_browser("http://x/", "/p")
        self.assertIsNone(process)
        self.assertEqual(how, "")


class UrlTest(unittest.TestCase):
    """Reading the URL the server prints, and noticing when it never does."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "log")

    def _server(self, alive=True):
        return mock.Mock(poll=lambda: None if alive else 1)

    def test_the_url_is_found_once_it_is_written(self):
        with open(self.log, "w") as handle:
            handle.write("starting\n  http://127.0.0.1:47999/?token=abc-DEF_123\n")
        self.assertEqual(launcher._read_url(self.log, self._server()),
                         "http://127.0.0.1:47999/?token=abc-DEF_123")

    def test_a_server_that_died_is_not_waited_on(self):
        open(self.log, "w").close()
        started = time.monotonic()
        self.assertEqual(launcher._read_url(self.log, self._server(alive=False)), "")
        self.assertLess(time.monotonic() - started, 5)

    def test_a_log_that_never_appears_is_not_fatal(self):
        with mock.patch.object(launcher.time, "monotonic", side_effect=[0, 100]):
            self.assertEqual(launcher._read_url("/nonexistent", self._server()), "")


class ShutDownTest(unittest.TestCase):
    """Whichever of the two is still up gets taken down."""

    def test_the_browser_is_ended_by_profile_not_only_by_handle(self):
        """Ending the launcher does not end the browser it started."""
        server = mock.Mock(poll=lambda: 0)
        browser = mock.Mock(poll=lambda: None)
        with mock.patch.object(launcher, "browsers", return_value=[11]), \
             mock.patch.object(launcher, "_end") as ended:
            launcher._shut_down(server, browser)
        self.assertTrue(browser.terminate.called)
        ended.assert_called_once_with([11])

    def test_the_server_is_ended_too(self):
        server = mock.Mock(poll=lambda: None)
        with mock.patch.object(launcher, "browsers", return_value=[]), \
             mock.patch.object(launcher, "_end"):
            launcher._shut_down(server, None)
        self.assertTrue(server.terminate.called)

    def test_nothing_still_running_is_nothing_to_do(self):
        server = mock.Mock(poll=lambda: 0)
        with mock.patch.object(launcher, "browsers", return_value=[]), \
             mock.patch.object(launcher, "_end"):
            launcher._shut_down(server, None)
        self.assertFalse(server.terminate.called)


class EntryPointTest(unittest.TestCase):
    """The bare command opens a window; anything else runs the program."""

    def test_no_arguments_opens_a_window(self):
        from sunshine_apps_ui import __main__ as entry
        with mock.patch("sunshine_apps_ui.launcher.launch", return_value=0) as launch:
            self.assertEqual(entry.main([]), 0)
        self.assertTrue(launch.called)

    def test_an_argument_runs_the_program_instead(self):
        from sunshine_apps_ui import __main__ as entry
        with mock.patch("sunshine_apps_ui.launcher.launch") as launch:
            with self.assertRaises(SystemExit):     # --version exits
                entry.main(["--version"])
        self.assertFalse(launch.called)


if __name__ == "__main__":
    unittest.main()
