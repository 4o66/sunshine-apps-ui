# SPDX-License-Identifier: GPL-3.0-or-later
"""What the engine reports about apps.json.

A front end draws an edit form from this. Anything it leaves out renders as
empty, and saving that form writes the empty value back -- so what this reports
is not a display detail, it is what survives an edit.
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core import api, run  # noqa: E402


REBOOT = {
    "name": "Zz Reboot",
    "auto-detach": True,
    "cmd": [],
    "detached": ["systemctl reboot"],
    "exclude-global-prep-cmd": False,
    "exit-timeout": 5,
    "image-path": "/img/Reboot.png",
    "output": "",
    "wait-all": True,
    "bsm": {"v": 1, "source": "launcher", "id": "reboot", "fields": {}},
}


class DumpStateTest(unittest.TestCase):
    def _dump(self, apps):
        with tempfile.TemporaryDirectory() as conf:
            with open(os.path.join(conf, "apps.json"), "w") as handle:
                json.dump({"apps": apps}, handle)
            return api.state(conf)

    def test_every_field_of_an_entry_is_reported(self):
        """Reporting a summary made the edit form blank out what it omitted."""
        entry = self._dump([REBOOT])["apps"][0]
        for field in ("auto-detach", "wait-all", "exit-timeout",
                      "exclude-global-prep-cmd", "output"):
            self.assertIn(field, entry, f"{field} would render empty")

    def test_flags_keep_their_value(self):
        entry = self._dump([REBOOT])["apps"][0]
        self.assertIs(entry["auto-detach"], True)
        self.assertIs(entry["wait-all"], True)
        self.assertIs(entry["exclude-global-prep-cmd"], False)

    def test_fields_the_form_cannot_edit_are_still_reported(self):
        entry = self._dump([REBOOT])["apps"][0]
        self.assertEqual(entry["detached"], ["systemctl reboot"])

    def test_the_ownership_marker_is_flattened_not_passed_through(self):
        entry = self._dump([REBOOT])["apps"][0]
        self.assertNotIn("bsm", entry)
        self.assertEqual((entry["source"], entry["id"]), ("launcher", "reboot"))
        self.assertTrue(entry["managed"])

    def test_an_unmanaged_entry_says_so(self):
        entry = self._dump([{"name": "Mine", "cmd": "/bin/true"}])["apps"][0]
        self.assertFalse(entry["managed"])
        self.assertIsNone(entry["source"])

    def test_an_entrys_own_keys_cannot_masquerade_as_ours(self):
        """Nothing stops an app in apps.json having a key called "managed"."""
        entry = self._dump([{"name": "Liar", "managed": True, "index": 99,
                             "source": "steam"}])["apps"][0]
        self.assertFalse(entry["managed"])
        self.assertEqual(entry["index"], 0)
        self.assertIsNone(entry["source"])

    def test_the_index_is_the_position_in_the_file(self):
        dumped = self._dump([{"name": "A"}, {"name": "B"}])
        self.assertEqual([e["index"] for e in dumped["apps"]], [0, 1])

    def test_a_list_cmd_is_reported_as_text_the_form_can_show(self):
        self.assertEqual(self._dump([REBOOT])["apps"][0]["cmd"], "")


if __name__ == "__main__":
    unittest.main()


class VersionTest(unittest.TestCase):
    """The fork's version has to say which upstream it came from.

    Upstream has called itself 2.0 in every commit it has ever made and
    publishes no tags, so "2.0" alone identifies nothing -- neither whose build
    this is nor what it was built from.
    """

    def test_it_begins_with_the_upstream_version(self):
        self.assertTrue(run.VERSION.startswith(run.UPSTREAM_VERSION + "+"),
                        run.VERSION)

    def test_it_names_the_fork_and_the_forks_own_version(self):
        self.assertIn("4o66", run.VERSION)
        self.assertTrue(run.VERSION.endswith(run.FORK_VERSION), run.VERSION)

    def test_the_fork_version_is_build_metadata_not_a_pre_release(self):
        """A "-" suffix would sort below upstream's 2.0, which is a lie in the
        other direction."""
        self.assertNotIn("-", run.VERSION)

    def test_the_upstream_commit_is_named_not_just_its_version(self):
        self.assertIn("4bedee5", run.UPSTREAM)
