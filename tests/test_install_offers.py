# SPDX-License-Identifier: GPL-3.0-or-later
"""Offering to install someone else's software, and being plain about it.

Two of these, one per platform, and both ask before doing anything a normal
install does not: on Linux the GTK 4 and WebKitGTK typelibs, which needs sudo,
and on Windows Microsoft's WebView2 runtime, which needs a download and
possibly administrator rights.

The rules both follow, and what these tests are actually about:

* **Never without being asked.** No prompt available -- a scripted install --
  means print the command and move on, never run it.
* **Say exactly what will run**, as the literal command where there is one.
* **Declining is a first-class answer** and the install continues.
* **A failure is reported, not swallowed**, and never leaves a half-state.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import gtkhost, installer, winhost  # noqa: E402


@unittest.skipIf(os.name == "nt", "the Linux toolkit offer")
class LinuxToolkitOfferTest(unittest.TestCase):
    def setUp(self):
        self.ran = []
        # These are about what the offer says and does for a person at a
        # terminal, which is the only place it runs anything.
        tty = mock.patch.object(installer, "_at_a_terminal", return_value=True)
        tty.start()
        self.addCleanup(tty.stop)
        patched = mock.patch.object(
            installer.subprocess, "run",
            side_effect=lambda cmd, **kw: self.ran.append(cmd) or mock.Mock(returncode=0))
        patched.start()
        self.addCleanup(patched.stop)
        family = mock.patch.object(gtkhost, "_family", return_value="debian")
        family.start()
        self.addCleanup(family.stop)

    def offer(self, answer, present_after=True):
        seen = {}

        def confirm(detail, question):
            seen["detail"], seen["question"] = detail, question
            return answer

        with mock.patch.object(gtkhost, "toolkit_present",
                               side_effect=[False, present_after]):
            lines = installer._provide_window_linux(confirm)
        return seen, lines

    def test_it_says_the_command_it_will_run(self):
        seen, _ = self.offer(False)
        self.assertIn("sudo apt install gir1.2-gtk-4.0 gir1.2-webkit-6.0",
                      seen["detail"])

    def test_it_says_this_is_the_only_part_needing_root(self):
        seen, _ = self.offer(False)
        self.assertIn("root", seen["detail"].lower())
        self.assertIn("home directory", seen["detail"])

    def test_it_says_the_password_never_reaches_this_program(self):
        """Somebody is about to type their password. They should know where."""
        seen, _ = self.offer(False)
        self.assertIn("sudo will ask for your password itself", seen["detail"])
        self.assertIn("not read, stored or seen by this program",
                      seen["detail"].lower())

    def test_declining_is_fine_and_runs_nothing(self):
        _, lines = self.offer(False)
        self.assertEqual(self.ran, [])
        self.assertIn("declined", " ".join(lines))
        self.assertIn("a browser", " ".join(lines))

    def test_declining_still_says_how_to_change_your_mind(self):
        _, lines = self.offer(False)
        self.assertIn("sudo apt install", " ".join(lines))

    def test_accepting_runs_it_without_a_shell(self):
        """A package name must never be able to become a second command."""
        self.offer(True)
        self.assertEqual(len(self.ran), 1)
        self.assertIsInstance(self.ran[0], list)
        self.assertEqual(self.ran[0][0], "sudo")

    def test_a_scripted_install_is_told_but_never_asked(self):
        with mock.patch.object(gtkhost, "toolkit_present", return_value=False):
            lines = installer._provide_window_linux(None)
        self.assertEqual(self.ran, [])
        self.assertIn("not interactive", " ".join(lines))
        self.assertIn("sudo apt install", " ".join(lines))

    def test_an_unknown_distribution_is_not_guessed_at(self):
        with mock.patch.object(gtkhost, "_family", return_value=""), \
                mock.patch.object(gtkhost, "toolkit_present", return_value=False):
            lines = installer._provide_window_linux(lambda d, q: True)
        self.assertEqual(self.ran, [], "it invented a package manager")
        self.assertIn("do not recognise", " ".join(lines))

    def test_a_failing_package_manager_is_reported(self):
        with mock.patch.object(installer.subprocess, "run",
                               return_value=mock.Mock(returncode=100)), \
                mock.patch.object(gtkhost, "toolkit_present", return_value=False):
            lines = installer._provide_window_linux(lambda d, q: True)
        self.assertIn("exited 100", " ".join(lines))
        self.assertIn("by hand", " ".join(lines))


class WindowsWebView2OfferTest(unittest.TestCase):
    def offer(self, answer):
        seen = {}

        def confirm(detail, question):
            seen["detail"], seen["question"] = detail, question
            return answer

        with mock.patch.object(winhost, "runtime_version", return_value=""):
            lines = installer._offer_webview2({"install": "/x"}, confirm)
        return seen, lines

    def test_it_says_whose_installer_it_is_and_where_from(self):
        seen, _ = self.offer(False)
        self.assertIn("Microsoft", seen["detail"])
        self.assertIn("microsoft.com", seen["detail"])

    def test_it_promises_to_check_the_signature(self):
        seen, _ = self.offer(False)
        self.assertIn("Authenticode", seen["detail"])

    def test_it_warns_that_administrator_may_be_asked_for_and_by_whom(self):
        seen, _ = self.offer(False)
        self.assertIn("administrator", seen["detail"].lower())
        self.assertIn("not this program", seen["detail"])

    def test_declining_is_fine(self):
        _, lines = self.offer(False)
        self.assertIn("declined", " ".join(lines))

    def test_a_scripted_install_is_not_asked(self):
        with mock.patch.object(winhost, "runtime_version", return_value=""):
            lines = installer._offer_webview2({"install": "/x"}, None)
        self.assertIn("not interactive", " ".join(lines))

    def test_an_unsigned_download_is_refused_rather_than_run(self):
        """An installer is the last thing to be relaxed about."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "powershell" in cmd[0]:
                return mock.Mock(returncode=0, stdout="HashMismatch\nCN=Somebody Else")
            return mock.Mock(returncode=0)

        with mock.patch.object(winhost.os, "name", "nt"), \
                mock.patch.object(winhost.subprocess, "run", fake_run), \
                mock.patch("urllib.request.urlopen",
                           mock.mock_open(read_data=b"MZ")):
            worked, said = winhost.install_runtime()
        self.assertFalse(worked)
        self.assertIn("not signed by Microsoft", said)
        self.assertEqual(len([c for c in calls if "powershell" not in c[0]]), 0,
                         "it ran the installer anyway")


if __name__ == "__main__":
    unittest.main()


class NoTerminalMeansNoPackageManagerTest(unittest.TestCase):
    """A confirm function is not somebody at a terminal.

    sudo prompts on the terminal itself, so without one the install either
    hangs or fails. And a test that answers yes to everything -- an ordinary
    thing for a test to do -- would otherwise run a real package manager on
    the machine running the suite. It did: on the Fedora VM, 2026-09-19, the
    suite reached dnf's transaction prompt and was saved only by having no tty
    to answer it at.
    """

    def _offer(self, tty):
        from sunshine_apps_ui import gtkhost, installer
        ran = []
        with mock.patch.object(installer, "_at_a_terminal", return_value=tty), \
             mock.patch.object(gtkhost, "install_command",
                               return_value=["sudo", "dnf", "install", "gtk4"]), \
             mock.patch.object(gtkhost, "toolkit_present", return_value=True), \
             mock.patch.object(installer.subprocess, "run",
                               side_effect=lambda *a, **k: (ran.append(a)
                                                            or mock.Mock(returncode=0))):
            lines = installer._offer_the_toolkit(lambda text, question: True)
        return ran, "\n".join(lines)

    def test_without_a_terminal_it_only_says_what_to_run(self):
        ran, said = self._offer(tty=False)
        self.assertEqual(ran, [])
        self.assertIn("sudo dnf install gtk4", said)
        self.assertIn("no terminal", said)

    def test_with_a_terminal_a_yes_still_runs_it(self):
        ran, _ = self._offer(tty=True)
        self.assertEqual(len(ran), 1)
