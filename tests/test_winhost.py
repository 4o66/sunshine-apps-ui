# SPDX-License-Identifier: GPL-3.0-or-later
"""Building our own window, and refusing to depend on one that does not work.

The window itself is Win32 and WebView2, and it is measured on the rig. What is
here is the part that is decisions: that a machine which cannot have one keeps
the browser, that a build is only trusted after it has been run, and that the
command line the window is started with is one the launcher still recognises as
its own -- which is what the orphan cleanup depends on.

The numbers this exists for, measured on the rig 2026-09-18 in the interactive
session: window on screen 0.36 s against a browser's 3.6 s to the app.
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import winbrowser, winhost  # noqa: E402
from sunshine_apps_ui.interpreter import ProvisionError  # noqa: E402


class ShippedSourceTest(unittest.TestCase):
    """The C# is shipped and readable, which is the argument for compiling here."""

    def test_the_source_is_where_it_says_it_is(self):
        self.assertTrue(os.path.isfile(winhost.source_path()),
                        "the window's source is not in the package")

    def test_it_is_the_only_thing_needed_to_build(self):
        source = open(winhost.source_path(), encoding="utf-8").read()
        self.assertIn("class AppWindow", source)
        self.assertIn("--check", source, "the install has no way to verify a build")

    def test_it_avoids_c_sharp_the_in_box_compiler_cannot_read(self):
        """csc.exe v4.0.30319 is a C# 5 compiler: no interpolation, no ?. ."""
        source = open(winhost.source_path(), encoding="utf-8").read()
        code = "\n".join(line for line in source.splitlines()
                         if not line.strip().startswith("//"))
        self.assertNotIn('$"', code)
        self.assertNotIn("?.", code)
        self.assertNotIn("nameof(", code)

    def test_the_window_starts_dark(self):
        """A white rectangle on a television is a flash of light in a dark room."""
        source = open(winhost.source_path(), encoding="utf-8").read()
        self.assertIn("0x21, 0x25, 0x29", source)


class PinnedArtifactTest(unittest.TestCase):
    def test_the_sdk_is_pinned_by_hash(self):
        self.assertEqual(len(winhost.WEBVIEW2.sha256), 64)
        self.assertRegex(winhost.WEBVIEW2.sha256, r"\A[0-9a-f]{64}\Z")

    def test_the_url_and_the_name_agree_on_the_version(self):
        """They drifted apart once in the interpreter; not again here."""
        version = winhost.WEBVIEW2.name.split()[1]
        self.assertIn(version, winhost.WEBVIEW2.url)

    def test_only_the_three_files_needed_are_kept(self):
        self.assertEqual(len(winhost.ASSEMBLIES), 3)
        self.assertTrue(any("WebView2Loader" in name
                            for name in winhost.ASSEMBLIES.values()))

    def test_the_native_loader_is_the_one_the_build_targets(self):
        """x64 loader, so /platform:x64 -- a 32-bit build could not load it."""
        self.assertTrue(any("win-x64" in member for member in winhost.ASSEMBLIES))
        command = winhost.compile_command("csc.exe", "a.cs", "a.exe", "d")
        self.assertIn("/platform:x64", command)

    def test_describe_says_what_would_be_fetched(self):
        text = "\n".join(winhost.describe())
        self.assertIn(winhost.WEBVIEW2.url, text)
        self.assertIn(winhost.WEBVIEW2.sha256, text)


class CompileCommandTest(unittest.TestCase):
    def test_it_references_both_assemblies_and_names_the_output(self):
        command = winhost.compile_command(r"C:\csc.exe", r"C:\b\AppWindow.cs",
                                          r"C:\b\AppWindow.exe", r"C:\b")
        self.assertEqual(command[0], r"C:\csc.exe")
        self.assertIn("/target:winexe", command)
        self.assertIn(r"/out:C:\b\AppWindow.exe", command)
        for name in winhost.REFERENCES:
            self.assertIn("/reference:" + os.path.join(r"C:\b", name), command)
        self.assertEqual(command[-1], r"C:\b\AppWindow.cs")


class NotOnThisMachineTest(unittest.TestCase):
    """Everything here has to be absent quietly, not loudly."""

    def test_nothing_is_offered_off_windows(self):
        if os.name == "nt":
            self.skipTest("this is the off-Windows behaviour")
        self.assertFalse(winhost.available())
        self.assertEqual(winhost.compiler(), "")
        self.assertEqual(winhost.runtime_version(), "")

    def test_a_window_that_is_not_there_does_not_work(self):
        self.assertFalse(winhost.works(""))
        self.assertFalse(winhost.works(os.path.join(tempfile.gettempdir(),
                                                    "no-such-AppWindow.exe")))

    def test_available_is_false_without_a_runtime(self):
        with mock.patch.object(winhost, "host_exe", return_value=r"C:\h\AppWindow.exe"), \
                mock.patch.object(winhost, "runtime_version", return_value=""), \
                mock.patch.object(os, "name", "nt"):
            self.assertFalse(winhost.available(r"C:\install"))

    def test_available_is_false_without_a_built_window(self):
        with mock.patch.object(winhost, "host_exe", return_value=""), \
                mock.patch.object(winhost, "runtime_version", return_value="153.0.1"), \
                mock.patch.object(os, "name", "nt"):
            self.assertFalse(winhost.available(r"C:\install"))

    def test_build_says_so_when_there_is_no_compiler(self):
        with mock.patch.object(winhost, "compiler", return_value=""):
            with self.assertRaises(ProvisionError) as caught:
                winhost.build(tempfile.gettempdir())
        self.assertIn("csc.exe", str(caught.exception))


class ExtractTest(unittest.TestCase):
    """Three files out of nine megabytes, and nothing taken on trust."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def package(self, members):
        path = os.path.join(self.tmp, "sdk.nupkg")
        with zipfile.ZipFile(path, "w") as archive:
            for member in members:
                archive.writestr(member, b"MZ fake")
            archive.writestr("tools/wv2winrt/huge.dll", b"x" * 1000)
        return path

    def test_it_takes_the_three_and_leaves_the_rest(self):
        into = os.path.join(self.tmp, "out")
        os.makedirs(into)
        winhost._extract(self.package(list(winhost.ASSEMBLIES)), into)
        self.assertEqual(sorted(os.listdir(into)),
                         sorted(winhost.ASSEMBLIES.values()))

    def test_a_package_missing_what_we_need_is_refused_by_name(self):
        into = os.path.join(self.tmp, "out")
        os.makedirs(into)
        members = list(winhost.ASSEMBLIES)[1:]
        with self.assertRaises(ProvisionError) as caught:
            winhost._extract(self.package(members), into)
        self.assertIn(list(winhost.ASSEMBLIES)[0], str(caught.exception))


class BuildIsVerifiedBeforeItIsTrustedTest(unittest.TestCase):
    """The interpreter's lesson, applied here: build beside, then swap.

    Replacing something that works with something that does not, while
    reporting success, is the failure that cost an afternoon on the rig.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.install = os.path.join(self.tmp, "install")
        os.makedirs(self.install)

        self.downloaded = mock.patch.object(
            winhost, "_download",
            side_effect=lambda artifact, into, say=None: self.fake_package(into))
        self.downloaded.start()
        self.addCleanup(self.downloaded.stop)
        compiler = mock.patch.object(winhost, "compiler", return_value=r"C:\csc.exe")
        compiler.start()
        self.addCleanup(compiler.stop)

    def fake_package(self, into):
        path = os.path.join(into, "sdk.nupkg")
        with zipfile.ZipFile(path, "w") as archive:
            for member in winhost.ASSEMBLIES:
                archive.writestr(member, b"MZ fake")
        return path

    def run_build(self, produce=True, works=True):
        # /out: is not the last argument; find it rather than assume.
        def run(command, **kwargs):
            if produce:
                target = next(a[len("/out:"):] for a in command
                              if a.startswith("/out:"))
                with open(target, "wb") as handle:
                    handle.write(b"MZ")
                return mock.Mock(returncode=0, stdout=b"")
            return mock.Mock(returncode=1, stdout=b"error CS1002: ; expected")

        with mock.patch.object(winhost.subprocess, "run", side_effect=run), \
                mock.patch.object(winhost, "works", return_value=works):
            return winhost.build(self.install, log=lambda line: None)

    def test_a_good_build_lands_where_the_launcher_looks_for_it(self):
        produced = self.run_build()
        self.assertEqual(produced, os.path.join(self.install, "host", "AppWindow.exe"))
        self.assertTrue(os.path.isfile(produced))
        self.assertEqual(winhost.host_exe(self.install), produced)
        # The assemblies it needs are beside it, not somewhere on a path.
        for name in winhost.ASSEMBLIES.values():
            self.assertTrue(os.path.isfile(os.path.join(self.install, "host", name)))

    def test_a_build_that_will_not_run_replaces_nothing(self):
        working = self.run_build()
        with open(working, "wb") as handle:
            handle.write(b"THE ONE THAT WORKS")
        with self.assertRaises(ProvisionError):
            self.run_build(works=False)
        self.assertEqual(open(working, "rb").read(), b"THE ONE THAT WORKS")

    def test_a_build_that_will_not_compile_says_what_the_compiler_said(self):
        with self.assertRaises(ProvisionError) as caught:
            self.run_build(produce=False)
        self.assertIn("CS1002", str(caught.exception))

    def test_nothing_is_left_beside_the_install_afterwards(self):
        self.run_build()
        self.assertEqual(sorted(os.listdir(self.install)), ["host"])


class OnlyRebuiltWhenItChangedTest(unittest.TestCase):
    """Nine megabytes and a compile, skipped when nothing moved."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.host = os.path.join(self.tmp, "host")
        os.makedirs(self.host)
        with open(os.path.join(self.host, winhost.EXE_NAME), "wb") as handle:
            handle.write(b"MZ")

    def copy_source(self, text=None):
        # Bytes, because build() copies with shutil.copyfile and is_current()
        # compares byte for byte. Writing it as text put \r\n in the copy on
        # Windows, so the test said "rebuild" about an identical source -- on
        # Windows, which is the only place this code runs.
        body = (text.encode("utf-8") if text is not None
                else open(winhost.source_path(), "rb").read())
        with open(os.path.join(self.host, winhost.SOURCE_NAME), "wb") as handle:
            handle.write(body)

    def test_the_same_source_and_a_working_build_is_left_alone(self):
        self.copy_source()
        with mock.patch.object(winhost, "works", return_value=True):
            self.assertTrue(winhost.is_current(self.tmp))

    def test_a_changed_source_is_rebuilt(self):
        self.copy_source("// an older window\n")
        with mock.patch.object(winhost, "works", return_value=True):
            self.assertFalse(winhost.is_current(self.tmp))

    def test_a_build_that_no_longer_runs_is_rebuilt(self):
        self.copy_source()
        with mock.patch.object(winhost, "works", return_value=False):
            self.assertFalse(winhost.is_current(self.tmp))

    def test_a_build_with_no_record_of_its_source_is_rebuilt(self):
        with mock.patch.object(winhost, "works", return_value=True):
            self.assertFalse(winhost.is_current(self.tmp))

    def test_nothing_built_at_all_is_not_current(self):
        self.assertFalse(winhost.is_current(os.path.join(self.tmp, "nowhere")))


class TheLauncherStillRecognisesItsOwnWindowTest(unittest.TestCase):
    """The window takes --user-data-dir for a reason that is not cosmetic.

    The launcher finds windows left over from a previous session by matching
    that flag in a command line (launcher.PROFILE_PATTERN). A window started
    with any other spelling would be invisible to the cleanup and would be left
    running on top of its replacement.
    """

    URL = "http://127.0.0.1:47999/?token=abc"
    PROFILE = os.path.join("C:\\state", "sunshine-apps-ui", "browser-profile")

    def command(self, streamed):
        return winbrowser.Browser("our own window", r"C:\i\host\AppWindow.exe",
                                  "webview2").command(self.URL, self.PROFILE, streamed)

    def test_the_profile_flag_matches_what_the_cleanup_looks_for(self):
        import re
        from sunshine_apps_ui import launcher
        line = " ".join(self.command(streamed=True))
        self.assertTrue(re.search(launcher.PROFILE_PATTERN, line),
                        "the launcher would not recognise its own window")

    def test_streamed_has_no_border_and_local_keeps_its_frame(self):
        """The maintainer's rule, 2026-09-17: fullscreen from Moonlight, framed at the machine."""
        self.assertIn("--fullscreen", self.command(streamed=True))
        self.assertNotIn("--windowed", self.command(streamed=True))
        self.assertIn("--windowed", self.command(streamed=False))
        self.assertNotIn("--fullscreen", self.command(streamed=False))

    def test_the_url_is_the_last_word_and_is_not_a_flag(self):
        command = self.command(streamed=True)
        self.assertEqual(command[-1], self.URL)
        self.assertEqual(command[0], r"C:\i\host\AppWindow.exe")


class OurWindowIsPreferredButNeverRequiredTest(unittest.TestCase):
    def found(self, ours):
        with mock.patch.object(winbrowser, "_own_window", return_value=ours), \
                mock.patch.object(winbrowser, "_candidates", return_value=[
                    ("edge", "app", [__file__])]):
            return winbrowser.find_browsers()

    def test_it_comes_first_when_it_is_there(self):
        ours = winbrowser.Browser("our own window", r"C:\i\host\AppWindow.exe",
                                  "webview2")
        found = self.found(ours)
        self.assertEqual(found[0], ours)
        self.assertEqual(found[1].name, "edge", "the browser is still offered")

    def test_the_browser_is_exactly_what_it_was_without_it(self):
        found = self.found(None)
        self.assertEqual([b.name for b in found], ["edge"])

    def test_a_broken_winhost_does_not_take_the_browser_down_with_it(self):
        """Nothing about our own window may ever be a reason not to open one."""
        with mock.patch.object(winhost, "available", side_effect=RuntimeError("boom")):
            self.assertIsNone(winbrowser._own_window())


if __name__ == "__main__":
    unittest.main()
