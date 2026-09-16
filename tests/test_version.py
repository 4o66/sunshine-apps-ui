# SPDX-License-Identifier: GPL-3.0-or-later
"""Which version this is, and which build of it.

Two forms for two audiences: PEP 440 so tools sort it, and something a person
reads that cannot be mistaken for a release.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import version  # noqa: E402


class FormatTest(unittest.TestCase):
    def setUp(self):
        patched = mock.patch.object(version, "_cached",
                                    {"build": "123", "commit": "abc1234",
                                     "dirty": False})
        patched.start()
        self.addCleanup(patched.stop)

    def test_a_development_build_says_so_first(self):
        """So it cannot be mistaken for a release at a glance."""
        self.assertTrue(version.display().startswith("dev "), version.display())

    def test_it_carries_the_release_it_is_heading_for(self):
        self.assertIn(version.RELEASE, version.display())

    def test_and_the_build_number(self):
        self.assertIn("123", version.display())

    def test_the_machine_readable_form_is_pep_440(self):
        self.assertEqual(version.version(), f"{version.RELEASE}.dev123")

    def test_a_development_build_sorts_below_the_release_it_precedes(self):
        """Which is the whole reason for the .devN form."""
        try:
            from packaging.version import Version
        except ImportError:
            self.skipTest("packaging is not installed")
        self.assertLess(Version(version.version()), Version(version.RELEASE))

    def test_a_release_drops_the_word_and_the_build(self):
        with mock.patch.object(version, "CHANNEL", ""):
            self.assertEqual(version.display(), version.RELEASE)
            self.assertEqual(version.version(), version.RELEASE)

    def test_uncommitted_changes_are_admitted(self):
        """A build with local edits is not the commit it claims to be."""
        with mock.patch.object(version, "_cached",
                               {"build": "123", "commit": "abc", "dirty": True}):
            self.assertTrue(version.display().endswith("+"), version.display())

    def test_the_long_form_names_the_commit_for_a_bug_report(self):
        self.assertIn("abc1234", version.long_display())


class WhereTheBuildComesFromTest(unittest.TestCase):
    """A checkout asks git. An installed copy has none, so it was written down."""

    def test_a_checkout_counts_commits(self):
        found = version._from_git()
        if found is None:
            self.skipTest("not a git checkout")
        self.assertTrue(found["build"].isdigit())
        self.assertNotEqual(found["build"], "0")

    def test_it_matches_what_git_says(self):
        found = version._from_git()
        if found is None:
            self.skipTest("not a git checkout")
        expected = subprocess.run(
            ["git", "-C", version._repo_root(), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(found["build"], expected)

    def test_a_build_number_never_goes_backwards(self):
        """The only question a build number is asked is which one is newer."""
        found = version._from_git()
        if found is None:
            self.skipTest("not a git checkout")
        earlier = subprocess.run(
            ["git", "-C", version._repo_root(), "rev-list", "--count", "HEAD~1"],
            capture_output=True, text=True).stdout.strip()
        if earlier:
            self.assertGreater(int(found["build"]), int(earlier))

    def test_without_git_or_a_baked_answer_it_says_zero_rather_than_guessing(self):
        with mock.patch.object(version, "_from_git", return_value=None), \
             mock.patch.object(version, "_from_baked", return_value=None):
            self.assertEqual(version.details(refresh=True)["build"], "0")
        version.details(refresh=True)

    def test_a_baked_answer_is_used_when_there_is_no_git(self):
        baked = {"build": "77", "commit": "deadbee", "dirty": False}
        with mock.patch.object(version, "_from_git", return_value=None), \
             mock.patch.object(version, "_from_baked", return_value=baked):
            self.assertEqual(version.details(refresh=True)["build"], "77")
        version.details(refresh=True)


class InstalledCopyTest(unittest.TestCase):
    """An install has no git, so the installer writes the answer down."""

    def test_the_installed_copy_reports_the_same_build(self):
        from sunshine_apps_ui import installer
        prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, prefix, True)
        with mock.patch.object(installer.legacy, "destructive_installs",
                               return_value=[]):
            ok, _ = installer.install(prefix)
        self.assertTrue(ok)

        command = os.path.join(prefix, "bin", "sunshine-apps-ui")
        # Run it from somewhere with no git above it, so it cannot cheat.
        result = subprocess.run([sys.executable, command, "--version"],
                                capture_output=True, text=True, cwd=tempfile.gettempdir(),
                                timeout=60)
        self.assertIn(version.version(), result.stdout + result.stderr)

    def test_what_was_baked_is_not_committed(self):
        """It describes one install, not the source it came from."""
        root = version._repo_root()
        with open(os.path.join(root, ".gitignore"), encoding="utf-8") as handle:
            self.assertIn("_build.py", handle.read())


if __name__ == "__main__":
    unittest.main()
