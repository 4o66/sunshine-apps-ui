# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for seeding and restoring Sunshine's shipped default apps."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core.reconcile import reconcile, tag  # noqa: E402
from sunshine_apps_ui.core.system_apps import (find_system_apps_json, load_system_apps,  # noqa: E402
                                restore_missing, system_app_names)

FACTORY = [
    {"name": "Desktop", "image-path": "desktop.png"},
    {"name": "Low Res Desktop", "image-path": "desktop.png",
     "prep-cmd": [{"do": "xrandr", "undo": "xrandr"}]},
    {"name": "Steam Big Picture", "detached": ["setsid steam steam://open/bigpicture"],
     "image-path": "steam.png"},
]


class TestDiscovery(unittest.TestCase):
    def test_override_wins_when_it_exists(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"apps": FACTORY}, f)
            path = f.name
        try:
            self.assertEqual(find_system_apps_json(path), path)
        finally:
            os.unlink(path)

    def test_override_that_does_not_exist_finds_nothing(self):
        """Better to report no defaults than to silently fall back to another file."""
        self.assertEqual(find_system_apps_json("/nonexistent/apps.json"), "")

    def test_load_tolerates_junk(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json at all")
            path = f.name
        try:
            self.assertEqual(load_system_apps(path), [])
        finally:
            os.unlink(path)
        self.assertEqual(load_system_apps(""), [])

    def test_load_accepts_a_bare_list_as_well_as_an_object(self):
        for payload in ({"apps": FACTORY}, FACTORY):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(payload, f)
                path = f.name
            try:
                self.assertEqual(system_app_names(load_system_apps(path)),
                                 {"Desktop", "Low Res Desktop", "Steam Big Picture"})
            finally:
                os.unlink(path)


class TestRestore(unittest.TestCase):
    def test_restores_only_what_is_absent(self):
        existing = [FACTORY[0]]
        out, restored = restore_missing(existing, FACTORY)
        self.assertEqual(restored, ["Low Res Desktop", "Steam Big Picture"])
        self.assertEqual([a["name"] for a in out].count("Desktop"), 1)

    def test_nothing_to_do_is_a_no_op(self):
        out, restored = restore_missing(list(FACTORY), FACTORY)
        self.assertEqual(restored, [])
        self.assertEqual(out, FACTORY)

    def test_an_edited_default_is_left_exactly_as_the_user_has_it(self):
        mine = [{"name": "Desktop", "image-path": "/my/own.png", "cmd": "mine"}]
        out, restored = restore_missing(mine, FACTORY)
        self.assertNotIn("Desktop", restored)
        desktop = [a for a in out if a["name"] == "Desktop"]
        self.assertEqual(len(desktop), 1)
        self.assertEqual(desktop[0]["image-path"], "/my/own.png")

    def test_restored_entries_stay_foreign_to_the_reconciler(self):
        """Restoring must not make the tool start managing Sunshine's defaults."""
        restored, _ = restore_missing([], FACTORY)
        generated = tag({"name": "Game", "cmd": "x"}, "steam", "1")
        out, plan = reconcile(restored, [generated])
        self.assertEqual(len(plan["kept_foreign"]), 3)
        for app in out[:3]:
            self.assertNotIn("bsm", app)

    def test_defaults_are_not_duplicated_across_repeated_restores(self):
        out, _ = restore_missing([], FACTORY)
        out2, restored2 = restore_missing(out, FACTORY)
        self.assertEqual(restored2, [])
        self.assertEqual(len(out2), 3)


if __name__ == "__main__":
    unittest.main()


class PlatformCandidatesTest(unittest.TestCase):
    """Where the shipped defaults live when there is no fixed path for them.

    Measured on the Windows rig 2026-09-19: the defaults were reported missing
    while sitting in `C:\\Program Files\\Sunshine\\assets\\apps.json`, because
    only the POSIX paths were ever looked at. Everything that reads the
    defaults was therefore dead on Windows -- seeding a fresh config, and the
    "put the default tiles back" button, which said it could not find them.
    """

    def test_windows_looks_beside_the_executable(self):
        import ntpath
        from sunshine_apps_ui.core import api, system_apps

        with mock.patch.object(os, "name", "nt"), \
             mock.patch.object(api, "_windows_install_dirs",
                               lambda: [r"C:\Program Files\Sunshine"]):
            found = system_apps._platform_candidates()
        self.assertEqual(found, [ntpath.join(r"C:\Program Files\Sunshine",
                                             "assets", "apps.json")])

    def test_macos_looks_inside_the_bundle(self):
        from sunshine_apps_ui.core import system_apps

        with mock.patch.object(os, "name", "posix"), \
             mock.patch.object(sys, "platform", "darwin"):
            found = system_apps._platform_candidates()
        self.assertIn("/Applications/Sunshine.app/Contents/Resources/assets/apps.json",
                      found)

    def test_linux_needs_no_extra_hunting(self):
        from sunshine_apps_ui.core import system_apps

        with mock.patch.object(os, "name", "posix"), \
             mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(system_apps._platform_candidates(), [])
