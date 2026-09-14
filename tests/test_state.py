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
