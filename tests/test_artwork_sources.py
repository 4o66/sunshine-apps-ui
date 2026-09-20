# SPDX-License-Identifier: GPL-3.0-or-later
"""The artwork picker's sources.

Nothing here touches the network: every source is exercised by substituting the
one function that fetches bytes, which is also the only thing that would be slow.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui.core import artwork_sources as art  # noqa: E402


def _sample_png() -> bytes:
    """A real PNG, because the code under test runs it through an image library.

    Noise rather than a flat colour: a solid image compresses below the size
    floor that tells a genuine cover apart from a CDN's placeholder.
    """
    from io import BytesIO
    from PIL import Image
    image = Image.frombytes(
        "RGB", (64, 64),
        bytes(bytearray(os.urandom(64 * 64 * 3))))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


SAMPLE_PNG = _sample_png()


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def fake_fetch(self, available=None):
        """Stand in for the network. *available* is the set of origins that work."""
        def fetch(origin, timeout):
            if available is None or origin in available:
                return SAMPLE_PNG
            raise OSError("404")
        return mock.patch.object(art, "_origin_bytes", side_effect=fetch)


class CandidateIdTest(_Fixture):
    def test_id_is_stable_for_an_origin(self):
        self.assertEqual(art.candidate_id("https://x/y.jpg"),
                         art.candidate_id("https://x/y.jpg"))

    def test_different_origins_differ(self):
        self.assertNotEqual(art.candidate_id("a"), art.candidate_id("b"))

    def test_id_is_a_safe_filename(self):
        self.assertRegex(art.candidate_id("../../etc/passwd"), r"^[0-9a-f]{16}$")


class SteamLocalTest(_Fixture):
    def _librarycache(self, *names):
        root = os.path.join(self.conf, "steam")
        cache = os.path.join(root, "appcache", "librarycache")
        for name in names:
            path = os.path.join(cache, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(SAMPLE_PNG)
        return root

    def test_flat_layout_is_found(self):
        root = self._librarycache("526870_library_600x900.jpg")
        found = art._steam_local(root, "526870")
        self.assertEqual([c["label"] for c in found], ["Portrait"])

    def test_per_appid_directory_layout_is_found(self):
        root = self._librarycache("526870/library_hero.jpg")
        found = art._steam_local(root, "526870")
        self.assertEqual([c["label"] for c in found], ["Hero banner"])

    def test_artwork_under_a_content_hash_is_found(self):
        # What a current Steam client actually writes: the portrait is two
        # levels down, in a directory named for the image's hash.
        root = self._librarycache("526870/8968499686cf/library_capsule.jpg")
        found = art._steam_local(root, "526870")
        self.assertEqual([c["label"] for c in found], ["Portrait"])

    def test_a_portrait_in_both_layouts_is_offered_once(self):
        root = self._librarycache("526870_library_600x900.jpg",
                                  "526870/abc/library_capsule.jpg")
        found = art._steam_local(root, "526870")
        self.assertEqual([c["label"] for c in found], ["Portrait"])

    def test_the_blurred_backdrop_is_not_offered_as_cover_art(self):
        root = self._librarycache("526870/library_hero_blur.jpg")
        self.assertEqual(art._steam_local(root, "526870"), [])

    def test_assets_come_in_a_useful_order(self):
        root = self._librarycache("526870/library_hero.jpg",
                                  "526870/abc/library_capsule.jpg")
        found = art._steam_local(root, "526870")
        self.assertEqual([c["label"] for c in found], ["Portrait", "Hero banner"])

    def test_another_games_artwork_is_not_offered(self):
        root = self._librarycache("99_library_600x900.jpg", "99/library_hero.jpg")
        self.assertEqual(art._steam_local(root, "526870"), [])

    def test_no_steam_means_no_candidates(self):
        self.assertEqual(art._steam_local("", "526870"), [])

    def test_a_missing_cache_is_not_an_error(self):
        self.assertEqual(art._steam_local(self.conf, "526870"), [])

    def test_a_non_numeric_id_is_not_a_steam_appid(self):
        root = self._librarycache("526870_library_600x900.jpg")
        self.assertEqual(art._steam_local(root, "apps-ui"), [])


class SteamCdnTest(_Fixture):
    def test_portrait_comes_first(self):
        found = art._steam_cdn("526870")
        self.assertEqual(found[0]["label"], "Portrait")

    def test_each_asset_is_offered_once_with_spare_hosts(self):
        found = art._steam_cdn("526870")
        self.assertEqual(len(found), 4)
        for candidate in found:
            self.assertTrue(candidate["alternates"])
            self.assertNotIn(candidate["origin"], candidate["alternates"])

    def test_nothing_for_a_launcher(self):
        self.assertEqual(art._steam_cdn("desktop"), [])


class FetchTest(_Fixture):
    def test_a_spare_host_is_used_when_the_first_fails(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch({candidate["alternates"][0]}):
            got = art._fetch_candidate(self.conf, dict(candidate), 1)
        self.assertIsNotNone(got)
        self.assertTrue(os.path.isfile(got["path"]))

    def test_the_cache_file_is_named_for_the_primary_origin(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch({candidate["alternates"][0]}):
            got = art._fetch_candidate(self.conf, dict(candidate), 1)
        self.assertEqual(os.path.basename(got["path"]), f"{candidate['id']}.png")

    def test_a_candidate_nothing_serves_is_dropped(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch(set()):
            self.assertIsNone(art._fetch_candidate(self.conf, dict(candidate), 1))

    def test_a_cached_candidate_is_not_refetched(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch() as fetch:
            art._fetch_candidate(self.conf, dict(candidate), 1)
            art._fetch_candidate(self.conf, dict(candidate), 1)
            self.assertEqual(fetch.call_count, 1)


class FindCandidatesTest(_Fixture):
    def test_local_artwork_is_offered_before_the_cdn(self):
        cache = os.path.join(self.conf, "steam", "appcache", "librarycache", "526870", "abc")
        os.makedirs(cache)
        with open(os.path.join(cache, "library_capsule.jpg"), "wb") as handle:
            handle.write(SAMPLE_PNG)
        with self.fake_fetch():
            result = art.find_candidates(
                self.conf, name="Satisfactory", source="steam", ident="526870",
                steam_root=os.path.join(self.conf, "steam"), sgdb_enable=False)
        sources = [c["source"] for c in result["candidates"]]
        self.assertEqual(sources[0], "steam-local")
        self.assertIn("steam-cdn", sources)

    def test_every_candidate_has_a_cached_file(self):
        with self.fake_fetch():
            result = art.find_candidates(self.conf, source="steam", ident="526870",
                                         sgdb_enable=False)
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertTrue(os.path.isfile(candidate["path"]))

    def test_an_unconfigured_key_is_explained_rather_than_ignored(self):
        with self.fake_fetch():
            result = art.find_candidates(self.conf, source="steam", ident="526870",
                                         sgdb_key="")
        self.assertTrue(any("SteamGridDB" in n for n in result["notes"]))

    def test_a_non_steam_app_with_no_key_says_so_rather_than_failing(self):
        """The note is still made, even now that one of ours has art regardless."""
        with self.fake_fetch():
            result = art.find_candidates(self.conf, name="Some Game",
                                         source="heroic", ident="abc123")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["notes"])

    def test_one_of_our_own_tiles_offers_both_versions_of_itself(self):
        """With words and without: which one somebody wants is a preference."""
        with self.fake_fetch():
            result = art.find_candidates(self.conf, name="Zz Reboot Host",
                                         source="launcher", ident="reboot")
        ours = [c for c in result["candidates"] if c["source"] == "ours"]
        self.assertEqual([c["label"] for c in ours],
                         ["Ours, in English", "Ours, without words"])
        self.assertTrue(all(c["path"] for c in ours))

    def test_english_is_offered_where_the_machine_has_no_language(self):
        """A server has no locale, so its set is the wordless one.

        Measured on the Arch, Debian and Ubuntu cloud images 2026-09-19: the
        picker offered exactly one picture, on the page whose whole purpose is
        choosing between them.
        """
        import os as _os
        from sunshine_apps_ui import i18n
        from sunshine_apps_ui.core.sources.launchers import our_tiles

        with mock.patch.dict(_os.environ, {"SAU_LANGUAGE": "C"}):
            i18n._cache.clear()
            labels = [t["label"] for t in our_tiles("apps-ui")]
        i18n._cache.clear()
        self.assertEqual(labels, ["Ours, in English", "Ours, without words"])

    def test_ours_come_before_anything_on_a_network(self):
        with self.fake_fetch():
            result = art.find_candidates(self.conf, name="Zz Steam",
                                         source="launcher", ident="steam")
        self.assertEqual(result["candidates"][0]["source"], "ours")

    def test_a_game_is_not_offered_our_tiles(self):
        with self.fake_fetch():
            result = art.find_candidates(self.conf, source="steam", ident="526870")
        self.assertFalse([c for c in result["candidates"] if c["source"] == "ours"])

    def test_an_entry_of_ours_we_have_no_tile_for_offers_nothing_of_ours(self):
        with self.fake_fetch():
            result = art.find_candidates(self.conf, name="Something",
                                         source="launcher", ident="not-a-tile")
        self.assertFalse([c for c in result["candidates"] if c["source"] == "ours"])


class SgdbTest(_Fixture):
    def _api(self, responses):
        def get(path, key, timeout):
            for prefix, payload in responses.items():
                if path.startswith(prefix):
                    return {"data": payload}
            return {"data": []}
        return mock.patch.object(art, "_sgdb_json", side_effect=get)

    def test_highest_scoring_artwork_comes_first(self):
        grids = [{"url": "https://g/low.png", "score": 1},
                 {"url": "https://g/high.png", "score": 99}]
        with self._api({"/grids/steam/526870": grids}):
            found, note = art._sgdb("Satisfactory", "526870", "key", 1)
        self.assertEqual(found[0]["origin"], "https://g/high.png")
        self.assertEqual(note, "")

    def test_a_non_steam_app_is_searched_for_by_name(self):
        with self._api({"/search/autocomplete/": [{"id": 42}],
                        "/grids/game/42": [{"url": "https://g/a.png", "score": 5}]}):
            found, note = art._sgdb("Hades", "", "key", 1)
        self.assertEqual([c["origin"] for c in found], ["https://g/a.png"])

    def test_the_artist_is_credited(self):
        grids = [{"url": "https://g/a.png", "score": 1, "author": {"name": "someone"}}]
        with self._api({"/grids/steam/526870": grids}):
            found, _ = art._sgdb("", "526870", "key", 1)
        self.assertEqual(found[0]["label"], "by someone")

    def test_the_list_is_capped(self):
        grids = [{"url": f"https://g/{i}.png", "score": i} for i in range(200)]
        with self._api({"/grids/steam/526870": grids}):
            found, _ = art._sgdb("", "526870", "key", 1)
        self.assertEqual(len(found), art.SGDB_LIMIT)

    def test_no_results_is_said_plainly(self):
        with self._api({}):
            found, note = art._sgdb("Nothing At All", "", "key", 1)
        self.assertEqual(found, [])
        self.assertIn("no artwork", note)


class ChooseTest(_Fixture):
    def _cached(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch():
            art._fetch_candidate(self.conf, dict(candidate), 1)
        return candidate["id"]

    def test_choosing_copies_into_the_images_tree(self):
        path = art.choose_artwork(self.conf, self._cached(), "Satisfactory")
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.startswith(art.chosen_dir(self.conf)))

    def test_chosen_art_is_kept_away_from_generated_art(self):
        # A rescan rewrites images/steam/<appid>.png. A hand-picked cover must
        # not be sitting there waiting to be overwritten.
        path = art.choose_artwork(self.conf, self._cached(), "Satisfactory")
        self.assertNotIn(os.path.join("images", "steam"), path)

    def test_the_name_appears_in_the_filename(self):
        path = art.choose_artwork(self.conf, self._cached(), "Deep Rock Galactic")
        self.assertIn("Deep-Rock-Galactic", os.path.basename(path))

    def test_a_hostile_name_cannot_escape_the_directory(self):
        path = art.choose_artwork(self.conf, self._cached(), "../../../etc/cron.d/x")
        self.assertEqual(os.path.dirname(path), art.chosen_dir(self.conf))

    def test_an_id_that_is_not_an_id_is_refused(self):
        with self.assertRaises(art.ArtworkError):
            art.choose_artwork(self.conf, "../../../etc/passwd", "x")

    def test_an_unknown_id_is_refused(self):
        with self.assertRaises(art.ArtworkError):
            art.choose_artwork(self.conf, "0" * 16, "x")


class CacheTest(_Fixture):
    def test_old_candidates_are_pruned(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch():
            got = art._fetch_candidate(self.conf, dict(candidate), 1)
        os.utime(got["path"], (0, 0))
        self.assertEqual(art.prune_cache(self.conf), 1)
        self.assertFalse(os.path.exists(got["path"]))

    def test_a_candidate_still_in_use_survives_a_prune(self):
        candidate = art._steam_cdn("526870")[0]
        with self.fake_fetch():
            got = art._fetch_candidate(self.conf, dict(candidate), 1)
        os.utime(got["path"], (0, 0))
        with self.fake_fetch():
            art._fetch_candidate(self.conf, dict(candidate), 1)  # touches it
        self.assertEqual(art.prune_cache(self.conf), 0)
        self.assertTrue(os.path.exists(got["path"]))

    def test_pruning_a_directory_that_does_not_exist_is_not_an_error(self):
        self.assertEqual(art.prune_cache(self.conf), 0)


class SgdbKeyTest(_Fixture):
    def test_a_stored_key_is_read_back(self):
        with mock.patch.object(art, "_sgdb_json", return_value={"data": []}):
            art.save_sgdb_key(self.conf, "abc123")
        with mock.patch.dict(os.environ, {"SGDB_API_KEY": ""}):
            self.assertEqual(art.load_sgdb_key(self.conf), "abc123")

    @unittest.skipIf(os.name == "nt",
                     "POSIX modes. Windows privacy is an ACL, covered in test_filemode")
    def test_the_key_file_is_not_readable_by_others(self):
        with mock.patch.object(art, "_sgdb_json", return_value={"data": []}):
            path = art.save_sgdb_key(self.conf, "abc123")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == "nt",
                     "POSIX modes. Windows privacy is an ACL, covered in test_filemode")
    def test_a_world_readable_key_is_ignored(self):
        with mock.patch.object(art, "_sgdb_json", return_value={"data": []}):
            path = art.save_sgdb_key(self.conf, "abc123")
        os.chmod(path, 0o644)
        with mock.patch.dict(os.environ, {"SGDB_API_KEY": ""}):
            self.assertEqual(art.load_sgdb_key(self.conf), "")

    def test_a_key_sunshine_griddb_rejects_is_not_stored(self):
        with mock.patch.object(art, "_sgdb_json", side_effect=OSError("401")):
            with self.assertRaises(art.ArtworkError):
                art.save_sgdb_key(self.conf, "nope")
        self.assertFalse(os.path.exists(os.path.join(self.conf, art.SGDB_KEY_FILE)))

    def test_no_key_anywhere_is_empty_not_an_error(self):
        with mock.patch.dict(os.environ, {"SGDB_API_KEY": ""}):
            self.assertEqual(art.load_sgdb_key(self.conf), "")


if __name__ == "__main__":
    unittest.main()


class NotesTest(_Fixture):
    """What the page says about what it found, which has to be true."""

    def test_nothing_found_says_so(self):
        with self.fake_fetch(set()):
            result = art.find_candidates(self.conf, name="Something",
                                         source="heroic", ident="abc")
        self.assertTrue(result["notes"])
        self.assertTrue(result["notes"][0].startswith("No artwork was found"))

    def test_something_found_does_not_claim_otherwise(self):
        """Ours are offered for our own tiles, so "nothing found" would be a lie."""
        with self.fake_fetch():
            result = art.find_candidates(self.conf, name="Zz Reboot Host",
                                         source="launcher", ident="reboot")
        self.assertTrue(result["candidates"])
        self.assertFalse(any(n.startswith("No artwork was found")
                             for n in result["notes"]))

    def test_the_steamgriddb_note_is_still_made(self):
        with self.fake_fetch():
            result = art.find_candidates(self.conf, name="Zz Reboot Host",
                                         source="launcher", ident="reboot")
        self.assertTrue(any("SteamGridDB" in n for n in result["notes"]))
