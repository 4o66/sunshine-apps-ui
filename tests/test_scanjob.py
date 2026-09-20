# SPDX-License-Identifier: GPL-3.0-or-later
"""Showing that a scan is running, which it never did.

A scan takes about fifty seconds on a real library -- almost all of it one
importer reading fourteen thousand files -- and it used to run on the request
thread, so the interface returned nothing at all until it was over. The maintainer,
having deleted two entries and pressed Rescan: "Scan runs with no visible
indicator, we need some sort of indicator it is running." He was about to
report the two entries as undetected when they came back.

What is tested here is that the scan is started and watched rather than waited
on, that what it is doing reaches the page, and that the things which go wrong
in a background thread -- an exception nobody catches, two scans at once -- do
not leave a page spinning for ever.
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import render, scanjob  # noqa: E402
from sunshine_apps_ui.core import utils  # noqa: E402


class JobTest(unittest.TestCase):
    def setUp(self):
        self.job = scanjob.ScanJob()

    def wait(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while self.job.running() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.job.running(), "the scan never finished")

    def test_it_returns_before_the_scan_does(self):
        """The whole point: asking must not wait for fifty seconds of scanning."""
        release = threading.Event()
        self.addCleanup(release.set)
        started = threading.Event()

        def work():
            started.set()
            release.wait(10)
            return 3

        asked = time.monotonic()
        self.assertTrue(self.job.start(work))
        self.assertLess(time.monotonic() - asked, 1.0)
        self.assertTrue(started.wait(5))
        self.assertTrue(self.job.running())
        release.set()
        self.wait()
        self.assertEqual(self.job.status()["staged"], 3)

    def test_what_the_scan_says_reaches_the_status(self):
        """The importers already say what they are doing; this listens."""
        seen = threading.Event()

        def work():
            utils.log("Building Heroic metadata cache from C:\\Users\\x")
            seen.set()
            return 0

        self.job.start(work)
        self.assertTrue(seen.wait(5))
        self.wait()
        status = self.job.status()
        self.assertIn("Building Heroic metadata cache", status["latest"])
        self.assertTrue(status["latest"].startswith("["), "the timestamp is lost")

    def test_it_stops_listening_when_the_scan_ends(self):
        """Otherwise every scan leaves a listener behind and they accumulate."""
        self.job.start(lambda: 0)
        self.wait()
        before = self.job.status()["latest"]
        utils.log("something else entirely, long afterwards")
        self.assertEqual(self.job.status()["latest"], before)

    def test_a_scan_that_raises_is_reported_and_not_left_running(self):
        """A page that polls a scan which died in a thread would spin for ever."""
        told = []
        self.job.start(lambda: (_ for _ in ()).throw(RuntimeError("no Sunshine here")),
                       on_error=told.append)
        self.wait()
        status = self.job.status()
        self.assertFalse(status["running"])
        self.assertIn("no Sunshine here", status["error"])
        self.assertEqual(told, ["no Sunshine here"])

    def test_a_watcher_that_throws_does_not_break_the_scan(self):
        def work():
            utils.log("still going")
            return 7

        utils.watch(lambda line: 1 / 0)
        self.addCleanup(lambda: None)
        try:
            self.job.start(work)
            self.wait()
        finally:
            for listener in list(utils._watchers):
                utils.unwatch(listener)
        self.assertEqual(self.job.status()["staged"], 7)

    def test_a_second_scan_joins_the_first(self):
        """Two at once would double the wait and stage everything twice."""
        release = threading.Event()
        self.addCleanup(release.set)
        runs = []

        def work():
            runs.append(1)
            release.wait(10)
            return 1

        self.assertTrue(self.job.start(work))
        self.assertFalse(self.job.start(work), "a second scan was allowed to start")
        release.set()
        self.wait()
        self.assertEqual(len(runs), 1)

    def test_nothing_has_run_yet_is_distinguishable_from_finished(self):
        """The scanning page needs the difference, or it redirects immediately."""
        self.assertFalse(self.job.status()["ran"])
        self.job.start(lambda: 0)
        self.wait()
        self.assertTrue(self.job.status()["ran"])

    def test_the_log_is_kept_but_bounded(self):
        def work():
            for i in range(scanjob.LINES * 3):
                utils.log("line %d" % i)
            return 0

        self.job.start(work)
        self.wait()
        status = self.job.status()
        self.assertEqual(len(status["lines"]), scanjob.LINES)
        self.assertIn("line %d" % (scanjob.LINES * 3 - 1), status["latest"])


class LongestStepSaysWhereItIsTest(unittest.TestCase):
    """The Heroic cache build is 58 of the 59 seconds, and said nothing in between.

    Measured on the rig: one line at 0.4 s, the next at 58.8 s. A spinner over
    a line that never changes is still a screen that looks stuck.
    """

    def test_it_reports_progress_while_it_walks(self):
        from sunshine_apps_ui.core.sources import heroic
        self.assertTrue(hasattr(heroic, "PROGRESS_EVERY"))
        self.assertLessEqual(heroic.PROGRESS_EVERY, 3.0,
                             "too slow to look like anything is happening")
        source = open(heroic.__file__, encoding="utf-8").read()
        self.assertIn("Reading Heroic's library:", source)
        self.assertIn("files so far", source)

    def test_it_counts_files_rather_than_promising_a_total(self):
        """rglob does not know how many there are until it has been all the way."""
        from sunshine_apps_ui.core.sources import heroic
        source = open(heroic.__file__, encoding="utf-8").read()
        line = next(l for l in source.splitlines() if "files so far" in l)
        self.assertIn("{scanned}", line)


class ScanningPageTest(unittest.TestCase):
    """The page itself: it has to say something, and it has to leave."""

    def page(self, **status):
        base = {"latest": "", "elapsed": 0.0, "running": True, "error": ""}
        base.update(status)
        return render.scanning_page("tok-123", base)

    def test_it_shows_what_the_scan_is_doing(self):
        html = self.page(latest="[21:34:16] Building Heroic metadata cache")
        self.assertIn("Building Heroic metadata cache", html)

    def test_it_says_something_before_the_first_line_arrives(self):
        self.assertIn("Starting...", self.page())

    def test_the_watcher_is_not_an_inline_script(self):
        """The pages are sent with script-src 'self'; inline is refused, silently.

        The first version of this page was inline. It rendered, showed the
        scan's first line, and then sat at "0.0s elapsed" for ever, which is
        indistinguishable from the hang the page exists to rule out.
        """
        html = self.page()
        self.assertNotIn("<script>", html)
        self.assertIn('<script src="/scanning.js?token=tok-123"', html)

    def test_it_tells_the_watcher_where_to_look_and_where_to_go(self):
        html = self.page()
        self.assertIn('data-scan-status="/scan/status?token=tok-123"', html)
        self.assertIn("data-scan-done=", html)
        self.assertIn("scanned=1", html)

    def test_it_polls_a_url_that_does_not_start_another_scan(self):
        html = self.page()
        self.assertIn("/scan/status?token=tok-123", html)
        self.assertNotIn("scan=1", html)

    def test_the_watcher_reads_both_urls_from_the_page(self):
        """No token in the script, so there is one copy of it and one escaping."""
        import os.path
        from sunshine_apps_ui import render as r
        path = os.path.join(os.path.dirname(os.path.abspath(r.__file__)),
                            "assets", "scanning.js")
        source = open(path, encoding="utf-8").read()
        self.assertIn("data-scan-status", source)
        self.assertIn("data-scan-done", source)
        self.assertIn("location.replace", source)
        code = "\n".join(l for l in source.splitlines()
                          if not l.strip().startswith("//"))
        self.assertNotIn("token", code, "the token does not belong in the script")

    def test_it_reloads_itself_without_javascript(self):
        """And at its own URL, so a refresh watches rather than restarts."""
        self.assertIn('<noscript><meta http-equiv="refresh" content="2">', self.page())

    def test_a_scan_that_failed_says_so_instead_of_spinning(self):
        html = self.page(error="Could not read apps.json", running=False)
        self.assertIn("Could not read apps.json", html)
        self.assertIn("The scan stopped", html)
        self.assertNotIn("Scanning your libraries", html)

    def test_the_token_is_escaped_once_into_every_link(self):
        html = render.scanning_page("a b&c", {"latest": "", "elapsed": 0,
                                              "running": True, "error": ""})
        self.assertNotIn("a b&c", html)
        self.assertIn("a%20b%26c", html)


if __name__ == "__main__":
    unittest.main()
