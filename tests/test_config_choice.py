# SPDX-License-Identifier: GPL-3.0-or-later
"""Saying which Sunshine config tree is in use, and letting it be changed.

Issue #19. Ranking by liveness was already there; what these cover is the part
that was missing: telling a judgment from a fact, a choice that stops counting
once its reason has gone, and a page that says which tree it picked when there
was more than one.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sunshine_apps_ui import engine, render, state  # noqa: E402
from sunshine_apps_ui.core import api, liveness  # noqa: E402
from unittest import mock  # noqa: E402
from sunshine_apps_ui.server import serve  # noqa: E402

import test_server  # noqa: E402

FLATPAK = os.path.join(".var", "app", "dev.lizardbyte.app.Sunshine", "config", "sunshine")
NATIVE = os.path.join(".config", "sunshine")


class Homes:
    """A home directory with config trees in it, used or not."""

    def __init__(self):
        self.home = tempfile.mkdtemp()

    def tree(self, relative, used_at=None, apps=0):
        path = os.path.join(self.home, relative)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "apps.json"), "w") as f:
            json.dump({"apps": [{"name": f"app {i}"} for i in range(apps)]}, f)
        if used_at is not None:
            log = os.path.join(path, "sunshine.log")
            open(log, "w").close()
            os.utime(log, (used_at, used_at))
        return path

    def cleanup(self):
        shutil.rmtree(self.home, ignore_errors=True)


@unittest.skipIf(os.name == "nt", "the POSIX candidate list; Windows has its own")
class ConfigChoiceTest(unittest.TestCase):
    def setUp(self):
        self.homes = Homes()
        self.addCleanup(self.homes.cleanup)
        self.home = self.homes.home
        self._override = os.environ.pop("SUNSHINE_CONF_DIR", None)
        # Nothing about this machine's own Sunshine leaks into these.
        quiet = mock.patch.object(liveness, "evidence",
                                  lambda home: {"running": [], "service": []})
        quiet.start()
        self.addCleanup(quiet.stop)

    def tearDown(self):
        if self._override is not None:
            os.environ["SUNSHINE_CONF_DIR"] = self._override

    def test_no_tree_at_all_is_the_native_default(self):
        choice = api.config_choice(self.home)
        self.assertEqual(choice["how"], "none")
        self.assertEqual(choice["chosen"], os.path.join(self.home, NATIVE))

    def test_one_tree_is_a_fact(self):
        native = self.homes.tree(NATIVE, used_at=1000)
        choice = api.config_choice(self.home)
        self.assertEqual((choice["how"], choice["chosen"]), ("only", native))

    def test_the_newest_wins_and_says_it_was_a_judgment(self):
        self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        choice = api.config_choice(self.home)
        self.assertEqual((choice["how"], choice["chosen"]), ("newest", native))
        self.assertEqual([c["path"] for c in choice["candidates"]][0], native)

    def test_two_trees_never_used_are_a_tie(self):
        """A fresh install beside an abandoned one: exactly the case ranking cannot answer."""
        self.homes.tree(FLATPAK)
        self.homes.tree(NATIVE)
        self.assertEqual(api.config_choice(self.home)["how"], "tie")

    def test_two_trees_used_at_the_same_moment_are_a_tie(self):
        self.homes.tree(FLATPAK, used_at=1500)
        self.homes.tree(NATIVE, used_at=1500)
        self.assertEqual(api.config_choice(self.home)["how"], "tie")

    def test_the_override_is_not_second_guessed(self):
        self.homes.tree(FLATPAK, used_at=1000)
        self.homes.tree(NATIVE, used_at=2000)
        os.environ["SUNSHINE_CONF_DIR"] = "/somewhere/else"
        try:
            choice = api.config_choice(self.home)
        finally:
            os.environ.pop("SUNSHINE_CONF_DIR")
        self.assertEqual((choice["how"], choice["chosen"]), ("override", "/somewhere/else"))

    def test_a_choice_beats_the_ranking(self):
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        self.homes.tree(NATIVE, used_at=2000)
        choice = api.config_choice(self.home, {"path": flatpak, "at": 3000})
        self.assertEqual((choice["how"], choice["chosen"]), ("preferred", flatpak))

    def test_a_choice_breaks_a_tie(self):
        flatpak = self.homes.tree(FLATPAK)
        self.homes.tree(NATIVE)
        choice = api.config_choice(self.home, {"path": flatpak, "at": time.time()})
        self.assertEqual((choice["how"], choice["chosen"]), ("preferred", flatpak))

    def test_a_choice_lapses_once_another_tree_is_used_after_it(self):
        """Otherwise pinning a tree is how the abandoned-Flatpak bug comes back."""
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=5000)
        choice = api.config_choice(self.home, {"path": flatpak, "at": 3000})
        self.assertEqual(choice["chosen"], native)
        self.assertTrue(choice["stale"])
        self.assertEqual(choice["was"], flatpak)

    def test_a_choice_that_no_longer_exists_lapses(self):
        self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        gone = os.path.join(self.home, "nowhere")
        choice = api.config_choice(self.home, {"path": gone, "at": 3000})
        self.assertEqual((choice["chosen"], choice["stale"]), (native, True))

    def test_config_dir_still_returns_just_the_path(self):
        native = self.homes.tree(NATIVE, used_at=2000)
        self.homes.tree(FLATPAK, used_at=1000)
        self.assertEqual(api.config_dir(self.home), native)


class TreeKindTest(unittest.TestCase):
    def test_a_flatpak_tree_is_named_by_its_app_id(self):
        self.assertEqual(render._tree_kind(f"/home/u/{FLATPAK}"),
                         "Flatpak (dev.lizardbyte.app.Sunshine)")

    def test_two_windows_installs_are_told_apart_by_their_folders(self):
        """The Windows rig showed "Installed beside Sunshine" twice."""
        self.assertEqual(render._tree_kind(r"C:\Program Files\Sunshine\config"),
                         r"Installed in C:\Program Files\Sunshine")
        self.assertEqual(render._tree_kind(r"C:\SunshinePortable\config"),
                         r"Installed in C:\SunshinePortable")

    def test_the_native_tree_is_not_called_a_flatpak(self):
        """The native RPM's unit name looks like a Flatpak's. Its tree does not."""
        self.assertEqual(render._tree_kind(f"/home/u/{NATIVE}"),
                         "Installed from a package")


@unittest.skipIf(os.name == "nt", "the POSIX candidate list; Windows has its own")
class SwitchTest(test_server.ServerTest):
    """The grid says which tree it is showing, and the other can be chosen."""

    def setUp(self):
        super().setUp()
        self._override = os.environ.pop("SUNSHINE_CONF_DIR", None)
        self.homes = Homes()
        self.addCleanup(self.homes.cleanup)
        self.evidence = {"running": [], "service": []}
        quiet = mock.patch.object(liveness, "evidence", lambda home: self.evidence)
        quiet.start()
        self.addCleanup(quiet.stop)

    def tearDown(self):
        super().tearDown()
        if self._override is not None:
            os.environ["SUNSHINE_CONF_DIR"] = self._override

    def restart(self, choice=None):
        """Serve again, with the choice main() would have made for this home."""
        self.httpd.shutdown()
        self.httpd.server_close()
        choice = choice or engine.config_choice(self.homes.home)
        self.httpd = serve(self.token, choice["chosen"], {}, port=0,
                           choice=choice, config_home=self.homes.home)
        self.httpd.daemon_threads = False
        self.httpd.block_on_close = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def in_use(self):
        return self.httpd.RequestHandlerClass.conf_dir

    def switch(self, path, back=""):
        return self.post({"path": path, "back": back}, token=self.token,
                         path="/config-dir")

    def test_one_tree_says_nothing_on_the_grid(self):
        self.homes.tree(NATIVE, used_at=2000)
        self.restart()
        _, body = self.get(f"/?token={self.token}")
        self.assertNotIn("Sunshine config here", body)
        self.assertNotIn("Which Sunshine is", body)

    def test_a_tie_asks(self):
        self.homes.tree(FLATPAK, apps=0)
        self.homes.tree(NATIVE, apps=12)
        self.restart()
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("Which Sunshine is this machine running?", body)
        self.assertIn("none of them has been used yet", body)
        self.assertIn("12 apps", body)
        self.assertIn('action="/config-dir?token=', body)

    def test_the_newest_is_said_and_can_be_kept(self):
        self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        self.restart()
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("More than one Sunshine config here", body)
        self.assertIn("Keep this one", body)

        status, headers = self.switch(native)
        self.assertEqual(status, 303)
        self.assertEqual(self.in_use(), native)
        _, body = self.get(f"/?token={self.token}")
        self.assertNotIn("More than one Sunshine config here", body)
        self.assertEqual(state.prefs()["config_dir"]["path"], native)

    def test_choosing_the_other_switches_the_running_server(self):
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        self.restart()
        self.assertEqual(self.in_use(), native)
        status, _ = self.switch(flatpak)
        self.assertEqual(status, 303)
        self.assertEqual(self.in_use(), flatpak)
        # And the next launch starts there too.
        self.assertEqual(engine.config_choice(self.homes.home)["chosen"], flatpak)

    def test_a_path_that_was_not_offered_is_refused(self):
        """The path comes from a form. A tree we did not find is not one to write to."""
        self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        self.restart()
        self.switch("/etc")
        self.assertEqual(self.in_use(), native)
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("not one of the Sunshine config directories", body)

    def test_queued_changes_hold_the_switch(self):
        """They were worked out against this tree's apps.json, by position."""
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        self.restart()
        state.enqueue({"op": "hide", "index": 0, "name": "x"})
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("disabled>Use this one", body)
        self.switch(flatpak)
        self.assertEqual(self.in_use(), native)
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("Apply or discard it first", body)

    def test_settings_lists_the_trees_and_returns_there(self):
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        self.homes.tree(NATIVE, used_at=2000)
        self.restart()
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("<h3>Which Sunshine</h3>", body)
        self.assertIn("Flatpak (dev.lizardbyte.app.Sunshine)", body)
        status, headers = self.switch(flatpak, back="settings")
        self.assertTrue(headers["Location"].startswith("/settings?"))

    def test_the_argument_cannot_be_switched_away_from(self):
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        native = self.homes.tree(NATIVE, used_at=2000)
        self.restart({"chosen": native, "how": "argument", "candidates": [],
                      "stale": False})
        self.switch(flatpak)
        self.assertEqual(self.in_use(), native)
        _, body = self.get(f"/settings?token={self.token}")
        self.assertIn("Set by <code>--conf-dir</code>", body)

    def test_a_lapsed_choice_is_said_rather_than_silently_dropped(self):
        flatpak = self.homes.tree(FLATPAK, used_at=1000)
        self.homes.tree(NATIVE, used_at=5000)
        state.set_pref("config_dir", {"path": flatpak, "at": 3000})
        self.restart()
        _, body = self.get(f"/?token={self.token}")
        self.assertIn("The config you chose earlier has been set aside", body)
        self.assertIn(flatpak, body)


if __name__ == "__main__":
    unittest.main()
