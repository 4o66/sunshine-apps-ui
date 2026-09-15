# SPDX-License-Identifier: GPL-3.0-or-later
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
        """From a file, never `bash -c`.

        With -c the whole script is in the shell's own command line, so the
        pattern it greps for matches the process doing the grepping and it
        kills itself. The launcher runs from a file, where that cannot happen;
        running it any other way tests something that does not exist.
        """
        path = os.path.join(self.home, "prologue.sh")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(prologue())
        return subprocess.run(["bash", path], env=self.env,
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

    def test_it_no_longer_needs_a_separate_importer(self):
        """The engine is part of this program now."""
        os.unlink(os.path.join(self.home, ".local", "bin", "sunshine-import"))
        self.assertEqual(self._run_prologue().returncode, 0)


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


class InstallScriptTest(unittest.TestCase):
    """The installer and uninstaller, as shapes rather than as runs.

    Running them for real would write to the machine the tests are on. What can
    be checked without that is the part that would be dangerous to get wrong.
    """

    @staticmethod
    def code(text: str) -> str:
        """The script without its comments.

        Otherwise a comment saying a flag is deliberately not passed reads as
        the flag being passed.
        """
        return "\n".join(line for line in text.splitlines()
                          if not line.lstrip().startswith("#"))

    def setUp(self):
        self.install = os.path.join(ROOT, "scripts", "install")
        self.uninstall = os.path.join(ROOT, "scripts", "uninstall")
        with open(self.install, encoding="utf-8") as handle:
            self.install_text = handle.read()
        with open(self.uninstall, encoding="utf-8") as handle:
            self.uninstall_text = handle.read()

    def test_both_are_valid_shell(self):
        for path in (self.install, self.uninstall):
            with self.subTest(script=os.path.basename(path)):
                self.assertEqual(subprocess.run(["bash", "-n", path]).returncode, 0)

    def test_both_are_executable(self):
        for path in (self.install, self.uninstall):
            self.assertTrue(os.access(path, os.X_OK), path)

    def test_install_offers_to_put_the_tile_back(self):
        self.assertIn("--put-the-tile-back-because-i-deleted-it", self.install_text)

    def test_putting_the_tile_back_does_not_become_a_library_scan(self):
        """Restoring one tile should not import every game found since."""
        self.assertIn("IMPORT_STEAM=0 IMPORT_HEROIC=0", self.install_text)

    def test_install_never_prunes(self):
        """A restore that removed entries would be a very unwelcome surprise."""
        self.assertNotIn("REMOVE_UNINSTALLED", self.code(self.install_text))

    def test_install_refuses_while_the_original_importer_is_present(self):
        """It rewrites apps.json wholesale, so the two cannot both be installed."""
        code = self.code(self.install_text)
        self.assertIn("destructive_installs", code)
        self.assertIn("exit 1", code)

    def test_uninstall_removes_the_tile_through_the_engine(self):
        """Editing apps.json directly would lose the marker and tombstone rules."""
        self.assertIn("api.mutate", self.uninstall_text)

    def test_uninstall_finds_the_tile_by_marker_not_by_name(self):
        """Renaming the tile is allowed, so the name identifies nothing."""
        self.assertIn('"launcher"', self.uninstall_text)
        self.assertIn('"apps-ui"', self.uninstall_text)

    def test_uninstall_removes_the_tile_before_the_files(self):
        """The other order leaves a tile pointing at a command that is gone."""
        self.assertLess(self.uninstall_text.index("api.mutate"),
                        self.uninstall_text.index('rm -rf "${DEST'))

    def test_uninstall_keeps_going_only_if_the_tile_really_went(self):
        self.assertIn("leaving the files in place", self.uninstall_text)

    def test_uninstall_keeps_the_copies_of_apps_json(self):
        """They are copies of your configuration, not of this program, and an
        uninstall is a moment you might want one back."""
        code = self.code(self.uninstall_text)
        self.assertIn("! -name backups", code)
        self.assertIn("--purge-backups", self.uninstall_text)

    def test_uninstall_leaves_everything_that_is_not_ours(self):
        """Removing this tool is not a reason to disturb the rest of apps.json."""
        self.assertIn("is untouched", self.uninstall_text)

    def test_neither_needs_root(self):
        for text in (self.install_text, self.uninstall_text):
            self.assertNotIn("sudo", text)


class LauncherArgumentsTest(unittest.TestCase):
    """Bare means "open a window"; anything else means "run the program".

    The installer tells people to run `sunshine-apps-ui --scan`, and that name
    is the kiosk launcher. Before this, the flag was ignored and a browser
    opened instead -- found on a VM, not here.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        # A stand-in for the module, so nothing real is started.
        self.ui = os.path.join(self.home, "share", "sunshine-apps-ui")
        os.makedirs(os.path.join(self.ui, "src", "sunshine_apps_ui"))
        with open(os.path.join(self.ui, "src", "sunshine_apps_ui",
                               "__init__.py"), "w"):
            pass
        with open(os.path.join(self.ui, "src", "sunshine_apps_ui",
                               "__main__.py"), "w") as handle:
            handle.write("import sys\nprint('ran with', sys.argv[1:])\n")
        self.env = dict(os.environ, HOME=self.home, BSM_UI_DIR=self.ui)

    def _run(self, *args):
        return subprocess.run(["bash", LAUNCHER, *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def test_an_argument_runs_the_program_rather_than_opening_a_window(self):
        result = self._run("--scan", "--dry-run")
        self.assertIn("ran with ['--scan', '--dry-run']", result.stdout)

    def test_help_reaches_the_program_too(self):
        self.assertIn("ran with ['--help']", self._run("--help").stdout)

    def test_the_bare_form_is_still_a_launch(self):
        """It must not fall through to the module and exit immediately."""
        with open(LAUNCHER, encoding="utf-8") as handle:
            text = handle.read()
        launch = text[text.index('if [[ $# -gt 0 ]]'):]
        self.assertIn("flatpak run", launch)


class BrowserChoiceTest(unittest.TestCase):
    """Which browser it opens, on machines that are not Bazzite.

    Only Bazzite necessarily has Chrome as a flatpak. Every other distribution
    Sunshine ships packages for installs browsers natively, and trying only
    flatpak meant falling through to xdg-open and losing the window this waits
    on -- which is what tells it when to shut the server down.
    """

    def setUp(self):
        with open(LAUNCHER, encoding="utf-8") as handle:
            self.text = handle.read()

    def test_flatpak_is_tried_first(self):
        """On an immutable system it is the one that is actually installed."""
        self.assertLess(self.text.index("launch_flatpak"),
                        self.text.index("launch_chromium"))

    def test_natively_installed_browsers_are_tried_too(self):
        for binary in ("google-chrome", "chromium", "brave-browser",
                       "vivaldi-stable"):
            self.assertIn(binary, self.text)

    def test_firefox_is_a_fallback_rather_than_a_peer(self):
        """--kiosk has no equivalent of --app: it takes the screen rather than
        giving us a window."""
        self.assertLess(self.text.index("launch_chromium"),
                        self.text.index("launch_firefox"))

    def test_a_window_is_still_found_when_it_is_firefox(self):
        """The teardown matches on the profile, and firefox spells it its own way."""
        self.assertIn("--profile ", self.text.split("PROFILE_MATCH=")[1][:120])

    def test_no_browser_at_all_says_so_and_keeps_serving(self):
        tail = self.text[self.text.index("No browser found."):]
        self.assertIn("$URL", tail)
        self.assertIn('wait "$SERVER"', tail)

    def test_every_launcher_records_the_pid_it_started(self):
        """Without it there is nothing to wait on, and the server exits at once."""
        for function in ("launch_flatpak", "launch_chromium", "launch_firefox"):
            body = self.text.split(f"{function}() {{", 1)[1].split("}", 1)[0]
            self.assertIn("BROWSER_PID=$!", body, function)


class CredentialScriptTest(unittest.TestCase):
    """Capturing a secret without it reaching argv, ps or shell history."""

    def setUp(self):
        self.scripts = {
            name: os.path.join(ROOT, "scripts", name)
            for name in ("set-sgdb-key", "set-sunshine-credentials")
        }
        self.text = {name: open(path, encoding="utf-8").read()
                     for name, path in self.scripts.items()}

    def test_both_are_valid_shell_and_executable(self):
        for name, path in self.scripts.items():
            with self.subTest(script=name):
                self.assertEqual(subprocess.run(["bash", "-n", path]).returncode, 0)
                self.assertTrue(os.access(path, os.X_OK))

    def test_the_secret_is_read_without_echo(self):
        for name, text in self.text.items():
            with self.subTest(script=name):
                self.assertIn("read -rs", text)

    def test_the_secret_never_becomes_an_argument(self):
        """argv is visible in ps and lands in history."""
        for name, text in self.text.items():
            with self.subTest(script=name):
                self.assertNotIn("--sgdb-key ", text)
                self.assertNotIn("--password ", text)

    def test_the_key_goes_to_the_manager_on_stdin(self):
        self.assertIn("--save-sgdb-key", self.text["set-sgdb-key"])
        self.assertIn("printf '%s\\n' \"$SGDB_KEY\" |", self.text["set-sgdb-key"])

    def test_it_no_longer_looks_for_the_old_importer(self):
        """That program is gone; asking for it would just fail confusingly."""
        self.assertNotIn("sunshine-import", self.text["set-sgdb-key"])
        self.assertNotIn("bsm-test-import", self.text["set-sgdb-key"])

    def test_nothing_is_written_when_the_key_is_refused(self):
        self.assertIn("Nothing was written", self.text["set-sgdb-key"])
