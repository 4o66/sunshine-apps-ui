"""The page tells the engine which scheme to draw its own controls in. #44.

Found in the WebKitGTK window on Ubuntu 26.04, 2026-09-26: with the app set to
Dark on a light desktop, the language <select> was near-white text on a
near-white box. WebKitGTK paints a native select from the GTK theme and takes
only the text color from the page. color-scheme is what changes the box.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sunshine_apps_ui import render  # noqa: E402


def rule(selector_pattern):
    """The body of the first CSS rule whose selector matches."""
    found = re.search(selector_pattern + r"\s*\{([^}]*)\}", render._CSS)
    assert found, selector_pattern
    return found.group(1)


class ColorSchemeTest(unittest.TestCase):
    def test_the_base_tokens_say_light(self):
        self.assertIn("color-scheme:light", rule(r"(?m)^:root"))

    def test_choosing_dark_says_dark(self):
        self.assertIn("color-scheme:dark", rule(r':root\[data-theme="dark"\]'))

    def test_following_a_dark_system_says_dark(self):
        self.assertIn("color-scheme:dark",
                      rule(r':root:not\(\[data-theme="light"\]\)'))



class ConfirmationWordingTest(unittest.TestCase):
    """What the Apply page says each queued change will do."""

    def test_a_restore_says_when_the_copy_is_from(self):
        html = render._queued_list([{"op": "rollback",
                                     "backup": "apps-20260927-005946.json",
                                     "name": "the copy from apps-20260927-005946.json"}])
        self.assertIn("Restore the copy from 27 Sep 2026 at 00:59:46", html)
        self.assertNotIn("rollback", html)
        self.assertNotIn(".json", html)

    def test_a_rename_says_the_new_name(self):
        html = render._queued_list([{"op": "edit", "name": "Team Fortress 2",
                                     "fields": {"name": "TF2 test", "cmd": "x"}}])
        self.assertIn("Rename Team Fortress 2 to TF2 test", html)

    def test_an_edit_that_keeps_the_name_is_still_an_edit(self):
        html = render._queued_list([{"op": "edit", "name": "Portal 2",
                                     "fields": {"name": "Portal 2", "cmd": "y"}}])
        self.assertIn("Edit Portal 2", html)


if __name__ == "__main__":
    unittest.main()
