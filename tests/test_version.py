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
    """Both channels, whichever this checkout happens to be on.

    These used to assume the dev channel, which was true for as long as there
    had never been a release. Cutting 1.0.0 turned six of them red without
    anything being wrong -- so each now says which channel it is about.
    """

    def setUp(self):
        patched = mock.patch.object(version, "_cached",
                                    {"build": "123", "commit": "abc1234",
                                     "dirty": False})
        patched.start()
        self.addCleanup(patched.stop)
        self.dev = mock.patch.object(version, "CHANNEL", "dev")
        self.release = mock.patch.object(version, "CHANNEL", "")

    def test_a_development_build_says_so_first(self):
        """So it cannot be mistaken for a release at a glance."""
        with self.dev:
            self.assertTrue(version.display().startswith("dev "), version.display())

    def test_it_carries_the_release_it_is_heading_for(self):
        with self.dev:
            self.assertIn(version.RELEASE, version.display())

    def test_and_the_build_number(self):
        with self.dev:
            self.assertIn("123", version.display())

    def test_the_machine_readable_form_is_pep_440(self):
        with self.dev:
            self.assertEqual(version.version(), f"{version.RELEASE}.dev123")

    def test_a_development_build_sorts_below_the_release_it_precedes(self):
        """Which is the whole reason for the .devN form."""
        try:
            from packaging.version import Version
        except ImportError:
            self.skipTest("packaging is not installed")
        with self.dev:
            self.assertLess(Version(version.version()), Version(version.RELEASE))

    def test_a_release_drops_the_word_and_the_build(self):
        with self.release:
            self.assertEqual(version.display(), version.RELEASE)
            self.assertEqual(version.version(), version.RELEASE)

    def test_a_release_is_a_plain_number_tools_can_sort(self):
        try:
            from packaging.version import Version
        except ImportError:
            self.skipTest("packaging is not installed")
        with self.release:
            self.assertEqual(Version(version.version()), Version(version.RELEASE))
            self.assertFalse(Version(version.version()).is_prerelease)

    def test_uncommitted_changes_are_admitted(self):
        """A build with local edits is not the commit it claims to be."""
        with self.dev, mock.patch.object(
                version, "_cached",
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

    def test_a_build_number_never_goes_backward(self):
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


@unittest.skipIf(os.name == "nt",
                 "installs to ~/.local and runs the launcher script it leaves; "
                 "Windows gets an installer of its own: issue #13")
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


class StampingTest(unittest.TestCase):
    """Packaging writes the build number down, and never writes it off.

    Installing from a source tree with no git -- an unpacked tarball, say --
    used to overwrite the number carried in that tarball with 0, which is the
    exact ambiguity writing it down exists to prevent. Found by deploying a
    tarball to the test machine and watching it report build 0.
    """

    def setUp(self):
        from sunshine_apps_ui import installer
        self.installer = installer
        self.package = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.package, True)

    def _write_existing(self, build="77"):
        with open(os.path.join(self.package, "_build.py"), "w") as handle:
            handle.write(f"BUILD = {build!r}\nCOMMIT = 'old'\nDIRTY = False\n")

    def _read(self):
        with open(os.path.join(self.package, "_build.py")) as handle:
            return handle.read()

    def test_a_checkout_writes_what_git_says(self):
        with mock.patch.object(version, "_from_git",
                               return_value={"build": "123", "commit": "abc",
                                             "dirty": False}):
            self.assertTrue(self.installer.stamp_build(self.package))
        self.assertIn("'123'", self._read())
        version.details(refresh=True)

    def test_it_will_not_replace_a_known_build_with_an_unknown_one(self):
        self._write_existing("77")
        with mock.patch.object(version, "_from_git", return_value=None), \
             mock.patch.object(version, "_from_baked", return_value=None):
            self.assertFalse(self.installer.stamp_build(self.package))
        self.assertIn("'77'", self._read())
        version.details(refresh=True)

    def test_but_it_will_write_one_where_there_is_none(self):
        with mock.patch.object(version, "_from_git",
                               return_value={"build": "9", "commit": "c",
                                             "dirty": False}):
            self.assertTrue(self.installer.stamp_build(self.package))
        self.assertIn("'9'", self._read())
        version.details(refresh=True)

    def test_a_better_answer_does_replace_a_worse_one(self):
        self._write_existing("0")
        with mock.patch.object(version, "_from_git",
                               return_value={"build": "42", "commit": "c",
                                             "dirty": False}):
            self.assertTrue(self.installer.stamp_build(self.package))
        self.assertIn("'42'", self._read())
        version.details(refresh=True)


class OffTheIntegrationBranchTest(unittest.TestCase):
    """A commit count only identifies a build on one line of history.

    `main` takes only what `dev` already has, so those two never hold
    different commits at the same depth and the number stands alone. Two issue
    branches cut from the same commit do reach the same count, so those say
    which branch and which commit as well. Issue #3.
    """

    def _on(self, branch, commit="abc1234", build="123", dirty=False):
        return mock.patch.object(version, "_cached",
                                 {"build": build, "commit": commit,
                                  "branch": branch, "dirty": dirty})

    def test_a_dev_build_is_named_by_its_number_alone(self):
        with mock.patch.object(version, "CHANNEL", "dev"), self._on("dev"):
            self.assertEqual(version.version(), f"{version.RELEASE}.dev123")
            self.assertEqual(version.display(), f"dev {version.RELEASE}.123")

    def test_and_so_is_one_off_main(self):
        with mock.patch.object(version, "CHANNEL", "dev"), self._on("main"):
            self.assertEqual(version.version(), f"{version.RELEASE}.dev123")

    def test_an_issue_branch_carries_the_branch_and_the_commit(self):
        with mock.patch.object(version, "CHANNEL", "dev"), self._on("issue-3"):
            self.assertEqual(version.version(),
                             f"{version.RELEASE}.dev123+issue.3.gabc1234")

    def test_two_branches_at_the_same_depth_are_told_apart(self):
        """The whole point: same build number, different version."""
        with mock.patch.object(version, "CHANNEL", "dev"):
            with self._on("issue-3", commit="aaaaaaa"):
                first = version.version()
            with self._on("issue-22", commit="bbbbbbb"):
                second = version.version()
        self.assertNotEqual(first, second)

    def test_a_branch_build_sorts_above_the_dev_build_it_branched_from(self):
        try:
            from packaging.version import Version
        except ImportError:
            self.skipTest("packaging is not installed")
        with mock.patch.object(version, "CHANNEL", "dev"):
            with self._on("dev"):
                base = version.version()
            with self._on("issue-3"):
                branch = version.version()
            self.assertGreater(Version(branch), Version(base))
            self.assertLess(Version(branch), Version(version.RELEASE))

    def test_a_person_sees_the_branch_next_to_the_number(self):
        with mock.patch.object(version, "CHANNEL", "dev"), self._on("issue-3"):
            self.assertEqual(version.display(),
                             f"dev {version.RELEASE}.123 (issue.3)")

    def test_uncommitted_changes_are_still_admitted_on_a_branch(self):
        with mock.patch.object(version, "CHANNEL", "dev"), \
                self._on("issue-3", dirty=True):
            self.assertIn("123+", version.display())
            self.assertIn("(issue.3)", version.display())

    def test_the_long_form_puts_the_branch_and_commit_in_one_parenthesis(self):
        with mock.patch.object(version, "CHANNEL", "dev"), self._on("issue-3"):
            self.assertEqual(version.long_display(),
                             f"dev {version.RELEASE}.123 (issue.3 abc1234)")

    def test_a_detached_head_falls_back_to_the_commit(self):
        """Not a branch name, so the commit does the identifying."""
        with mock.patch.object(version, "CHANNEL", "dev"), self._on(""):
            self.assertEqual(version.version(),
                             f"{version.RELEASE}.dev123+gabc1234")
            self.assertIn("detached", version.display())

    def test_a_copy_that_does_not_know_says_nothing(self):
        """Stamped before branches existed. Silence beats a wrong claim."""
        with mock.patch.object(version, "CHANNEL", "dev"), self._on(None):
            self.assertEqual(version.version(), f"{version.RELEASE}.dev123")
            self.assertEqual(version.display(), f"dev {version.RELEASE}.123")

    def test_a_branch_name_becomes_a_legal_local_segment(self):
        """PEP 440 allows alphanumerics and periods, and nothing else."""
        for name, expected in (("issue-3", "issue.3"),
                               ("feature/tile_art", "feature.tile.art"),
                               ("ISSUE-3", "issue.3"),
                               ("--", "branch")):
            self.assertEqual(version._slug(name), expected, name)
            self.assertRegex(version._slug(name), r"^[a-z0-9]+(\.[a-z0-9]+)*$")

    def test_a_release_off_a_branch_admits_it(self):
        """Releases are cut on main, so this is a warning sign worth seeing."""
        with mock.patch.object(version, "CHANNEL", ""), self._on("issue-3"):
            self.assertIn("(issue.3)", version.display())

    def test_a_checkout_reports_the_branch_it_is_on(self):
        found = version._from_git()
        if found is None:
            self.skipTest("not a git checkout")
        expected = subprocess.run(
            ["git", "-C", version._repo_root(), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(found["branch"], "" if expected == "HEAD" else expected)

    def test_a_worktree_is_still_a_checkout(self):
        """Its `.git` is a file, not a directory -- issue branches live in one,
        and testing for a directory reported build 0 for every one of them."""
        root = version._repo_root()
        if not os.path.exists(os.path.join(root, ".git")):
            self.skipTest("not a git checkout")
        self.assertIsNotNone(version._from_git())


class WhatIsStampedTest(unittest.TestCase):
    """The branch has to survive into a copy that has no git."""

    def test_the_branch_is_written_down(self):
        from sunshine_apps_ui import installer
        package = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, package, True)
        with mock.patch.object(version, "_from_git",
                               return_value={"build": "123", "commit": "abc",
                                             "branch": "issue-3", "dirty": False}):
            self.assertTrue(installer.stamp_build(package))
        with open(os.path.join(package, "_build.py")) as handle:
            self.assertIn("BRANCH = 'issue-3'", handle.read())
        version.details(refresh=True)


if __name__ == "__main__":
    unittest.main()
