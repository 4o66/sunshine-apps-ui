# SPDX-License-Identifier: GPL-3.0-or-later
"""What a generated entry's `cmd` has to say on Windows.

Sunshine decides how to run a command by looking at it
(`resolve_command_string`, `src/platform/windows/misc.cpp`):

* a **URL** is resolved through its registered scheme handler;
* a path ending **.exe** goes straight to `CreateProcess`;
* a bare name with **no extension** is handed to `CreateProcess` to find on
  `PATH`.

The third case is what these tests exist for. `steam -applaunch 3606890` is a
perfectly good Linux command and, on Windows, an entry that looks right on the
grid and does nothing when a gamepad presses it: there is no `steam` on PATH.
Found on the rig with a real Steam and a real game installed -- the importer
produced exactly that line.

The URL form is what Sunshine's own shipped Windows entry uses
(`steam://open/bigpicture`), and it names no path, so it also survives Steam
being moved to another drive.

These drive the real importers over a fabricated library; only the artwork
fetch is stood in for, because it is the one part that would reach the network.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core.sources import steam as steam_source  # noqa: E402


class NoDownloads:
    """The artwork fetch, minus the network."""

    def __init__(self, *args, **kwargs):
        pass

    def download_batch(self, tasks, desc=""):
        return {key: "" for key in tasks}


class SteamImportTest(unittest.TestCase):
    """Run the importer over a library shaped like the rig's."""

    APPID = "3606890"          # Upload Labs, the game actually installed there
    NAME = "Upload Labs"

    def setUp(self):
        self.real_name = os.name
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.images = os.path.join(self.tmp, "images")
        os.makedirs(self.images)

        steamapps = os.path.join(self.tmp, "steamapps")
        os.makedirs(steamapps)
        with open(os.path.join(steamapps, "appmanifest_%s.acf" % self.APPID), "w") as handle:
            handle.write('"AppState"\n{\n\t"appid"\t\t"%s"\n\t"name"\t\t"%s"\n'
                         '\t"installdir"\t\t"UploadLabs"\n}\n' % (self.APPID, self.NAME))
        # The importer only offers games that are actually on disk -- a manifest
        # alone means Steam knows about it, not that it is installed.
        os.makedirs(os.path.join(steamapps, "common", "UploadLabs"))

        patched = mock.patch.object(steam_source, "find_steam_root",
                                    return_value=(self.tmp, "native"))
        patched.start()
        self.addCleanup(patched.stop)
        offline = mock.patch.object(steam_source, "ImageDownloader", NoDownloads)
        offline.start()
        self.addCleanup(offline.stop)

    def tearDown(self):
        os.name = self.real_name

    def entry(self, platform):
        os.name = platform
        apps = steam_source.import_steam(self.tmp, self.tmp, self.images, {})
        return next(a for a in apps if a["name"] == self.NAME)

    def test_windows_launches_the_game_by_url(self):
        self.assertEqual(self.entry("nt")["cmd"], f"steam://rungameid/{self.APPID}")

    def test_windows_never_produces_a_bare_command_name(self):
        """A name with no extension is looked for on PATH, and there is no steam there."""
        command = self.entry("nt")["cmd"]
        self.assertNotEqual(command.split()[0], "steam")
        self.assertIn("://", command)

    def test_windows_names_no_path_so_moving_steam_does_not_break_it(self):
        command = self.entry("nt")["cmd"]
        self.assertNotIn("Program Files", command)
        self.assertNotIn("\\", command)

    def test_linux_is_unchanged(self):
        self.assertEqual(self.entry("posix")["cmd"],
                         f"steam -applaunch {self.APPID}")

    def test_the_game_is_still_found_and_named_either_way(self):
        for platform in ("nt", "posix"):
            entry = self.entry(platform)
            self.assertEqual(entry["name"], self.NAME)
            self.assertTrue(entry["working-dir"])


class HeroicConfigRootTest(unittest.TestCase):
    """Where Heroic keeps its config, which is not under $HOME on Windows.

    Measured on the rig: `%APPDATA%\\heroic`, with `gog_store\\installed.json`
    and `store_cache\\legendary_library.json` present. The importer looked only
    at `~/.config/heroic` and the Flatpak path, so on a Windows machine with
    Heroic installed it found nothing and reported that there was nothing there.
    """

    def setUp(self):
        self.real_name = os.name
        self.real_environ = dict(os.environ)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.images = os.path.join(self.tmp, "images")
        os.makedirs(self.images)

    def tearDown(self):
        os.name = self.real_name
        os.environ.clear()
        os.environ.update(self.real_environ)

    def run_import(self):
        from sunshine_apps_ui.core.sources import heroic as heroic_source
        report = {}
        heroic_source.import_heroic(self.tmp, self.tmp, self.images, {}, report)
        return report

    def test_it_finds_heroic_in_appdata(self):
        os.name = "nt"
        appdata = os.path.join(self.tmp, "Roaming")
        root = os.path.join(appdata, "heroic")
        os.makedirs(os.path.join(root, "gog_store"))
        with open(os.path.join(root, "gog_store", "installed.json"), "w") as handle:
            handle.write('{"installed": []}')
        os.environ["APPDATA"] = appdata

        report = self.run_import()
        self.assertEqual(report.get("status"), "ok")
        self.assertEqual(report.get("root"), root)

    def test_a_posix_layout_is_not_consulted_on_windows(self):
        """The dotted directory may exist on a machine that also ran WSL."""
        os.name = "nt"
        os.makedirs(os.path.join(self.tmp, ".config", "heroic"))
        os.environ["APPDATA"] = os.path.join(self.tmp, "Roaming")
        report = self.run_import()
        self.assertNotEqual(report.get("root"), os.path.join(self.tmp, ".config", "heroic"))

    def test_linux_still_looks_where_it_always_did(self):
        os.name = "posix"
        root = os.path.join(self.tmp, ".config", "heroic")
        os.makedirs(root)
        report = self.run_import()
        self.assertEqual(report.get("root"), root)


if __name__ == "__main__":
    unittest.main()
