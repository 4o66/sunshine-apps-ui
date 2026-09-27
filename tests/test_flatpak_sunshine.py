"""Commands under Flathub's Sunshine, which runs them in its sandbox. #49.

Found on Ubuntu 26.04, 2026-09-27: our own tiles were put on the host, but a
Steam game tile failed -- "Couldn't run [/snap/bin/steam -applaunch 440]: No
such file or directory" -- and the Sunshine tiles we take over kept commands
that cannot run inside the Flatpak.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sunshine_apps_ui.core import artwork_sources, run  # noqa: E402
from sunshine_apps_ui.core.reconcile import tag  # noqa: E402
from sunshine_apps_ui.core.sources import launchers  # noqa: E402
from sunshine_apps_ui.core.sources import steam as steam_source  # noqa: E402

HOST = "flatpak-spawn --host "


class HostEntryTest(unittest.TestCase):
    def test_every_command_field_goes_to_the_host(self):
        entry = {"name": "x", "cmd": "steam -applaunch 1",
                 "detached": ["setsid steam steam://open/bigpicture"],
                 "prep-cmd": [{"do": "xrandr a", "undo": "xrandr b"}]}
        out = launchers.host_entry(entry, True)
        self.assertEqual(out["cmd"], HOST + "steam -applaunch 1")
        self.assertEqual(out["detached"], [HOST + "setsid steam steam://open/bigpicture"])
        self.assertEqual(out["prep-cmd"], [{"do": HOST + "xrandr a",
                                            "undo": HOST + "xrandr b"}])

    def test_it_is_left_alone_when_sunshine_is_not_sandboxed(self):
        entry = {"name": "x", "cmd": "steam -applaunch 1"}
        self.assertEqual(launchers.host_entry(entry, False), entry)

    def test_wrapping_twice_is_wrapping_once(self):
        """A second scan sees what the first wrote."""
        once = launchers.host_entry({"cmd": "steam"}, True)
        self.assertEqual(launchers.host_entry(once, True), once)

    def test_the_managers_own_tile_is_not_wrapped_again(self):
        ui = launchers._host_as_launched("/home/u/.local/bin/sunshine-apps-ui", True)
        self.assertEqual(launchers._host(ui, True), ui)

    def test_an_empty_prep_step_stays_empty(self):
        out = launchers.host_entry({"prep-cmd": [{"do": "", "undo": "x"}]}, True)
        self.assertEqual(out["prep-cmd"][0]["do"], "")


class CarryTakeoverCommandsTest(unittest.TestCase):
    def test_a_takeover_carries_the_commands_of_the_tile_it_claims(self):
        existing = [{"name": "Steam Big Picture", "image-path": "steam.png",
                     "detached": ["setsid steam steam://open/bigpicture"]}]
        wanted = [tag({"name": "Zz Steam Big Picture"}, "launcher", "steam-bigpicture")]
        claims = {"Steam Big Picture": ("launcher", "steam-bigpicture")}
        out = launchers.carry_takeover_commands(wanted, existing, claims)
        self.assertEqual(out[0]["detached"], ["setsid steam steam://open/bigpicture"])

    def test_and_so_does_one_already_ours(self):
        existing = [tag({"name": "Zz Steam Big Picture",
                         "detached": [HOST + "setsid steam x"]},
                        "launcher", "steam-bigpicture")]
        wanted = [tag({"name": "Zz Steam Big Picture"}, "launcher", "steam-bigpicture")]
        out = launchers.carry_takeover_commands(wanted, existing, {})
        self.assertEqual(out[0]["detached"], [HOST + "setsid steam x"])


class NoDownloads:
    def __init__(self, *args, **kwargs):
        pass

    def download_batch(self, tasks, desc=""):
        return {key: "" for key in tasks}


def library(root, appid="440", folder="Team Fortress 2"):
    steamapps = os.path.join(root, "steamapps")
    os.makedirs(os.path.join(steamapps, "common", folder))
    with open(os.path.join(steamapps, f"appmanifest_{appid}.acf"), "w") as handle:
        handle.write('"AppState"\n{\n\t"appid"\t\t"%s"\n\t"name"\t\t"TF2"\n'
                     '\t"installdir"\t\t"%s"\n}\n' % (appid, folder))


@unittest.skipIf(os.name == "nt", "Flatpak is Linux")
class ScanUnderFlatpakSunshineTest(unittest.TestCase):
    """The whole scan, dry, as Rescan runs it."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        for target, name, value in (
                (steam_source, "ImageDownloader", NoDownloads),
                (artwork_sources.sys, "platform", "linux")):
            patched = mock.patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        env = mock.patch.dict(os.environ, {"HOME": self.home,
                                           "XDG_STATE_HOME": os.path.join(self.home, "state")})
        env.start()
        self.addCleanup(env.stop)

    def conf(self, flatpak):
        conf = (os.path.join(self.home, ".var", "app", "dev.lizardbyte.app.Sunshine",
                             "config", "sunshine") if flatpak
                else os.path.join(self.home, ".config", "sunshine"))
        os.makedirs(conf)
        with open(os.path.join(conf, "apps.json"), "w") as handle:
            json.dump({"apps": [
                {"name": "Desktop", "image-path": "desktop.png"},
                {"name": "Steam Big Picture", "image-path": "steam.png",
                 "detached": ["setsid steam steam://open/bigpicture"]}]}, handle)
        return conf

    def plan(self, conf):
        doc = run.execute(conf, {"BSM_DRY_RUN": True, "BSM_RELOAD": False,
                                 "IMPORT_HEROIC": "0"}, home=self.home)
        entries = {}
        for key in ("added", "updated"):
            for item in doc["plan"].get(key) or []:
                entries[item["name"]] = item["entry"]
        return entries

    def test_a_game_tile_runs_on_the_host(self):
        library(os.path.join(self.home, ".local", "share", "Steam"))
        entries = self.plan(self.conf(flatpak=True))
        self.assertEqual(entries["TF2"]["cmd"], HOST + "steam -applaunch 440")

    def test_a_kept_sunshine_tile_runs_on_the_host(self):
        entries = self.plan(self.conf(flatpak=True))
        self.assertEqual(entries["Zz Steam Big Picture"]["detached"],
                         [HOST + "setsid steam steam://open/bigpicture"])

    def test_nothing_is_wrapped_for_a_native_sunshine(self):
        library(os.path.join(self.home, ".local", "share", "Steam"))
        entries = self.plan(self.conf(flatpak=False))
        self.assertEqual(entries["TF2"]["cmd"], "steam -applaunch 440")
        self.assertEqual(entries["Zz Steam Big Picture"]["detached"],
                         ["setsid steam steam://open/bigpicture"])

    def test_a_flatpak_steam_under_a_native_sunshine_needs_no_flatpak_spawn(self):
        """Ubuntu has no flatpak-spawn outside a sandbox."""
        library(os.path.join(self.home, ".var", "app", "com.valvesoftware.Steam",
                             ".local", "share", "Steam"))
        entries = self.plan(self.conf(flatpak=False))
        self.assertEqual(entries["TF2"]["cmd"],
                         "flatpak run com.valvesoftware.Steam steam -applaunch 440")

    def test_and_under_a_flatpak_sunshine_it_is_put_on_the_host_once(self):
        library(os.path.join(self.home, ".var", "app", "com.valvesoftware.Steam",
                             ".local", "share", "Steam"))
        entries = self.plan(self.conf(flatpak=True))
        self.assertEqual(entries["TF2"]["cmd"],
                         HOST + "flatpak run com.valvesoftware.Steam steam -applaunch 440")


if __name__ == "__main__":
    unittest.main()
