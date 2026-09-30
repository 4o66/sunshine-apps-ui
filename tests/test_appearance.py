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
        html = render._queued_rows([{"op": "rollback",
                                     "backup": "apps-20260927-005946.json",
                                     "name": "the copy from apps-20260927-005946.json"}], [])
        self.assertIn("Restore the copy from 27 Sep 2026 at 00:59:46", html)
        self.assertNotIn("rollback", html)
        self.assertNotIn(".json", html)

    def test_a_rename_says_the_new_name(self):
        html = render._queued_rows([{"op": "edit", "name": "Team Fortress 2",
                                     "fields": {"name": "TF2 test", "cmd": "x"}}], [])
        self.assertIn("Rename Team Fortress 2 to TF2 test", html)

    def test_an_edit_that_keeps_the_name_is_still_an_edit(self):
        html = render._queued_rows([{"op": "edit", "name": "Portal 2",
                                     "fields": {"name": "Portal 2", "cmd": "y"}}], [])
        self.assertIn("Edit Portal 2", html)



class TileCaptionTest(unittest.TestCase):
    """The name goes under the picture, not over it. #47.

    Over it, on a scrim, it covered the words our worded tiles carry at the
    bottom -- seen in the WebKitGTK window on Ubuntu 26.04 with the English set.
    """

    def grid_rule(self, selector):
        found = re.search(re.escape(selector) + r"\{([^}]*)\}", render._GRID_CSS)
        self.assertTrue(found, selector)
        return found.group(1)

    def test_the_caption_is_not_laid_over_the_art(self):
        cap = self.grid_rule(".tile .cap")
        self.assertNotIn("position:absolute", cap)
        self.assertNotIn("gradient", cap)

    def test_the_picture_keeps_its_own_shape(self):
        self.assertIn("aspect-ratio:2/3", self.grid_rule(".tile img"))
        self.assertIn("aspect-ratio:2/3", self.grid_rule(".tile .fallback"))

    def test_the_tile_itself_is_not_held_to_2_3(self):
        """Or the caption would be squeezed into the picture's height again."""
        self.assertNotIn("aspect-ratio", self.grid_rule(".tile"))


if __name__ == "__main__":
    unittest.main()


class FlowScreensTest(unittest.TestCase):
    """2.0's flow screens (#67, #68, #70)."""

    def test_confirm_shows_each_change_with_its_picture_and_flag(self):
        apps = [{"name": "Satisfactory", "image-path": "/img/s.png"}]
        html = render.confirm_page({}, "t", True, pending=[
            {"op": "edit", "index": 0, "name": "Satisfactory", "fields": {"name": "Satisfactory"}},
            {"op": "adopt", "name": "NIMRODS", "entry": {"image-path": "/img/n.png"}},
        ], apps=apps)
        self.assertIn("This will disconnect you.", html)
        self.assertIn('/art?p=%2Fimg%2Fs.png', html)
        self.assertIn('<span class="name">Edit Satisfactory</span></span><span class="what">EDITED</span>', html)
        self.assertIn('<span class="name">Add NIMRODS</span></span><span class="what">NEW</span>', html)
        self.assertIn("Write and reload", html)

    def test_nothing_to_apply_offers_no_reload(self):
        html = render.confirm_page({}, "t", True, pending=[])
        self.assertNotIn("Write and reload", html)
        self.assertIn("Nothing would change.", html)

    def test_applied_while_streamed_has_nothing_to_press(self):
        streamed = render.applied_page("t", True)
        self.assertNotIn('<footer class="bar">', streamed)
        self.assertIn('<a class="btn sec" href="/" data-back>', render.applied_page("t", False))

    def test_the_password_can_be_shown_from_the_field_and_the_bar(self):
        html = render.connect_page("t", username="sunshine")
        self.assertEqual(html.count('data-show-password="p"'), 2)
        self.assertIn('value="sunshine"', html)
        self.assertIn('<script src="/app.js"></script>', html)

    def test_a_failed_scan_says_why_and_offers_the_way_back(self):
        html = render.scanning_page("t", {"error": "Steam could not be read", "latest": "", "elapsed": 1})
        self.assertIn("<h1>The scan stopped</h1>", html)
        self.assertIn("Steam could not be read", html)
        self.assertIn("Back to the apps", html)
