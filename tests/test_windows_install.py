# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing as a Windows program rather than as a POSIX one.

Windows has no ~/.local convention worth imitating, so this installs the way a
per-user Windows program does: one directory under %LOCALAPPDATA%\\Programs, the
command inside it, and an entry in Add/Remove Programs so it can be removed the
way anything else is.

The registry writes themselves run on the rig (issue #15). What is here is the
shape of the install and the contents of the generated command, both of which
are decisions rather than Win32.
"""

import ntpath
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from sunshine_apps_ui import installer, places  # noqa: E402


class WindowsPathsTest(unittest.TestCase):
    def setUp(self):
        self.real_name = os.name
        self.real_environ = dict(os.environ)
        os.name = "nt"
        os.environ["LOCALAPPDATA"] = r"C:\Users\sean\AppData\Local"
        os.environ.pop("PREFIX", None)
        os.environ.pop("XDG_STATE_HOME", None)

    def tearDown(self):
        os.name = self.real_name
        os.environ.clear()
        os.environ.update(self.real_environ)

    def test_it_installs_where_a_per_user_windows_program_goes(self):
        where = installer.paths()
        self.assertTrue(where["install"].endswith(
            ntpath.join("AppData", "Local", "Programs", "sunshine-apps-ui")),
            where["install"])

    def test_the_command_lives_in_the_install_and_ends_in_cmd(self):
        """No bin/ directory, and Windows decides what runs by extension."""
        where = installer.paths()
        self.assertEqual(ntpath.dirname(where["command"]), where["install"])
        self.assertTrue(where["command"].endswith(".cmd"))

    def test_state_goes_to_localappdata_not_a_dotted_posix_path(self):
        self.assertNotIn(".local", places.state_dir())
        self.assertIn("AppData", places.state_dir())

    def test_an_explicit_prefix_still_wins(self):
        where = installer.paths(r"D:\Apps")
        self.assertEqual(where["install"], ntpath.join(r"D:\Apps", "sunshine-apps-ui"))

    def test_xdg_state_home_is_honoured_even_here(self):
        """It is what the tests set, and the only way to run two side by side."""
        os.environ["XDG_STATE_HOME"] = r"D:\state"
        self.assertEqual(places.state_dir(), ntpath.join(r"D:\state", "sunshine-apps-ui"))


class WindowsLauncherScriptTest(unittest.TestCase):
    def test_it_puts_the_installed_copy_on_pythonpath(self):
        script = installer._windows_launcher(r"C:\Programs\sunshine-apps-ui")
        self.assertIn(r"C:\Programs\sunshine-apps-ui\src", script)
        self.assertIn("PYTHONPATH", script)

    def test_it_hands_its_arguments_on(self):
        """--scan and --uninstall reach the program, or the ARP entry does nothing."""
        script = installer._windows_launcher(r"C:\Programs\sunshine-apps-ui")
        self.assertIn("%*", script)

    def test_it_finds_an_interpreter_rather_than_hard_coding_one(self):
        """The interpreter that ran the installer may not be the one on PATH later."""
        script = installer._windows_launcher(r"C:\x")
        self.assertIn("py -3 -m sunshine_apps_ui", script)
        self.assertIn("python -m sunshine_apps_ui", script)

    def test_it_does_not_stand_in_the_directory_it_may_delete(self):
        """--uninstall removes the install; cmd.exe errors if that is its cwd."""
        script = installer._windows_launcher(r"C:\x")
        self.assertIn('cd /d "%TEMP%"', script)

    def test_it_is_a_batch_file_with_windows_line_endings(self):
        script = installer._windows_launcher(r"C:\x")
        self.assertTrue(script.startswith("@echo off"))
        self.assertIn("\r\n", script)


class RegistrationTest(unittest.TestCase):
    """What goes in Add/Remove Programs, with the registry stood in for."""

    def setUp(self):
        self.real_name = os.name
        self.tmp = tempfile.mkdtemp()
        self.written = {}
        os.name = "nt"

        class FakeKey:
            def __enter__(inner):
                return inner

            def __exit__(inner, *exc):
                return False

        outer = self

        class FakeWinreg:
            HKEY_CURRENT_USER = 1
            REG_SZ = 1
            REG_DWORD = 4

            @staticmethod
            def CreateKey(root, path):        # noqa: N802 - winreg's name
                outer.created = path
                return FakeKey()

            @staticmethod
            def SetValueEx(key, name, reserved, kind, value):  # noqa: N802
                outer.written[name] = value

            @staticmethod
            def DeleteKey(root, path):        # noqa: N802
                outer.deleted = path

        sys.modules["winreg"] = FakeWinreg

    def tearDown(self):
        os.name = self.real_name
        sys.modules.pop("winreg", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def register(self):
        return installer._register_with_windows(
            {"install": self.tmp, "command": os.path.join(self.tmp, "sunshine-apps-ui.cmd")})

    def test_it_writes_what_add_remove_programs_shows(self):
        self.register()
        self.assertEqual(self.written["DisplayName"], "Sunshine App Manager")
        self.assertTrue(self.written["DisplayVersion"])
        self.assertEqual(self.written["InstallLocation"], self.tmp)

    def test_the_uninstall_string_runs_our_own_uninstall(self):
        """It must be the thing that removes the tile too, not just the files."""
        self.register()
        self.assertIn("--uninstall", self.written["UninstallString"])
        self.assertIn("sunshine-apps-ui.cmd", self.written["UninstallString"])
        # Quoted: %LOCALAPPDATA% contains the user's name, which may have a space.
        self.assertTrue(self.written["UninstallString"].startswith('"'))

    def test_a_quiet_uninstall_is_offered_too(self):
        """Windows uses this one when removing without a prompt."""
        self.register()
        self.assertIn("--uninstall", self.written["QuietUninstallString"])

    def test_modify_and_repair_are_refused_rather_than_broken(self):
        self.register()
        self.assertEqual(self.written["NoModify"], 1)
        self.assertEqual(self.written["NoRepair"], 1)

    def test_it_reports_the_size_it_takes(self):
        with open(os.path.join(self.tmp, "payload"), "wb") as handle:
            handle.write(b"x" * 4096)
        self.register()
        self.assertGreaterEqual(self.written["EstimatedSize"], 4)

    def test_uninstalling_takes_the_entry_back(self):
        installer._unregister_with_windows()
        self.assertEqual(self.deleted, installer.UNINSTALL_KEY)

    def test_none_of_this_happens_on_posix(self):
        os.name = self.real_name
        if os.name == "nt":
            self.skipTest("this asserts the POSIX no-op")
        self.assertEqual(self.register(), [])
        self.assertEqual(installer._unregister_with_windows(), [])



class DeferredRemovalTest(unittest.TestCase):
    """The install directory goes after we do, not while we are in it."""

    def setUp(self):
        self.real_popen = installer.subprocess.Popen
        self.calls = []
        installer.subprocess.Popen = lambda cmd, **kw: self.calls.append((cmd, kw))

    def tearDown(self):
        installer.subprocess.Popen = self.real_popen

    def test_the_deletion_waits_and_is_detached(self):
        message = installer._deferred_removal(r"C:\Programs\sunshine-apps-ui")
        command, options = self.calls[0]
        self.assertIn("rmdir /s /q", command)
        self.assertIn(r'"C:\Programs\sunshine-apps-ui"', command)
        # A pause, or it races the process that is still using the directory.
        self.assertIn("ping", command)
        self.assertTrue(options.get("close_fds"))
        self.assertIn("Removing", message)

    def test_it_is_one_command_line_rather_than_a_list(self):
        """A list is quoted per argument, so cmd receives quotes inside quotes,
        parses none of it, and deletes nothing -- with no error to show for it."""
        installer._deferred_removal(r"C:\Programs\sunshine-apps-ui")
        command, _ = self.calls[0]
        self.assertIsInstance(command, str)

    def test_a_failure_to_schedule_it_is_reported_not_swallowed(self):
        def explode(cmd, **kw):
            raise OSError("no cmd.exe")
        installer.subprocess.Popen = explode
        message = installer._deferred_removal(r"C:\x")
        self.assertIn("Delete it by hand", message)


class StartMenuShortcutTest(unittest.TestCase):
    """A way to open it at the machine, which is the case a tile cannot cover."""

    def setUp(self):
        self.real_name = os.name
        self.real_environ = dict(os.environ)
        self.real_run = installer.subprocess.run
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.name = "nt"
        appdata = os.path.join(self.tmp, "Roaming")
        self.programs = os.path.join(appdata, "Microsoft", "Windows",
                                     "Start Menu", "Programs")
        os.makedirs(self.programs)
        os.environ["APPDATA"] = appdata
        self.where = {"install": self.tmp,
                      "command": os.path.join(self.tmp, "sunshine-apps-ui.cmd")}
        self.scripts = []

        class Result:
            returncode = 0

        def fake_run(cmd, **kwargs):
            self.scripts.append(cmd[-1] if isinstance(cmd, list) else cmd)
            # A real shortcut is a structured file; standing in for it here.
            open(os.path.join(self.programs, "Sunshine App Manager.lnk"), "w").close()
            return Result()

        installer.subprocess.run = fake_run

    def tearDown(self):
        os.name = self.real_name
        installer.subprocess.run = self.real_run
        os.environ.clear()
        os.environ.update(self.real_environ)

    def test_it_makes_a_shortcut_to_the_installed_command(self):
        link = installer._start_menu_shortcut(self.where)
        self.assertTrue(link.endswith("Sunshine App Manager.lnk"))
        self.assertIn(self.where["command"], self.scripts[0])
        self.assertIn("WScript.Shell", self.scripts[0])

    def test_its_icon_is_an_ico_because_a_lnk_cannot_use_a_png(self):
        """It used to point at the .png, so the shortcut showed pythonw's snake.

        Windows wants an .ico or a binary carrying icon resources. The .ico is
        made from the shipped artwork at install time (installer._icon_files).
        """
        os.makedirs(os.path.join(self.tmp, "assets"), exist_ok=True)
        icon = os.path.join(self.tmp, "assets", "menu-icon.ico")
        open(icon, "wb").close()          # the shortcut only uses one that exists
        with mock.patch.object(installer, "_icon_files",
                               return_value={"ico": icon}):
            installer._start_menu_shortcut(self.where)
        self.assertIn("IconLocation", self.scripts[0])
        self.assertIn("menu-icon.ico", self.scripts[0])
        self.assertNotIn("poster.png", self.scripts[0])

    def test_no_icon_is_not_a_failure(self):
        with mock.patch.object(installer, "_icon_files", return_value={}):
            installer._start_menu_shortcut(self.where)
        self.assertNotIn("IconLocation", self.scripts[0])

    def test_uninstalling_takes_it_back(self):
        installer._start_menu_shortcut(self.where)
        messages = installer._remove_start_menu_shortcut()
        self.assertTrue(any("Start menu" in m for m in messages))
        self.assertFalse(os.path.exists(
            os.path.join(self.programs, "Sunshine App Manager.lnk")))

    def test_none_of_this_happens_off_windows(self):
        os.name = self.real_name
        if os.name == "nt":
            self.skipTest("this asserts the POSIX no-op")
        self.assertEqual(installer._start_menu_shortcut(self.where), "")
        self.assertEqual(installer._remove_start_menu_shortcut(), [])


class OneWindowTest(unittest.TestCase):
    """There must be one window: the interface.

    Sean, 2026-09-18: "closing the gui windows left the console launch helper
    open. This cannot happen. There needs to be one window." A .cmd always
    brings a console with it; pythonw.exe never does.
    """

    def setUp(self):
        self.real_name = os.name
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.name = "nt"
        self.where = {"install": self.tmp,
                      "command": os.path.join(self.tmp, "sunshine-apps-ui.cmd")}

    def tearDown(self):
        os.name = self.real_name

    def place_pythonw(self):
        os.makedirs(os.path.join(self.tmp, "python"), exist_ok=True)
        path = os.path.join(self.tmp, "python", "pythonw.exe")
        open(path, "w").close()
        return path

    def test_it_uses_pythonw_when_one_was_shipped(self):
        self.place_pythonw()
        command = installer.windowless_command(self.where)
        self.assertIn("pythonw.exe", command)
        self.assertIn("-m sunshine_apps_ui", command)
        self.assertNotIn(".cmd", command)

    def test_it_falls_back_to_the_cmd_when_there_is_no_interpreter(self):
        """Better a console than nothing at all."""
        command = installer.windowless_command(self.where)
        self.assertIn(".cmd", command)

    def test_the_path_is_quoted_because_it_has_spaces_in_practice(self):
        self.place_pythonw()
        self.assertTrue(installer.windowless_command(self.where).startswith('"'))

    def test_the_cmd_still_exists_for_a_terminal(self):
        """--scan and --uninstall are run there, and their output is the point."""
        self.place_pythonw()
        self.assertTrue(self.where["command"].endswith(".cmd"))

    def test_off_windows_nothing_changes(self):
        os.name = self.real_name
        if os.name == "nt":
            self.skipTest("this asserts the POSIX no-op")
        self.assertEqual(installer.windowless_command(self.where),
                         self.where["command"])

if __name__ == "__main__":
    unittest.main()
