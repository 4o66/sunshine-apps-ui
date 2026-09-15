# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the older importer, and telling the two kinds apart.

The distinction matters more than the detection: the fork this project absorbed
is harmless, and the original it came from will silently delete half your
apps.json. Warning about the wrong one teaches people to ignore the warning.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import legacy  # noqa: E402


class InstallDetectionTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def _helper(self, *files):
        root = os.path.join(self.home, ".config", "sunshine", "helper")
        os.makedirs(root, exist_ok=True)
        for name in ("sunshine-import.sh",) + files:
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write("#!/bin/sh\n")
        return root

    def _link(self, target, name="sunshine-import"):
        binroot = os.path.join(self.home, ".local", "bin")
        os.makedirs(binroot, exist_ok=True)
        link = os.path.join(binroot, name)
        os.symlink(target, link)
        return link

    def test_nothing_installed_is_nothing_found(self):
        self.assertEqual(legacy.find_installs(self.home, search_path=False), [])

    def test_the_original_is_found_where_its_installer_puts_it(self):
        self._helper()
        found = legacy.find_installs(self.home, search_path=False)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "original")

    def test_the_original_is_flagged_as_destructive(self):
        self._helper()
        self.assertTrue(legacy.find_installs(self.home, False)[0]["destructive"])

    def test_the_fork_is_recognised_and_not_flagged(self):
        """It has the reconciler; the original never did."""
        self._helper("common/reconcile.py")
        found = legacy.find_installs(self.home, search_path=False)
        self.assertEqual(found[0]["kind"], "fork")
        self.assertFalse(found[0]["destructive"])

    def test_only_the_destructive_one_is_reported_when_asked(self):
        self._helper("common/reconcile.py")
        self.assertEqual(legacy.destructive_installs(self.home, False), [])

    def test_it_is_found_through_its_launcher_too(self):
        """Installed somewhere else and linked into ~/.local/bin."""
        root = os.path.join(self.home, "elsewhere")
        os.makedirs(root)
        script = os.path.join(root, "sunshine-import.sh")
        open(script, "w").close()
        self._link(script)
        found = legacy.find_installs(self.home, search_path=False)
        self.assertEqual([f["root"] for f in found], [os.path.realpath(root)])

    def test_one_install_reached_two_ways_is_reported_once(self):
        root = self._helper()
        self._link(os.path.join(root, "sunshine-import.sh"))
        self.assertEqual(len(legacy.find_installs(self.home, search_path=False)), 1)

    def test_a_dangling_launcher_is_not_an_install(self):
        self._link(os.path.join(self.home, "gone", "sunshine-import.sh"))
        self.assertEqual(legacy.find_installs(self.home, search_path=False), [])


class RemovalPlanTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.root = os.path.join(self.home, ".config", "sunshine", "helper")
        os.makedirs(self.root)
        self.script = os.path.join(self.root, "sunshine-import.sh")
        open(self.script, "w").close()
        binroot = os.path.join(self.home, ".local", "bin")
        os.makedirs(binroot)
        self.link = os.path.join(binroot, "sunshine-import")
        os.symlink(self.script, self.link)

    def test_it_lists_the_install_and_its_launcher(self):
        install = legacy.find_installs(self.home, search_path=False)[0]
        plan = legacy.removal_plan(install, self.home)
        self.assertIn(os.path.realpath(self.root), plan)
        self.assertIn(self.link, plan)

    def test_it_never_offers_to_remove_apps_json(self):
        """Removing a tool is not a reason to touch what it managed."""
        install = legacy.find_installs(self.home, search_path=False)[0]
        for path in legacy.removal_plan(install, self.home):
            self.assertNotIn("apps.json", path)

    def test_it_leaves_a_launcher_belonging_to_something_else_alone(self):
        other = os.path.join(self.home, "other")
        os.makedirs(other)
        script = os.path.join(other, "sunshine-import.sh")
        open(script, "w").close()
        os.symlink(script, os.path.join(self.home, ".local", "bin",
                                        "bsm-test-import"))
        install = legacy.find_installs(self.home, search_path=False)[0]
        plan = legacy.removal_plan(install, self.home)
        self.assertNotIn(os.path.join(self.home, ".local", "bin",
                                      "bsm-test-import"), plan)


class WordingTest(unittest.TestCase):
    """The warnings have to be true, and the obvious guess about Sunshine is not."""

    def test_the_original_is_described_by_what_it_actually_does(self):
        self.assertIn("rewrites apps.json from scratch", legacy.REWRITES_EVERYTHING)

    def test_sunshines_web_ui_is_not_accused_of_corrupting_anything(self):
        text = legacy.SUNSHINE_WEB_UI.lower()
        self.assertIn("safe to use", text)
        for word in ("corrupt", "damage", "destroy"):
            self.assertNotIn(word, text)

    def test_but_the_one_real_caveat_is_still_stated(self):
        self.assertIn("not recorded as a deletion", legacy.SUNSHINE_WEB_UI)


if __name__ == "__main__":
    unittest.main()
