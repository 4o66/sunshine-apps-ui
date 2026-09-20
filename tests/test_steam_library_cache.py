# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the picture Steam already has for a game.

Steam changed where it keeps them. It used to be flat files named after the
appid; it is now a directory per appid, with the asset a further level down
under a content hash. The importer only knew the old shape, so on any current
Steam it found nothing -- every imported game arrived with no artwork, and the
picker then offered SteamGridDB as though a key were required for a picture that
was already on the disk.

Measured on the rig with a real Steam: five files present under
``appcache/librarycache/3606890/``, and both of the flat names absent.

The picker already knew both layouts. These tests are mostly about the two
answering the same question the same way, because that is what went wrong.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core import artwork_sources  # noqa: E402


class LibraryCacheLayoutTest(unittest.TestCase):
    APPID = "3606890"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = os.path.join(self.tmp, "appcache", "librarycache")
        os.makedirs(self.cache)

    def place(self, *parts, content=b"\x89PNG\r\n\x1a\n"):
        path = os.path.join(self.cache, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return path

    # --- the layout Steam uses now ----------------------------------------

    def test_the_portrait_is_found_under_a_content_hash(self):
        """librarycache/<appid>/<hash>/library_capsule.jpg -- the current shape."""
        wanted = self.place(self.APPID, "8968499686cff", "library_capsule.jpg")
        self.assertEqual(artwork_sources.steam_local_portrait(self.tmp, self.APPID),
                         wanted)

    def test_the_portrait_is_found_directly_in_the_appid_directory(self):
        wanted = self.place(self.APPID, "library_600x900.jpg")
        self.assertEqual(artwork_sources.steam_local_portrait(self.tmp, self.APPID),
                         wanted)

    def test_a_hero_banner_is_not_offered_as_a_portrait(self):
        """A tile is portrait; a wide banner stretched into one looks wrong."""
        self.place(self.APPID, "library_hero.jpg")
        self.assertEqual(artwork_sources.steam_local_portrait(self.tmp, self.APPID), "")

    # --- the layout it used to use, which still exists on upgraded machines --

    def test_the_old_flat_name_still_works(self):
        wanted = self.place(f"{self.APPID}_library_600x900.jpg")
        self.assertEqual(artwork_sources.steam_local_portrait(self.tmp, self.APPID),
                         wanted)

    def test_a_machine_with_both_layouts_gets_one_answer(self):
        self.place(f"{self.APPID}_library_600x900.jpg")
        self.place(self.APPID, "8968499686cff", "library_capsule.jpg")
        found = artwork_sources.steam_local_portrait(self.tmp, self.APPID)
        self.assertTrue(found)

    # --- and the cases where there is nothing ------------------------------

    def test_another_game_s_artwork_is_not_offered(self):
        self.place("999999", "8968499686cff", "library_capsule.jpg")
        self.assertEqual(artwork_sources.steam_local_portrait(self.tmp, self.APPID), "")

    def test_no_cache_at_all_is_not_an_error(self):
        self.assertEqual(artwork_sources.steam_local_portrait(self.tmp, self.APPID), "")
        self.assertEqual(artwork_sources.steam_local_portrait("", self.APPID), "")


class ImporterAgreesWithPickerTest(unittest.TestCase):
    """The bug was two answers to one question. This is the property that failed."""

    APPID = "3606890"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.images = os.path.join(self.tmp, "images")
        os.makedirs(self.images)
        self.cache = os.path.join(self.tmp, "appcache", "librarycache")
        os.makedirs(self.cache)

    def test_what_the_picker_offers_is_what_the_importer_uses(self):
        from PIL import Image

        source = os.path.join(self.cache, self.APPID, "8968499686cff")
        os.makedirs(source)
        portrait = os.path.join(source, "library_capsule.jpg")
        Image.new("RGB", (600, 900), (20, 40, 80)).save(portrait)

        offered = artwork_sources.steam_local_portrait(self.tmp, self.APPID)
        self.assertEqual(offered, portrait)

        from sunshine_apps_ui.core.images import steam_local_to_png
        produced = steam_local_to_png(int(self.APPID), self.images, steam_root=self.tmp)
        self.assertTrue(produced, "the importer found nothing the picker could see")
        self.assertTrue(os.path.isfile(produced))

    def test_the_importer_finds_nothing_when_there_is_nothing(self):
        from sunshine_apps_ui.core.images import steam_local_to_png
        self.assertEqual(
            steam_local_to_png(int(self.APPID), self.images, steam_root=self.tmp), "")



class SgdbNoteTest(unittest.TestCase):
    """What the picker says when it has found nothing.

    The maintainer, on seeing the old one: "why do i suddenly need a key? no regular user
    will have the slightest clue what this means." The wording is issue #22 and
    still open; what is settled is that it must not name a command that does not
    exist.
    """

    def note(self):
        candidates, note = artwork_sources._sgdb(
            name="Whatever", appid="", key="", timeout=1)
        self.assertEqual(candidates, [])
        return note

    def test_it_does_not_name_the_old_importer(self):
        """sunshine-import was the previous project's command. It is not here."""
        self.assertNotIn("sunshine-import ", self.note())

    def test_it_names_the_command_that_exists(self):
        self.assertIn("sunshine-apps-ui --save-sgdb-key", self.note())

    def test_it_says_what_steamgriddb_is(self):
        self.assertIn("community library", self.note())

    def test_it_does_not_claim_anything_about_what_was_found(self):
        """This function has no idea. It is one source among several.

        It used to lead with "No artwork was found for this one", which read
        correctly while SteamGridDB was the last resort -- and became a lie the
        moment our own tiles were offered on the same page. The lead is now
        added by find_candidates, which is the only thing that knows.
        """
        self.assertFalse(self.note().startswith("No artwork was found"))

    def test_the_situation_still_leads_when_there_is_nothing(self):
        with mock.patch.object(artwork_sources, "_origin_bytes",
                               side_effect=OSError("404")):
            result = artwork_sources.find_candidates(
                tempfile.mkdtemp(), name="Whatever", source="heroic", ident="x")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["notes"][0].startswith("No artwork was found"))

if __name__ == "__main__":
    unittest.main()
