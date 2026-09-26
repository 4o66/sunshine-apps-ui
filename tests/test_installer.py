# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing and removing this, without root and without a shell.

The install and uninstall scripts were bash. What they guaranteed is what is
tested here: the tile goes before the files, the copies of apps.json survive,
nothing needs root, and the original importer is refused rather than warned
about.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import installer  # noqa: E402


@unittest.skipIf(os.name == "nt",
                 "the ~/.local install model. Windows gets an installer of its own: issue #13")
class InstallTest(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prefix, True)
        nothing = mock.patch.object(installer.legacy, "destructive_installs",
                                    return_value=[])
        nothing.start()
        self.addCleanup(nothing.stop)

    def test_it_installs_where_it_was_asked_to(self):
        ok, _ = installer.install(self.prefix)
        self.assertTrue(ok)
        self.assertTrue(os.path.isdir(
            os.path.join(self.prefix, "share", "sunshine-apps-ui", "src")))

    def test_the_command_it_leaves_behind_runs_the_installed_copy(self):
        installer.install(self.prefix)
        command = os.path.join(self.prefix, "bin", "sunshine-apps-ui")
        self.assertTrue(os.access(command, os.X_OK))
        with open(command, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(os.path.join(self.prefix, "share", "sunshine-apps-ui", "src"),
                      text)

    def test_tests_are_not_installed(self):
        """What is needed to run it. Tests and git history are not."""
        installer.install(self.prefix)
        self.assertFalse(os.path.exists(
            os.path.join(self.prefix, "share", "sunshine-apps-ui", "tests")))

    def test_the_upstream_notice_travels_with_the_code_it_covers(self):
        installer.install(self.prefix)
        for name in ("LICENSE", "LICENSE.upstream-MIT", "NOTICE"):
            self.assertTrue(os.path.exists(
                os.path.join(self.prefix, "share", "sunshine-apps-ui", name)), name)

    def test_installing_twice_replaces_rather_than_accumulates(self):
        installer.install(self.prefix)
        stray = os.path.join(self.prefix, "share", "sunshine-apps-ui", "src",
                             "stray.py")
        open(stray, "w").close()
        installer.install(self.prefix)
        self.assertFalse(os.path.exists(stray))

    def test_installing_from_the_installed_copy_leaves_it_whole(self):
        """Source and target the same directory used to delete src/ and then fail."""
        installer.install(self.prefix)
        installed = os.path.join(self.prefix, "share", "sunshine-apps-ui")
        with mock.patch.object(installer, "_source_root", return_value=installed):
            ok, messages = installer.install(self.prefix)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(
            os.path.join(installed, "src", "sunshine_apps_ui", "__init__.py")))
        self.assertTrue(any("left as they are" in m for m in messages))

    def test_nothing_needs_root(self):
        """Installing the program needs no root.

        One line may still *mention* sudo: the optional offer to install the
        distribution's GTK typelibs, which is not installing this program and
        says so. What must never appear is a step of the install itself that
        needs privileges.
        """
        ok, messages = installer.install(self.prefix)
        self.assertTrue(ok)
        for line in messages:
            if "sudo" in line.lower():
                joined = "\n".join(messages).lower()
                self.assertIn("faster window", joined,
                              "sudo appeared outside the optional toolkit offer")
            else:
                self.assertNotIn("root", line.lower())


class RefusingTheOriginalTest(unittest.TestCase):
    """It rewrites apps.json wholesale, so the two cannot both be installed."""

    def setUp(self):
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prefix, True)
        self.found = [{"root": "/home/u/.config/sunshine/helper",
                       "command": "/home/u/.config/sunshine/helper/x.sh",
                       "kind": "original", "destructive": True}]
        patched = mock.patch.object(installer.legacy, "destructive_installs",
                                    return_value=self.found)
        patched.start()
        self.addCleanup(patched.stop)
        plan = mock.patch.object(installer.legacy, "removal_plan",
                                 return_value=["/home/u/.config/sunshine/helper"])
        plan.start()
        self.addCleanup(plan.stop)

    def test_saying_no_installs_nothing(self):
        ok, messages = installer.install(self.prefix, confirm=lambda text, question: False)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "bin")))
        self.assertTrue(any("Nothing was installed" in m for m in messages))

    def test_what_would_be_removed_is_shown_before_asking(self):
        shown = {}
        installer.install(self.prefix,
                          confirm=lambda text, question: shown.setdefault("text", text) and False)
        self.assertIn("would remove:", shown["text"])
        self.assertIn("rewrites apps.json from scratch", shown["text"])

    def test_sunshines_own_web_ui_is_not_accused_along_with_it(self):
        shown = {}
        installer.install(self.prefix,
                          confirm=lambda text, question: shown.setdefault("text", text) and False)
        self.assertIn("safe to use", shown["text"])

    def test_saying_yes_removes_it_and_installs(self):
        with mock.patch.object(installer, "_remove", return_value=True) as removed:
            ok, _ = installer.install(self.prefix, confirm=lambda text, question: True)
        self.assertTrue(ok)
        self.assertTrue(any("helper" in str(call) for call in removed.mock_calls))


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prefix, True)
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state, True)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state})
        env.start()
        self.addCleanup(env.stop)
        quiet = mock.patch("sunshine_apps_ui.launcher.stop_previous")
        quiet.start()
        self.addCleanup(quiet.stop)
        nothing = mock.patch.object(installer.legacy, "destructive_installs",
                                    return_value=[])
        nothing.start()
        self.addCleanup(nothing.stop)
        self.backups = os.path.join(self.state, "sunshine-apps-ui", "backups")
        os.makedirs(self.backups)
        open(os.path.join(self.backups, "apps-20260915-101500.json"), "w").close()
        os.makedirs(os.path.join(self.state, "sunshine-apps-ui"), exist_ok=True)
        with open(os.path.join(self.state, "sunshine-apps-ui", "queue.json"), "w") as h:
            h.write("[]")

    def _installed(self):
        installer.install(self.prefix)

    def test_the_tile_goes_before_the_files(self):
        """The other order leaves a tile pointing at a command that is gone."""
        order = []
        with mock.patch.object(installer, "_remove_tile",
                               side_effect=lambda: (order.append("tile"), (True, "ok"))[1]), \
             mock.patch.object(installer, "_remove",
                               side_effect=lambda p: order.append("files") or True):
            installer.uninstall(self.prefix)
        self.assertEqual(order[0], "tile")

    def test_a_tile_that_will_not_go_stops_the_uninstall(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile",
                               return_value=(False, "could not")):
            ok, messages = installer.uninstall(self.prefix)
        self.assertFalse(ok)
        # Asked of the installer, not spelled out: Windows installs to one
        # directory rather than a share/bin split.
        self.assertTrue(os.path.isdir(installer.paths(self.prefix)["install"]))
        self.assertTrue(any("Leaving the files in place" in m for m in messages))

    def test_the_copies_of_apps_json_are_kept(self):
        """They are copies of your configuration, not of this program."""
        self._installed()
        with mock.patch.object(installer, "_remove_tile", return_value=(True, "ok")):
            ok, messages = installer.uninstall(self.prefix)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(
            os.path.join(self.backups, "apps-20260915-101500.json")))
        self.assertTrue(any("Kept" in m and "backups" in m for m in messages))

    def test_the_rest_of_the_state_does_go(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile", return_value=(True, "ok")):
            installer.uninstall(self.prefix)
        self.assertFalse(os.path.exists(
            os.path.join(self.state, "sunshine-apps-ui", "queue.json")))

    def test_purging_takes_the_copies_too_for_someone_who_means_it(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile", return_value=(True, "ok")):
            installer.uninstall(self.prefix, purge_backups=True)
        self.assertFalse(os.path.exists(self.backups))

    def test_keeping_state_keeps_everything(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile", return_value=(True, "ok")):
            installer.uninstall(self.prefix, keep_state=True)
        self.assertTrue(os.path.exists(
            os.path.join(self.state, "sunshine-apps-ui", "queue.json")))

    def test_keeping_the_tile_leaves_apps_json_alone(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile") as tile:
            installer.uninstall(self.prefix, keep_tile=True)
        self.assertFalse(tile.called)

    def test_the_files_and_the_command_are_removed(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile", return_value=(True, "ok")):
            installer.uninstall(self.prefix)
        self.assertFalse(os.path.exists(
            os.path.join(self.prefix, "share", "sunshine-apps-ui")))
        self.assertFalse(os.path.exists(
            os.path.join(self.prefix, "bin", "sunshine-apps-ui")))

    def test_it_says_what_it_did_not_touch(self):
        self._installed()
        with mock.patch.object(installer, "_remove_tile", return_value=(True, "ok")):
            _, messages = installer.uninstall(self.prefix)
        self.assertTrue(any("is untouched" in m for m in messages))


class TileRemovalTest(unittest.TestCase):
    """The tile is found by its ownership marker, because renaming it is allowed."""

    def test_it_is_found_by_marker_not_by_name(self):
        state = {"apps": [{"index": 0, "name": "Renamed By Someone",
                           "source": "launcher", "id": "apps-ui"}]}
        with mock.patch("sunshine_apps_ui.core.api.config_dir", return_value="/c"), \
             mock.patch("sunshine_apps_ui.core.api.state", return_value=state), \
             mock.patch("sunshine_apps_ui.core.api.mutate",
                        return_value=(True, "Applied 1 change(s)", [])) as mutate:
            ok, _ = installer._remove_tile()
        self.assertTrue(ok)
        self.assertEqual(mutate.call_args[0][1][0]["name"], "Renamed By Someone")

    def test_no_tile_is_not_a_failure(self):
        with mock.patch("sunshine_apps_ui.core.api.config_dir", return_value="/c"), \
             mock.patch("sunshine_apps_ui.core.api.state", return_value={"apps": []}):
            ok, message = installer._remove_tile()
        self.assertTrue(ok)
        self.assertIn("No tile to remove", message)

    def test_an_unreadable_app_list_is_a_failure_rather_than_a_shrug(self):
        with mock.patch("sunshine_apps_ui.core.api.config_dir", return_value="/c"), \
             mock.patch("sunshine_apps_ui.core.api.state",
                        side_effect=OSError("apps.json is gone")):
            ok, message = installer._remove_tile()
        self.assertFalse(ok)
        self.assertIn("apps.json is gone", message)


if __name__ == "__main__":
    unittest.main()


class HiddenTileTest(unittest.TestCase):
    """A hidden tile does not come back on its own, so installing offers.

    Deleting the tile and hiding it look the same from Sunshine, but only one
    of them is recorded. A deletion leaves nothing behind, so the next scan
    treats the launcher as new and adds it; a hide writes a tombstone that
    every later scan obeys. Reinstalling to get the tile back therefore works
    in one case and silently does nothing in the other.
    """

    def setUp(self):
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prefix, True)
        nothing = mock.patch.object(installer.legacy, "destructive_installs",
                                    return_value=[])
        nothing.start()
        self.addCleanup(nothing.stop)

        from sunshine_apps_ui.core import api
        self.api = api
        self.conf = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.conf, True)
        self.mutations = []

        patches = [
            mock.patch.object(api, "config_dir", return_value=self.conf),
            mock.patch.object(api, "mutate", side_effect=self._mutate),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _mutate(self, conf_dir, ops, reload=True):
        self.mutations.extend(ops)
        return True, "restored", []

    def _hidden(self, *tombstones):
        return mock.patch.object(self.api, "state",
                                 return_value={"apps": [], "hidden": list(tombstones)})

    TILE = {"name": "Z App Manager", "source": "launcher", "id": "apps-ui"}

    def test_a_hidden_tile_is_offered_back(self):
        asked = []
        with self._hidden(self.TILE):
            ok, messages = installer.install(
                self.prefix,
                confirm=lambda text, question: asked.append(question) or True)
        self.assertTrue(ok)
        self.assertEqual(
            self.mutations,
            [{"op": "restore", "selector": "launcher:apps-ui"}])
        self.assertTrue(any("Z App Manager" in q for q in asked), asked)
        self.assertTrue(any("Unhid" in m for m in messages), messages)

    def test_saying_no_leaves_it_hidden(self):
        """The tombstone is a decision. Installing does not overrule it."""
        with self._hidden(self.TILE):
            ok, messages = installer.install(
                self.prefix, confirm=lambda text, question: False)
        self.assertTrue(ok, "declining the offer must not fail the install")
        self.assertEqual(self.mutations, [])
        self.assertTrue(any("Left hidden" in m for m in messages), messages)

    def test_nobody_to_ask_means_say_so_rather_than_decide(self):
        with self._hidden(self.TILE):
            ok, messages = installer.install(self.prefix, confirm=None)
        self.assertTrue(ok)
        self.assertEqual(self.mutations, [])
        joined = "\n".join(messages)
        self.assertIn("hidden", joined)
        self.assertIn("--put-the-tile-back-because-i-deleted-it", joined,
                      "the note should say why the obvious flag will not help")

    def test_nothing_is_said_when_the_tile_is_not_hidden(self):
        """Silence is the normal case; an install should not nag."""
        with self._hidden():
            ok, messages = installer.install(
                self.prefix, confirm=lambda text, question: True)
        self.assertTrue(ok)
        self.assertEqual(self.mutations, [])
        self.assertNotIn("hidden", "\n".join(messages))

    def test_another_hidden_app_is_not_mistaken_for_the_tile(self):
        with self._hidden({"name": "Portal", "source": "steam", "id": "400"}):
            ok, messages = installer.install(
                self.prefix, confirm=lambda text, question: True)
        self.assertTrue(ok)
        self.assertEqual(self.mutations, [],
                         "only this manager's own tile is the installer's business")

    def test_an_unreadable_config_does_not_fail_the_install(self):
        with mock.patch.object(self.api, "state", side_effect=OSError("no")):
            ok, _ = installer.install(
                self.prefix, confirm=lambda text, question: True)
        self.assertTrue(ok)

    def test_a_suppressed_tile_says_the_tombstone_is_gone_not_that_it_is_back(self):
        """Suppress keeps no entry, so clearing it unblocks rather than restores."""
        states = [
            {"apps": [], "hidden": [self.TILE]},   # before: hidden, no entry kept
            {"apps": [], "hidden": []},            # after: unblocked, still no tile
        ]
        with mock.patch.object(self.api, "state", side_effect=states):
            ok, messages = installer.install(
                self.prefix, confirm=lambda text, question: True)
        self.assertTrue(ok)
        joined = "\n".join(messages)
        self.assertIn("no kept copy", joined)
        self.assertIn("--put-the-tile-back-because-i-deleted-it", joined)

    def test_a_hidden_tile_that_comes_straight_back_says_so_plainly(self):
        states = [
            {"apps": [], "hidden": [self.TILE]},
            {"apps": [dict(self.TILE)], "hidden": []},
        ]
        with mock.patch.object(self.api, "state", side_effect=states):
            ok, messages = installer.install(
                self.prefix, confirm=lambda text, question: True)
        self.assertTrue(ok)
        joined = "\n".join(messages)
        self.assertIn("Unhid Z App Manager.", joined)
        self.assertNotIn("no kept copy", joined)
