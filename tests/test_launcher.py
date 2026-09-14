"""The launcher's half of "one session at a time".

This is shell, not Python, and it earned a test the hard way: a relaunch left
the previous browser running, which took the URL, opened a window in its own
process and let the new launcher exit -- taking down the server it had just
started and leaving every window dead.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "scripts", "sunshine-apps-ui-launch")

# A cmdline that looks like our browser, spelled the way an ostree system
# might: /home is a symlink to /var/home, so the same profile has two names.
FAKE_BROWSER = "--user-data-dir=/var/home/u/.local/state/sunshine-apps-ui/browser-profile"


def prologue() -> str:
    """The launcher up to and including stop_previous, and nothing after it.

    Running the whole thing would start a server and a browser. What is being
    tested is only what it does about the last session.
    """
    with open(LAUNCHER, "r", encoding="utf-8") as handle:
        lines = []
        for line in handle:
            lines.append(line)
            if line.strip() == "stop_previous":
                return "".join(lines)
    raise AssertionError("stop_previous is no longer called in the launcher")


@unittest.skipUnless(shutil.which("pgrep") and shutil.which("pkill"),
                     "needs pgrep and pkill")
class StopPreviousTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        # The launcher refuses to run without an importer, so give it one.
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        stub = os.path.join(self.home, ".local", "bin", "sunshine-import")
        with open(stub, "w") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub, 0o755)
        self.env = dict(os.environ, HOME=self.home)
        self.spawned = []

    def tearDown(self):
        for proc in self.spawned:
            proc.kill()
            proc.wait()

    def _spawn(self, marker):
        proc = subprocess.Popen(
            ["bash", "-c", "while :; do sleep 0.2; done", marker],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.spawned.append(proc)
        time.sleep(0.3)
        return proc

    def _run_prologue(self):
        return subprocess.run(["bash", "-c", prologue()], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def test_a_browser_left_from_last_time_is_ended(self):
        proc = self._spawn(FAKE_BROWSER)
        self._run_prologue()
        self.assertIsNotNone(proc.poll(), "the previous browser is still running")

    def test_it_waits_until_the_browser_is_actually_gone(self):
        """Starting while the old one lives hands it the URL, which is the bug."""
        proc = self._spawn(FAKE_BROWSER)
        self._run_prologue()
        self.assertIsNotNone(proc.poll())

    def test_an_unrelated_browser_is_left_alone(self):
        """Killing every Chrome on the machine would not be a fix."""
        proc = self._spawn("--user-data-dir=/home/u/.config/google-chrome")
        self.addCleanup(proc.kill)
        self._run_prologue()
        self.assertIsNone(proc.poll(), "someone else's browser was killed")

    def test_nothing_left_over_is_not_an_error(self):
        self.assertEqual(self._run_prologue().returncode, 0)

    def test_it_refuses_to_run_without_an_importer(self):
        os.unlink(os.path.join(self.home, ".local", "bin", "sunshine-import"))
        self.assertNotEqual(self._run_prologue().returncode, 0)


class LauncherShapeTest(unittest.TestCase):
    """Things about the script that a signal handler cannot be trusted to do."""

    def setUp(self):
        with open(LAUNCHER, "r", encoding="utf-8") as handle:
            self.text = handle.read()

    def test_it_is_valid_shell(self):
        self.assertEqual(
            subprocess.run(["bash", "-n", LAUNCHER]).returncode, 0)

    def test_cleanup_ends_the_browser_by_profile_not_by_wrapper_pid(self):
        """A signal to `flatpak run` does not reach the browser in the sandbox,
        which is how a window outlives the session that opened it."""
        cleanup = self.text.split("cleanup() {", 1)[1].split("}", 1)[0]
        self.assertIn("PROFILE_MATCH", cleanup)

    def test_the_profile_is_matched_by_its_tail(self):
        """/home is a symlink to /var/home here; an absolute pattern misses."""
        self.assertNotIn('"--user-data-dir=$PROFILE"', self.text)


if __name__ == "__main__":
    unittest.main()
