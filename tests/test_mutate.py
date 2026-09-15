# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for manual changes applied to apps.json."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core.mutate import MutateError, apply_ops  # noqa: E402
from sunshine_apps_ui.core.reconcile import MARKER, tag  # noqa: E402


def payload():
    managed = tag({"name": "Portal 2", "cmd": "steam -applaunch 620",
                   "image-path": "/img/620.png"}, "steam", "620")
    return {
        "env": {"PATH": "x"},
        "apps": [{"name": "Desktop", "image-path": "desktop.png"}, managed],
        "meta": {"generated-by": "bazzite-sunshine-manager",
                 "managed": ["steam:620"], "removed": []},
    }


def names(p):
    return [a["name"] for a in p["apps"]]


class TestEdit(unittest.TestCase):
    def test_a_field_is_changed(self):
        out, res = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                          "fields": {"cmd": "custom"}}])
        self.assertTrue(res[0]["ok"])
        self.assertEqual(out["apps"][1]["cmd"], "custom")

    def test_unknown_fields_are_ignored_not_written_through(self):
        out, _ = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                        "fields": {"name": "P2", "evil": "x"}}])
        self.assertEqual(out["apps"][1]["name"], "P2")
        self.assertNotIn("evil", out["apps"][1])

    def test_editing_leaves_the_marker_alone_so_divergence_is_detected(self):
        out, _ = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                        "fields": {"cmd": "custom"}}])
        self.assertIn(MARKER, out["apps"][1])

    def test_a_moved_entry_is_found_by_name(self):
        p = payload()
        p["apps"].insert(0, {"name": "New First"})
        out, res = apply_ops(p, [{"op": "edit", "index": 1, "name": "Portal 2",
                                  "fields": {"cmd": "custom"}}])
        self.assertTrue(res[0]["ok"])
        self.assertEqual([a for a in out["apps"] if a["name"] == "Portal 2"][0]["cmd"],
                         "custom")

    def test_a_vanished_entry_is_refused_rather_than_guessed(self):
        p = payload()
        p["apps"] = [p["apps"][0]]
        _, res = apply_ops(p, [{"op": "edit", "index": 1, "name": "Portal 2",
                                "fields": {"cmd": "x"}}])
        self.assertFalse(res[0]["ok"])
        self.assertIn("no longer where it was", res[0]["error"])

    def test_an_ambiguous_name_is_refused(self):
        p = payload()
        p["apps"].append({"name": "Portal 2"})
        p["apps"].insert(0, {"name": "shifted"})
        _, res = apply_ops(p, [{"op": "edit", "index": 9, "name": "Portal 2",
                                "fields": {"cmd": "x"}}])
        self.assertFalse(res[0]["ok"])
        self.assertIn("more than one", res[0]["error"])


class TestClone(unittest.TestCase):
    def test_the_copy_is_unmarked_so_the_importer_never_claims_it(self):
        out, _ = apply_ops(payload(), [{"op": "clone", "index": 1, "name": "Portal 2",
                                        "fields": {"name": "Portal 2 (modded)"}}])
        copy_entry = [a for a in out["apps"] if a["name"] == "Portal 2 (modded)"][0]
        self.assertNotIn(MARKER, copy_entry)

    def test_the_original_is_untouched(self):
        out, _ = apply_ops(payload(), [{"op": "clone", "index": 1, "name": "Portal 2",
                                        "fields": {"name": "Copy", "cmd": "other"}}])
        original = [a for a in out["apps"] if a["name"] == "Portal 2"][0]
        self.assertEqual(original["cmd"], "steam -applaunch 620")

    def test_the_copy_lands_next_to_the_original(self):
        out, _ = apply_ops(payload(), [{"op": "clone", "index": 1, "name": "Portal 2",
                                        "fields": {"name": "Copy"}}])
        self.assertEqual(names(out), ["Desktop", "Portal 2", "Copy"])

    def test_a_copy_needs_a_name(self):
        _, res = apply_ops(payload(), [{"op": "clone", "index": 1, "name": "Portal 2",
                                        "fields": {"name": ""}}])
        self.assertFalse(res[0]["ok"])


class TestDeleteAndHide(unittest.TestCase):
    """Same immediate result, opposite long-term behaviour."""

    def test_delete_removes_it_and_forgets_it_so_a_scan_finds_it_again(self):
        out, _ = apply_ops(payload(), [{"op": "delete", "index": 1, "name": "Portal 2"}])
        self.assertNotIn("Portal 2", names(out))
        self.assertEqual(out["meta"]["managed"], [])
        self.assertEqual(out["meta"]["removed"], [])

    def test_hide_removes_it_and_records_it_so_it_stays_gone(self):
        out, _ = apply_ops(payload(), [{"op": "hide", "index": 1, "name": "Portal 2"}])
        self.assertNotIn("Portal 2", names(out))
        self.assertEqual(out["meta"]["managed"], [])
        self.assertEqual(out["meta"]["removed"][0]["id"], "620")

    def test_hiding_keeps_the_artwork_for_the_muted_tile(self):
        out, _ = apply_ops(payload(), [{"op": "hide", "index": 1, "name": "Portal 2"}])
        self.assertEqual(out["meta"]["removed"][0]["image-path"], "/img/620.png")

    def test_hiding_something_the_importer_never_made_is_refused(self):
        """Nothing would bring it back, so hiding is just deleting with extra steps."""
        _, res = apply_ops(payload(), [{"op": "hide", "index": 0, "name": "Desktop"}])
        self.assertFalse(res[0]["ok"])
        self.assertIn("same as deleting", res[0]["error"])

    def test_deleting_an_unmanaged_entry_is_fine(self):
        out, res = apply_ops(payload(), [{"op": "delete", "index": 0, "name": "Desktop"}])
        self.assertTrue(res[0]["ok"])
        self.assertNotIn("Desktop", names(out))

    def test_hiding_twice_does_not_duplicate_the_tombstone(self):
        out, _ = apply_ops(payload(), [{"op": "hide", "index": 1, "name": "Portal 2"}])
        out["apps"].append(tag({"name": "Portal 2", "cmd": "x"}, "steam", "620"))
        out["meta"]["managed"] = ["steam:620"]
        out2, _ = apply_ops(out, [{"op": "hide", "index": 2, "name": "Portal 2"}])
        self.assertEqual(len(out2["meta"]["removed"]), 1)


class TestRestore(unittest.TestCase):
    def test_restore_clears_the_tombstone(self):
        hidden, _ = apply_ops(payload(), [{"op": "hide", "index": 1, "name": "Portal 2"}])
        out, res = apply_ops(hidden, [{"op": "restore", "selector": "steam:620"}])
        self.assertTrue(res[0]["ok"])
        self.assertEqual(out["meta"]["removed"], [])

    def test_restoring_something_not_hidden_is_refused(self):
        _, res = apply_ops(payload(), [{"op": "restore", "selector": "steam:999"}])
        self.assertFalse(res[0]["ok"])


class TestAddAndBatch(unittest.TestCase):
    def test_a_new_entry_is_appended_unmarked(self):
        out, _ = apply_ops(payload(), [{"op": "add", "fields": {"name": "Mine", "cmd": "x"}}])
        self.assertEqual(names(out)[-1], "Mine")
        self.assertNotIn(MARKER, out["apps"][-1])

    def test_a_nameless_entry_is_refused(self):
        _, res = apply_ops(payload(), [{"op": "add", "fields": {"cmd": "x"}}])
        self.assertFalse(res[0]["ok"])

    def test_one_bad_operation_does_not_abandon_the_rest(self):
        out, res = apply_ops(payload(), [
            {"op": "edit", "index": 99, "name": "Nope", "fields": {"cmd": "x"}},
            {"op": "add", "fields": {"name": "Mine", "cmd": "x"}},
        ])
        self.assertFalse(res[0]["ok"])
        self.assertTrue(res[1]["ok"])
        self.assertIn("Mine", names(out))

    def test_the_input_payload_is_not_mutated(self):
        p = payload()
        apply_ops(p, [{"op": "delete", "index": 1, "name": "Portal 2"}])
        self.assertIn("Portal 2", names(p))

    def test_other_top_level_keys_survive(self):
        out, _ = apply_ops(payload(), [{"op": "add", "fields": {"name": "Mine"}}])
        self.assertEqual(out["env"], {"PATH": "x"})


if __name__ == "__main__":
    unittest.main()


class TestAdopt(unittest.TestCase):
    """Taking what a scan offered, exactly as the importer would have written it."""

    def _discovered(self):
        return tag({"name": "TF2", "cmd": "steam -applaunch 440",
                    "image-path": "/img/440.png"}, "steam", "440")

    def test_the_entry_is_written_with_its_marker_intact(self):
        out, res = apply_ops(payload(), [{"op": "adopt", "entry": self._discovered()}])
        self.assertTrue(res[0]["ok"])
        added = [a for a in out["apps"] if a["name"] == "TF2"][0]
        self.assertIn(MARKER, added)

    def test_it_is_registered_as_managed_so_a_later_scan_recognises_it(self):
        out, _ = apply_ops(payload(), [{"op": "adopt", "entry": self._discovered()}])
        self.assertIn("steam:440", out["meta"]["managed"])

    def test_adopting_twice_does_not_duplicate(self):
        once, _ = apply_ops(payload(), [{"op": "adopt", "entry": self._discovered()}])
        twice, _ = apply_ops(once, [{"op": "adopt", "entry": self._discovered()}])
        self.assertEqual([a["name"] for a in twice["apps"]].count("TF2"), 1)

    def test_adopting_clears_any_tombstone_for_it(self):
        p = payload()
        p["meta"]["removed"] = [{"name": "TF2", "source": "steam", "id": "440"}]
        out, _ = apply_ops(p, [{"op": "adopt", "entry": self._discovered()}])
        self.assertEqual(out["meta"]["removed"], [])

    def test_an_unmarked_entry_cannot_be_adopted(self):
        _, res = apply_ops(payload(), [{"op": "adopt", "entry": {"name": "X"}}])
        self.assertFalse(res[0]["ok"])
        self.assertIn("no ownership marker", res[0]["error"])


class TestSuppress(unittest.TestCase):
    """Refusing something a scan offered, before it exists in the file."""

    def test_it_records_a_tombstone_without_needing_an_entry(self):
        out, res = apply_ops(payload(), [{"op": "suppress", "source": "steam",
                                          "id": "440", "name": "TF2"}])
        self.assertTrue(res[0]["ok"])
        self.assertEqual(out["meta"]["removed"][0]["id"], "440")

    def test_it_keeps_the_artwork_for_the_muted_tile(self):
        out, _ = apply_ops(payload(), [{"op": "suppress", "source": "steam", "id": "440",
                                        "name": "TF2", "image-path": "/img/440.png"}])
        self.assertEqual(out["meta"]["removed"][0]["image-path"], "/img/440.png")

    def test_suppressing_twice_is_refused_rather_than_duplicated(self):
        once, _ = apply_ops(payload(), [{"op": "suppress", "source": "steam",
                                         "id": "440", "name": "TF2"}])
        _, res = apply_ops(once, [{"op": "suppress", "source": "steam",
                                   "id": "440", "name": "TF2"}])
        self.assertFalse(res[0]["ok"])

    def test_it_needs_a_source_and_id(self):
        _, res = apply_ops(payload(), [{"op": "suppress", "name": "TF2"}])
        self.assertFalse(res[0]["ok"])


class TestFieldTypes(unittest.TestCase):
    """Sunshine reads some of these with a type in mind.

    getApps() runs std::stoi over the integer fields, so a string it cannot
    parse makes Sunshine's whole configuration API answer 400 -- which looked
    from the front end like the credentials had stopped working.
    """

    def test_a_blank_integer_field_is_dropped_not_written_as_empty(self):
        out, res = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                          "fields": {"exit-timeout": ""}}])
        self.assertTrue(res[0]["ok"])
        self.assertNotIn("exit-timeout", out["apps"][1])

    def test_a_numeric_string_becomes_a_number(self):
        out, _ = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                        "fields": {"exit-timeout": "5"}}])
        self.assertEqual(out["apps"][1]["exit-timeout"], 5)
        self.assertIsInstance(out["apps"][1]["exit-timeout"], int)

    def test_nonsense_in_a_numeric_field_is_refused_with_a_reason(self):
        _, res = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                        "fields": {"exit-timeout": "soon"}}])
        self.assertFalse(res[0]["ok"])
        self.assertIn("whole number", res[0]["error"])

    def test_checkbox_values_become_real_booleans(self):
        out, _ = apply_ops(payload(), [{"op": "edit", "index": 1, "name": "Portal 2",
                                        "fields": {"elevated": "on", "wait-all": False}}])
        self.assertIs(out["apps"][1]["elevated"], True)
        self.assertIs(out["apps"][1]["wait-all"], False)

    def test_a_clone_does_not_inherit_an_unparseable_value(self):
        out, res = apply_ops(payload(), [{"op": "clone", "index": 1, "name": "Portal 2",
                                          "fields": {"name": "Copy", "exit-timeout": ""}}])
        self.assertTrue(res[0]["ok"])
        copy_entry = [a for a in out["apps"] if a["name"] == "Copy"][0]
        self.assertNotIn("exit-timeout", copy_entry)


class TestUnhideBringsItBack(unittest.TestCase):
    """Clearing a tombstone is not the same as having the app again."""

    def _hidden(self):
        out, _ = apply_ops(payload(), [{"op": "hide", "index": 1, "name": "Portal 2"}])
        return out

    def test_hiding_keeps_the_whole_entry(self):
        out = self._hidden()
        self.assertEqual(out["meta"]["removed"][0]["entry"]["cmd"],
                         "steam -applaunch 620")

    def test_un_hiding_returns_the_app_itself(self):
        out, res = apply_ops(self._hidden(), [{"op": "restore", "selector": "steam:620"}])
        self.assertTrue(res[0]["ok"])
        self.assertIn("Portal 2", [a["name"] for a in out["apps"]])
        self.assertEqual(out["meta"]["removed"], [])

    def test_the_returned_entry_is_managed_again(self):
        out, _ = apply_ops(self._hidden(), [{"op": "restore", "selector": "steam:620"}])
        self.assertIn("steam:620", out["meta"]["managed"])
        restored = [a for a in out["apps"] if a["name"] == "Portal 2"][0]
        self.assertIn(MARKER, restored)

    def test_un_hiding_reports_the_name_not_the_selector(self):
        _, res = apply_ops(self._hidden(), [{"op": "restore", "selector": "steam:620"}])
        self.assertEqual(res[0]["name"], "Portal 2")

    def test_it_does_not_duplicate_if_the_app_is_somehow_back_already(self):
        hidden = self._hidden()
        hidden["apps"].append(tag({"name": "Portal 2", "cmd": "x"}, "steam", "620"))
        out, _ = apply_ops(hidden, [{"op": "restore", "selector": "steam:620"}])
        self.assertEqual([a["name"] for a in out["apps"]].count("Portal 2"), 1)


class TestAdoptCoercesToo(unittest.TestCase):
    """Adopt was the one route into apps.json that skipped validation.

    Safe only while its entries came straight from the importer. Editing a
    pending entry sends form strings down this path, and an exit-timeout of ""
    is what made Sunshine's configuration API answer 400.
    """

    def _entry(self, **over):
        base = {"name": "TF2", "cmd": "steam -applaunch 440"}
        base.update(over)
        return tag(base, "steam", "440")

    def test_a_blank_integer_is_dropped_rather_than_written(self):
        out, res = apply_ops(payload(), [{"op": "adopt",
                                          "entry": self._entry(**{"exit-timeout": ""})}])
        self.assertTrue(res[0]["ok"])
        added = [a for a in out["apps"] if a["name"] == "TF2"][0]
        self.assertNotIn("exit-timeout", added)

    def test_a_numeric_string_becomes_a_number(self):
        out, _ = apply_ops(payload(), [{"op": "adopt",
                                        "entry": self._entry(**{"exit-timeout": "7"})}])
        added = [a for a in out["apps"] if a["name"] == "TF2"][0]
        self.assertEqual(added["exit-timeout"], 7)

    def test_a_string_boolean_becomes_a_boolean(self):
        out, _ = apply_ops(payload(), [{"op": "adopt",
                                        "entry": self._entry(elevated="on")}])
        added = [a for a in out["apps"] if a["name"] == "TF2"][0]
        self.assertIs(added["elevated"], True)

    def test_nonsense_is_refused_rather_than_stored(self):
        _, res = apply_ops(payload(), [{"op": "adopt",
                                        "entry": self._entry(**{"exit-timeout": "soon"})}])
        self.assertFalse(res[0]["ok"])

    def test_the_marker_survives_coercion(self):
        out, _ = apply_ops(payload(), [{"op": "adopt",
                                        "entry": self._entry(**{"exit-timeout": "5"})}])
        added = [a for a in out["apps"] if a["name"] == "TF2"][0]
        self.assertIn(MARKER, added)

    def test_the_op_payload_is_not_mutated(self):
        entry = self._entry(**{"exit-timeout": "5"})
        apply_ops(payload(), [{"op": "adopt", "entry": entry}])
        self.assertEqual(entry["exit-timeout"], "5")
