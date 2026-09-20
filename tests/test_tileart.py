# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetching a language's tiles, and noticing when the ones here are old.

Nothing here touches the network: the transport is replaced, so what is tested
is the decisions -- what is safe to save, what counts as out of date, what a
half-finished download does.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from sunshine_apps_ui import i18n, tileart  # noqa: E402


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class TileArtTest(unittest.TestCase):
    def setUp(self):
        self.tiles = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tiles, True)
        patched = mock.patch.object(i18n, "tiles_dir", lambda: self.tiles)
        patched.start()
        self.addCleanup(patched.stop)
        self.served = {}

    def put(self, code, name, body):
        os.makedirs(os.path.join(self.tiles, code), exist_ok=True)
        with open(os.path.join(self.tiles, code, name), "wb") as handle:
            handle.write(body)

    def publish(self, sets):
        """What the server would hand out, as {code: {name: bytes}}."""
        manifest = {"schema": 1, "sets": {
            code: {name: digest(body) for name, body in files.items()}
            for code, files in sets.items()}}
        self.served = {f"{tileart.BASE_URL}/{code}/{name}": body
                       for code, files in sets.items()
                       for name, body in files.items()}
        self.served[tileart.MANIFEST_URL] = json.dumps(manifest).encode()

        def get(url, timeout=0):
            if url not in self.served:
                raise OSError("404")
            return self.served[url]

        patched = mock.patch.object(tileart, "_get", get)
        patched.start()
        self.addCleanup(patched.stop)
        return manifest

    # --- what a manifest is allowed to ask for ------------------------------

    def test_a_set_is_pngs_and_nothing_else(self):
        cleaned = tileart.clean({"sets": {"fr": {
            "steam.png": "a" * 64,
            "evil.py": "b" * 64,
            "../../escape.png": "c" * 64,
            "sub/dir.png": "d" * 64,
        }}})
        self.assertEqual(list(cleaned["fr"]), ["steam.png"])

    def test_a_hash_has_to_look_like_one(self):
        cleaned = tileart.clean({"sets": {"fr": {"a.png": "not-a-hash",
                                                 "b.png": "f" * 64}}})
        self.assertEqual(list(cleaned["fr"]), ["b.png"])

    def test_a_language_code_has_to_look_like_one(self):
        cleaned = tileart.clean({"sets": {"../etc": {"a.png": "f" * 64},
                                          "fr": {"a.png": "f" * 64},
                                          "_wordless": {"a.png": "f" * 64}}})
        self.assertEqual(sorted(cleaned), ["_wordless", "fr"])

    def test_rubbish_is_not_a_manifest(self):
        self.assertEqual(tileart.clean("nonsense"), {})
        self.assertEqual(tileart.clean({"sets": []}), {})

    # --- downloading --------------------------------------------------------

    def test_it_saves_a_set(self):
        self.publish({"fr": {"steam.png": b"one", "heroic.png": b"two"}})
        written, why = tileart.fetch_set("fr")
        self.assertEqual((written, why), (2, ""))
        with open(os.path.join(self.tiles, "fr", "steam.png"), "rb") as handle:
            self.assertEqual(handle.read(), b"one")

    def test_a_file_that_does_not_match_stops_the_whole_set(self):
        """Half a set is a grid half in one language: worse than not starting."""
        self.publish({"fr": {"good.png": b"one", "bad.png": b"two"}})
        self.served[f"{tileart.BASE_URL}/fr/bad.png"] = b"something else"
        written, why = tileart.fetch_set("fr")
        self.assertEqual(written, 0)
        self.assertIn("did not match", why)
        self.assertFalse(os.path.exists(os.path.join(self.tiles, "fr")))

    def test_nothing_is_written_when_a_download_fails_partway(self):
        self.publish({"fr": {"a.png": b"one", "b.png": b"two"}})
        del self.served[f"{tileart.BASE_URL}/fr/b.png"]
        written, why = tileart.fetch_set("fr")
        self.assertEqual(written, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tiles, "fr")))

    def test_it_will_not_fetch_a_language_nobody_published(self):
        self.publish({"fr": {"a.png": b"one"}})
        written, why = tileart.fetch_set("de")
        self.assertEqual(written, 0)
        self.assertIn("no de artwork", why)

    def test_it_will_not_fetch_a_path(self):
        self.publish({"fr": {"a.png": b"one"}})
        written, why = tileart.fetch_set("../../etc")
        self.assertEqual(written, 0)
        self.assertIn("not a language code", why)

    def test_an_offline_machine_says_so_and_changes_nothing(self):
        def broken(url, timeout=0):
            raise OSError("no route to host")

        with mock.patch.object(tileart, "_get", broken):
            sets, why = tileart.remote_manifest()
        self.assertEqual(sets, {})
        self.assertIn("could not be reached", why)

    # --- what is out of date ------------------------------------------------

    def test_only_sets_we_have_are_out_of_date(self):
        self.put("_wordless", "steam.png", b"old")
        remote = self.publish({"_wordless": {"steam.png": b"new"},
                               "de": {"steam.png": b"whatever"}})
        behind = tileart.stale(tileart.clean(remote))
        self.assertEqual(behind, {"_wordless": 1})

    def test_a_set_that_matches_is_not_offered(self):
        self.put("fr", "steam.png", b"same")
        remote = self.publish({"fr": {"steam.png": b"same"}})
        self.assertEqual(tileart.stale(tileart.clean(remote)), {})

    def test_a_file_we_are_missing_counts_as_out_of_date(self):
        self.put("fr", "steam.png", b"same")
        remote = self.publish({"fr": {"steam.png": b"same",
                                      "heroic.png": b"new one"}})
        self.assertEqual(tileart.stale(tileart.clean(remote)), {"fr": 1})

    # --- which languages are covered ---------------------------------------

    def test_a_region_is_covered_by_its_language(self):
        self.put("pt", "steam.png", b"x")
        self.assertTrue(tileart.have_set("pt-BR"))

    def test_and_is_not_covered_by_a_different_one(self):
        self.put("pt", "steam.png", b"x")
        self.assertFalse(tileart.have_set("fr"))


if __name__ == "__main__":
    unittest.main()
