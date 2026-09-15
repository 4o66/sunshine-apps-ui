# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the change queue and the explain-once preferences."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import state  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.dir

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self._old
        shutil.rmtree(self.dir, ignore_errors=True)


class TestQueue(StateTest):
    def test_it_starts_empty(self):
        self.assertEqual(state.queue(), [])

    def test_operations_accumulate_in_order(self):
        state.enqueue({"op": "edit", "name": "A"})
        state.enqueue({"op": "hide", "name": "B"})
        self.assertEqual([o["name"] for o in state.queue()], ["A", "B"])

    def test_it_survives_a_fresh_read(self):
        state.enqueue({"op": "edit", "name": "A"})
        self.assertEqual(len(state.queue()), 1)

    def test_clearing_empties_it(self):
        state.enqueue({"op": "edit", "name": "A"})
        state.clear_queue()
        self.assertEqual(state.queue(), [])

    def test_a_corrupt_queue_reads_as_empty_rather_than_raising(self):
        with open(os.path.join(state.state_dir(), state.QUEUE_FILE), "w") as f:
            f.write("{ not json")
        self.assertEqual(state.queue(), [])

    def test_dropping_one_leaves_the_others(self):
        for name in "ABC":
            state.enqueue({"op": "edit", "name": name})
        state.drop(1)
        self.assertEqual([o["name"] for o in state.queue()], ["A", "C"])

    def test_dropping_out_of_range_is_harmless(self):
        state.enqueue({"op": "edit", "name": "A"})
        state.drop(9)
        self.assertEqual(len(state.queue()), 1)


class TestExplainPreference(StateTest):
    def test_destructive_operations_are_explained_by_default(self):
        self.assertTrue(state.should_explain("hide"))
        self.assertTrue(state.should_explain("delete"))

    def test_other_operations_are_not(self):
        for op in ("edit", "clone", "add"):
            self.assertFalse(state.should_explain(op))

    def test_silencing_one_leaves_the_other_alone(self):
        """You might want reminding about hide but not about delete."""
        state.set_explain("delete", False)
        self.assertFalse(state.should_explain("delete"))
        self.assertTrue(state.should_explain("hide"))

    def test_it_can_be_turned_back_on(self):
        state.set_explain("hide", False)
        state.set_explain("hide", True)
        self.assertTrue(state.should_explain("hide"))

    def test_a_corrupt_prefs_file_falls_back_to_explaining(self):
        with open(os.path.join(state.state_dir(), state.PREFS_FILE), "w") as f:
            f.write("nonsense")
        self.assertTrue(state.should_explain("hide"))


if __name__ == "__main__":
    unittest.main()


class TestStagePlan(StateTest):
    """A scan's findings become queued changes, visible on the grid."""

    def _plan(self):
        return {
            "added": [{"name": "TF2", "source": "steam", "id": "440",
                       "entry": {"name": "TF2", "bsm": {"source": "steam", "id": "440"}}}],
            "updated": [{"name": "Portal 2", "source": "steam", "id": "620",
                         "fields": ["image-path"],
                         "entry": {"name": "Portal 2",
                                   "bsm": {"source": "steam", "id": "620"}}}],
        }

    def test_findings_land_in_the_queue(self):
        self.assertEqual(state.stage_plan(self._plan()), 2)
        self.assertEqual([o["op"] for o in state.queue()], ["adopt", "adopt"])

    def test_they_are_marked_as_coming_from_a_scan(self):
        state.stage_plan(self._plan())
        self.assertTrue(all(o["from_scan"] for o in state.queue()))

    def test_the_whole_entry_is_carried_so_it_can_be_written_back(self):
        state.stage_plan(self._plan())
        self.assertIn("bsm", state.queue()[0]["entry"])

    def test_scanning_twice_does_not_stage_the_same_thing_twice(self):
        state.stage_plan(self._plan())
        self.assertEqual(state.stage_plan(self._plan()), 0)
        self.assertEqual(len(state.queue()), 2)

    def test_a_decision_you_already_made_is_not_overridden(self):
        """Hiding something then rescanning should not re-propose adding it."""
        state.enqueue({"op": "hide", "index": 1, "name": "Portal 2",
                       "source": "steam", "id": "620"})
        self.assertEqual(state.stage_plan(self._plan()), 1)
        ops = [(o["op"], o.get("name")) for o in state.queue()]
        self.assertIn(("hide", "Portal 2"), ops)
        self.assertNotIn(("adopt", "Portal 2"), ops)

    def test_an_entry_without_a_payload_is_skipped(self):
        self.assertEqual(state.stage_plan({"added": [{"name": "X"}]}), 0)

    def test_an_empty_plan_stages_nothing(self):
        self.assertEqual(state.stage_plan({}), 0)
        self.assertEqual(state.queue(), [])


class TestStableIds(StateTest):
    """Positions shift as changes are queued and dropped; ids do not."""

    def test_every_queued_op_gets_an_id(self):
        state.enqueue({"op": "edit", "name": "A"})
        self.assertTrue(state.queue()[0]["qid"])

    def test_ids_are_unique(self):
        for name in "ABC":
            state.enqueue({"op": "edit", "name": name})
        ids = [o["qid"] for o in state.queue()]
        self.assertEqual(len(set(ids)), 3)

    def test_staged_scan_results_get_ids_too(self):
        state.stage_plan({"added": [{"name": "TF2", "source": "steam", "id": "440",
                                     "entry": {"name": "TF2"}}]})
        self.assertTrue(state.queue()[0]["qid"])

    def test_find_locates_by_id(self):
        state.enqueue({"op": "edit", "name": "A"})
        qid = state.queue()[0]["qid"]
        self.assertEqual(state.find(qid)["name"], "A")
        self.assertIsNone(state.find("nope"))

    def test_update_revises_in_place_and_keeps_its_position(self):
        for name in "ABC":
            state.enqueue({"op": "edit", "name": name})
        qid = state.queue()[1]["qid"]
        self.assertTrue(state.update(qid, {"name": "revised"}))
        self.assertEqual([o["name"] for o in state.queue()], ["A", "revised", "C"])

    def test_updating_an_unknown_id_changes_nothing(self):
        state.enqueue({"op": "edit", "name": "A"})
        self.assertFalse(state.update("nope", {"name": "x"}))
        self.assertEqual(state.queue()[0]["name"], "A")

    def test_drop_by_id_removes_only_that_one(self):
        for name in "ABC":
            state.enqueue({"op": "edit", "name": name})
        qid = state.queue()[1]["qid"]
        self.assertTrue(state.drop_qid(qid))
        self.assertEqual([o["name"] for o in state.queue()], ["A", "C"])

    def test_dropping_an_unknown_id_is_harmless(self):
        state.enqueue({"op": "edit", "name": "A"})
        self.assertFalse(state.drop_qid("nope"))
        self.assertEqual(len(state.queue()), 1)

    def test_an_id_survives_other_entries_being_dropped_around_it(self):
        for name in "ABC":
            state.enqueue({"op": "edit", "name": name})
        target = state.queue()[2]["qid"]
        state.drop_qid(state.queue()[0]["qid"])
        self.assertEqual(state.find(target)["name"], "C")


class DraftLifetimeTest(StateTest):
    """A draft belongs to a form that is open, not to the machine."""

    def test_starting_the_server_forgets_old_drafts(self):
        state.set_draft("index:1", {"name": "typed last month"})
        state.clear_drafts()
        self.assertEqual(state.draft("index:1"), {})

    def test_it_does_not_touch_the_queue(self):
        """Queued changes are the opposite: they exist to be applied later."""
        state.enqueue({"op": "edit", "name": "A"})
        state.clear_drafts()
        self.assertEqual(len(state.queue()), 1)

    def test_forgetting_when_there_is_nothing_to_forget_is_harmless(self):
        state.clear_drafts()
        self.assertEqual(state.draft("new"), {})
