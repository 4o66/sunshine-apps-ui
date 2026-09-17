# SPDX-License-Identifier: GPL-3.0-or-later
"""The startup question: can we write apps.json, and what do we say if not.

Every Windows-specific case is exercised by standing in for the two things that
differ -- whether the file opens for writing, and what the token says -- because
the answers this module gives are wording, and wording is what the tests are
for. The mechanics of asking Windows are one ctypes call, tested on Windows by
running it there.
"""

import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import privilege  # noqa: E402


class PrivilegeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.conf = os.path.join(self.tmp, "sunshine")
        os.makedirs(self.conf)
        self.apps = os.path.join(self.conf, "apps.json")
        self._real_can_write = privilege._can_write_file
        self._real_elevated = privilege.is_elevated

    def tearDown(self):
        privilege._can_write_file = self._real_can_write
        privilege.is_elevated = self._real_elevated
        if os.path.exists(self.apps):
            os.chmod(self.apps, stat.S_IRUSR | stat.S_IWUSR)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_apps(self):
        with open(self.apps, "w") as fh:
            json.dump({"apps": []}, fh)

    # --- the ordinary case -------------------------------------------------

    def test_writable_config_is_writable(self):
        self.write_apps()
        state = privilege.check(self.conf)
        self.assertTrue(state.can_write)
        self.assertFalse(state.read_only)
        self.assertEqual(state.detail, "")

    def test_missing_apps_json_is_not_a_failure(self):
        """Sunshine writes it on first run; a writable directory is the same answer."""
        self.assertTrue(privilege.check(self.conf).can_write)

    def test_missing_config_dir_reports_read_only(self):
        missing = os.path.join(self.tmp, "nowhere")
        state = privilege.check(missing)
        self.assertFalse(state.can_write)
        # Which sentence comes back depends on what the token says, and that
        # differs between an elevated run and an ordinary one. What must hold
        # either way: it says no, it names the file, and it has a headline to
        # put on the banner.
        self.assertIn(privilege.apps_json_path(missing), state.detail)
        self.assertTrue(state.headline)

    def test_checking_does_not_touch_the_file(self):
        """r+b, never w: the test must not truncate the file or restamp it."""
        self.write_apps()
        body = open(self.apps).read()
        stamp = os.stat(self.apps)
        os.utime(self.apps, (stamp.st_atime, stamp.st_mtime - 100))
        expected = os.stat(self.apps).st_mtime

        self.assertTrue(privilege.check(self.conf).can_write)
        self.assertEqual(open(self.apps).read(), body)
        self.assertEqual(os.stat(self.apps).st_mtime, expected)

    def test_no_stray_files_left_behind(self):
        privilege.check(self.conf)
        self.assertEqual(os.listdir(self.conf), [])

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX modes; Windows uses ACLs")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anything")
    def test_unwritable_apps_json_is_detected(self):
        self.write_apps()
        os.chmod(self.apps, stat.S_IRUSR)
        state = privilege.check(self.conf)
        self.assertFalse(state.can_write)
        self.assertIn(self.apps, state.detail)
        self.assertTrue(state.headline)

    def test_elevation_is_only_asked_on_windows(self):
        platform = sys.platform
        try:
            sys.platform = "linux"
            self.assertIsNone(privilege.is_elevated())
        finally:
            sys.platform = platform

    # --- the two Windows failures that would otherwise be silent -----------

    def unwritable(self, elevated):
        self.write_apps()
        privilege._can_write_file = lambda path: False
        privilege.is_elevated = lambda: elevated
        return privilege.check(self.conf)

    def test_unelevated_says_what_grants_the_right(self):
        state = self.unwritable(elevated=False)
        self.assertFalse(state.can_write)
        self.assertIs(state.elevated, False)
        # It has to name the mechanism, or the reader cannot act on it.
        for word in ("elevated", "service", "administrator"):
            self.assertIn(word, state.detail)
        # And say what still works, so it does not read as "nothing works".
        self.assertIn("reloading still work", state.detail)

    def test_elevated_but_unwritable_points_at_the_file(self):
        state = self.unwritable(elevated=True)
        self.assertFalse(state.can_write)
        self.assertIs(state.elevated, True)
        self.assertIn("permissions problem on the file", state.detail)
        # Not a missing right, so it must not send anyone looking for one.
        self.assertNotIn("not elevated", state.detail.lower())

    def test_elevated_and_writable_says_nothing(self):
        self.write_apps()
        privilege.is_elevated = lambda: True
        state = privilege.check(self.conf)
        self.assertTrue(state.can_write)
        self.assertEqual(state.detail, "")

    # --- what startup logs -------------------------------------------------

    def test_startup_line_names_the_file_when_it_works(self):
        self.write_apps()
        line = privilege.startup_line(privilege.check(self.conf), self.conf)
        self.assertIn("apps.json", line)
        self.assertIn("writable", line)

    def test_startup_line_leads_with_read_only(self):
        state = self.unwritable(elevated=False)
        line = privilege.startup_line(state, self.conf)
        self.assertTrue(line.startswith("READ-ONLY:"))


if __name__ == "__main__":
    unittest.main()
