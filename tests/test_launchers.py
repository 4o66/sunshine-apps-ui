# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated launcher entries.

These are synthesised rather than discovered, so the thing worth testing is not
whether they are found -- it is that renaming one renames it, rather than
orphaning the old entry and adding a second beside it.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core.reconcile import MARKER, identity  # noqa: E402
from sunshine_apps_ui.core.sources import launchers  # noqa: E402
from sunshine_apps_ui.core.sources.launchers import NAMES, import_launchers  # noqa: E402


class LauncherEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        # An empty PATH, so what these tests find is what this test put there.
        # Without it, a machine with the manager installed passes the test for
        # it not being installed -- which is how this was first caught.
        empty = os.path.join(self.home, "nothing")
        os.makedirs(empty)
        patched = mock.patch.dict(os.environ, {"PATH": empty})
        patched.start()
        self.addCleanup(patched.stop)
        self.images = os.path.join(self.home, "images")
        os.makedirs(self.images)
        # Posters are only downloaded when absent, so putting them there keeps
        # this test off the network.
        for name in ("Desktop.png", "Steam.png", "Heroic.png", "Reboot.png"):
            with open(os.path.join(self.images, name), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")
        # "Installed" means something different per platform, so build what that
        # platform's installer actually leaves behind. On POSIX that is an
        # executable in ~/.local/bin; on Windows it is a .cmd inside the install
        # directory, found through the installer rather than guessed at here.
        if os.name == "nt":
            from sunshine_apps_ui import installer as _installer
            self._previous_prefix = os.environ.get("PREFIX")
            os.environ["PREFIX"] = self.home
            self.addCleanup(self._restore_prefix)
            where = _installer.paths()
            os.makedirs(where["install"], exist_ok=True)
            self.ui_path = where["command"]
            with open(self.ui_path, "w") as handle:
                handle.write("@echo off\r\n")
            # What the entry should say: quoted, because the path usually has a
            # space in it. self.ui_path is the file itself, for tests that
            # remove it -- the two are not interchangeable.
            self.ui = f'"{self.ui_path}"'
        else:
            os.makedirs(os.path.join(self.home, ".local", "bin"))
            self.ui = os.path.join(self.home, ".local", "bin", "sunshine-apps-ui")
            self.ui_path = self.ui
            with open(self.ui, "w") as handle:
                handle.write("#!/bin/sh\n")
            os.chmod(self.ui, 0o755)

    def _restore_prefix(self):
        if getattr(self, "_previous_prefix", None) is None:
            os.environ.pop("PREFIX", None)
        else:
            os.environ["PREFIX"] = self._previous_prefix

    def _apps(self):
        return import_launchers(self.home, self.home, self.images, {})

    def _apps_ui(self):
        return next((a for a in self._apps()
                     if a.get(MARKER, {}).get("id") == "apps-ui"), None)

    def test_the_manager_gets_an_entry_when_it_is_installed(self):
        self.assertIsNotNone(self._apps_ui())

    def test_it_is_called_what_we_call_it(self):
        self.assertEqual(self._apps_ui()["name"], "Zz App Manager")

    def test_renaming_it_does_not_change_what_it_is(self):
        """The marker, not the name, is what ties this to the entry already in
        apps.json. If the id moved, a rename would orphan the old entry and add
        a second one beside it."""
        self.assertEqual(identity(self._apps_ui()), ("launcher", "apps-ui"))

    def test_it_sorts_to_the_end_of_the_list(self):
        """Moonlight sorts by name, and a tool belongs after the games."""
        self.assertTrue(NAMES["apps-ui"].startswith("Zz"))

    def test_it_runs_the_launcher_that_was_found(self):
        self.assertEqual(self._apps_ui()["cmd"], self.ui)

    def test_no_entry_when_it_is_not_installed(self):
        os.unlink(self.ui_path)
        self.assertIsNone(self._apps_ui())

    def test_every_generated_entry_is_marked_as_ours(self):
        for app in self._apps():
            self.assertIn(MARKER, app)

    def test_the_marker_ids_are_the_keys_of_the_name_table(self):
        """So a display name can be changed without touching identity."""
        ids = {a[MARKER]["id"] for a in self._apps()}
        self.assertTrue(ids.issubset(set(NAMES)), ids - set(NAMES))


if __name__ == "__main__":
    unittest.main()


class SandboxedSunshineTest(LauncherEntryTest):
    """When Sunshine itself is a Flatpak, every command we generate names a
    path it cannot see.

    Config discovery already knows about a Flatpak Sunshine -- it looks under
    ~/.var/app for it -- so the tile it generates has to account for the same
    thing. Upstream says it outright: the Flatpak of Sunshine requires commands
    to be prefixed with flatpak-spawn --host.
    """

    def _flatpak_conf(self):
        conf = os.path.join(self.home, ".var", "app",
                            "dev.lizardbyte.app.Sunshine", "config", "sunshine")
        os.makedirs(conf, exist_ok=True)
        return conf

    def _entries(self, conf_dir):
        return import_launchers(self.home, conf_dir, self.images, {})

    def test_it_notices_sunshine_is_sandboxed(self):
        from sunshine_apps_ui.core.sources.launchers import _sunshine_is_flatpak
        self.assertTrue(_sunshine_is_flatpak(self._flatpak_conf()))
        self.assertFalse(_sunshine_is_flatpak(
            os.path.join(self.home, ".config", "sunshine")))

    def test_the_managers_own_tile_runs_on_the_host(self):
        entry = next(a for a in self._entries(self._flatpak_conf())
                     if a.get(MARKER, {}).get("id") == "apps-ui")
        self.assertTrue(entry["cmd"].startswith("flatpak-spawn --host "),
                        entry["cmd"])
        self.assertIn(self.ui, entry["cmd"])

    def test_reboot_runs_on_the_host_too(self):
        entry = next(a for a in self._entries(self._flatpak_conf())
                     if a.get(MARKER, {}).get("id") == "reboot")
        # What is asserted here is the flatpak-spawn prefix, not which command
        # reboots this machine -- that is the platform's business, and tested
        # separately. Hard-coding systemctl here made this fail on macOS.
        self.assertEqual(entry["detached"],
                         [f"flatpak-spawn --host {launchers._reboot_cmd()}"])

    def test_a_native_sunshine_is_left_exactly_as_it_was(self):
        conf = os.path.join(self.home, ".config", "sunshine")
        os.makedirs(conf, exist_ok=True)
        entry = next(a for a in self._entries(conf)
                     if a.get(MARKER, {}).get("id") == "apps-ui")
        self.assertEqual(entry["cmd"], self.ui)

    def test_it_does_not_prefix_something_already_prefixed(self):
        from sunshine_apps_ui.core.sources.launchers import _host
        already = "flatpak-spawn --host steam"
        self.assertEqual(_host(already, True), already)

    def test_an_empty_command_stays_empty(self):
        """The desktop entry has no command; a prefix alone would be nonsense."""
        from sunshine_apps_ui.core.sources.launchers import _host
        self.assertEqual(_host("", True), "")
        entry = next(a for a in self._entries(self._flatpak_conf())
                     if a.get(MARKER, {}).get("id") == "desktop")
        self.assertEqual(entry["cmd"], "")


class RebootCommandTest(unittest.TestCase):
    """The Reboot tile has to actually reboot the machine it is on.

    `systemctl reboot` on Windows is the worst kind of wrong: an entry that
    looks right on the grid and does nothing when a gamepad presses it.
    """

    def setUp(self):
        self.real_name = os.name
        self.real_platform = sys.platform

    def tearDown(self):
        os.name = self.real_name
        sys.platform = self.real_platform

    def test_windows_uses_shutdown(self):
        os.name = "nt"
        self.assertEqual(launchers._reboot_cmd(), "shutdown /r /t 0")

    def test_macos_asks_without_sudo(self):
        os.name = "posix"
        sys.platform = "darwin"
        cmd = launchers._reboot_cmd()
        self.assertIn("osascript", cmd)
        self.assertNotIn("sudo", cmd)

    def test_linux_is_unchanged(self):
        os.name = "posix"
        sys.platform = "linux"
        self.assertEqual(launchers._reboot_cmd(), "systemctl reboot")


class ElevationOnWindowsTest(unittest.TestCase):
    """The manager's own tile asks for elevation on Windows, and nowhere else.

    apps.json is under Program Files there, so an unelevated tile can read
    everything and change nothing. Sunshine grants the rights to an entry marked
    "elevated" without a UAC prompt, because it is already SYSTEM -- so this one
    flag is the difference between a working install and a read-only one.

    On Linux and macOS the config directory belongs to the user, and asking for
    root would be asking for rights the program does not need.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.images = os.path.join(self.home, "images")
        os.makedirs(self.images)
        self.real_name = os.name

    def tearDown(self):
        os.name = self.real_name

    def entry(self, platform):
        os.name = platform
        with mock.patch.object(launchers, "_apps_ui",
                               return_value=("C:\\x\\sunshine-apps-ui.cmd", "")), \
             mock.patch.object(launchers, "_ensure_posters",
                               return_value={k: "" for k in ("desktop", "steam",
                                                             "heroic", "reboot")}):
            apps = import_launchers(self.home, self.home, self.images, {})
        return next(a for a in apps if a.get(MARKER, {}).get("id") == "apps-ui")

    def test_windows_asks_for_elevation(self):
        self.assertIs(self.entry("nt")["elevated"], True)

    def test_posix_does_not(self):
        self.assertIs(self.entry("posix")["elevated"], False)
