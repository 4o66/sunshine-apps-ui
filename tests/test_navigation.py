# SPDX-License-Identifier: GPL-3.0-or-later
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
ART = [{"id": "a" * 16, "source": "steam-cdn", "label": "Portrait",
        "path": "/img/a.png"}]


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
        "artwork": render.artwork_page(ART, "t", key="index:0", label="X",
                                       notes=["nothing configured"]),
        "artwork (empty)": render.artwork_page([], "t", key="new", label="X"),
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
                for target in re.findall(r'(?:href|src)="(/[^"]*)"', html):
                    if target.startswith("//"):
                        continue
                    self.assertIn("token=", target, f"{name}: {target} has no token")

    def test_every_form_carries_a_token(self):
        """A GET form drops its action's query string, so those pass it as a
        hidden field instead. Either way it has to be in the request."""
        for name, html in pages().items():
            with self.subTest(page=name):
                for form in re.findall(r'<form\b.*?</form>', html, re.S):
                    action = re.search(r'action="([^"]*)"', form)
                    carried = ("token=" in (action.group(1) if action else "")
                               or 'name="token"' in form)
                    self.assertTrue(carried, f"{name}: a form has no token")


if __name__ == "__main__":
    unittest.main()


class ItSaysWhatProgramThisIsTest(unittest.TestCase):
    """One name, on every page.

    The navbar said "apps import" on some pages and "apps" on others, and the
    window title said "Sunshine apps" -- none of which is what this is called.
    It runs as its own window, so the title is what the title bar and the task
    switcher show.
    """

    def test_every_page_names_the_program_in_its_title(self):
        for name, html in pages().items():
            with self.subTest(page=name):
                title = re.search(r"<title>(.*?)</title>", html, re.S)
                self.assertIsNotNone(title, f"{name} has no title")
                self.assertIn(render.PRODUCT, title.group(1))

    def test_every_page_says_the_same_thing_in_the_navbar(self):
        seen = set()
        for name, html in pages().items():
            found = re.search(r'class="where">([^<]*)<', html)
            self.assertIsNotNone(found, f"{name} has no navbar label")
            seen.add(found.group(1))
        self.assertEqual(len(seen), 1, f"the navbar says several things: {seen}")

    def test_no_page_still_calls_it_an_importer(self):
        """Importing is one of the things it does, not what it is."""
        for name, html in pages().items():
            with self.subTest(page=name):
                self.assertNotIn("apps import", html)

    def test_the_title_leads_with_the_program_rather_than_the_page(self):
        """That is what someone is looking for in a task switcher."""
        title = re.search(r"<title>(.*?)</title>",
                          render.app_page(APP, "t"), re.S).group(1)
        self.assertTrue(title.startswith(render.PRODUCT), title)


class RestorePreviewTest(unittest.TestCase):
    """What a restore would do, said on the grid and marked on the tile."""

    STATE = {"apps": [{"index": 0, "name": "Satisfactory 1.2", "source": "steam",
                       "id": "526870", "image-path": "", "managed": True}],
             "hidden": []}
    RESTORE = {"backup": "apps-20260915-193715.json", "qid": "q1",
               "returning": [{"name": "Portal: Revolution"}], "going": [],
               "changing": [{"name": "Satisfactory 1.2", "becomes": "Satisfactory",
                             "key": "steam:526870",
                             "fields": ["name", "image-path"]}],
               "hidden_now": 0, "hidden_then": 0}

    def _html(self, restore=None):
        return render.grid_page(
            self.STATE, "t", pending=[{"op": "rollback", "backup": "x", "qid": "q1"}],
            restore=restore if restore is not None else self.RESTORE)

    def test_it_says_what_the_name_would_become(self):
        self.assertIn("Satisfactory", self._html())
        self.assertRegex(self._html(), r"Satisfactory 1\.2\s*&rarr;\s*<b>Satisfactory</b>")

    def test_it_says_which_other_fields_change(self):
        """"artwork", not "image-path": nobody thinks of a cover that way."""
        self.assertIn("artwork", self._html())
        self.assertNotIn("image-path", self._html())

    def test_the_tile_itself_is_marked(self):
        """It was not, because it was looked up by the name it would become."""
        self.assertIn("pending", self._html())

    def test_it_is_found_by_its_marker_not_its_name(self):
        renamed = dict(self.RESTORE)
        renamed["changing"] = [dict(self.RESTORE["changing"][0], name="Something Else")]
        self.assertIn("pending", self._html(renamed))

    def test_a_change_with_no_rename_reads_plainly(self):
        plain = dict(self.RESTORE)
        plain["changing"] = [{"name": "Satisfactory 1.2", "becomes": None,
                              "key": "steam:526870", "fields": ["cmd"]}]
        html = self._html(plain)
        self.assertIn("Satisfactory 1.2 (command)", html)
        self.assertNotIn("&rarr;", html)


class ItSaysWhichBuildTest(unittest.TestCase):
    """Which build is on screen, so a screenshot answers the question.

    In both places on purpose: the navbar is what a photograph of a television
    catches, and the window title is what a task switcher shows.
    """

    def test_every_page_shows_the_version_in_the_bar(self):
        for name, html in pages().items():
            with self.subTest(page=name):
                self.assertIn(render.version_display(), html)

    def test_every_page_carries_it_in_the_title_too(self):
        for name, html in pages().items():
            with self.subTest(page=name):
                title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
                self.assertIn(render.version_display(), title)

    def test_a_development_build_is_marked_as_one(self):
        self.assertIn("dev", render.version_display())
