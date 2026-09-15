# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for deletion tombstones and opt-in removal of uninstalled entries."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core.reconcile import reconcile, tag  # noqa: E402


def game(appid="620", name="Portal 2"):
    return tag({"name": name, "cmd": f"steam -applaunch {appid}"}, "steam", appid)


def names(entries):
    return [e["name"] for e in entries]


class TestTombstones(unittest.TestCase):
    def test_a_deleted_entry_is_not_silently_recreated(self):
        desired = [game()]
        out, plan = reconcile([], desired, previously_managed=["steam:620"])
        self.assertEqual(out, [])
        self.assertEqual(names(plan["removed_by_user"]), ["Portal 2"])
        self.assertEqual(plan["added"], [])

    def test_without_history_the_same_state_is_just_a_new_entry(self):
        """An entry we never wrote is new, not deleted -- the distinction is the history."""
        out, plan = reconcile([], [game()], previously_managed=[])
        self.assertEqual(names(plan["added"]), ["Portal 2"])
        self.assertEqual(plan["removed_by_user"], [])

    def test_the_tombstone_suppresses_it_on_later_runs(self):
        _, plan = reconcile([], [game()], previously_managed=["steam:620"])
        out2, plan2 = reconcile([], [game()], tombstones=plan["tombstones"])
        self.assertEqual(out2, [])
        self.assertEqual(names(plan2["suppressed"]), ["Portal 2"])
        self.assertEqual(plan2["removed_by_user"], [])

    def test_restore_removed_brings_it_back(self):
        _, plan = reconcile([], [game()], previously_managed=["steam:620"])
        out, plan2 = reconcile([], [game()], tombstones=plan["tombstones"],
                               restore_removed=["steam:620"])
        self.assertEqual(names(plan2["added"]), ["Portal 2"])
        self.assertEqual(plan2["tombstones"], [])
        self.assertEqual(len(plan2["restored"]), 1)

    def test_restore_all_clears_every_tombstone(self):
        _, plan = reconcile([], [game(), game("440", "TF2")],
                            previously_managed=["steam:620", "steam:440"])
        self.assertEqual(len(plan["tombstones"]), 2)
        _, plan2 = reconcile([], [game(), game("440", "TF2")],
                             tombstones=plan["tombstones"], restore_removed=["all"])
        self.assertEqual(plan2["tombstones"], [])

    def test_a_selector_restores_only_that_entry(self):
        _, plan = reconcile([], [game(), game("440", "TF2")],
                            previously_managed=["steam:620", "steam:440"])
        out, plan2 = reconcile([], [game(), game("440", "TF2")],
                               tombstones=plan["tombstones"], restore_removed=["steam:440"])
        self.assertEqual(names(plan2["added"]), ["TF2"])
        self.assertEqual(names(plan2["suppressed"]), ["Portal 2"])

    def test_managed_list_round_trips(self):
        out, plan = reconcile([], [game()])
        self.assertEqual(plan["managed"], ["steam:620"])
        _, plan2 = reconcile(out, [game()], previously_managed=plan["managed"])
        self.assertEqual(plan2["removed_by_user"], [])


class TestPrune(unittest.TestCase):
    def _installed_then_gone(self):
        out, _ = reconcile([], [game(), game("440", "TF2")])
        return out

    def test_uninstalled_entries_are_kept_by_default(self):
        out, plan = reconcile(self._installed_then_gone(), [game()])
        self.assertIn("TF2", [a["name"] for a in out])
        self.assertEqual(names(plan["missing"]), ["TF2"])
        self.assertEqual(plan["pruned"], [])

    def test_prune_removes_them_when_the_source_scanned_cleanly(self):
        out, plan = reconcile(self._installed_then_gone(), [game()],
                              prunable_sources=["steam"])
        self.assertNotIn("TF2", [a["name"] for a in out])
        self.assertEqual(names(plan["pruned"]), ["TF2"])

    def test_prune_never_touches_a_source_that_is_not_listed(self):
        """The rail: an unhealthy source is simply absent from prunable_sources."""
        out, plan = reconcile(self._installed_then_gone(), [game()],
                              prunable_sources=["heroic"])
        self.assertIn("TF2", [a["name"] for a in out])
        self.assertEqual(names(plan["missing"]), ["TF2"])

    def test_prune_never_touches_entries_that_are_not_ours(self):
        factory = [{"name": "Desktop", "image-path": "desktop.png"}]
        existing = factory + self._installed_then_gone()
        out, plan = reconcile(existing, [game()], prunable_sources=["steam"])
        self.assertIn("Desktop", [a["name"] for a in out])
        self.assertEqual(names(plan["kept_foreign"]), ["Desktop"])

    def test_pruning_does_not_create_a_tombstone(self):
        """Uninstalled is not deleted-by-you; reinstalling must bring the game back."""
        out, plan = reconcile(self._installed_then_gone(), [game()],
                              prunable_sources=["steam"])
        self.assertEqual(plan["tombstones"], [])
        out2, plan2 = reconcile(out, [game(), game("440", "TF2")],
                                previously_managed=plan["managed"])
        self.assertIn("TF2", [a["name"] for a in out2])


if __name__ == "__main__":
    unittest.main()
