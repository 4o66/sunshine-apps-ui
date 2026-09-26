# SPDX-License-Identifier: GPL-3.0-or-later
"""Asking Sunshine which config tree is live, rather than trusting mtimes. #19.

The shapes here are the Bazzite box's, 2026-09-26: a native /usr/bin/sunshine
whose fds and environment are unreadable (it holds file capabilities), run by
a unit named like a Flatpak's.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from sunshine_apps_ui import render  # noqa: E402
from sunshine_apps_ui.core import api, liveness  # noqa: E402

HOME = "/home/u"
NATIVE = "/home/u/.config/sunshine"
FLATPAK = "/home/u/.var/app/dev.lizardbyte.app.Sunshine/config/sunshine"

# What `systemctl --user show -p Id -p ExecStart` printed on the box.
BOX_SHOW = """Id=app-dev.lizardbyte.app.Sunshine.service
ExecStart={ path=/usr/bin/sunshine ; argv[]=/usr/bin/sunshine ; ignore_errors=no ; start_time=[Sat 2026-09-12 23:04:28 PDT] ; stop_time=[n/a] ; pid=58580 ; code=(null) ; status=0/0 }

Id=app-dev.lizardbyte.app.Sunshine@autostart.service
ExecStart={ path=/usr/bin/env ; argv[]=/usr/bin/env systemctl start --u sunshine ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }

Id=steam.service
ExecStart={ path=/usr/bin/steam ; argv[]=/usr/bin/steam -silent ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }
"""


class CommandTest(unittest.TestCase):
    def test_the_native_binary_reads_the_native_tree(self):
        self.assertEqual(liveness.tree_for_command(["/usr/bin/sunshine"], HOME), [NATIVE])

    def test_xdg_config_home_is_respected_when_it_can_be_read(self):
        trees = liveness.tree_for_command(["/usr/bin/sunshine"], HOME,
                                          {"XDG_CONFIG_HOME": "/cfg"})
        self.assertEqual(trees, ["/cfg/sunshine"])

    def test_a_config_file_argument_names_the_tree(self):
        trees = liveness.tree_for_command(["sunshine", "/srv/sun/sunshine.conf"], HOME)
        self.assertEqual(trees, ["/srv/sun"])

    def test_flatpak_run_names_its_app(self):
        trees = liveness.tree_for_command(
            ["/usr/bin/flatpak", "run", "--branch=stable", "dev.lizardbyte.app.Sunshine"], HOME)
        self.assertEqual(trees, [FLATPAK])

    def test_a_sandboxed_binary_with_a_known_id(self):
        trees = liveness.tree_for_command(["/app/bin/sunshine"], HOME,
                                          flatpak_id="dev.lizardbyte.app.Sunshine")
        self.assertEqual(trees, [FLATPAK])

    def test_a_sandboxed_binary_without_one_could_be_either_flatpak(self):
        trees = liveness.tree_for_command(["/app/bin/sunshine"], HOME)
        self.assertEqual(len(trees), 2)

    def test_the_autostart_shim_is_not_sunshine(self):
        """Named like a Flatpak, and it only starts the native unit."""
        self.assertEqual(liveness.tree_for_command(
            ["/usr/bin/env", "systemctl", "start", "--u", "sunshine"], HOME), [])

    def test_another_flatpak_is_not_sunshine(self):
        self.assertEqual(liveness.tree_for_command(
            ["flatpak", "run", "com.valvesoftware.Steam"], HOME), [])


class ServiceTest(unittest.TestCase):
    def test_the_boxs_units_point_at_the_native_tree(self):
        """app-dev.lizardbyte.app.Sunshine.service is the native RPM, not a Flatpak."""
        def systemctl(args):
            if args[0] == "list-unit-files":
                return ("app-dev.lizardbyte.app.Sunshine.service enabled disabled\n"
                        "steam.service enabled enabled\n")
            return BOX_SHOW

        self.assertEqual(liveness.service_trees(HOME, systemctl), [NATIVE])

    def test_no_enabled_units_is_no_answer(self):
        self.assertEqual(liveness.service_trees(HOME, lambda args: ""), [])


@unittest.skipIf(os.name == "nt", "a /proc")
class RunningTest(unittest.TestCase):
    """A fake /proc, spelled the way the box's is."""

    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proc, True)

    def process(self, pid, comm, argv, environ=None, flatpak_id=""):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "comm"), "w") as f:
            f.write(comm + "\n")
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in argv) + b"\0")
        if environ is not None:
            with open(os.path.join(d, "environ"), "wb") as f:
                f.write(b"\0".join(f"{k}={v}".encode() for k, v in environ.items()))
        if flatpak_id:
            os.makedirs(os.path.join(d, "root"))
            with open(os.path.join(d, "root", ".flatpak-info"), "w") as f:
                f.write(f"[Application]\nname={flatpak_id}\n")

    def test_the_native_process_is_found_from_its_command_line_alone(self):
        """No environ file: it is unreadable for the capability-holding binary."""
        self.process(58580, "sunshine", ["/usr/bin/sunshine"])
        self.process(100, "bash", ["bash"])
        self.assertEqual(liveness.running_trees(HOME, self.proc), [NATIVE])

    def test_a_flatpak_process_is_found_by_its_app_id(self):
        self.process(7, "sunshine", ["/app/bin/sunshine"],
                     flatpak_id="dev.lizardbyte.app.Sunshine")
        self.assertEqual(liveness.running_trees(HOME, self.proc), [FLATPAK])

    def test_nothing_running_is_nothing(self):
        self.process(100, "bash", ["bash"])
        self.assertEqual(liveness.running_trees(HOME, self.proc), [])


@unittest.skipIf(os.name == "nt", "the POSIX candidate list")
class PrecedenceTest(unittest.TestCase):
    """Sunshine's own word, then a choice, then its service, then mtimes."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self._override = os.environ.pop("SUNSHINE_CONF_DIR", None)
        self.native = os.path.join(self.home, ".config", "sunshine")
        self.flatpak = os.path.join(self.home, ".var", "app",
                                    "dev.lizardbyte.app.Sunshine", "config", "sunshine")
        for tree in (self.native, self.flatpak):
            os.makedirs(tree)

    def tearDown(self):
        if self._override is not None:
            os.environ["SUNSHINE_CONF_DIR"] = self._override

    def used(self, tree, at):
        path = os.path.join(tree, "sunshine.log")
        open(path, "w").close()
        os.utime(path, (at, at))

    def choose(self, preferred=None, running=(), service=()):
        return api.config_choice(self.home, preferred,
                                 {"running": list(running), "service": list(service)})

    def test_running_beats_the_newest(self):
        """Something touched the abandoned tree's files more recently. Sunshine knows better."""
        self.used(self.flatpak, 5000)
        self.used(self.native, 1000)
        choice = self.choose(running=[self.native])
        self.assertEqual((choice["how"], choice["chosen"]), ("running", self.native))

    def test_the_service_settles_a_fresh_install_beside_an_abandoned_one(self):
        """The case #19 began with: newest would pick the abandoned Flatpak."""
        self.used(self.flatpak, 1000)          # an old log from the Flatpak
        choice = self.choose(service=[self.native])
        self.assertEqual((choice["how"], choice["chosen"]), ("service", self.native))

    def test_the_service_settles_a_tie(self):
        choice = self.choose(service=[self.native])
        self.assertEqual(choice["how"], "service")

    def test_a_choice_beats_the_service(self):
        choice = self.choose({"path": self.flatpak, "at": time.time()},
                             service=[self.native])
        self.assertEqual((choice["how"], choice["chosen"]), ("preferred", self.flatpak))

    def test_but_not_what_is_running(self):
        choice = self.choose({"path": self.flatpak, "at": time.time()},
                             running=[self.native])
        self.assertEqual((choice["how"], choice["chosen"]), ("running", self.native))
        self.assertTrue(choice["stale"])
        self.assertEqual(choice["stale_reason"], "running")
        self.assertEqual(choice["was"], self.flatpak)

    def test_a_running_tree_nobody_listed_becomes_a_candidate(self):
        custom = os.path.join(self.home, "elsewhere")
        os.makedirs(custom)
        choice = self.choose(running=[custom])
        self.assertEqual(choice["chosen"], custom)
        self.assertIn(custom, [c["path"] for c in choice["candidates"]])

    def test_evidence_for_a_tree_that_does_not_exist_is_ignored(self):
        self.used(self.native, 2000)
        self.used(self.flatpak, 1000)
        choice = self.choose(running=[os.path.join(self.home, "gone")])
        self.assertEqual(choice["how"], "newest")

    def test_no_tree_asks_nothing(self):
        shutil.rmtree(self.flatpak)
        shutil.rmtree(self.native)
        calls = []
        real = liveness.evidence
        liveness.evidence = lambda home: calls.append(home) or {}
        try:
            api.config_choice(self.home)
        finally:
            liveness.evidence = real
        self.assertEqual(calls, [])

    def test_a_service_for_a_tree_not_made_yet_is_reported(self):
        """#19's own case: the native install has never run, the Flatpak's tree is left."""
        shutil.rmtree(self.native)
        self.used(self.flatpak, 1000)
        choice = self.choose(service=[self.native])
        self.assertEqual((choice["how"], choice["chosen"]), ("only", self.flatpak))
        self.assertEqual(choice["missing"], self.native)

    def test_nothing_is_missing_when_the_service_agrees(self):
        shutil.rmtree(self.native)
        choice = self.choose(service=[self.flatpak])
        self.assertNotIn("missing", choice)


class WordingTest(unittest.TestCase):
    CANDIDATES = [{"path": NATIVE, "last_used": 0, "apps": 4},
                  {"path": FLATPAK, "last_used": 0, "apps": 1}]

    def test_running_needs_no_banner(self):
        config = {"how": "running", "chosen": NATIVE, "candidates": self.CANDIDATES}
        self.assertEqual(render.config_banner(config, "t"), "")

    def test_nor_does_a_service(self):
        config = {"how": "service", "chosen": NATIVE, "candidates": self.CANDIDATES}
        self.assertEqual(render.config_banner(config, "t"), "")

    def test_a_choice_overruled_by_what_is_running_is_said(self):
        config = {"how": "running", "chosen": NATIVE, "candidates": self.CANDIDATES,
                  "stale": True, "stale_reason": "running", "was": FLATPAK}
        banner = render.config_banner(config, "t")
        self.assertIn("Sunshine is running from", banner)
        self.assertIn(FLATPAK, banner)

    def test_a_missing_live_tree_is_the_loudest_thing_on_the_page(self):
        config = {"how": "only", "chosen": FLATPAK, "candidates": self.CANDIDATES[1:],
                  "missing": NATIVE}
        banner = render.config_banner(config, "t")
        self.assertIn("This is not the Sunshine that runs", banner)
        self.assertIn(NATIVE, banner)
        self.assertIn('class="err"', banner)

    def test_settings_says_why(self):
        config = {"how": "running", "chosen": NATIVE, "candidates": self.CANDIDATES}
        self.assertIn("certainly live", render.config_setting(config, "t"))


if __name__ == "__main__":
    unittest.main()
