"""Steam as a snap, which is what Ubuntu's App Center installs. Issue #43.

Inside the snap Steam's home is ~/snap/steam/common, so its root is there and
nothing is made in the real home. Found on Ubuntu 26.04, 2026-09-26: the same
one-game library was imported from ~/.local/share/Steam and "not_found" from
the snap's root.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sunshine_apps_ui.core import artwork_sources  # noqa: E402
from sunshine_apps_ui.core.sources import steam as steam_source  # noqa: E402


class NoDownloads:
    """The artwork fetch, minus the network."""

    def __init__(self, *args, **kwargs):
        pass

    def download_batch(self, tasks, desc=""):
        return {key: "" for key in tasks}


def library(root, appid="440", name="Team Fortress 2", folder="Team Fortress 2"):
    """A library in the form Steam writes it, with one game installed."""
    steamapps = os.path.join(root, "steamapps")
    os.makedirs(os.path.join(steamapps, "common", folder))
    with open(os.path.join(steamapps, "libraryfolders.vdf"), "w") as handle:
        handle.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % root)
    with open(os.path.join(steamapps, f"appmanifest_{appid}.acf"), "w") as handle:
        handle.write('"AppState"\n{\n\t"appid"\t\t"%s"\n\t"name"\t\t"%s"\n'
                     '\t"installdir"\t\t"%s"\n}\n' % (appid, name, folder))


@unittest.skipIf(os.name == "nt", "snaps are Linux")
class SteamSnapTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.snap_root = os.path.join(self.home, "snap", "steam", "common",
                                      ".local", "share", "Steam")
        offline = mock.patch.object(steam_source, "ImageDownloader", NoDownloads)
        offline.start()
        self.addCleanup(offline.stop)
        # The root finder has a macOS branch; these are about Linux, and should
        # run on a Mac too.
        linux = mock.patch.object(artwork_sources.sys, "platform", "linux")
        linux.start()
        self.addCleanup(linux.stop)

    def scan(self):
        images = os.path.join(self.home, "images")
        os.makedirs(images, exist_ok=True)
        report = {}
        apps = steam_source.import_steam(self.home, self.home, images, {}, report)
        return apps, report

    def test_the_snaps_root_is_found(self):
        os.makedirs(self.snap_root)
        self.assertEqual(artwork_sources.find_steam_root(self.home),
                         (self.snap_root, "snap"))

    def test_its_games_are_imported(self):
        library(self.snap_root)
        apps, report = self.scan()
        self.assertEqual(report.get("status"), "ok")
        self.assertEqual([a["name"] for a in apps], ["Team Fortress 2"])

    def test_they_launch_through_the_snap_by_its_full_path(self):
        """Whether /snap/bin is on Sunshine's PATH is not ours to know."""
        library(self.snap_root)
        apps, _ = self.scan()
        self.assertEqual(apps[0]["cmd"], "/snap/bin/steam -applaunch 440")
        self.assertEqual(apps[0]["working-dir"], self.snap_root)

    def test_a_flatpak_still_comes_first(self):
        flatpak = os.path.join(self.home, ".var", "app", "com.valvesoftware.Steam",
                               ".local", "share", "Steam")
        os.makedirs(flatpak)
        os.makedirs(self.snap_root)
        self.assertEqual(artwork_sources.find_steam_root(self.home)[1], "flatpak")

    def test_a_native_steam_is_unchanged(self):
        native = os.path.join(self.home, ".local", "share", "Steam")
        library(native)
        apps, _ = self.scan()
        self.assertEqual(apps[0]["cmd"], "steam -applaunch 440")

    def test_the_steam_tile_runs_the_snap_by_its_full_path_too(self):
        from sunshine_apps_ui.core.sources import launchers
        os.makedirs(self.snap_root)
        fake_bin = os.path.join(self.home, "snap-bin-steam")
        open(fake_bin, "w").close()
        with mock.patch.object(launchers, "SNAP_STEAM_BIN", fake_bin), \
             mock.patch.object(launchers, "have_cmd", lambda name: name == "steam"):
            self.assertEqual(launchers._steam_cmd(self.home), (fake_bin, self.snap_root))

    def test_a_snap_root_without_the_snap_is_not_used(self):
        """A home copied or restored from another machine can hold the folder
        without the snap; a tile naming /snap/bin/steam would then do nothing."""
        from sunshine_apps_ui.core.sources import launchers
        os.makedirs(self.snap_root)
        with mock.patch.object(launchers, "SNAP_STEAM_BIN",
                               os.path.join(self.home, "absent")), \
             mock.patch.object(launchers, "have_cmd", lambda name: False):
            self.assertEqual(launchers._steam_cmd(self.home), ("", ""))


if __name__ == "__main__":
    unittest.main()
