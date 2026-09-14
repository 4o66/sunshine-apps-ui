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
