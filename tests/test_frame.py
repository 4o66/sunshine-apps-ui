# SPDX-License-Identifier: GPL-3.0-or-later
"""The 2.0 page frame (#56): title bar, scrolling page, action bar."""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sunshine_apps_ui import frame  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class FrameTest(unittest.TestCase):
    def tearDown(self):
        frame.set_context(streamed=False, text_size="standard")

    def test_the_stylesheet_is_the_approved_one(self):
        """The build's stylesheet is the prototypes' byte for byte: the build
        matches the design, and this is where that starts."""
        design = os.path.join(HERE, "..", "design", "2.0", "app.css")
        with open(design, encoding="utf-8") as handle:
            self.assertEqual(frame.css(), handle.read())

    def test_a_page_has_the_three_parts_in_order(self):
        body = frame.page("Grid", "<main class=\"main\">x</main>", "<a class=\"btn\" href=\"/\">A</a>", theme_name="dark")
        self.assertLess(body.index('<header class="top">'), body.index('<main class="main">'))
        self.assertLess(body.index('<main class="main">'), body.index('<footer class="bar">'))

    def test_the_gear_ends_the_bar_and_the_bug_follows_it(self):
        body = frame.page("Grid", "<main class=\"main\"></main>", "<a href=\"/\">A</a>", with_bug=True, theme_name="dark")
        bar = body[body.index('<footer class="bar">'):]
        self.assertLess(bar.index('aria-label="Settings"'), bar.index('aria-label="Report a bug"'))
        self.assertLess(bar.index('<a href="/">A</a>'), bar.index('aria-label="Settings"'))

    def test_on_settings_the_gear_is_drawn_flat(self):
        body = frame.page("Settings", "<main class=\"main\"></main>", "", settings_here=True, theme_name="dark")
        self.assertIn('class="btn sec icon gear flat"', body)
        self.assertNotIn('href="/settings"', body)

    def test_a_page_with_no_bar_has_no_footer(self):
        body = frame.page("Closing", "<main class=\"main\"></main>", None, theme_name="dark")
        self.assertNotIn("<footer", body)

    def test_streamed_is_couch_and_at_the_machine_is_desk(self):
        frame.set_context(streamed=True)
        self.assertIn('class="couch"', frame.html_open("dark"))
        frame.set_context(streamed=False)
        self.assertIn('class="desk"', frame.html_open("dark"))

    def test_the_theme_is_carried(self):
        self.assertIn('data-theme="light"', frame.html_open("light"))
        self.assertNotIn("data-theme", frame.html_open("system"))

    def test_an_unknown_text_size_is_standard(self):
        frame.set_context(text_size="enormous")
        self.assertNotIn("size-", frame.html_open("dark"))

    def test_no_inline_script(self):
        body = frame.page("Grid", "<main class=\"main\"></main>", "", theme_name="dark")
        self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)", body))


if __name__ == "__main__":
    unittest.main()
