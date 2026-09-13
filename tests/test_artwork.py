"""Tests for artwork path handling."""
import os
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
