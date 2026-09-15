# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the apps.json reconcile logic. Standard library only:

    python3 -m unittest discover -s tests -v
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core.reconcile import (MARKER, SCHEMA_VERSION, field_hash, identity,  # noqa: E402
                              plan_document, reconcile, tag)


def names(entries):
    """Plan entries are objects; most assertions only care about the names."""
    return [e["name"] for e in entries]

FACTORY = [
    {"name": "Desktop", "image-path": "desktop.png"},
    {"name": "Steam Big Picture", "detached": ["setsid steam steam://open/bigpicture"],
     "image-path": "steam.png"},
]


def game(appid="620", name="Portal 2", image="/img/620.png"):
    return tag({"name": name, "output": "", "cmd": f"steam -applaunch {appid}",
                "working-dir": "/home/u/.local/share/Steam",
                "image-path": image, "detached": False, "elevated": False,
                "exit-on-close": True}, "steam", appid)


class TestReconcile(unittest.TestCase):
    def test_factory_entries_are_never_touched(self):
        out, plan = reconcile(FACTORY, [game()])
        self.assertEqual(names(plan["kept_foreign"]), ["Desktop", "Steam Big Picture"])
        self.assertEqual(out[0], FACTORY[0])
        self.assertEqual(out[1], FACTORY[1])
        self.assertEqual(names(plan["added"]), ["Portal 2"])
        self.assertEqual(len(out), 3)

    def test_second_run_is_idempotent(self):
        once, _ = reconcile(FACTORY, [game()])
        twice, plan = reconcile(once, [game()])
        self.assertEqual(once, twice)
        self.assertEqual(names(plan["unchanged"]), ["Portal 2"])
        self.assertEqual(plan["added"], [])
        self.assertEqual(plan["updated"], [])

    def test_user_edit_is_kept_and_flagged(self):
        out, _ = reconcile(FACTORY, [game()])
        out[2]["cmd"] = "gamemoderun steam -applaunch 620"     # user edits in the web UI
        out2, plan = reconcile(out, [game()])
        self.assertEqual(out2[2]["cmd"], "gamemoderun steam -applaunch 620")
        self.assertEqual(len(plan["diverged"]), 1)
        self.assertEqual(plan["diverged"][0]["fields"][0]["field"], "cmd")

    def test_divergence_is_reported_every_run_not_just_once(self):
        out, _ = reconcile(FACTORY, [game()])
        out[2]["cmd"] = "custom"
        out2, _ = reconcile(out, [game()])
        out3, plan = reconcile(out2, [game()])
        self.assertEqual(out3[2]["cmd"], "custom")
        self.assertEqual(len(plan["diverged"]), 1)

    def test_untouched_fields_still_refresh_beside_an_edited_one(self):
        out, _ = reconcile(FACTORY, [game()])
        out[2]["cmd"] = "custom"
        out2, plan = reconcile(out, [game(image="/img/620-new.png")])
        self.assertEqual(out2[2]["cmd"], "custom")              # yours, kept
        self.assertEqual(out2[2]["image-path"], "/img/620-new.png")  # ours, refreshed
        self.assertIn("image-path", plan["updated"][0]["fields"])

    def test_refresh_edited_reclaims_the_field(self):
        out, _ = reconcile(FACTORY, [game()])
        out[2]["cmd"] = "custom"
        out2, plan = reconcile(out, [game()], refresh=["steam:620"])
        self.assertEqual(out2[2]["cmd"], "steam -applaunch 620")
        self.assertEqual(plan["diverged"], [])

    def test_refresh_selector_does_not_affect_other_entries(self):
        out, _ = reconcile(FACTORY, [game(), game("440", "TF2")])
        out[2]["cmd"] = "custom-620"
        out[3]["cmd"] = "custom-440"
        out2, _ = reconcile(out, [game(), game("440", "TF2")], refresh=["steam:620"])
        self.assertEqual(out2[2]["cmd"], "steam -applaunch 620")   # reclaimed
        self.assertEqual(out2[3]["cmd"], "custom-440")             # untouched

    def test_user_converging_on_our_value_clears_divergence(self):
        out, _ = reconcile(FACTORY, [game()])
        out[2]["cmd"] = "steam -applaunch 999"
        out2, _ = reconcile(out, [game()])                 # diverged
        out2[2]["cmd"] = "steam -applaunch 620"            # user puts it back
        out3, plan = reconcile(out2, [game()])
        self.assertEqual(plan["diverged"], [])
        self.assertEqual(names(plan["unchanged"]), ["Portal 2"])

    def test_sunshine_erasing_empty_keys_is_not_an_edit(self):
        """saveApp() deletes prep-cmd/detached when empty; that must not look like a user edit."""
        desired = tag({"name": "X", "cmd": "x", "prep-cmd": [], "detached": []}, "launcher", "x")
        out, _ = reconcile([], [desired])
        saved = copy.deepcopy(out)
        del saved[0]["prep-cmd"]        # exactly what Sunshine does on save
        del saved[0]["detached"]
        out2, plan = reconcile(saved, [desired])
        self.assertEqual(plan["diverged"], [])
        self.assertEqual(names(plan["unchanged"]), ["X"])
        self.assertEqual(plan["updated"], [])
        # absent and empty are the same state, so do not put the keys back
        self.assertNotIn("prep-cmd", out2[0])

    def test_reconcile_does_not_mutate_its_inputs(self):
        desired = [game()]
        snapshot = copy.deepcopy(desired)
        out, _ = reconcile(list(FACTORY), desired)
        out[-1]["cmd"] = "mutated"
        out[-1]["name"] = "mutated"
        self.assertEqual(desired, snapshot)

    def test_uninstalled_entry_is_kept_and_reported(self):
        out, _ = reconcile(FACTORY, [game(), game("440", "TF2")])
        out2, plan = reconcile(out, [game()])            # TF2 uninstalled
        self.assertEqual([a.get("name") for a in out2].count("TF2"), 1)
        self.assertEqual(len(plan["missing"]), 1)
        self.assertEqual(plan["missing"][0]["name"], "TF2")

    def test_user_added_keys_on_our_entry_survive(self):
        out, _ = reconcile(FACTORY, [game()])
        out[2]["prep-cmd"] = [{"do": "x", "undo": "y"}]   # user adds a field we do not manage
        out2, _ = reconcile(out, [game()])
        self.assertEqual(out2[2]["prep-cmd"], [{"do": "x", "undo": "y"}])

    def test_adopt_by_name_migrates_a_pre_marker_file(self):
        legacy = [{"name": "Portal 2", "cmd": "steam -applaunch 620", "image-path": "/old.png"}]
        out, plan = reconcile(legacy, [game()], adopt_by_name=True)
        self.assertEqual(len(out), 1)                     # adopted, not duplicated
        self.assertEqual(identity(out[0]), ("steam", "620"))
        self.assertEqual(out[0]["image-path"], "/img/620.png")

    def test_without_adopt_a_pre_marker_file_would_duplicate(self):
        legacy = [{"name": "Portal 2", "cmd": "steam -applaunch 620"}]
        out, _ = reconcile(legacy, [game()], adopt_by_name=False)
        self.assertEqual(len(out), 2)                     # why the migration flag exists

    def test_desired_app_without_marker_is_rejected(self):
        with self.assertRaises(ValueError):
            reconcile([], [{"name": "untagged"}])

    def test_marker_records_only_fields_we_manage(self):
        g = game()
        self.assertEqual(set(g[MARKER]["fields"]), set(k for k in g if k != MARKER))

    def test_hash_is_over_values_not_serialized_text(self):
        """Sunshine re-dumps with sorted keys; key order must not register as a change."""
        self.assertEqual(field_hash("prep-cmd", [{"do": "a", "undo": "b"}]),
                         field_hash("prep-cmd", [{"undo": "b", "do": "a"}]))

    def test_absent_and_empty_hash_identically(self):
        self.assertEqual(field_hash("detached", None), field_hash("detached", []))
        self.assertNotEqual(field_hash("cmd", None), field_hash("cmd", ""))

    def test_output_is_json_serializable(self):
        out, _ = reconcile(FACTORY, [game()])
        json.dumps({"apps": out})


class TestPlanDocument(unittest.TestCase):
    def _doc(self, dry_run=True):
        _, plan = reconcile(FACTORY, [game()])
        return plan_document(plan, config_dir="/c", apps_json="/c/apps.json",
                             sources=[{"name": "steam", "enabled": True,
                                       "status": "ok", "imported": 1}],
                             dry_run=dry_run, generator_version="2.0")

    def test_document_is_json_serializable_and_versioned(self):
        doc = self._doc()
        json.dumps(doc)
        self.assertEqual(doc["schema"], SCHEMA_VERSION)
        self.assertEqual(doc["generator"]["name"], "bazzite-sunshine-manager")

    def test_totals_match_the_plan(self):
        doc = self._doc()
        for key, total in doc["totals"].items():
            self.assertEqual(total, len(doc["plan"].get(key, [])), key)

    def test_a_partial_plan_still_serializes(self):
        """A caller building a plan by hand should not crash the document."""
        doc = plan_document({"added": []}, config_dir="/c", apps_json="/c/a.json",
                            sources=[], dry_run=True, generator_version="2.0")
        self.assertEqual(doc["totals"]["pruned"], 0)
        json.dumps(doc)

    def test_every_plan_entry_is_addressable(self):
        """The UI needs a selector for --refresh-edited, so entries carry source and id."""
        doc = self._doc()
        for key in ("added", "updated", "unchanged", "diverged", "missing"):
            for entry in doc["plan"][key]:
                self.assertIn("source", entry, key)
                self.assertIn("id", entry, key)

    def test_dry_run_flag_is_recorded(self):
        self.assertTrue(self._doc(dry_run=True)["dry_run"])
        self.assertFalse(self._doc(dry_run=False)["dry_run"])

    def test_source_status_distinguishes_error_from_empty(self):
        doc = plan_document({"added": [], "updated": [], "unchanged": [],
                             "diverged": [], "missing": [], "kept_foreign": []},
                            config_dir="/c", apps_json="/c/apps.json",
                            sources=[{"name": "steam", "enabled": True, "status": "error",
                                      "error": "boom", "imported": 0},
                                     {"name": "heroic", "enabled": True,
                                      "status": "ok", "imported": 0}],
                            dry_run=False, generator_version="2.0")
        by = {s["name"]: s for s in doc["sources"]}
        self.assertEqual(by["steam"]["status"], "error")
        self.assertEqual(by["heroic"]["status"], "ok")
        self.assertEqual(by["steam"]["imported"], by["heroic"]["imported"])


class TestDuplicatedEntries(unittest.TestCase):
    """Sunshine's web UI duplicates an app by deep-cloning it, marker included."""

    def _cloned(self):
        g = game()
        out, _ = reconcile([], [g])
        clone = copy.deepcopy(out[0])
        clone["name"] = "Portal 2 (modded)"
        clone["cmd"] = "steam -applaunch 620 -console"
        return g, out + [clone]

    def test_a_duplicated_entry_is_never_deleted(self):
        g, existing = self._cloned()
        out, _ = reconcile(existing, [g])
        self.assertIn("Portal 2 (modded)", names_of(out))
        self.assertIn("Portal 2", names_of(out))

    def test_the_copy_becomes_the_users_own_entry(self):
        g, existing = self._cloned()
        out, plan = reconcile(existing, [g])
        copy_entry = [a for a in out if a["name"] == "Portal 2 (modded)"][0]
        self.assertNotIn(MARKER, copy_entry)
        self.assertTrue(any(e.get("adopted_copy") for e in plan["kept_foreign"]))

    def test_the_copy_is_then_left_alone_forever(self):
        g, existing = self._cloned()
        out, _ = reconcile(existing, [g])
        out2, plan = reconcile(out, [g])
        self.assertEqual(out, out2)
        self.assertEqual(len(plan["kept_foreign"]), 1)

    def test_the_original_still_tracks_normally(self):
        g, existing = self._cloned()
        out, _ = reconcile(existing, [g])
        out2, plan = reconcile(out, [game(image="/new.png")])
        original = [a for a in out2 if a["name"] == "Portal 2"][0]
        self.assertEqual(original["image-path"], "/new.png")
        modded = [a for a in out2 if a["name"] == "Portal 2 (modded)"][0]
        self.assertEqual(modded["cmd"], "steam -applaunch 620 -console")


def names_of(apps):
    return [a.get("name") for a in apps]


if __name__ == "__main__":
    unittest.main()


class TestTombstoneArtwork(unittest.TestCase):
    """A hidden entry should still be showable as itself, not a blank tile."""

    def test_a_tombstone_keeps_the_artwork(self):
        g = tag({"name": "Portal 2", "cmd": "x", "image-path": "/img/620.png"},
                "steam", "620")
        _, plan = reconcile([], [g], previously_managed=["steam:620"])
        self.assertEqual(plan["tombstones"][0]["image-path"], "/img/620.png")

    def test_a_tombstone_without_artwork_omits_the_key(self):
        g = tag({"name": "X", "cmd": "x", "image-path": ""}, "launcher", "x")
        _, plan = reconcile([], [g], previously_managed=["launcher:x"])
        self.assertNotIn("image-path", plan["tombstones"][0])


class TestPlanCarriesPayload(unittest.TestCase):
    """A front end that stages a plan needs the entries, not just their names."""

    def test_an_added_entry_carries_itself(self):
        g = game()
        _, plan = reconcile([], [g])
        self.assertEqual(plan["added"][0]["entry"]["name"], "Portal 2")
        self.assertIn(MARKER, plan["added"][0]["entry"])

    def test_an_updated_entry_carries_the_new_values(self):
        out, _ = reconcile([], [game()])
        _, plan = reconcile(out, [game(image="/new.png")])
        self.assertEqual(plan["updated"][0]["values"]["image-path"], "/new.png")
        self.assertEqual(plan["updated"][0]["entry"]["image-path"], "/new.png")

    def test_the_payload_is_a_copy_not_a_reference(self):
        g = game()
        out, plan = reconcile([], [g])
        plan["added"][0]["entry"]["name"] = "mutated"
        self.assertEqual(out[0]["name"], "Portal 2")


class GeneratorIdentityTest(unittest.TestCase):
    """A plan document says which fork produced it, and on what.

    Upstream publishes no tags, so "bazzite-sunshine-manager 2.0" identifies
    neither whose build it is nor which upstream it came from -- which is all a
    bug report has to go on.
    """

    def _doc(self, **extra):
        return plan_document({"added": []}, config_dir="/c", apps_json="/c/a.json",
                             sources=[], dry_run=True, generator_version="0.1.0",
                             **extra)

    def test_the_fork_is_named(self):
        doc = self._doc(fork="4o66/bazzite-sunshine-manager")
        self.assertEqual(doc["generator"]["fork"], "4o66/bazzite-sunshine-manager")

    def test_the_upstream_it_was_built_on_is_named(self):
        doc = self._doc(upstream="wadiebs/bazzite-sunshine-manager 2.0 (4bedee5)")
        self.assertIn("4bedee5", doc["generator"]["upstream"])

    def test_a_plain_build_says_neither_rather_than_saying_nothing_useful(self):
        generator = self._doc()["generator"]
        self.assertNotIn("fork", generator)
        self.assertNotIn("upstream", generator)
        self.assertEqual(generator["version"], "0.1.0")

    def test_the_schema_is_unchanged_by_saying_more(self):
        """Consumers reject an unknown schema, so this must not look like one."""
        self.assertEqual(self._doc(fork="x", upstream="y")["schema"], SCHEMA_VERSION)
