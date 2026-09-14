"""Every page must offer a way onward.

This exists because a page shipped with no links at all: the "already queued to
un-hide" branch rendered a sentence and nothing else, so the only way out was
the browser's back button. The tests for it asserted the sentence was present
and the button was absent, which was exactly wrong.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import render  # noqa: E402

APP = {"name": "X", "index": 0, "source": "steam", "id": "1"}
HIDDEN = {"name": "X", "source": "steam", "id": "1", "image-path": ""}
PLAN = {"plan": {"added": []}, "totals": {}}


def pages():
    return {
        "grid": render.grid_page({"apps": [], "hidden": []}, "t"),
        "app": render.app_page(APP, "t"),
        "app (new)": render.app_page({}, "t", is_new=True),
        "hidden": render.hidden_page(HIDDEN, "t"),
        "hidden (queued)": render.hidden_page(HIDDEN, "t", queued=True),
        "explain hide": render.explain_page("hide", APP, "t"),
        "explain delete": render.explain_page("delete", APP, "t"),
        "connect": render.connect_page("t"),
        "confirm": render.confirm_page(PLAN, "t"),
        "confirm (nothing)": render.confirm_page({"plan": {}, "totals": {}}, "t"),
        "applied": render.applied_page("t"),
        "error": render.error_page("boom", token="t"),
    }


class TestEveryPageHasAWayOnward(unittest.TestCase):
    def test_each_page_offers_at_least_one_link_or_button(self):
        for name, html in pages().items():
            with self.subTest(page=name):
                affordances = (len(re.findall(r'<a\b', html))
                               + len(re.findall(r'<button\b', html)))
                self.assertGreater(affordances, 0, f"{name} is a dead end")

    def test_each_page_can_reach_the_grid_in_one_step(self):
        """Not only some link: a way back to where everything starts."""
        for name, html in pages().items():
            if name == "grid":
                continue
            with self.subTest(page=name):
                to_grid = re.search(r'href="/(\?token=[^"]*)?"', html)
                to_app = re.search(r'href="/app\?', html)
                self.assertTrue(to_grid or to_app,
                                f"{name} cannot get back to the grid or an app")

    def test_no_page_still_talks_about_a_plan(self):
        """Wording left from when this was an import preview rather than a manager."""
        for name, html in pages().items():
            with self.subTest(page=name):
                self.assertNotIn("Could not read a plan", html)

    def test_every_link_and_form_carries_a_token(self):
        """A link without one lands on a refusal, as /app.js did."""
        for name, html in pages().items():
            with self.subTest(page=name):
                for target in re.findall(r'(?:href|action|src)="(/[^"]*)"', html):
                    if target.startswith("//"):
                        continue
                    self.assertIn("token=", target, f"{name}: {target} has no token")


if __name__ == "__main__":
    unittest.main()
