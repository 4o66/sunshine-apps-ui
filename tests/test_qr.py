# SPDX-License-Identifier: GPL-3.0-or-later
"""The QR code on the "report a bug" page, and the page itself.

A bug report from a television is the case this exists for: through Moonlight
there is no keyboard, no address bar and nothing to copy a URL into, so the
address is a code the phone in your hand can read.

**The encoder is checked against two independent implementations.** Neither is
a dependency of this program -- they were installed in a scratch environment
while this was written, and what they produced is here as a fixture, so the
suite needs nothing installed. `python-qrcode` produces exactly this matrix,
mask selection included. `segno` agrees except for one extra `0x00` codeword
between the terminated data and the padding, which decoders never see: they
stop at the character count.

A QR code that does not scan is worse than no QR code, which is why this is
pinned to a matrix rather than to "it looked square".
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import qr, render  # noqa: E402

# github.com/4o66/sunshine-apps-ui/issues, error correction M, byte mode.
# Verified identical to python-qrcode's output for the same string.
ROWS = (
    "111111101111100010010101001111111",
    "100000101111001001000011101000001",
    "101110100101111010101000101011101",
    "101110101011100000110010001011101",
    "101110100101010011100000101011101",
    "100000100100110111100110101000001",
    "111111101010101010101010101111111",
    "000000001001100111010000000000000",
    "101101110101001111000110101001011",
    "011110001010010011011101001101101",
    "111001101100010010101011011111011",
    "001111011110100111011000000101000",
    "110000100100101110001011010011011",
    "000001001100111001001110100101010",
    "111011101010000001111100101111000",
    "100101000100001100100101111011100",
    "001001101010010010000111011010100",
    "011000010100101100000011111011011",
    "011110100111001100101000101110100",
    "111100000010100111110011111010011",
    "010010101000000110000010110001100",
    "101100011010001111001101001100101",
    "000110101110111100111101111111011",
    "010000000011010100101000001011001",
    "101101111100000001010011111111011",
    "000000001000110110111100100011000",
    "111111101010000001111101101010000",
    "100000101100101111101001100011101",
    "101110100010111011110011111110110",
    "101110101011000010010111000100011",
    "101110101101011111101010001100100",
    "100000100101111001101011110110001",
    "111111101101101001110101001011100",
)


class TheCodeIsTheOneThatScansTest(unittest.TestCase):
    def test_the_issues_url_encodes_to_the_verified_matrix(self):
        """If this fails, the code changed. Re-verify it before changing this."""
        produced = ["".join(str(cell) for cell in row)
                    for row in qr.matrix(render.ISSUES_URL)]
        self.assertEqual(produced, list(ROWS))

    def test_it_is_the_size_the_version_says(self):
        self.assertEqual(len(ROWS), 33)          # version 4
        self.assertTrue(all(len(row) == 33 for row in ROWS))

    def test_the_three_finder_patterns_are_where_they_must_be(self):
        grid = qr.matrix(render.ISSUES_URL)
        size = len(grid)
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
            self.assertEqual([grid[top][left + i] for i in range(7)],
                             [1, 1, 1, 1, 1, 1, 1], (top, left))
            self.assertEqual(grid[top + 1][left + 1], 0)
            self.assertEqual(grid[top + 3][left + 3], 1)

    def test_the_timing_pattern_alternates(self):
        grid = qr.matrix(render.ISSUES_URL)
        row = [grid[6][i] for i in range(8, len(grid) - 8)]
        self.assertEqual(row, [1 - (i % 2) for i in range(len(row))])

    def test_a_longer_string_needs_a_bigger_code(self):
        small = len(qr.matrix("hello"))
        large = len(qr.matrix("https://example.com/" + "x" * 90))
        self.assertGreater(large, small)

    def test_it_refuses_what_it_cannot_encode_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            qr.matrix("x" * 300)


class TheSvgIsUsableOnThesePagesTest(unittest.TestCase):
    def svg(self):
        return qr.svg(render.ISSUES_URL)

    def test_it_is_inline_and_needs_no_second_request(self):
        """default-src 'none' and img-src 'self': one fewer thing to be refused."""
        markup = self.svg()
        self.assertTrue(markup.startswith("<svg "))
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', markup)
        self.assertNotIn("<image", markup)

    def test_it_has_a_quiet_zone_or_nothing_will_read_it(self):
        markup = self.svg()
        modules = len(qr.matrix(render.ISSUES_URL))
        self.assertIn(f'viewBox="0 0 {modules + 8} {modules + 8}"', markup)

    def test_it_is_black_on_white_whatever_the_page_is(self):
        """A code inverted by a dark theme does not scan."""
        markup = self.svg()
        self.assertIn('fill="#ffffff"', markup)
        self.assertIn('fill="#000000"', markup)

    def test_the_url_in_the_label_is_escaped(self):
        markup = qr.svg("https://x/?a=1&b=2")
        self.assertIn("&amp;", markup)
        self.assertNotIn("a=1&b=2", markup)


class TheReportPageTest(unittest.TestCase):
    """Two ways of looking at it, and the page leads with the right one."""

    def page(self, streamed):
        return render.report_page("tok-123", via_sunshine=streamed,
                                  platform="Windows 11")

    def test_on_a_stream_the_code_comes_first(self):
        html = self.page(True)
        self.assertLess(html.index("Scan this with your phone"),
                        html.index("at the machine itself"))

    def test_at_the_machine_the_link_comes_first(self):
        html = self.page(False)
        self.assertLess(html.index("Open the issues page"),
                        html.index("Or scan it with your phone"))

    def test_both_are_always_there(self):
        """Getting the detection wrong must cost nothing."""
        for streamed in (True, False):
            html = self.page(streamed)
            self.assertIn("<svg ", html)
            self.assertIn(render.ISSUES_URL, html)

    def test_the_link_leaves_this_window_alone(self):
        """In our own window it goes to the desktop; in a browser, a new tab.

        Either way the manager is still there afterwards -- there is no way
        back from a page with no address bar.
        """
        html = self.page(False)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_it_says_what_to_put_in_the_report(self):
        html = self.page(True)
        self.assertIn("Worth mentioning", html)
        self.assertIn("Windows 11", html)
        self.assertIn("through Sunshine", html)

    def test_it_can_be_left(self):
        self.assertIn('href="/?token=tok-123"', self.page(True))

    def test_the_grid_offers_it(self):
        grid = render.grid_page({"apps": [], "apps_json": "/x/apps.json"}, "tok")
        self.assertIn("/report?token=tok", grid)
        self.assertIn("Report a bug", grid)


if __name__ == "__main__":
    unittest.main()
