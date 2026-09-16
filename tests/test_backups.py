# SPDX-License-Identifier: GPL-3.0-or-later
"""Copies of apps.json, and putting one back.

The point of a copy is the moment it is taken: immediately before a write, so
it holds what preceded the mistake rather than the mistake itself.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core import backups  # noqa: E402
from sunshine_apps_ui.core.mutate import MutateError, apply_ops  # noqa: E402


def apps_file(path, names, meta=None):
    payload = {"apps": [{"name": n} for n in names]}
    if meta is not None:
        payload["meta"] = meta
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = os.path.join(self.tmp.name, "conf")
        os.makedirs(self.conf)
        self.apps_json = os.path.join(self.conf, "apps.json")
        patched = mock.patch.dict(
            os.environ, {"BSM_BACKUP_DIR": os.path.join(self.tmp.name, "data")})
        patched.start()
        self.addCleanup(patched.stop)

    def _capture_at(self, stamp, names=("A",)):
        """Take a copy with a chosen timestamp, so ordering can be tested."""
        apps_file(self.apps_json, names)
        with mock.patch.object(backups.time, "strftime", return_value=stamp):
            return backups.capture(self.apps_json)

    def test_a_copy_is_kept_away_from_sunshines_directory(self):
        apps_file(self.apps_json, ["A"])
        path = backups.capture(self.apps_json)
        self.assertTrue(path)
        self.assertNotEqual(os.path.dirname(path), self.conf)
        self.assertEqual(os.listdir(self.conf), ["apps.json"])

    def test_the_copy_is_named_for_when_it_was_taken(self):
        path = self._capture_at("20260915-101500")
        self.assertEqual(os.path.basename(path), "apps-20260915-101500.json")

    def test_a_copy_holds_what_was_there_before(self):
        apps_file(self.apps_json, ["Portal 2", "Hades"])
        path = backups.capture(self.apps_json)
        apps_file(self.apps_json, ["ruined"])
        with open(path) as handle:
            self.assertEqual([a["name"] for a in json.load(handle)["apps"]],
                             ["Portal 2", "Hades"])

    def test_nothing_to_copy_is_not_an_error(self):
        self.assertEqual(backups.capture(self.apps_json), "")

    def test_only_ten_are_kept(self):
        for i in range(14):
            self._capture_at(f"2026091{i//10}-0000{i%10:02d}")
        self.assertEqual(len(backups.list_backups()), 10)

    def test_the_oldest_are_the_ones_dropped(self):
        for i in range(12):
            self._capture_at(f"20260915-0000{i:02d}")
        kept = [b["name"] for b in backups.list_backups()]
        self.assertIn("apps-20260915-000011.json", kept)
        self.assertNotIn("apps-20260915-000000.json", kept)

    def test_two_writes_in_one_second_keep_the_earlier_copy(self):
        """The first copy is the one that predates both changes."""
        apps_file(self.apps_json, ["before"])
        with mock.patch.object(backups.time, "strftime", return_value="20260915-120000"):
            first = backups.capture(self.apps_json)
            apps_file(self.apps_json, ["after"])
            second = backups.capture(self.apps_json)
        self.assertEqual(first, second)
        with open(first) as handle:
            self.assertEqual(json.load(handle)["apps"][0]["name"], "before")

    def test_listing_is_newest_first(self):
        for stamp in ("20260915-090000", "20260915-100000", "20260915-110000"):
            self._capture_at(stamp)
        names = [b["name"] for b in backups.list_backups()]
        self.assertEqual(names, sorted(names, reverse=True))

    def test_a_listing_says_what_is_in_each_copy(self):
        self._capture_at("20260915-090000", names=("A", "B", "C"))
        entry = backups.list_backups()[0]
        self.assertEqual(entry["apps"], 3)
        self.assertTrue(entry["readable"])
        self.assertTrue(entry["at"].startswith("2026-09-15T09:00"))

    def test_an_unreadable_copy_is_listed_as_unusable_not_hidden(self):
        os.makedirs(backups.backup_dir(), exist_ok=True)
        with open(os.path.join(backups.backup_dir(),
                               "apps-20260915-090000.json"), "w") as handle:
            handle.write("{not json")
        entry = backups.list_backups()[0]
        self.assertFalse(entry["readable"])

    def test_no_directory_yet_is_an_empty_list(self):
        self.assertEqual(backups.list_backups(), [])


class NameTest(unittest.TestCase):
    """A name arrives from a request, so it is checked rather than trusted."""

    def test_our_own_names_are_accepted(self):
        self.assertTrue(backups.is_backup("apps-20260915-101500.json"))

    def test_a_path_is_not_a_name(self):
        for bad in ("../../etc/passwd", "sub/apps-20260915-101500.json",
                    "apps-20260915-101500.json/../x"):
            self.assertFalse(backups.is_backup(bad), bad)

    def test_something_else_in_the_directory_is_not_a_copy(self):
        for bad in ("apps.json", "notes.txt", "apps-.json", "apps-2026.json"):
            self.assertFalse(backups.is_backup(bad), bad)


class RollbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patched = mock.patch.dict(
            os.environ, {"BSM_BACKUP_DIR": os.path.join(self.tmp.name, "data")})
        patched.start()
        self.addCleanup(patched.stop)
        os.makedirs(backups.backup_dir(), exist_ok=True)
        self.name = "apps-20260915-101500.json"
        with open(os.path.join(backups.backup_dir(), self.name), "w") as handle:
            json.dump({"apps": [{"name": "Portal 2"}, {"name": "Hades"}],
                       "meta": {"managed": ["steam:620"],
                                "removed": [{"source": "steam", "id": "440"}]}},
                      handle)

    def _now(self):
        return {"apps": [{"name": "wrecked"}], "meta": {"managed": [], "removed": []}}

    def test_a_rollback_puts_the_apps_back(self):
        updated, results = apply_ops(self._now(),
                                     [{"op": "rollback", "backup": self.name}])
        self.assertTrue(results[0]["ok"])
        self.assertEqual([a["name"] for a in updated["apps"]],
                         ["Portal 2", "Hades"])

    def test_it_also_puts_back_what_apps_alone_cannot_carry(self):
        """The managed list and the tombstones are the reason this is a whole
        file operation and not a set of per-entry edits."""
        updated, _ = apply_ops(self._now(),
                               [{"op": "rollback", "backup": self.name}])
        self.assertEqual(updated["meta"]["managed"], ["steam:620"])
        self.assertEqual(updated["meta"]["removed"][0]["id"], "440")

    def test_a_name_that_is_not_one_of_ours_is_refused(self):
        updated, results = apply_ops(self._now(),
                                     [{"op": "rollback", "backup": "../../etc/passwd"}])
        self.assertFalse(results[0]["ok"])
        self.assertEqual([a["name"] for a in updated["apps"]], ["wrecked"])

    def test_a_missing_copy_is_refused_without_taking_the_batch_down(self):
        updated, results = apply_ops(
            self._now(), [{"op": "rollback", "backup": "apps-20991231-235959.json"},
                          {"op": "add", "fields": {"name": "Still Ran"}}])
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_changes_queued_after_a_rollback_apply_to_the_restored_file(self):
        updated, _ = apply_ops(self._now(),
                               [{"op": "rollback", "backup": self.name},
                                {"op": "add", "fields": {"name": "Added After"}}])
        self.assertEqual([a["name"] for a in updated["apps"]],
                         ["Portal 2", "Hades", "Added After"])


class AdoptLegacyTest(unittest.TestCase):
    """Copies the old layout left in Sunshine's directory are worth keeping."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = os.path.join(self.tmp.name, "conf")
        os.makedirs(self.conf)
        patched = mock.patch.dict(
            os.environ, {"BSM_BACKUP_DIR": os.path.join(self.tmp.name, "data")})
        patched.start()
        self.addCleanup(patched.stop)

    def _legacy(self, stamp, names=("A",)):
        return apps_file(os.path.join(self.conf, f"apps.json.bak-{stamp}"), names)

    def test_old_copies_are_moved_rather_than_discarded(self):
        self._legacy("20260914-101500", ["Kept"])
        self.assertEqual(backups.adopt_legacy(self.conf), 1)
        entry = backups.list_backups()[0]
        self.assertEqual(entry["name"], "apps-20260914-101500.json")
        self.assertEqual(entry["apps"], 1)

    def test_sunshines_directory_is_left_clean(self):
        self._legacy("20260914-101500")
        backups.adopt_legacy(self.conf)
        self.assertEqual(os.listdir(self.conf), [])

    def test_nothing_to_adopt_is_not_an_error(self):
        self.assertEqual(backups.adopt_legacy(self.conf), 0)

    def test_adopting_respects_the_limit(self):
        for i in range(13):
            self._legacy(f"20260914-0000{i:02d}")
        backups.adopt_legacy(self.conf)
        self.assertEqual(len(backups.list_backups()), 10)


if __name__ == "__main__":
    unittest.main()


class WhereCopiesLiveTest(unittest.TestCase):
    """Copies must not live inside the directory an install replaces.

    They did. An rsync --delete onto the install directory removed ten of them,
    and scripts/uninstall would have removed the rest -- at the moment you are
    most likely to want one.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            "XDG_STATE_HOME": os.path.join(self.tmp.name, "state"),
            "XDG_DATA_HOME": os.path.join(self.tmp.name, "share"),
            "BSM_BACKUP_DIR": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_copies_are_not_kept_where_the_program_is_installed(self):
        install = os.path.join(self.tmp.name, "share", "sunshine-apps-ui")
        self.assertFalse(backups.backup_dir().startswith(install),
                         backups.backup_dir())

    def test_they_are_kept_under_state(self):
        self.assertTrue(
            backups.backup_dir().startswith(os.path.join(self.tmp.name, "state")))

    def test_copies_left_in_the_old_place_are_rescued(self):
        old = os.path.join(self.tmp.name, "share", "sunshine-apps-ui", "backups")
        os.makedirs(old)
        apps_file(os.path.join(old, "apps-20260915-101500.json"), ["Rescued"])
        self.assertEqual(backups.adopt_previous_location(), 1)
        self.assertEqual([b["name"] for b in backups.list_backups()],
                         ["apps-20260915-101500.json"])

    def test_rescuing_is_not_an_error_when_there_is_nothing_there(self):
        self.assertEqual(backups.adopt_previous_location(), 0)

    def test_an_override_is_still_honoured(self):
        with mock.patch.dict(os.environ, {"BSM_BACKUP_DIR": "/tmp/elsewhere"}):
            self.assertEqual(backups.backup_dir(), "/tmp/elsewhere")


class WhatWouldChangeTest(unittest.TestCase):
    """A restore has to say what it would change, and about which tile.

    Naming the changed entry by what it *would become* makes it unfindable in
    exactly the case where the name is the thing that changes -- which is how a
    renamed game showed "1 would change" with no mark on any tile.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patched = mock.patch.dict(
            os.environ, {"BSM_BACKUP_DIR": os.path.join(self.tmp.name, "data")})
        patched.start()
        self.addCleanup(patched.stop)
        os.makedirs(backups.backup_dir(), exist_ok=True)

    def _copy(self, apps, name="apps-20260915-193715.json"):
        with open(os.path.join(backups.backup_dir(), name), "w") as handle:
            json.dump({"apps": apps}, handle)
        return name

    MARKER = {"v": 1, "source": "steam", "id": "526870", "fields": {}}

    def _marked(self, was, now):
        """Both entries carry the marker, which is what ties them together."""
        name = self._copy([dict(was, bsm=self.MARKER)])
        return backups.compare({"apps": [dict(now, bsm=self.MARKER)]},
                               name)["changing"][0]

    def test_it_is_named_by_what_it_is_called_now(self):
        """So the tile can be found before the change happens."""
        item = self._marked({"name": "Satisfactory"}, {"name": "Satisfactory 1.2"})
        self.assertEqual(item["name"], "Satisfactory 1.2")

    def test_it_says_what_the_name_would_become(self):
        item = self._marked({"name": "Satisfactory"}, {"name": "Satisfactory 1.2"})
        self.assertEqual(item["becomes"], "Satisfactory")

    def test_nothing_becomes_anything_when_the_name_is_unchanged(self):
        item = self._marked({"name": "Hades", "cmd": "a"},
                            {"name": "Hades", "cmd": "b"})
        self.assertIsNone(item["becomes"])

    def test_it_carries_how_the_two_were_matched(self):
        """A marker survives a rename; a name does not."""
        item = self._marked({"name": "Satisfactory"}, {"name": "Satisfactory 1.2"})
        self.assertEqual(item["key"], "steam:526870")

    def test_a_rename_with_no_marker_reads_as_two_entries(self):
        """Honest rather than clever: nothing ties an unmarked entry to the
        name it used to have, so it leaves and a different one arrives."""
        name = self._copy([{"name": "Satisfactory"}])
        result = backups.compare({"apps": [{"name": "Satisfactory 1.2"}]}, name)
        self.assertEqual(result["changing"], [])
        self.assertEqual([i["name"] for i in result["returning"]], ["Satisfactory"])
        self.assertEqual([i["name"] for i in result["going"]], ["Satisfactory 1.2"])

    def test_it_lists_which_fields_differ(self):
        item = self._marked({"name": "A", "cmd": "old", "image-path": "/a.png"},
                            {"name": "A", "cmd": "new", "image-path": "/b.png"})
        self.assertEqual(sorted(item["fields"]), ["cmd", "image-path"])
