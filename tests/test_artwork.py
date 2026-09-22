# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for artwork path handling."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import artwork  # noqa: E402

STATE = {
    "apps": [{"name": "A", "image-path": "/tmp/a.png"},
             {"name": "B", "image-path": ""}],
    "hidden": [{"name": "C", "image-path": "/tmp/c.png"}],
}


class TestAllowlist(unittest.TestCase):
    def test_it_collects_from_apps_and_hidden(self):
        self.assertEqual(artwork.allowed_paths(STATE), {"/tmp/a.png", "/tmp/c.png"})

    def test_empty_paths_are_not_collected(self):
        self.assertNotIn("", artwork.allowed_paths(STATE))


class TestCachedArtworkIsAllowed(unittest.TestCase):
    """Artwork being chosen is referred to by nothing yet, so nothing else
    would let the picker show it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = self.tmp.name
        self.candidates = os.path.join(self.conf, "images", ".candidates")
        self.chosen = os.path.join(self.conf, "images", "chosen")
        for directory in (self.candidates, self.chosen):
            os.makedirs(directory)
        self.state = dict(STATE, config_dir=self.conf)

    def _write(self, directory, name):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")
        return path

    def test_a_fetched_candidate_may_be_shown(self):
        path = self._write(self.candidates, "abc.png")
        self.assertIn(path, artwork.allowed_paths(self.state))

    def test_a_chosen_cover_may_be_shown_before_it_is_applied(self):
        path = self._write(self.chosen, "Game-abc.png")
        self.assertIn(path, artwork.allowed_paths(self.state))

    def test_a_file_beside_the_cache_is_not_allowed(self):
        other = self._write(os.path.join(self.conf, "images"), "elsewhere.png")
        self.assertNotIn(other, artwork.allowed_paths(self.state))

    def test_walking_out_of_the_cache_is_not_allowed(self):
        self._write(self.candidates, "abc.png")
        allowed = artwork.allowed_paths(self.state)
        self.assertIsNone(artwork.read(
            os.path.join(self.candidates, "../../../etc/passwd"), allowed))

    def test_the_apps_own_artwork_is_still_allowed(self):
        self.assertIn("/tmp/a.png", artwork.allowed_paths(self.state))

    def test_a_state_without_a_config_dir_is_not_an_error(self):
        self.assertEqual(artwork.allowed_paths(STATE),
                         {"/tmp/a.png", "/tmp/c.png"})


class TestRead(unittest.TestCase):
    def setUp(self):
        fd, self.png = tempfile.mkstemp(suffix=".png")
        # smallest valid-ish PNG header; content is not parsed, only the type
        os.write(fd, b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        os.close(fd)
        self.allowed = {self.png}

    def tearDown(self):
        os.path.exists(self.png) and os.unlink(self.png)

    def test_a_referenced_png_is_served(self):
        found = artwork.read(self.png, self.allowed)
        self.assertIsNotNone(found)
        self.assertEqual(found[1], "image/png")

    def test_an_unreferenced_path_is_refused(self):
        self.assertIsNone(artwork.read("/etc/passwd", self.allowed))

    def test_traversal_cannot_reach_outside_the_allowlist(self):
        self.assertIsNone(artwork.read(self.png + "/../../etc/passwd", self.allowed))

    def test_a_non_image_extension_is_refused_even_if_referenced(self):
        fd, path = tempfile.mkstemp(suffix=".sh")
        os.write(fd, b"#!/bin/sh\n"); os.close(fd)
        try:
            self.assertIsNone(artwork.read(path, {path}))
        finally:
            os.unlink(path)

    def test_an_oversized_file_is_refused(self):
        original = artwork.MAX_BYTES
        artwork.MAX_BYTES = 8
        try:
            self.assertIsNone(artwork.read(self.png, self.allowed))
        finally:
            artwork.MAX_BYTES = original


class TestResolve(unittest.TestCase):
    def test_a_relative_path_resolves_against_sunshine_assets(self):
        """Sunshine's own defaults use bare names like desktop.png."""
        self.assertEqual(artwork.resolve("definitely-not-here.png"), "")

    def test_an_absolute_missing_path_resolves_to_nothing(self):
        self.assertEqual(artwork.resolve("/nope/nope.png"), "")

    def test_empty_resolves_to_nothing(self):
        self.assertEqual(artwork.resolve(""), "")


class TestQueuedArtwork(unittest.TestCase):
    """A staged entry is in neither apps.json nor its tombstones."""

    def test_a_staged_entry_may_show_its_art(self):
        pending = [{"op": "adopt", "name": "TF2",
                    "entry": {"name": "TF2", "image-path": "/img/440.png"}}]
        self.assertIn("/img/440.png", artwork.allowed_paths(STATE, pending))

    def test_a_queued_edit_may_show_its_new_art(self):
        pending = [{"op": "edit", "name": "A", "fields": {"image-path": "/img/new.png"}}]
        self.assertIn("/img/new.png", artwork.allowed_paths(STATE, pending))

    def test_a_tombstone_style_op_may_show_its_art(self):
        pending = [{"op": "suppress", "name": "X", "image-path": "/img/x.png"}]
        self.assertIn("/img/x.png", artwork.allowed_paths(STATE, pending))

    def test_the_queue_does_not_widen_it_to_anything_else(self):
        pending = [{"op": "adopt", "entry": {"name": "TF2", "image-path": "/img/440.png"}}]
        allowed = artwork.allowed_paths(STATE, pending)
        self.assertNotIn("/etc/passwd", allowed)
        self.assertEqual(allowed, {"/tmp/a.png", "/tmp/c.png", "/img/440.png"})

    def test_no_queue_behaves_as_before(self):
        self.assertEqual(artwork.allowed_paths(STATE), {"/tmp/a.png", "/tmp/c.png"})


class WindowsPathMatchingTest(unittest.TestCase):
    """C:\\x\\y.png, c:/x/y.png and C:\\X\\Y.PNG are one file.

    An allowlist of exact strings refuses two of those three, so Sunshine's own
    tiles show broken images. Loosening the match must not loosen the allowlist:
    it stays an exact set of paths read out of apps.json.
    """

    def setUp(self):
        self.real_name = os.name
        os.name = "nt"

    def tearDown(self):
        os.name = self.real_name

    def test_separator_and_case_do_not_decide_whether_a_tile_has_a_cover(self):
        allowed = {r"C:\ProgramData\cover.png"}
        for spelling in (r"C:\ProgramData\cover.png", "C:/ProgramData/cover.png",
                         r"c:\programdata\COVER.PNG"):
            self.assertEqual(artwork._key(spelling), artwork._key(r"C:\ProgramData\cover.png"),
                             f"{spelling} should be the same file")
            self.assertIn(artwork._key(spelling), {artwork._key(p) for p in allowed})

    def test_a_different_file_is_still_refused(self):
        allowed = {artwork._key(r"C:\ProgramData\cover.png")}
        for other in (r"C:\ProgramData\other.png", r"C:\Windows\System32\config\SAM",
                      r"C:\ProgramData\cover.png.exe"):
            self.assertNotIn(artwork._key(other), allowed)

    def test_traversal_does_not_become_a_way_in(self):
        """normpath collapses "..", so check it cannot reach outside the set."""
        allowed = {artwork._key(r"C:\ProgramData\cover.png")}
        self.assertNotIn(artwork._key(r"C:\ProgramData\..\Windows\win.ini"), allowed)

    def test_posix_is_left_case_sensitive(self):
        os.name = self.real_name
        if os.name == "nt":
            self.skipTest("POSIX only")
        self.assertNotEqual(artwork._key("/tmp/Cover.png"), artwork._key("/tmp/cover.png"))


class OurTileInUseTest(unittest.TestCase):
    """One of ours is used from where it lies, not from the candidate cache."""

    def _page(self, current):
        from sunshine_apps_ui.render import artwork_page
        return artwork_page(
            [{"id": "a1", "source": "ours", "label": "Ours, in English",
              "origin": "/opt/app/assets/tiles/en/steam.png",
              "path": "/conf/.candidates/a1.png"}],
            token="t", key="index:0", label="Zz Steam", current=current)

    def test_the_origin_counts_as_in_use(self):
        self.assertIn("in use", self._page("/opt/app/assets/tiles/en/steam.png"))

    def test_the_cached_copy_still_counts_as_in_use(self):
        self.assertIn("in use", self._page("/conf/.candidates/a1.png"))

    def test_anything_else_does_not(self):
        self.assertNotIn("in use", self._page("/home/u/my-own.png"))


class TheSettingsOfferOnThePickerTest(unittest.TestCase):
    """Issue #22. When there is no SteamGridDB key, the note says one can be
    added in Settings -- so there has to be a way to get to Settings from here.

    A link, not an instruction: this page is read on a television, and the way
    to Settings on a television is something you can move a gamepad onto.
    """

    def _page(self, offer):
        from sunshine_apps_ui.render import artwork_page
        return artwork_page([], token="tok", key="index:0", label="Zz Steam",
                            notes=["More artwork is available from SteamGridDB."],
                            offer_sgdb=offer)

    def test_the_link_is_there_when_a_key_could_be_added(self):
        body = self._page(True)
        self.assertIn("/settings?token=tok", body)

    def test_it_is_absent_when_a_key_is_already_stored(self):
        self.assertNotIn("/settings?token=tok", self._page(False))

    def test_the_picker_never_names_a_command(self):
        """Every command this ever named was one somebody could not run."""
        body = self._page(True)
        for fragment in ("sunshine-import", "--save-sgdb-key"):
            self.assertNotIn(fragment, body)


class TheOfferIsDecidedByTheSourceTest(unittest.TestCase):
    """find_candidates says whether a key was wanted and missing, rather than
    the page matching on the note's wording. Reworded text must not silently
    take the offer away with it."""

    def setUp(self):
        self.conf = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.conf, True)

    def _result(self, **kw):
        # No network: with a key set, _sgdb would go and ask SteamGridDB, and a
        # test whose result depends on the machine having a route out is a test
        # that fails on an aeroplane.
        from unittest import mock
        from sunshine_apps_ui.core import artwork_sources
        with mock.patch.object(artwork_sources, "_sgdb_json",
                               side_effect=OSError("no network in tests")):
            return artwork_sources.find_candidates(self.conf, name="Zz Nothing",
                                                   **kw)

    def test_offered_when_there_is_no_key(self):
        self.assertTrue(self._result(sgdb_key="").get("offer_sgdb"))

    def test_not_offered_when_a_key_is_stored(self):
        self.assertFalse(self._result(sgdb_key="a-key").get("offer_sgdb"))

    def test_not_offered_when_the_source_is_turned_off(self):
        self.assertFalse(
            self._result(sgdb_key="", sgdb_enable=False).get("offer_sgdb"))
