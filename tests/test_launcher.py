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
        # stop_previous() ends the server named in the record before it scans
        # for one, and the record lives in the state directory. Without a
        # state directory of its own this test reads whatever the machine
        # running it happens to have: on the Ubuntu and Arch VMs a record left
        # by an earlier session made _end fire twice, and the test failed
        # there while passing on the machine it was written on.
        import tempfile
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state, True)
        previous = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = state
        self.addCleanup(lambda: os.environ.__setitem__("XDG_STATE_HOME", previous)
                        if previous is not None
                        else os.environ.pop("XDG_STATE_HOME", None))

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
        self.assertEqual(found.call_args[0][0], launcher.SERVER_PATTERN)
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

    @unittest.skipIf(os.name == "nt",
                     "the POSIX branch; Windows stops a helper by its record")
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


@unittest.skipIf(os.name == "nt",
                 "the POSIX chain: flatpak, then native Chromium, then Firefox. "
                 "Windows has its own route and its own tests")
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


class ServerPatternTest(unittest.TestCase):
    """The pattern that finds a previous server must match the one we start.

    These stopped agreeing silently. Adding --serve to the command left the
    pattern matching nothing, so every relaunch quietly left the previous
    server running -- and the tests did not notice, because they tested the
    pattern and the command separately.
    """

    def test_the_pattern_matches_the_command_we_actually_run(self):
        import re
        command_line = " ".join(launcher.server_command())
        self.assertRegex(command_line, launcher.SERVER_PATTERN)

    def test_it_matches_whatever_port_was_chosen(self):
        for port in ("0", "47999", "8899"):
            self.assertRegex(" ".join(launcher.server_command(port)),
                             launcher.SERVER_PATTERN)

    def test_it_does_not_match_the_launcher_doing_the_matching(self):
        """The launcher carries no --port, and killing ourselves would be bad."""
        import re
        self.assertNotRegex("python3 -m sunshine_apps_ui",
                            launcher.SERVER_PATTERN)

    def test_it_does_not_match_an_unrelated_program(self):
        import re
        self.assertNotRegex("python3 -m something_else --port 0",
                            launcher.SERVER_PATTERN)


class LeavingDoesNotDisturbTheNextSessionTest(unittest.TestCase):
    """A relaunch ends this session. This session's cleanup must not then kill
    the window that replaced it.

    Found by running the old shell version and the new one side by side on the
    machine this actually runs on: the shell version won the race by being
    slower, and the port lost it.
    """

    def test_only_our_own_browser_is_ended(self):
        server = mock.Mock(poll=lambda: 0)
        # 11 was ours. 22 belongs to whatever replaced us.
        with mock.patch.object(launcher, "browsers", return_value=[11, 22]), \
             mock.patch.object(launcher, "_end") as ended:
            launcher._shut_down(server, None, ours=[11])
        ended.assert_called_once_with([11])

    def test_with_nothing_recorded_it_falls_back_to_what_is_there(self):
        """The old behaviour, for a path that never got as far as a window."""
        server = mock.Mock(poll=lambda: 0)
        with mock.patch.object(launcher, "browsers", return_value=[33]), \
             mock.patch.object(launcher, "_end") as ended:
            launcher._shut_down(server, None)
        ended.assert_called_once_with([33])

    def test_a_session_that_started_no_browser_kills_nothing_elses(self):
        server = mock.Mock(poll=lambda: 0)
        with mock.patch.object(launcher, "browsers", return_value=[44]), \
             mock.patch.object(launcher, "_end") as ended:
            launcher._shut_down(server, None, ours=[])
        ended.assert_called_once_with([])


class ChildCanImportUsTest(unittest.TestCase):
    """The server is a child process, and sys.path does not survive into one.

    The installed command puts the installed copy on sys.path and hands over.
    A server started without PYTHONPATH then answers "No module named
    sunshine_apps_ui", and the launcher reports only that the interface did not
    start -- which is true, and says nothing about why.

    Found by installing it and running it for real. Every test passed, because
    every test ran from a checkout with the path already set.
    """

    def test_the_child_is_told_where_to_import_us_from(self):
        environment = launcher.server_environment({})
        self.assertIn(launcher.package_path(),
                      environment["PYTHONPATH"].split(os.pathsep))

    def test_that_path_really_contains_the_package(self):
        self.assertTrue(os.path.isdir(
            os.path.join(launcher.package_path(), "sunshine_apps_ui")))

    def test_an_existing_pythonpath_is_kept_rather_than_replaced(self):
        environment = launcher.server_environment({"PYTHONPATH": "/somewhere/else"})
        parts = environment["PYTHONPATH"].split(os.pathsep)
        self.assertIn("/somewhere/else", parts)
        self.assertIn(launcher.package_path(), parts)

    def test_ours_comes_first(self):
        environment = launcher.server_environment({"PYTHONPATH": "/somewhere/else"})
        self.assertEqual(environment["PYTHONPATH"].split(os.pathsep)[0],
                         launcher.package_path())

    def test_it_is_not_added_twice(self):
        once = launcher.server_environment({"PYTHONPATH": launcher.package_path()})
        self.assertEqual(once["PYTHONPATH"].split(os.pathsep).count(
            launcher.package_path()), 1)

    def test_the_child_is_told_when_it_is_being_watched_through_a_stream(self):
        """Sunshine puts its own variables in the environment of what it starts."""
        with mock.patch.dict(os.environ, {"SUNSHINE_APP_ID": "3"}):
            self.assertEqual(
                launcher.server_environment({})["BSM_UI_VIA_SUNSHINE"], "1")

    def test_and_told_when_it_is_not(self):
        """Opened at the machine, nothing is being interrupted by applying a
        change -- and this used to claim otherwise, because it was asserted
        rather than asked. The maintainer's report, 2026-09-17."""
        for name in ("SUNSHINE_APP_ID", "SUNSHINE_CLIENT_NAME", "SUNSHINE_APP_NAME"):
            os.environ.pop(name, None)
        self.assertEqual(
            launcher.server_environment({})["BSM_UI_VIA_SUNSHINE"], "0")

    def test_the_server_starts_from_a_bare_interpreter(self):
        """The real check: spawn it the way the launcher does, with nothing
        else on the path, and see whether it can import itself."""
        import subprocess
        result = subprocess.run(
            launcher.server_command() + ["--help"],
            env={"PATH": os.environ.get("PATH", ""),
                 **{k: v for k, v in launcher.server_environment({}).items()
                    if k in ("PYTHONPATH", "BSM_UI_VIA_SUNSHINE")}},
            capture_output=True, text=True, timeout=60)
        self.assertNotIn("No module named", result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr[:400])


class ServerRecordTest(unittest.TestCase):
    """The previous run's server, ended without hunting for it.

    Finding it by enumerating every process costs several seconds on Windows,
    on every launch, usually to discover there is not one. The maintainer measured the
    result as "10 or more seconds" before the window appeared.
    """

    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state, True)
        self._previous = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state
        self.ended = []
        patched = mock.patch.object(launcher, "_end", self.ended.append)
        patched.start()
        self.addCleanup(patched.stop)

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._previous

    def test_the_server_is_written_down_when_it_starts(self):
        class Process:
            pid = 4242
        launcher.remember_server(Process())
        written = open(launcher._server_record_path()).read().splitlines()
        self.assertEqual(int(written[0]), 4242)
        self.assertTrue(written[1])

    def test_no_record_means_nothing_to_stop(self):
        self.assertFalse(launcher._stop_recorded_server())

    def test_a_damaged_record_is_not_an_error(self):
        os.makedirs(os.path.dirname(launcher._server_record_path()), exist_ok=True)
        with open(launcher._server_record_path(), "w") as handle:
            handle.write("nonsense")
        self.assertFalse(launcher._stop_recorded_server())

    @unittest.skipIf(os.name == "nt", "the POSIX path ends it without checking the image")
    def test_a_recorded_server_is_ended(self):
        class Process:
            pid = 4242
        launcher.remember_server(Process())
        self.assertTrue(launcher._stop_recorded_server())
        self.assertEqual(self.ended, [[4242]])


class NoConsoleStreamsTest(unittest.TestCase):
    """Started by pythonw, a process has no stdout and no stderr at all.

    They are None rather than closed, so the first print() raises
    AttributeError and the program dies before doing anything. That is what
    happened when the Start menu shortcut was pointed at pythonw: the shortcut
    ran, no window appeared, and nothing was left behind to say why.
    """

    def setUp(self):
        self.real_out, self.real_err = sys.stdout, sys.stderr
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state, True)
        self._previous = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state

    def tearDown(self):
        sys.stdout, sys.stderr = self.real_out, self.real_err
        if self._previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._previous

    def test_printing_works_after_it_runs(self):
        from sunshine_apps_ui.__main__ import _ensure_streams
        sys.stdout = None
        sys.stderr = None
        _ensure_streams()
        print("this must not raise")
        print("nor this", file=sys.stderr)
        self.assertIsNotNone(sys.stdout)
        self.assertIsNotNone(sys.stderr)

    def test_what_is_written_goes_somewhere_readable(self):
        from sunshine_apps_ui.__main__ import _ensure_streams
        from sunshine_apps_ui import places
        sys.stdout = None
        sys.stderr = None
        _ensure_streams()
        print("a line worth keeping", file=sys.stderr)
        sys.stderr.flush()
        written = open(os.path.join(places.state_dir(), "launcher.log")).read()
        self.assertIn("a line worth keeping", written)

    @unittest.skipIf(os.name == "nt", "POSIX modes; Windows is an ACL")
    def test_that_file_is_private_because_it_carries_the_url(self):
        from sunshine_apps_ui.__main__ import _ensure_streams
        from sunshine_apps_ui import places
        sys.stdout = None
        sys.stderr = None
        _ensure_streams()
        sys.stderr.flush()
        import stat as stat_module
        mode = os.stat(os.path.join(places.state_dir(), "launcher.log")).st_mode
        self.assertEqual(stat_module.S_IMODE(mode), 0o600)

    def test_a_real_console_is_left_alone(self):
        from sunshine_apps_ui.__main__ import _ensure_streams
        before_out, before_err = sys.stdout, sys.stderr
        _ensure_streams()
        self.assertIs(sys.stdout, before_out)
        self.assertIs(sys.stderr, before_err)


class ImportsSurviveWithoutStreamsTest(unittest.TestCase):
    """Nothing may touch stdout or stderr while being imported.

    pythonw.exe gives a process neither, and core.utils asked
    sys.stderr.isatty() at import time -- so the whole program died with
    AttributeError before main(). From the outside: the Start menu shortcut did
    nothing whatsoever and left nothing behind to say why. Found on the rig by
    writing a probe to a file, because there was no stderr to read.
    """

    def test_the_package_imports_with_both_streams_taken_away(self):
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import sys\n"
            "sys.stdout = None\n"
            "sys.stderr = None\n"
            "import sunshine_apps_ui\n"
            "import sunshine_apps_ui.__main__\n"
            "from sunshine_apps_ui.core import utils\n"
            "utils.log('this must not raise either')\n"
            "with open(r'%s', 'w') as handle:\n"
            "    handle.write('survived')\n"
        )
        marker = os.path.join(tempfile.mkdtemp(), "marker")
        environment = dict(os.environ, PYTHONPATH=os.path.join(here, "src"),
                           XDG_STATE_HOME=tempfile.mkdtemp())
        result = subprocess.run([sys.executable, "-c", code % marker.replace("\\", "\\\\")],
                                capture_output=True, text=True, env=environment)
        self.assertTrue(os.path.exists(marker),
                        f"import died without streams:\n{result.stderr}")

    def test_colour_is_off_when_there_is_no_terminal_to_colour(self):
        from sunshine_apps_ui.core import utils
        real = sys.stderr
        try:
            sys.stderr = None
            self.assertFalse(utils._stderr_is_a_terminal())
        finally:
            sys.stderr = real


class WindowFirstTest(unittest.TestCase):
    """The window opens before the server, so something appears at once.

    The maintainer: "it needs to open nearly instantly, even if just to show a spinning
    please wait." Most of the wait is the browser starting, which happens
    whatever we do -- so the browser starts first, on a page that spins, and
    the server comes up beside it.
    """

    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state, True)
        self._previous = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._previous

    def test_a_port_is_chosen_before_anything_binds_it(self):
        port = launcher.free_port()
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)
        # And it really is free: something else can take it right now.
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))

    def test_the_starting_page_carries_the_url_it_will_go_to(self):
        url = "http://127.0.0.1:41234/?token=abc"
        path = launcher.write_starting_page(url)
        page = open(path, encoding="utf-8").read()
        self.assertIn(url, page)
        self.assertIn("Starting the app manager", page)

    def test_it_says_something_rather_than_nothing_if_the_server_never_comes(self):
        page = open(launcher.write_starting_page("http://127.0.0.1:1/?token=x"),
                    encoding="utf-8").read()
        self.assertIn("did not start", page)

    def test_the_token_reaches_the_server_in_a_file_not_an_argument(self):
        """argv is readable by every process on the machine."""
        command = launcher.server_command("41234", "/state/session-token")
        self.assertIn("--token-file", command)
        self.assertIn("/state/session-token", command)
        self.assertFalse(any("token=" in part for part in command))

    def test_a_local_page_is_handed_over_as_a_file_url(self):
        as_url = launcher._as_url(os.path.join(self.state, "starting.html"))
        self.assertTrue(as_url.startswith("file:"))
        self.assertIn("starting.html", as_url)


def path_of(url):
    """The path a file: URL names, however this Python spelled it.

    Python 3.14's pathname2url gives "///tmp/x" where 3.12 gave "/tmp/x", so
    the URL is "file:///tmp/x" or "file:/tmp/x". Both are right. #39.
    """
    from urllib.parse import urlsplit
    from urllib.request import url2pathname
    parts = urlsplit(url)
    assert parts.scheme == "file", url
    return url2pathname(parts.path)


class PathOfTest(unittest.TestCase):
    def test_both_spellings_name_the_same_file(self):
        self.assertEqual(path_of("file:/tmp/a%20b.html"), "/tmp/a b.html")
        self.assertEqual(path_of("file:///tmp/a%20b.html"), "/tmp/a b.html")

    def test_and_so_does_whatever_as_url_gives_here(self):
        path = os.path.abspath(os.path.join("somewhere", "a b.html"))
        self.assertEqual(path_of(launcher._as_url(path)), path)


@unittest.skipIf(os.name == "nt", "Flatpak is Linux")
class FlatpakSandboxTest(unittest.TestCase):
    """A Flatpak browser sees neither our state directory nor our profile.

    Found on a Bazzite VM, 2026-09-25: Chrome sat on ERR_FILE_NOT_FOUND for the
    starting page (#34), and stock Bazzite's only browser, Firefox as a
    Flatpak, was never found at all (#33).
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.runtime = os.path.join(self.tmp, "run")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.runtime)
        os.makedirs(self.home)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.runtime,
                                           "HOME": self.home})
        env.start()
        self.addCleanup(env.stop)
        self.page = os.path.join(self.tmp, "state", "starting.html")
        os.makedirs(os.path.dirname(self.page))
        with open(self.page, "w", encoding="utf-8") as handle:
            handle.write("<p>Starting the app manager...</p>")

        self.spawned = []

        def spawn(command):
            self.spawned.append(command)
            return mock.Mock(poll=lambda: None, pid=4242)

        patched = mock.patch.object(launcher, "_spawn", spawn)
        patched.start()
        self.addCleanup(patched.stop)

    def open_with(self, apps, native=None):
        with mock.patch.object(launcher, "_flatpak_installed", lambda app: app in apps), \
             mock.patch.object(launcher.shutil, "which",
                               lambda b: native if b in ("firefox",) and native else None):
            return launcher.open_browser(self.page, "/state/browser-profile",
                                         as_file=True, own_window=False)

    def argument(self, prefix):
        return next(a for a in self.spawned[0] if a.startswith(prefix))

    def page_of(self, prefix):
        return path_of(self.argument(prefix)[len(prefix):])

    def test_flatpak_chrome_is_given_a_page_inside_its_sandbox(self):
        self.open_with({"com.google.Chrome"})
        page = self.page_of("--app=")
        self.assertTrue(page.startswith(
            os.path.join(self.runtime, "app", "com.google.Chrome")), page)
        self.assertEqual(open(page, encoding="utf-8").read(),
                         open(self.page, encoding="utf-8").read())

    def test_that_copy_is_this_users_alone(self):
        """It carries the token, as the original does."""
        self.open_with({"com.google.Chrome"})
        page = self.page_of("--app=")
        self.assertEqual(os.stat(page).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(page)).st_mode & 0o777, 0o700)

    def test_the_token_is_not_put_on_the_command_line(self):
        """A data: URL would have needed no file, and would have done this."""
        with open(self.page, "w", encoding="utf-8") as handle:
            handle.write("http://127.0.0.1:1/?token=secret")
        self.open_with({"com.google.Chrome"})
        self.assertFalse(any("secret" in part for part in self.spawned[0]))

    def test_flatpak_chrome_gets_a_profile_it_can_write(self):
        self.open_with({"com.google.Chrome"})
        profile = self.argument("--user-data-dir=")[len("--user-data-dir="):]
        self.assertTrue(profile.startswith(
            os.path.join(self.home, ".var", "app", "com.google.Chrome")), profile)
        self.assertTrue(os.path.isdir(profile))

    def test_and_that_profile_is_still_recognised_as_ours(self):
        """The teardown and the next launch find the browser by this pattern."""
        self.open_with({"com.google.Chrome"})
        import re
        self.assertTrue(re.search(launcher.PROFILE_PATTERN, " ".join(self.spawned[0])))

    def test_stock_bazzites_firefox_is_found(self):
        process, how = self.open_with({"org.mozilla.firefox"})
        self.assertIsNotNone(process)
        self.assertEqual(how, "flatpak org.mozilla.firefox")
        command = self.spawned[0]
        self.assertEqual(command[:3], ["flatpak", "run", "org.mozilla.firefox"])
        self.assertIn("--kiosk", command)
        profile = command[command.index("--profile") + 1]
        self.assertTrue(profile.startswith(
            os.path.join(self.home, ".var", "app", "org.mozilla.firefox")), profile)
        self.assertTrue(path_of(command[-1]).startswith(
            os.path.join(self.runtime, "app", "org.mozilla.firefox")), command[-1])

    def test_a_chromium_flatpak_still_comes_before_firefox(self):
        _, how = self.open_with({"org.mozilla.firefox", "com.google.Chrome"})
        self.assertEqual(how, "flatpak com.google.Chrome")

    def test_a_native_firefox_comes_before_the_flatpak_one(self):
        _, how = self.open_with({"org.mozilla.firefox"}, native="/usr/bin/firefox")
        self.assertEqual(how, "firefox")

    def test_a_url_rather_than_a_page_is_passed_straight_through(self):
        with mock.patch.object(launcher, "_flatpak_installed",
                               lambda app: app == "com.google.Chrome"), \
             mock.patch.object(launcher.shutil, "which", return_value=None):
            launcher.open_browser("http://127.0.0.1:1/", "/p")
        self.assertIn("--app=http://127.0.0.1:1/", self.spawned[0])


@unittest.skipIf(os.name == "nt", "snaps are Linux")
class SnapBrowserTest(unittest.TestCase):
    """A snap browser cannot reach anything under ~/.local either. #36.

    Found on stock Ubuntu 24.04, 26.04 and 26.10, 2026-09-26: Firefox is a
    snap there, reached through /usr/bin/firefox, a shell script. Given a
    profile in our state directory it could not lock it and said "Firefox is
    already running, but is not responding".
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.snap_bin = os.path.join(self.tmp, "snap", "bin")
        self.usr_bin = os.path.join(self.tmp, "usr", "bin")
        for directory in (self.home, self.snap_bin, self.usr_bin):
            os.makedirs(directory)
        env = mock.patch.dict(os.environ, {"HOME": self.home})
        env.start()
        self.addCleanup(env.stop)
        patched = mock.patch.object(launcher, "SNAP_BIN", self.snap_bin)
        patched.start()
        self.addCleanup(patched.stop)

        self.page = os.path.join(self.tmp, "state", "starting.html")
        os.makedirs(os.path.dirname(self.page))
        with open(self.page, "w", encoding="utf-8") as handle:
            handle.write("<p>Starting the app manager...</p>")

        self.spawned = []

        def spawn(command):
            self.spawned.append(command)
            return mock.Mock(poll=lambda: None, pid=4242)

        patched = mock.patch.object(launcher, "_spawn", spawn)
        patched.start()
        self.addCleanup(patched.stop)

    def snap(self, name):
        """A snap as snapd installs it: /snap/bin/<name>."""
        path = os.path.join(self.snap_bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")
        return path

    def wrapper(self, name, snap):
        """Ubuntu's transitional script, as /usr/bin/firefox is."""
        path = os.path.join(self.usr_bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n"
                         f"if ! [ -x {self.snap_bin}/{snap} ]; then\n"
                         "    echo 'requires the snap' >&2; exit 1\nfi\n"
                         f"exec {self.snap_bin}/{snap} \"$@\"\n")
        return path

    def native(self, name):
        path = os.path.join(self.usr_bin, name)
        with open(path, "wb") as handle:
            handle.write(b"\x7fELF\x02\x01\x01")
        return path

    def open_with(self, found, target=None, as_file=True):
        with mock.patch.object(launcher, "_flatpak_installed", lambda app: False), \
             mock.patch.object(launcher.shutil, "which", lambda b: found.get(b)):
            return launcher.open_browser(target or self.page, "/state/browser-profile",
                                         as_file=as_file, own_window=False)

    def common(self, name):
        return os.path.join(self.home, "snap", name, "common", "sunshine-apps-ui")

    def test_ubuntus_firefox_is_run_as_the_snap_itself(self):
        """Not through the wrapper, which edits the user's settings on its way."""
        self.snap("firefox")
        _, how = self.open_with({"firefox": self.wrapper("firefox", "firefox")})
        self.assertEqual(how, "firefox")
        self.assertEqual(self.spawned[0][0], os.path.join(self.snap_bin, "firefox"))

    def test_its_profile_is_somewhere_it_can_write(self):
        self.snap("firefox")
        self.open_with({"firefox": self.wrapper("firefox", "firefox")})
        command = self.spawned[0]
        profile = command[command.index("--profile") + 1]
        self.assertEqual(profile, os.path.join(self.common("firefox"), "browser-profile"))
        self.assertTrue(os.path.isfile(os.path.join(profile, "user.js")))

    def test_and_that_profile_is_still_recognised_as_ours(self):
        import re
        self.snap("firefox")
        self.open_with({"firefox": self.wrapper("firefox", "firefox")})
        self.assertTrue(re.search(launcher.PROFILE_PATTERN, " ".join(self.spawned[0])))

    def test_its_page_is_somewhere_it_can_read_and_nobody_else_can(self):
        self.snap("firefox")
        self.open_with({"firefox": self.wrapper("firefox", "firefox")})
        page = path_of(self.spawned[0][-1])
        self.assertEqual(os.path.dirname(page), self.common("firefox"))
        self.assertEqual(open(page, encoding="utf-8").read(),
                         open(self.page, encoding="utf-8").read())
        self.assertEqual(os.stat(page).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(page)).st_mode & 0o777, 0o700)

    def test_a_chromium_snap_found_directly_is_treated_the_same(self):
        self.snap("chromium")
        self.open_with({"chromium": os.path.join(self.snap_bin, "chromium")})
        command = self.spawned[0]
        profile = next(a for a in command if a.startswith("--user-data-dir="))
        self.assertEqual(profile[len("--user-data-dir="):],
                         os.path.join(self.common("chromium"), "browser-profile"))
        page = path_of(next(a for a in command if a.startswith("--app="))[len("--app="):])
        self.assertEqual(os.path.dirname(page), self.common("chromium"))

    def test_ubuntus_chromium_wrapper_names_a_different_snap(self):
        self.snap("chromium")
        self.open_with({"chromium-browser": self.wrapper("chromium-browser", "chromium")})
        self.assertEqual(self.spawned[0][0], os.path.join(self.snap_bin, "chromium"))

    def test_a_native_firefox_is_left_as_it_was(self):
        path = self.native("firefox")
        self.open_with({"firefox": path})
        command = self.spawned[0]
        self.assertEqual(command[0], path)
        self.assertEqual(command[command.index("--profile") + 1], "/state/browser-profile")
        self.assertEqual(path_of(command[-1]), self.page)

    def test_a_script_that_is_not_about_a_snap_is_not_one(self):
        path = os.path.join(self.usr_bin, "firefox")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexec /opt/firefox/firefox \"$@\"\n")
        self.assertEqual(launcher._snap_name(path), "")

    def test_a_wrapper_whose_snap_is_not_installed_is_not_one(self):
        """The wrapper stays when the snap is removed, and says so if run."""
        self.assertEqual(launcher._snap_name(self.wrapper("firefox", "firefox")), "")

    def test_a_url_rather_than_a_page_is_passed_straight_through(self):
        self.snap("firefox")
        self.open_with({"firefox": self.wrapper("firefox", "firefox")},
                       target="http://127.0.0.1:1/", as_file=False)
        self.assertEqual(self.spawned[0][-1], "http://127.0.0.1:1/")


class AWindowThatDiesTest(unittest.TestCase):
    """Our window going before it showed anything is not the user closing it. #40.

    Measured on Ubuntu 24.04 with the sandbox check forced wrong: the window
    aborted at once, the crash reporter held its process for ten seconds, and
    the launcher -- which had counted it as up the moment it existed -- then
    took everything down. A browser that worked sat unused.
    """

    PORT = 45678

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.opened = []
        self.shut = []
        self.server = mock.Mock(poll=mock.Mock(return_value=None))
        for name, value in (
                ("_leave_on_signal", lambda: None),
                ("stop_previous", lambda: None),
                ("free_port", lambda: self.PORT),
                ("write_starting_page", lambda url: os.path.join(self.tmp, "starting.html")),
                ("remember_server", lambda server: None),
                ("server_environment", lambda: {}),
                ("_ours", lambda browser, how: []),
                ("_shut_down", lambda *a: self.shut.append(a))):
            patched = mock.patch.object(launcher, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        for target, value in ((launcher.subprocess, "Popen"), (launcher.time, "sleep")):
            patched = mock.patch.object(target, value,
                                        (lambda *a, **k: self.server) if value == "Popen"
                                        else (lambda s: None))
            patched.start()
            self.addCleanup(patched.stop)

    def run_with(self, windows, up, shown=False):
        """*windows*: what open_browser returns, in turn. *up*: browser_is_up, in turn."""
        answers = iter(windows)

        def open_browser(page, profile, as_file=False, own_window=True):
            self.opened.append(own_window)
            return next(answers)

        states = iter(up)
        if shown:
            from sunshine_apps_ui import places
            os.makedirs(os.path.dirname(places.shown_marker()), exist_ok=True)
        with mock.patch.object(launcher, "open_browser", open_browser), \
             mock.patch.object(launcher, "browser_is_up", lambda p: next(states, False)), \
             mock.patch.object(launcher, "window_was_shown", lambda port: shown):
            return launcher.launch([])

    def window(self, code=None):
        return mock.Mock(poll=mock.Mock(return_value=code), returncode=code)

    def test_a_window_that_went_unseen_gets_a_browser(self):
        self.run_with([(self.window(-6), launcher.OUR_WINDOW),
                       (self.window(), "firefox")],
                      up=[True, False, True, True, False])
        self.assertEqual(self.opened, [True, False])

    def test_a_window_that_was_seen_and_closed_is_left_closed(self):
        self.run_with([(self.window(0), launcher.OUR_WINDOW)],
                      up=[True, False], shown=True)
        self.assertEqual(self.opened, [True])

    def test_a_server_that_stopped_on_its_own_is_not_a_failed_window(self):
        """It stops by itself after applying; the window then closing is right."""
        self.server.poll.return_value = 0
        self.run_with([(self.window(0), launcher.OUR_WINDOW)], up=[True, True])
        self.assertEqual(self.opened, [True])

    def test_a_browser_going_is_never_taken_for_our_window(self):
        self.run_with([(self.window(0), "firefox")], up=[True, False])
        self.assertEqual(self.opened, [True])

    def test_it_falls_back_once_only(self):
        """Windows offers our window first whatever it is asked."""
        self.run_with([(self.window(1), launcher.OUR_WINDOW),
                       (self.window(1), launcher.OUR_WINDOW)],
                      up=[True, False, True, False])
        self.assertEqual(self.opened, [True, False])

    def test_the_teardown_still_happens(self):
        self.run_with([(self.window(-6), launcher.OUR_WINDOW),
                       (self.window(), "firefox")],
                      up=[True, False, True, False])
        self.assertEqual(len(self.shut), 1)

    def test_an_earlier_sessions_marker_is_not_this_ones(self):
        from sunshine_apps_ui import places
        os.makedirs(os.path.dirname(places.shown_marker()), exist_ok=True)
        with open(places.shown_marker(), "w", encoding="utf-8") as handle:
            handle.write("1111")
        self.assertFalse(launcher.window_was_shown(self.PORT))
        self.assertTrue(launcher.window_was_shown(1111))

    def test_and_it_is_cleared_before_the_server_starts(self):
        from sunshine_apps_ui import places
        os.makedirs(os.path.dirname(places.shown_marker()), exist_ok=True)
        with open(places.shown_marker(), "w", encoding="utf-8") as handle:
            handle.write(str(self.PORT))
        self.run_with([(self.window(0), "firefox")], up=[True, False])
        self.assertFalse(os.path.exists(places.shown_marker()))


class RecordingOurBrowserTest(unittest.TestCase):
    """Which processes are ours is asked once the browser really exists. #35.

    `flatpak run` carries our profile on its own command line, so it matched
    before the browser did, and leaving ended only the wrapper.
    """

    WRAPPER = 100

    def browser(self, alive=True):
        return mock.Mock(pid=self.WRAPPER, poll=lambda: None if alive else 0)

    def test_a_flatpak_launch_waits_past_the_wrapper(self):
        answers = iter([[self.WRAPPER], [self.WRAPPER], [self.WRAPPER, 101, 102]])
        with mock.patch.object(launcher, "browsers", lambda: next(answers)), \
             mock.patch.object(launcher.time, "sleep"):
            ours = launcher._ours(self.browser(), "flatpak com.google.Chrome")
        self.assertEqual(ours, [self.WRAPPER, 101, 102])

    def test_anything_else_is_recorded_at_once(self):
        calls = []

        def browsers():
            calls.append(1)
            return [7]

        with mock.patch.object(launcher, "browsers", browsers):
            self.assertEqual(launcher._ours(self.browser(), "chromium"), [7])
        self.assertEqual(len(calls), 1)

    def test_a_browser_that_never_appears_is_not_waited_on_for_ever(self):
        with mock.patch.object(launcher, "browsers", lambda: [self.WRAPPER]), \
             mock.patch.object(launcher.time, "sleep"):
            ours = launcher._ours(self.browser(), "flatpak com.google.Chrome",
                                  timeout=0.05)
        self.assertEqual(ours, [self.WRAPPER])

    def test_a_wrapper_that_has_gone_is_not_waited_on(self):
        with mock.patch.object(launcher, "browsers", lambda: [self.WRAPPER]), \
             mock.patch.object(launcher.time, "sleep") as slept:
            launcher._ours(self.browser(alive=False), "flatpak org.mozilla.firefox")
        slept.assert_not_called()


class FirefoxProfileTest(unittest.TestCase):
    """A fresh Firefox profile greets you, and in --kiosk that is all you see."""

    def test_the_profile_is_told_not_to_greet(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = launcher._firefox_profile(os.path.join(tmp, "browser-profile"))
        text = open(os.path.join(path, "user.js"), encoding="utf-8").read()
        self.assertIn('user_pref("termsofuse.bypassNotification", true);', text)
        self.assertIn('user_pref("browser.aboutwelcome.enabled", false);', text)
        self.assertIn('user_pref("browser.startup.homepage_override.mstone", "ignore");', text)

    @unittest.skipIf(os.name == "nt", "Windows browsers are launched by winbrowser")
    def test_native_firefox_gets_it_too(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        # Native, whatever this machine's /usr/bin/firefox is: on Ubuntu it is
        # the snap's wrapper, and SnapBrowserTest is about that. #36.
        with mock.patch.object(launcher, "_spawn", return_value=mock.Mock()), \
             mock.patch.object(launcher, "_flatpak_installed", return_value=False), \
             mock.patch.object(launcher, "_snap_name", return_value=""), \
             mock.patch.object(launcher.shutil, "which",
                               lambda b: "/usr/bin/firefox" if b == "firefox" else None):
            launcher.open_browser("http://x/", tmp)
        self.assertTrue(os.path.exists(os.path.join(tmp, "user.js")))


@unittest.skipIf(os.name == "nt", "Windows browsers are launched by winbrowser, with DPAPI")
class KeyringTest(unittest.TestCase):
    """Chrome waits for ever on a keyring nothing has unlocked. #34."""

    def launched(self, flatpak):
        spawned = []
        with mock.patch.object(launcher, "_spawn",
                               lambda command, **k: spawned.append(command) or mock.Mock()), \
             mock.patch.object(launcher, "_flatpak_installed",
                               lambda app: flatpak and app == "com.google.Chrome"), \
             mock.patch.object(launcher.shutil, "which",
                               lambda b: "/usr/bin/chromium" if b == "chromium" else None):
            launcher.open_browser("http://x/", tempfile.gettempdir())
        return spawned[0]

    def test_a_flatpak_chrome_is_kept_away_from_the_keyring(self):
        self.assertIn("--password-store=basic", self.launched(flatpak=True))

    def test_so_is_a_native_one(self):
        self.assertIn("--password-store=basic", self.launched(flatpak=False))
