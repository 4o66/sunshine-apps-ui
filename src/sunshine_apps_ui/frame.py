# SPDX-License-Identifier: GPL-3.0-or-later
"""The 2.0 page frame: the title bar, the page, the action bar.

Every 2.0 page is `page(title, main, bar)`. The frame is the approved design's
(#56, the prototypes in design/2.0): a title bar only as tall as its words, a
scrolling page between the bars, and an action bar whose last buttons are the
Settings gear and, on the grid, Report a bug. The stylesheet is app2.css, put
inline as 1.x's is, because the policy has no style-src 'self'.

Whether the page is streamed ("couch") or at the machine ("desk") decides how
rem is sized; the server says which, once, through `set_context`.
"""

import html
import os
from typing import Optional

from .version import display as version_display

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_CSS: Optional[str] = None

# Set by the server for the pages it sends: whether this session is streamed,
# and the text size chosen for the device it is streamed to.
_CONTEXT = {"streamed": False, "text_size": "standard"}

TEXT_SIZES = ("smaller", "standard", "larger")

GEAR_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 '
            '.3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 '
            '0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 '
            '1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 '
            '0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 '
            '0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>')
BUG_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
           'stroke-linejoin="round" aria-hidden="true"><path d="M8 2l1.9 1.9M16 2l-1.9 1.9M9 7.1V6a3 3 0 1 1 6 0v1.1"/>'
           '<path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6z"/><path d="M12 20v-9M6.5 '
           '9C4.600 8.800 3 7.200 3 5M6 13H2M3 21c0-2.100 1.700-3.900 3.800-4M20.970 5c0 2.100-1.600 3.800-3.500 4M22 13h-4M17.200 '
           '17c2.100.100 3.800 1.900 3.800 4"/></svg>')


def set_context(*, streamed: Optional[bool] = None, text_size: Optional[str] = None) -> None:
    """What the server knows about this session, for every page it frames."""
    if streamed is not None:
        _CONTEXT["streamed"] = bool(streamed)
    if text_size is not None:
        _CONTEXT["text_size"] = text_size if text_size in TEXT_SIZES else "standard"


def css() -> str:
    """app2.css, read once."""
    global _CSS
    if _CSS is None:
        with open(os.path.join(_ASSETS, "app2.css"), encoding="utf-8") as handle:
            _CSS = handle.read()
    return _CSS


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def html_open(theme_name: Optional[str] = None) -> str:
    """The opening <html>: the theme, and couch or desk sizing."""
    if theme_name is None:
        from .render import theme
        theme_name = theme()
    attrs = ' lang="en"'
    if theme_name in ("light", "dark"):
        attrs += f' data-theme="{theme_name}"'
    classes = ["couch" if _CONTEXT["streamed"] else "desk"]
    if _CONTEXT["text_size"] != "standard":
        classes.append("size-" + _CONTEXT["text_size"])
    attrs += f' class="{" ".join(classes)}"'
    return f"<html{attrs}>"


def gear(here: bool = False) -> str:
    """Settings, always last-but-one or last in the bar. Flat on Settings itself."""
    if here:
        return f'<span class="btn sec icon gear flat" aria-label="Settings">{GEAR_SVG}</span>'
    return (f'<a class="btn sec icon gear" href="/settings" aria-label="Settings">'
            f'<span class="glyph wide">☰</span>{GEAR_SVG}</a>')


def bug() -> str:
    """Report a bug, after the gear, on the grid only."""
    return f'<a class="btn sec icon" href="/report" aria-label="Report a bug">{BUG_SVG}</a>'


def page(title: str, main: str, bar: str = "", *, settings_here: bool = False,
         with_bug: bool = False, theme_name: Optional[str] = None) -> str:
    """A whole 2.0 page. `main` goes in the scrolling area; `bar` is the action
    bar's own buttons, left to right, and the gear (and bug) are added after
    them. A page with no bar (Applied, Closing) passes bar=None."""
    from .render import _title
    top = ('<header class="top">\n<span class="brand">Sunshine</span><span class="sep">/</span>'
           '<span class="where">App Manager</span>\n'
           f'<span class="ver">{_e(version_display())}</span>\n</header>')
    footer = ""
    if bar is not None:
        end = gear(settings_here) + ("\n" + bug() if with_bug else "")
        footer = f'\n<footer class="bar">\n{bar}\n{end}\n</footer>'
    return ("<!doctype html>\n" + html_open(theme_name) + "\n<head>\n<meta charset=\"utf-8\">\n"
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f"<title>{_e(_title(title))}</title>\n<style>{css()}</style>\n</head>\n<body>\n"
            f"{top}\n{main}{footer}\n</body>\n</html>\n")
