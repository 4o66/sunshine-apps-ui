# SPDX-License-Identifier: GPL-3.0-or-later
"""Language: choosing one, falling back, and never showing a blank label.

Strings ship with the program because they are tiny. Artwork does not, because
a tile is a picture with the words baked in -- and because with the Pillow we
ship on Windows there is no text shaping, so most scripts cannot be rendered
correctly at all. The wordless set is the default, and these tests are mostly
about that being true in every direction.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import i18n  # noqa: E402


class TagsTest(unittest.TestCase):
    def test_the_shapes_a_machine_actually_reports(self):
        for given, wanted in (("en_GB.UTF-8", "en-GB"), ("pt_br", "pt-BR"),
                              ("fr", "fr"), ("zh-hans", "zh-Hans"),
                              ("de_DE@euro", "de-DE"), ("", "")):
            self.assertEqual(i18n._normalise(given), wanted, given)

    def test_the_chain_narrows_then_gives_up_to_english(self):
        self.assertEqual(i18n.candidates("pt-BR"), ["pt-BR", "pt", "en"])
        self.assertEqual(i18n.candidates("fr"), ["fr", "en"])
        self.assertEqual(i18n.candidates("en"), ["en"])

    def test_c_and_posix_are_not_languages(self):
        for value in ("C", "POSIX", "c.UTF-8"):
            with mock.patch.dict(os.environ, {"LANG": value, "SAU_LANGUAGE": "",
                                              "LANGUAGE": "", "LC_ALL": "",
                                              "LC_MESSAGES": ""}, clear=False):
                self.assertNotIn(i18n.system_language().lower(), ("c", "posix"))

    def test_an_override_wins(self):
        with mock.patch.dict(os.environ, {"SAU_LANGUAGE": "ja_JP.UTF-8"}):
            self.assertEqual(i18n.system_language(), "ja-JP")


class CatalogueTest(unittest.TestCase):
    def setUp(self):
        i18n._cache.clear()
        self.addCleanup(i18n._cache.clear)

    def test_english_is_shipped_and_complete_enough_to_be_a_template(self):
        self.assertIn("en", i18n.available())
        data = json.load(open(os.path.join(i18n.locales_dir(), "en.json"),
                              encoding="utf-8"))
        for section in ("tiles", "names", "ui", "scanning", "settings", "report"):
            self.assertIn(section, data)
        self.assertIn("_meta", data, "a translator needs somewhere to say what this is")

    def test_a_string_comes_back(self):
        self.assertEqual(i18n.text("ui.rescan", "en"), "Rescan")

    def test_fields_are_substituted(self):
        self.assertEqual(i18n.text("ui.apply_many", "en", count=3),
                         "Apply 3 changes")

    def test_a_missing_key_shows_the_key_rather_than_nothing(self):
        """A blank label reads as a rendering bug; the key says what to fix."""
        self.assertEqual(i18n.text("ui.no_such_thing", "en"), "ui.no_such_thing")

    def test_a_missing_field_does_not_raise(self):
        self.assertIn("{count}", i18n.text("ui.apply_many", "en"))

    def test_an_unknown_language_is_english_rather_than_empty(self):
        self.assertEqual(i18n.text("ui.rescan", "xx-YY"), "Rescan")

    def test_the_prefixes_are_in_the_catalogue_with_their_reason_recorded(self):
        """#1 and Zz are sort keys; a translator must not helpfully drop them."""
        data = json.load(open(os.path.join(i18n.locales_dir(), "en.json"),
                              encoding="utf-8"))
        self.assertTrue(data["names"]["desktop"].startswith("#1"))
        self.assertTrue(data["names"]["steam"].startswith("Zz"))
        self.assertIn("sort", data["names"]["_comment"].lower())


class PartialTranslationTest(unittest.TestCase):
    """The normal state of a translation is unfinished."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copy(os.path.join(i18n.locales_dir(), "en.json"), self.tmp)
        with open(os.path.join(self.tmp, "fr.json"), "w", encoding="utf-8") as fh:
            json.dump({"_meta": {"code": "fr"}, "ui": {"rescan": "Analyser"}}, fh)
        patched = mock.patch.object(i18n, "locales_dir", return_value=self.tmp)
        patched.start()
        self.addCleanup(patched.stop)
        i18n._cache.clear()
        self.addCleanup(i18n._cache.clear)

    def test_what_is_translated_is_used(self):
        self.assertEqual(i18n.text("ui.rescan", "fr"), "Analyser")

    def test_what_is_not_falls_back_to_english_rather_than_blank(self):
        self.assertEqual(i18n.text("ui.discard", "fr"), "Discard")

    def test_a_regional_tag_uses_the_base_language(self):
        self.assertEqual(i18n.text("ui.rescan", "fr-CA"), "Analyser")


class ArtworkTest(unittest.TestCase):
    """Wordless is the default, and the fallback is per tile, not per set."""

    def setUp(self):
        i18n._cache.clear()
        self.addCleanup(i18n._cache.clear)

    def test_both_sets_are_shipped(self):
        for name in ("_wordless", "en"):
            self.assertTrue(os.path.isdir(os.path.join(i18n.tiles_dir(), name)),
                            name)

    def test_english_gets_the_english_set(self):
        self.assertEqual(os.path.basename(i18n.tile_set("en-GB")), "en")

    def test_a_language_we_have_not_drawn_gets_the_wordless_one(self):
        """Not a consolation prize: it is correct in every language."""
        self.assertEqual(os.path.basename(i18n.tile_set("ar-EG")), "_wordless")
        self.assertEqual(os.path.basename(i18n.tile_set("hi-IN")), "_wordless")

    def test_every_english_tile_has_a_wordless_twin(self):
        worded = {n for n in os.listdir(os.path.join(i18n.tiles_dir(), "en"))
                  if n.endswith(".png")}
        wordless = {n for n in os.listdir(os.path.join(i18n.tiles_dir(), "_wordless"))
                    if n.endswith(".png")}
        self.assertEqual(worded - wordless, set(),
                         "a tile with no wordless twin cannot be shown to most users")

    def test_a_tile_resolves_to_a_real_file(self):
        path = i18n.tile("steam.png", "en")
        self.assertTrue(os.path.isfile(path))
        self.assertIn(os.path.join("tiles", "en"), path)

    def test_an_incomplete_set_falls_back_tile_by_tile(self):
        """A translator who did the common four is still useful."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(i18n.tiles_dir(), "_wordless"),
                        os.path.join(tmp, "_wordless"))
        os.makedirs(os.path.join(tmp, "fr"))
        shutil.copy(os.path.join(i18n.tiles_dir(), "en", "steam.png"),
                    os.path.join(tmp, "fr", "steam.png"))
        with mock.patch.object(i18n, "tiles_dir", return_value=tmp):
            self.assertIn(os.path.join("fr", "steam.png"), i18n.tile("steam.png", "fr"))
            self.assertIn("_wordless", i18n.tile("heroic.png", "fr"))

    def test_describe_says_which_artwork_is_in_use(self):
        with mock.patch.object(i18n, "system_language", return_value="ar-EG"):
            self.assertIn("wordless", i18n.describe())
        with mock.patch.object(i18n, "system_language", return_value="en-US"):
            self.assertIn("assets/tiles/en", i18n.describe())


if __name__ == "__main__":
    unittest.main()
