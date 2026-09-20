# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening a window on Windows.

What is tested here is the part that is decisions rather than Win32: which flag
each browser gets, which browser is preferred, and that a fresh Firefox profile
is seeded before it can open onboarding instead of the page. The job object and
the de-elevated helper are Win32 and are exercised on the rig (issue #15), where
they were measured in the first place.

Each of these encodes something that was measured and contradicts the obvious
implementation, so they are worth keeping even though they look like they are
testing a lookup table.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import winbrowser  # noqa: E402


class BrowserFlagsTest(unittest.TestCase):
    URL = "http://127.0.0.1:47999/?token=abc"
    PROFILE = r"C:\state\browser-profile"

    def command(self, name, kind):
        return winbrowser.Browser(name, rf"C:\{name}.exe", kind).command(self.URL, self.PROFILE)

    def test_edge_and_chrome_get_app_mode(self):
        for name in ("edge", "chrome"):
            command = self.command(name, "app")
            self.assertIn(f"--app={self.URL}", command)
            self.assertIn(f"--user-data-dir={self.PROFILE}", command)
            self.assertNotIn("--kiosk", command)

    def test_opera_gets_kiosk_because_it_ignores_app(self):
        """Measured: Opera accepts --app and opens an ordinary window anyway.

        Speed Dial, tabs, address bar, a "make Opera default" prompt, and our
        page never loaded. Accepting a flag and ignoring it is worse than
        rejecting it, because nothing reports a failure.
        """
        command = self.command("opera", "kiosk-chromium")
        self.assertIn("--kiosk", command)
        self.assertIn(self.URL, command)
        self.assertFalse(any(part.startswith("--app") for part in command))

    def test_firefox_gets_kiosk_and_a_profile_directory(self):
        command = self.command("firefox", "kiosk-firefox")
        self.assertIn("--kiosk", command)
        self.assertIn("--profile", command)
        self.assertIn(self.PROFILE, command)
        # --no-remote, or a Firefox already running takes the URL and this
        # process returns immediately, leaving nothing to wait on.
        self.assertIn("--no-remote", command)

    def test_the_url_is_always_present_exactly_once(self):
        for name, kind in (("edge", "app"), ("chrome", "app"),
                           ("opera", "kiosk-chromium"), ("firefox", "kiosk-firefox")):
            command = self.command(name, kind)
            appearances = [part for part in command if self.URL in part]
            self.assertEqual(len(appearances), 1, f"{name}: {command}")

    def test_chromium_family_is_not_one_case(self):
        """Opera is Chromium-family and needs a different flag from Chrome."""
        chrome = self.command("chrome", "app")
        opera = self.command("opera", "kiosk-chromium")
        self.assertNotEqual([p for p in chrome if p.startswith("--app") or p == "--kiosk"],
                            [p for p in opera if p.startswith("--app") or p == "--kiosk"])


class BrowserPreferenceTest(unittest.TestCase):
    def setUp(self):
        self.real_environ = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        # On a real Windows box the App Paths registry knows about the browsers
        # that are genuinely installed, which would answer a question this test
        # is not asking. Only what is placed below should be found.
        self.real_registered = winbrowser._registered
        winbrowser._registered = lambda executable: ""

    def tearDown(self):
        winbrowser._registered = self.real_registered
        os.environ.clear()
        os.environ.update(self.real_environ)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def place(self, *parts):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_edge_is_preferred_because_windows_always_has_it(self):
        os.environ["ProgramFiles(x86)"] = self.tmp
        os.environ["ProgramFiles"] = self.tmp
        os.environ["LOCALAPPDATA"] = self.tmp
        self.place("Microsoft", "Edge", "Application", "msedge.exe")
        self.place("Google", "Chrome", "Application", "chrome.exe")
        found = winbrowser.find_browsers()
        self.assertTrue(found)
        self.assertEqual(found[0].name, "edge")

    def test_a_browser_that_is_not_installed_is_not_offered(self):
        os.environ["ProgramFiles(x86)"] = self.tmp
        os.environ["ProgramFiles"] = self.tmp
        os.environ["LOCALAPPDATA"] = self.tmp
        self.place("Mozilla Firefox", "firefox.exe")
        names = [b.name for b in winbrowser.find_browsers()]
        self.assertEqual(names, ["firefox"])

    def test_each_found_browser_carries_its_own_kind(self):
        os.environ["ProgramFiles(x86)"] = self.tmp
        os.environ["ProgramFiles"] = self.tmp
        os.environ["LOCALAPPDATA"] = self.tmp
        self.place("Programs", "Opera", "opera.exe")
        self.place("Mozilla Firefox", "firefox.exe")
        kinds = {b.name: b.kind for b in winbrowser.find_browsers()}
        self.assertEqual(kinds["opera"], "kiosk-chromium")
        self.assertEqual(kinds["firefox"], "kiosk-firefox")


class FirefoxProfileTest(unittest.TestCase):
    """A fresh profile opens onboarding in kiosk mode, full screen, over the page."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.profile = os.path.join(self.tmp, "browser-profile")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seeding_writes_the_prefs_that_suppress_onboarding(self):
        winbrowser.seed_firefox_profile(self.profile)
        prefs = open(os.path.join(self.profile, "user.js")).read()
        for pref in ("browser.aboutwelcome.enabled",
                     "datareporting.policy.dataSubmissionPolicyBypassNotification",
                     "browser.startup.homepage_override.mstone"):
            self.assertIn(pref, prefs)

    def test_seeding_creates_the_directory_if_it_is_not_there(self):
        winbrowser.seed_firefox_profile(self.profile)
        self.assertTrue(os.path.isdir(self.profile))

    def test_seeding_an_unwritable_place_is_not_fatal(self):
        """Worst case the first launch shows onboarding once; it must not crash."""
        winbrowser.seed_firefox_profile(os.path.join(os.devnull, "nope"))


class HelperCommandTest(unittest.TestCase):
    def test_the_helper_is_this_program_pointed_at_a_request_file(self):
        command = winbrowser.helper_command(r"C:\state\browser-request.json")
        self.assertIn("--browser-helper", command)
        self.assertEqual(command[command.index("--browser-helper") + 1],
                         r"C:\state\browser-request.json")
        self.assertIn("sunshine_apps_ui", command)

    def test_the_request_keeps_the_token_out_of_the_command_line(self):
        """The URL carries the session token; argv is readable by every process."""
        where = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, where, True)
        path = winbrowser.write_request("http://127.0.0.1:1/?token=secret",
                                        r"C:\p", where)
        command = winbrowser.helper_command(path)
        self.assertFalse(any("secret" in part for part in command))
        written = json.load(open(path))
        self.assertEqual(written["url"], "http://127.0.0.1:1/?token=secret")
        self.assertEqual(written["profile"], r"C:\p")
        self.assertEqual(written["parent"], os.getpid())

    def test_the_request_file_is_read_once_and_deleted(self):
        where = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, where, True)
        path = winbrowser.write_request("http://127.0.0.1:1/?token=secret",
                                        r"C:\p", where)
        request = winbrowser._read_request(path)
        self.assertEqual(request["url"], "http://127.0.0.1:1/?token=secret")
        self.assertFalse(os.path.exists(path), "the token must not be left lying about")

    def test_a_malformed_payload_is_refused_rather_than_raising(self):
        self.assertEqual(winbrowser.helper_main("not json"), 2)



class WindowsRoutingTest(unittest.TestCase):
    """How the launcher chooses between holding the browser and handing it over.

    Unelevated, we hold it: we own the handle, and the job dies with us.
    Elevated, we must not -- our rights came from Sunshine so we could write
    apps.json, and a browser with those rights is a far bigger surface than the
    server is. A helper takes it at medium integrity instead.
    """

    def setUp(self):
        from sunshine_apps_ui import launcher, privilege
        self.launcher = launcher
        self.real_windows = launcher.WINDOWS
        self.real_elevated = privilege.is_elevated
        self.real_find = winbrowser.find_browsers
        self.real_start = winbrowser.start_browser
        self.real_helper = winbrowser.start_helper_de_elevated
        self.privilege = privilege
        launcher.WINDOWS = True
        winbrowser.find_browsers = lambda: [
            winbrowser.Browser("edge", r"C:\msedge.exe", "app")]
        self.helper_calls = []
        winbrowser.start_helper_de_elevated = lambda url, profile: (
            self.helper_calls.append((url, profile)) or True)
        winbrowser.start_browser = lambda url, profile, **kw: ("process", "edge", "job")

    def tearDown(self):
        self.launcher.WINDOWS = self.real_windows
        self.privilege.is_elevated = self.real_elevated
        winbrowser.find_browsers = self.real_find
        winbrowser.start_browser = self.real_start
        winbrowser.start_helper_de_elevated = self.real_helper
        self.launcher._JOB = None

    def test_unelevated_we_hold_the_browser_ourselves(self):
        self.privilege.is_elevated = lambda: False
        process, how = self.launcher.open_browser("http://x/", r"C:\p")
        self.assertEqual((process, how), ("process", "edge"))
        self.assertEqual(self.helper_calls, [])
        self.assertEqual(self.launcher._JOB, "job")

    def test_elevated_the_browser_goes_to_a_helper(self):
        self.privilege.is_elevated = lambda: True
        process, how = self.launcher.open_browser("http://x/", r"C:\p")
        self.assertIsNone(process)
        self.assertEqual(how, self.launcher._HELPER_HOLDS_IT)
        self.assertEqual(self.helper_calls, [("http://x/", r"C:\p")])

    def test_elevated_and_the_helper_fails_means_no_browser(self):
        """Refusing is right: running it as administrator is the thing to avoid."""
        self.privilege.is_elevated = lambda: True
        winbrowser.start_helper_de_elevated = lambda url, profile: False
        process, how = self.launcher.open_browser("http://x/", r"C:\p")
        self.assertIsNone(process)
        self.assertEqual(how, "")

    def test_no_browser_installed_is_reported_before_anything_is_started(self):
        self.privilege.is_elevated = lambda: False
        winbrowser.find_browsers = lambda: []
        process, how = self.launcher.open_browser("http://x/", r"C:\p")
        self.assertEqual((process, how), (None, ""))


class HelperLoopTest(unittest.TestCase):
    """The helper's waiting loop, which nothing else exercises.

    It exists because a refactor once deleted process_alive() and every test
    still passed: the only test that called helper_main returned early on a bad
    payload, so the loop was never entered. It took a NameError on the rig to
    find. These run the loop.
    """

    def setUp(self):
        self.real_start = winbrowser.start_browser
        self.real_has = winbrowser._job_has_processes
        self.real_showing = winbrowser.job_is_showing
        self.real_alive = winbrowser.process_alive

        class FakeJob:
            terminated = False

            def terminate(self):
                FakeJob.terminated = True

            def close(self):
                pass

        class FakeProcess:
            pid = 1234

        self.job = FakeJob
        winbrowser.start_browser = lambda url, profile, **kw: (FakeProcess(), "edge", FakeJob())

    def tearDown(self):
        winbrowser.start_browser = self.real_start
        winbrowser._job_has_processes = self.real_has
        winbrowser.job_is_showing = self.real_showing
        winbrowser.process_alive = self.real_alive

    def payload(self, parent):
        return json.dumps({"url": "http://x/", "profile": r"C:\p", "parent": parent})

    def showing(self, answers):
        """job_is_showing answers these in order, then repeats the last."""
        self.asked = []

        def ask(job):
            index = min(len(self.asked), len(answers) - 1)
            self.asked.append(answers[index])
            return answers[index]

        winbrowser.job_is_showing = ask

    def test_it_waits_for_the_window_to_appear(self):
        """A window is not on screen the instant its process exists.

        The helper used to ask once, immediately, and take down anything that
        was not already showing -- which no window could satisfy. Found on the
        rig on 2026-09-18: the launcher said "Opened with helper" and nothing
        ever appeared, with a window that puts itself on screen in 0.2 s.
        """
        self.showing([False] * 5 + [True, False])
        winbrowser._job_has_processes = lambda job: True
        winbrowser.process_alive = lambda pid: True
        self.assertEqual(winbrowser.helper_main(self.payload(4321)), 0)
        self.assertGreater(len(self.asked), 5,
                           "it gave up before the window could appear")
        self.assertTrue(self.job.terminated)

    def test_it_gives_up_when_the_window_never_comes(self):
        """But not by waiting the whole timeout: an empty job is an answer."""
        self.showing([False])
        winbrowser._job_has_processes = lambda job: False
        winbrowser.process_alive = lambda pid: True
        started = time.monotonic()
        self.assertEqual(winbrowser.helper_main(self.payload(4321)), 0)
        self.assertLess(time.monotonic() - started, 5.0,
                        "it sat through the whole appear timeout")
        self.assertTrue(self.job.terminated)

    def test_it_returns_when_the_browser_window_is_gone(self):
        self.showing([True, False])
        winbrowser._job_has_processes = lambda job: True
        winbrowser.process_alive = lambda pid: True
        self.assertEqual(winbrowser.helper_main(self.payload(4321)), 0)
        self.assertTrue(self.job.terminated, "the job must be torn down on the way out")

    def test_it_returns_when_the_launcher_is_gone(self):
        """Otherwise an elevated launcher that is killed leaves a browser nobody holds."""
        self.showing([True])
        winbrowser._job_has_processes = lambda job: True
        winbrowser.process_alive = lambda pid: False
        self.assertEqual(winbrowser.helper_main(self.payload(4321)), 0)

    def test_a_parent_of_zero_means_nobody_to_follow(self):
        """Not "the launcher is already gone", which is what a pid of 0 would say."""
        self.showing([True, False])
        winbrowser._job_has_processes = lambda job: True
        winbrowser.process_alive = lambda pid: self.fail("0 is not a pid to ask about")
        self.assertEqual(winbrowser.helper_main(self.payload(0)), 0)

    def test_a_browser_that_will_not_start_is_reported(self):
        winbrowser.start_browser = lambda url, profile, **kw: (None, "", None)
        self.assertEqual(winbrowser.helper_main(self.payload(0)), 1)


class UninstallTaskTest(unittest.TestCase):
    """The task the Windows launcher registers must not outlive the install."""

    def test_nothing_is_attempted_off_windows(self):
        from sunshine_apps_ui import installer
        if os.name == "nt":
            self.skipTest("this asserts the POSIX no-op")
        self.assertEqual(installer._remove_browser_task(), [])

    def test_it_asks_schtasks_for_the_name_the_launcher_registers(self):
        from sunshine_apps_ui import installer
        real_name, real_run = os.name, installer.subprocess.run
        calls = []

        class Result:
            returncode = 0

        try:
            os.name = "nt"
            installer.subprocess.run = lambda cmd, **kw: calls.append(cmd) or Result()
            messages = installer._remove_browser_task()
        finally:
            os.name = real_name
            installer.subprocess.run = real_run
        self.assertEqual(calls[0][:3], ["schtasks", "/delete", "/tn"])
        self.assertEqual(calls[0][3], winbrowser.TASK_NAME)
        self.assertTrue(messages)


class CheapLivenessTest(unittest.TestCase):
    """How the launcher asks whether the browser is still up.

    It used to enumerate every process on the machine through WMI, at 2.5-3.3
    seconds a call, in two loops whose sleeps were 0.5 and 1 second. That was
    most of the ten seconds it took to open, and all of the lag on closing.
    Both answers below are exact and cost nothing.
    """

    def setUp(self):
        from sunshine_apps_ui import launcher
        self.launcher = launcher
        self.real_windows = launcher.WINDOWS
        self.real_job = launcher._JOB
        self.real_browsers = launcher.browsers
        self.real_read = winbrowser.read_helper_pid
        self.real_alive = winbrowser.process_alive
        self.real_occupied = winbrowser.job_is_occupied
        self.real_showing = winbrowser.job_is_showing
        launcher.WINDOWS = True
        launcher.browsers = lambda: self.fail("the expensive path was taken")

    def tearDown(self):
        self.launcher.WINDOWS = self.real_windows
        self.launcher._JOB = self.real_job
        self.launcher.browsers = self.real_browsers
        winbrowser.read_helper_pid = self.real_read
        winbrowser.process_alive = self.real_alive
        winbrowser.job_is_occupied = self.real_occupied
        winbrowser.job_is_showing = self.real_showing

    def test_when_we_hold_the_job_the_window_is_what_is_asked_about(self):
        """Not "is anything still running": Edge leaves processes behind when
        its window closes, and waiting for those left the console open and the
        stream connected after the person had closed the window."""
        self.launcher._JOB = object()
        winbrowser.job_is_showing = lambda job: True
        self.assertTrue(self.launcher.browser_is_up(r"C:\p"))
        winbrowser.job_is_showing = lambda job: False
        self.assertFalse(self.launcher.browser_is_up(r"C:\p"))

    def test_when_a_helper_holds_it_the_helper_is_watched(self):
        self.launcher._JOB = None
        winbrowser.read_helper_pid = lambda profile: 4321
        winbrowser.process_alive = lambda pid: pid == 4321
        self.assertTrue(self.launcher.browser_is_up(r"C:\p"))
        winbrowser.process_alive = lambda pid: False
        self.assertFalse(self.launcher.browser_is_up(r"C:\p"))

    def test_the_expensive_path_is_the_last_resort_only(self):
        """Neither a job nor a helper: fall back, rather than answer wrongly."""
        self.launcher._JOB = None
        winbrowser.read_helper_pid = lambda profile: 0
        self.launcher.browsers = lambda: [111]
        self.assertTrue(self.launcher.browser_is_up(r"C:\p"))


class HelperRecordTest(unittest.TestCase):
    """The helper says who it is, so a later run can end it without hunting."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.profile = os.path.join(self.tmp, "browser-profile")
        os.makedirs(self.profile)

    def write(self, pid, image, started=0):
        with open(winbrowser.helper_pid_path(self.profile), "w", encoding="utf-8") as handle:
            handle.write(f"{pid}\n{image}\n{started}\n")

    def test_it_records_the_pid_what_is_running_and_when_it_started(self):
        """All three: a pid is not an identity, and neither is a pid plus an
        image when every process here is the same python.exe. A recycled number
        passed that weaker test on the rig and something innocent was ended."""
        self.write(1234, r"C:\x\python.exe", 133012345678901234)
        self.assertEqual(winbrowser.read_helper_record(self.profile),
                         (1234, r"C:\x\python.exe", 133012345678901234))
        self.assertEqual(winbrowser.read_helper_pid(self.profile), 1234)

    def test_no_record_is_not_an_error(self):
        self.assertEqual(winbrowser.read_helper_record(self.profile), (0, "", 0))
        self.assertEqual(winbrowser.read_helper_pid(self.profile), 0)

    def test_a_damaged_record_is_not_an_error(self):
        with open(winbrowser.helper_pid_path(self.profile), "w") as handle:
            handle.write("not a pid")
        self.assertEqual(winbrowser.read_helper_record(self.profile), (0, "", 0))

    def test_a_reused_pid_is_not_terminated(self):
        """This is not hypothetical: it happened on the rig, and the launcher
        ended something innocent and exited."""
        real = (winbrowser.process_alive, winbrowser.process_image,
                winbrowser.process_start_time)
        try:
            self.write(4321, r"C:\ours\python.exe", started=111)
            winbrowser.process_alive = lambda pid: True
            winbrowser.process_image = lambda pid: r"C:\ours\python.exe"
            # Same pid, same image, different process.
            winbrowser.process_start_time = lambda pid: 999
            self.assertFalse(winbrowser.stop_helper(self.profile))
        finally:
            (winbrowser.process_alive, winbrowser.process_image,
             winbrowser.process_start_time) = real

    def test_our_own_pid_is_never_ended(self):
        self.write(os.getpid(), r"C:\ours\python.exe", started=0)
        self.assertFalse(winbrowser.stop_helper(self.profile))

    def test_a_helper_that_is_gone_needs_no_stopping(self):
        real_alive = winbrowser.process_alive
        try:
            self.write(4321, r"C:\ours\python.exe", started=111)
            winbrowser.process_alive = lambda pid: False
            self.assertFalse(winbrowser.stop_helper(self.profile))
        finally:
            winbrowser.process_alive = real_alive


class WindowShapeTest(unittest.TestCase):
    """The maintainer's rule, 2026-09-17: fullscreen either way, border only at the machine.

    "on windows, fullscreen with the window border is fine, but from moonlight
    fullscreen no window border."
    """

    URL = "http://127.0.0.1:1/?token=x"
    PROFILE = r"C:\state\browser-profile"

    def command(self, name, kind, streamed):
        return winbrowser.Browser(name, rf"C:\{name}.exe", kind).command(
            self.URL, self.PROFILE, streamed=streamed)

    def test_streamed_chromium_is_fullscreen(self):
        for name in ("edge", "chrome"):
            command = self.command(name, "app", streamed=True)
            self.assertIn("--start-fullscreen", command)
            self.assertNotIn("--start-maximized", command)

    def test_local_chromium_keeps_its_frame(self):
        for name in ("edge", "chrome"):
            command = self.command(name, "app", streamed=False)
            self.assertIn("--start-maximized", command)
            self.assertNotIn("--start-fullscreen", command)

    def test_app_mode_is_used_either_way(self):
        """The page should never be framed by tabs and an address bar."""
        for streamed in (True, False):
            self.assertIn(f"--app={self.URL}", self.command("edge", "app", streamed))

    def test_streamed_firefox_and_opera_are_kiosk(self):
        for name, kind in (("firefox", "kiosk-firefox"), ("opera", "kiosk-chromium")):
            self.assertIn("--kiosk", self.command(name, kind, streamed=True))

    def test_local_firefox_and_opera_are_not(self):
        """Kiosk has no way out, which is wrong on a desktop."""
        for name, kind in (("firefox", "kiosk-firefox"), ("opera", "kiosk-chromium")):
            command = self.command(name, kind, streamed=False)
            self.assertNotIn("--kiosk", command)
            self.assertIn(self.URL, command)


class LaunchedBySunshineTest(unittest.TestCase):
    """Whether Sunshine started us, asked rather than asserted."""

    def setUp(self):
        self.real_environ = dict(os.environ)
        for name in ("SUNSHINE_APP_ID", "SUNSHINE_CLIENT_NAME", "SUNSHINE_APP_NAME"):
            os.environ.pop(name, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.real_environ)

    def test_sunshine_says_so_in_the_environment(self):
        for name in ("SUNSHINE_APP_ID", "SUNSHINE_CLIENT_NAME", "SUNSHINE_APP_NAME"):
            os.environ[name] = "something"
            self.assertTrue(winbrowser.launched_by_sunshine(), name)
            os.environ.pop(name)

    def test_opened_at_the_machine_it_says_nothing(self):
        self.assertFalse(winbrowser.launched_by_sunshine())

    def test_an_empty_value_does_not_count(self):
        os.environ["SUNSHINE_APP_ID"] = ""
        self.assertFalse(winbrowser.launched_by_sunshine())

if __name__ == "__main__":
    unittest.main()
