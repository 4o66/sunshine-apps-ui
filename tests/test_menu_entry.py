# SPDX-License-Identifier: GPL-3.0-or-later
"""Being findable at the machine, not only from a stream.

Windows has had a Start menu shortcut since Sean asked for one; this is the
Linux half, and the icon both of them use. Sean, 2026-09-18: "we should have
the app manager icon in the windows start menu and linux equivalent. if the
start menu is categorized like bazzite, use the same category as sunshine."

Sunshine's own entry on Bazzite, read off the machine:

    Categories=RemoteAccess;Network;
    Keywords=gamestream;stream;moonlight;remote play;

so this sits beside it rather than under "Other".
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import installer, places  # noqa: E402


class DesktopEntryTest(unittest.TestCase):
    def setUp(self):
        if os.name == "nt":
            self.skipTest("the Linux half")
        self.data = tempfile.mkdtemp()
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        self.addCleanup(shutil.rmtree, self.prefix, True)
        patched = mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.data})
        patched.start()
        self.addCleanup(patched.stop)
        self.where = installer.paths(self.prefix)
        os.makedirs(os.path.join(self.where["install"], "assets"), exist_ok=True)

    def with_artwork(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copy(os.path.join(here, "assets", "poster.png"),
                    os.path.join(self.where["install"], "assets", "poster.png"))

    def entry(self):
        path = os.path.join(self.data, "applications", installer.DESKTOP_FILE)
        return open(path, encoding="utf-8").read()

    def test_it_lands_where_every_desktop_looks(self):
        installer._desktop_entry(self.where)
        self.assertTrue(os.path.isfile(
            os.path.join(self.data, "applications", installer.DESKTOP_FILE)))

    def test_it_sits_in_the_same_category_as_sunshine(self):
        installer._desktop_entry(self.where)
        self.assertIn("Categories=RemoteAccess;Network;", self.entry())

    def test_it_can_be_found_by_searching_for_sunshine(self):
        installer._desktop_entry(self.where)
        self.assertIn("sunshine", self.entry().split("Keywords=")[1].lower())

    def test_it_runs_the_installed_command(self):
        installer._desktop_entry(self.where)
        self.assertIn("Exec=%s" % self.where["command"], self.entry())

    def test_it_opens_no_terminal(self):
        """The launcher is a window; a console beside it confuses everything."""
        installer._desktop_entry(self.where)
        self.assertIn("Terminal=false", self.entry())

    def test_it_uses_the_artwork_when_there_is_some(self):
        self.with_artwork()
        installer._desktop_entry(self.where)
        icon = [l for l in self.entry().splitlines() if l.startswith("Icon=")][0]
        self.assertTrue(icon.endswith(".png"), icon)
        self.assertTrue(os.path.isfile(icon.split("=", 1)[1]))

    def test_it_still_has_an_icon_name_when_there_is_no_artwork(self):
        """A missing picture must not produce `Icon=` with nothing after it."""
        installer._desktop_entry(self.where)
        icon = [l for l in self.entry().splitlines() if l.startswith("Icon=")][0]
        self.assertNotEqual(icon.strip(), "Icon=")

    def test_uninstalling_takes_it_away(self):
        installer._desktop_entry(self.where)
        self.assertEqual(installer._remove_desktop_entry(),
                         ["Removed the menu entry."])
        self.assertFalse(os.path.isfile(
            os.path.join(self.data, "applications", installer.DESKTOP_FILE)))

    def test_removing_one_that_is_not_there_says_nothing(self):
        self.assertEqual(installer._remove_desktop_entry(), [])

    def test_nothing_is_attempted_on_windows(self):
        with mock.patch.object(os, "name", "nt"):
            self.assertEqual(installer._desktop_entry(self.where), [])
            self.assertEqual(installer._remove_desktop_entry(), [])


class MenuIconTest(unittest.TestCase):
    """A square picture, made from the artwork that is already shipped.

    Nothing is designed here -- a new icon is issue #20, and dropping
    `assets/icon.png` in beside the poster is how it arrives.
    """

    def setUp(self):
        self.prefix = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prefix, True)
        self.where = installer.paths(self.prefix)
        self.assets = os.path.join(self.where["install"], "assets")
        os.makedirs(self.assets, exist_ok=True)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copy(os.path.join(here, "assets", "poster.png"),
                    os.path.join(self.assets, "poster.png"))

    def test_it_makes_a_square_from_a_portrait_poster(self):
        from PIL import Image

        made = installer._icon_files(self.where)
        with Image.open(made["png"]) as icon:
            self.assertEqual(icon.size, (256, 256))

    def test_a_supplied_icon_is_preferred_over_the_poster(self):
        """Which is how issue #20 lands: a file, no code change."""
        from PIL import Image

        Image.new("RGB", (400, 400), (1, 2, 3)).save(
            os.path.join(self.assets, "icon.png"))
        made = installer._icon_files(self.where)
        with Image.open(made["png"]) as icon:
            self.assertEqual(icon.getpixel((10, 10))[:3], (1, 2, 3))

    def test_windows_gets_an_ico_because_a_lnk_cannot_use_a_png(self):
        if os.name != "nt":
            self.skipTest("the .ico is only made on Windows")
        self.assertTrue(installer._icon_files(self.where).get("ico", "")
                        .endswith(".ico"))

    def test_no_artwork_at_all_is_not_an_error(self):
        os.unlink(os.path.join(self.assets, "poster.png"))
        self.assertEqual(installer._icon_files(self.where), {})

    def test_no_pillow_is_not_an_error_either(self):
        """Pillow is bundled on Windows and absent on plenty of Linux boxes."""
        real = __import__("builtins").__import__

        def refuse(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("no Pillow here")
            return real(name, *args, **kwargs)

        with mock.patch("builtins.__import__", refuse):
            self.assertEqual(installer._icon_files(self.where), {"png": ""})


class DataHomeTest(unittest.TestCase):
    def test_it_honours_the_xdg_variable(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/somewhere/else"}):
            self.assertEqual(places.data_home(), "/somewhere/else")

    def test_it_falls_back_to_the_usual_place(self):
        environ = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertTrue(places.data_home().endswith(
                os.path.join(".local", "share")))


if __name__ == "__main__":
    unittest.main()
